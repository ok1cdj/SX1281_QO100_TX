"""
Web SDR window for the Tk client (Linux desktop).

Tk cannot show a web page with JavaScript and audio, so the SDR runs in a
Chromium --app window that the client keeps docked under its own window. The
client moves and retunes it over the Chrome DevTools protocol (CDP); the
websocket for it is a minimal stdlib client, so nothing extra is installed.
"""
import base64
import json
import logging
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("pyCWdclient")

BROWSERS = ["chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave", "brave-browser"]
PROFILE_DIR = Path.home() / ".cache" / "pyCWdclient-websdr"
START_TIMEOUT_S = 15


def find_browser():
    for name in BROWSERS:
        path = shutil.which(name)
        if path:
            return path
    return None


class WebSocket:
    """Just enough of RFC 6455 for CDP: text frames, client side, no fragmentation."""

    def __init__(self, url, timeout=5):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("WebSocket handshake: connection closed")
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"WebSocket handshake failed: {response.splitlines()[0]!r}")

    def send(self, text):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header = bytes([0x81, 0x80 | n])
        elif n < 65536:
            header = bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big")
        else:
            header = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big")
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("WebSocket closed")
            data += chunk
        return data

    def recv(self):
        """Next text message; other frames are skipped."""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            payload = self._read(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed by the browser")
            if opcode == 0x1:
                return payload.decode()

    def close(self):
        self.sock.close()


class Cdp:
    """One CDP connection (browser or page target)."""

    def __init__(self, ws_url):
        self.ws = WebSocket(ws_url)
        self.next_id = 0

    def call(self, method, **params):
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def close(self):
        self.ws.close()


class WebSdrWindow:
    """
    The browser process and its CDP connections. All CDP calls run one at a
    time in a worker thread; on_error(text) is called from that thread.
    """

    def __init__(self, browser, on_error):
        self.browser = browser
        self.on_error = on_error
        self.proc = None
        self.jobs = None
        self.browser_cdp = None
        self.page_cdp = None
        self.window_id = None

    def is_open(self):
        return self.proc is not None and self.proc.poll() is None

    def open(self, url, bounds):
        """bounds: (left, top, width, height) of the window, in screen pixels."""
        if self.is_open():
            return
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        port_file = PROFILE_DIR / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        left, top, width, height = bounds
        cmd = [self.browser, f"--app={url}", f"--user-data-dir={PROFILE_DIR}",
               "--remote-debugging-port=0", "--remote-allow-origins=*",
               "--autoplay-policy=no-user-gesture-required", "--no-first-run",
               f"--window-position={left},{top}", f"--window-size={width},{height}"]
        log.info("WebSDR: %s", url)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.jobs = queue.Queue()
        threading.Thread(target=self._run, args=(self.jobs, port_file, url), daemon=True).start()

    def move(self, bounds):
        if self.is_open():
            self.jobs.put(lambda: self._set_bounds(bounds))

    def run_js(self, js):
        if self.is_open():
            self.jobs.put(lambda: self.page_cdp.call("Runtime.evaluate", expression=js))

    def evaluate(self, js, on_result):
        """Evaluate js in the page; on_result(value, error) is called from the worker thread."""
        if not self.is_open():
            on_result(None, "WebSDR window is not open")
            return

        def job():
            try:
                r = self.page_cdp.call("Runtime.evaluate", expression=js, returnByValue=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "JS error"))
                on_result(r["result"].get("value"), None)
            except Exception as e:
                on_result(None, str(e))
        self.jobs.put(job)

    def close(self):
        if self.jobs:
            self.jobs.put(None)
            self.jobs = None
        if self.is_open():
            self.proc.terminate()
        self.proc = None

    # --- worker thread ---

    def _run(self, jobs, port_file, url):
        try:
            self._connect(port_file, url)
        except Exception as e:
            log.debug("WebSDR CDP connect failed", exc_info=True)
            self.on_error(f"WebSDR: no DevTools connection ({e}) - not following the keyer")
            return
        while True:
            job = jobs.get()
            if job is None:
                break
            try:
                job()
            except Exception as e:
                log.debug("WebSDR CDP call failed", exc_info=True)
                if self.is_open():
                    self.on_error(f"WebSDR: {e}")
        for cdp in (self.page_cdp, self.browser_cdp):
            if cdp:
                cdp.close()

    def _connect(self, port_file, url):
        deadline = time.monotonic() + START_TIMEOUT_S
        while not port_file.exists() or len(port_file.read_text().split()) < 2:
            if not self.is_open():
                # A browser already running with this profile takes the window over and we exit
                raise RuntimeError("browser exited - is another client's WebSDR window open?")
            if time.monotonic() > deadline:
                raise TimeoutError("browser did not start")
            time.sleep(0.2)
        port, path = port_file.read_text().split()[:2]
        self.browser_cdp = Cdp(f"ws://127.0.0.1:{port}{path}")
        # The profile may restore pages of an earlier session; ours is the one with our URL
        base = url.split("#")[0]
        while True:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                pages = [t for t in json.load(r) if t.get("type") == "page" and t["url"].startswith(base)]
            if pages:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("SDR page not found in the browser")
            time.sleep(0.2)
        self.page_cdp = Cdp(pages[0]["webSocketDebuggerUrl"])
        # Until the page has loaded, scripts run in the initial about:blank and are lost
        while self.page_cdp.call("Runtime.evaluate", expression="location.href")["result"].get("value") == "about:blank":
            if time.monotonic() > deadline:
                raise TimeoutError("SDR page did not load")
            time.sleep(0.2)
        self.window_id = self.browser_cdp.call("Browser.getWindowForTarget",
                                               targetId=pages[0]["id"])["windowId"]

    def _set_bounds(self, bounds):
        left, top, width, height = bounds
        self.browser_cdp.call("Browser.setWindowBounds", windowId=self.window_id,
                              bounds={"left": left, "top": top, "width": width, "height": height})
