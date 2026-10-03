"""
QO100TX - CW Daemon Client.

Sends CW macros to a cwdaemon-compatible keyer over UDP and logs QSOs
to Cloudlog as ADIF.
"""
import argparse
import copy
import json
import logging
import math
import queue
import re
import socket
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import ttk
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pyperclip

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "udp": {"host": "192.168.99.109", "port": 6789},
    "station": {"call": "SV0SYH", "name": "ONDRA", "locator": "KN10LO"},
    "speed_wpm": 20,
    "macros": {
        "cq": "CQ CQ de {mycall} {mycall} K",
        "rpt": "{call} HI UR {rst} NAME {name} loc {myloc} K",
        "tu": "TU 73 de {mycall}",
        "de": "de {mycall} {mycall}",
    },
    "cloudlog": {"url": "", "api_key": "", "station_id": ""},
    # Keyer web UI; if url is set, TX frequency is shown, tunable and logged.
    # correction_hz = real frequency (SDR/GPS) - frequency computed by the keyer
    "keyer_web": {"url": "http://192.168.99.109/", "apikey": "1111", "poll_s": 3, "correction_hz": 0},
    "adif": {
        "band": "13cm",
        "band_rx": "3cm",
        "freq": "2400.025",
        "freq_rx": "",
        "sat_name": "QO-100",
        "sat_mode": "S/X",
        # QO-100 NB downlink = uplink + 8089.5 MHz; used for FREQ_RX with keyer frequency
        "rx_offset_mhz": 8089.5,
    },
}


def merge(base, override):
    """Recursively merge dict override into a copy of base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path):
    path = Path(path)
    if not path.exists():
        log.warning("Config %s not found, using defaults", path)
        return copy.deepcopy(DEFAULT_CONFIG)
    with path.open(encoding="utf-8") as f:
        try:
            return merge(DEFAULT_CONFIG, json.load(f))
        except json.JSONDecodeError as e:
            sys.exit(f"Invalid config {path}: {e.msg} at line {e.lineno}, column {e.colno}")


class CwDaemon:
    """Minimal cwdaemon UDP client."""

    ESC = chr(27)

    def __init__(self, host, port):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _send_raw(self, data):
        self.sock.sendto(data.encode("ascii", errors="replace"), self.addr)

    def send(self, text):
        log.info("Sending - %s", text)
        self._send_raw(text)

    def set_speed(self, wpm):
        log.info("Speed %s WPM", wpm)
        self._send_raw(f"{self.ESC}2{wpm}")

    def abort(self):
        log.info("Abort")
        self._send_raw(f"{self.ESC}4")


def adif_field(name, value):
    value = str(value)
    return f"<{name}:{len(value)}>{value}"


def build_adif(call, locator, rst_sent, rst_rcvd, adif_cfg, when=None):
    when = when or datetime.now(timezone.utc)
    fields = [
        ("BAND", adif_cfg["band"]),
        ("BAND_RX", adif_cfg["band_rx"]),
        ("CALL", call),
        ("GRIDSQUARE", locator),
        ("MODE", "CW"),
        ("PROP_MODE", "SAT"),
        ("RST_RCVD", rst_rcvd),
        ("RST_SENT", rst_sent),
        ("SAT_MODE", adif_cfg["sat_mode"]),
        ("SAT_NAME", adif_cfg["sat_name"]),
        ("FREQ", adif_cfg["freq"]),
        ("FREQ_RX", adif_cfg["freq_rx"]),
        ("QSO_DATE", when.strftime("%Y%m%d")),
        ("TIME_ON", when.strftime("%H%M%S")),
    ]
    lines = [adif_field(name, value) for name, value in fields if value]
    lines.append("<EOR>")
    return "\n".join(lines)


class KeyerWeb:
    """
    Client for the QO-100 TX keyer web UI.

    The keyer holds the TX frequency as an index; frequency = index * STEP Hz.
    STEP and the allowed index range are read from the keyer page.
    """

    def __init__(self, url, apikey, correction_hz=0):
        self.url = url.rstrip("/")
        self.apikey = apikey
        self.correction_hz = correction_hz
        self.step = None
        self.min_index = None
        self.max_index = None
        self.power = None
        self.power_levels = []  # [(value, label)] from the keyer power select

    def _get(self, path, timeout=3, **params):
        params["apikey"] = self.apikey
        url = f"{self.url}{path}?{urlencode(params)}"
        return urllib.request.urlopen(url, timeout=timeout).read().decode("utf-8", errors="replace")

    def read_index(self):
        page = self._get("/")

        def find(pattern):
            match = re.search(pattern, page)
            if not match:
                raise ValueError(f"{pattern!r} not found on keyer page")
            return match.group(1)

        self.step = float(find(r"const\s+STEP\s*=\s*([\d.]+)"))
        self.min_index = int(find(r"const\s+MIN\s*=\s*(\d+)"))
        self.max_index = int(find(r"const\s+MAX\s*=\s*(\d+)"))
        options = re.findall(r'<option value="(\d+)"\s*(SELECTED)?\s*>([^<]*)</option>', page)
        self.power_levels = [(int(value), label.strip()) for value, _, label in options]
        self.power = next((int(value) for value, selected, _ in options if selected), None)
        return int(find(r'name="frq_index"\s+value="(\d+)"'))

    def set_power(self, value):
        self._get("/", pwr=value)
        self.power = value

    def command(self, name, label):
        """Press a keyer form button, e.g. ("cmd_T", "Tune") or ("cmd_B", "Break")."""
        # Tune keeps the keyer busy for 3 s before it answers
        self._get("/", timeout=8, **{name: label})

    def set_index(self, index):
        index = self.clamp(index)
        response = self._get("/frq", val=index).strip()
        if response != "OK":
            raise RuntimeError(f"Keyer answered {response!r}")
        return index

    def clamp(self, index):
        return min(max(index, self.min_index), self.max_index)

    def freq_hz(self, index):
        return index * self.step + self.correction_hz

    def index_for_hz(self, hz):
        return self.clamp(round((hz - self.correction_hz) / self.step))


class BackgroundWorker:
    """Runs blocking calls one at a time in a thread; callbacks run in the Tk loop."""

    def __init__(self, root):
        self.root = root
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()
        self._dispatch()

    def submit(self, func, callback):
        self.jobs.put((func, callback))

    def _run(self):
        while True:
            func, callback = self.jobs.get()
            try:
                result, error = func(), None
            except Exception as e:
                result, error = None, e
            self.results.put((callback, result, error))

    def _dispatch(self):
        while not self.results.empty():
            callback, result, error = self.results.get()
            callback(result, error)
        self.root.after(100, self._dispatch)


def format_mhz(hz):
    text = f"{hz / 1e6:.6f}"
    return f"{text[:-3]} {text[-3:]}"


def load_memories(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sorted(m["index"] for m in json.load(f))
    except FileNotFoundError:
        return []
    except (ValueError, KeyError, TypeError):
        log.exception("Invalid memories file %s", path)
        return []


def save_memories(path, indexes):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"index": i} for i in indexes], f, indent=2)


def test_cloudlog(base_url):
    """
    Check that we can make a request to the given cloudlog URL.
    """
    response = urllib.request.urlopen(f"{base_url}/index.php/api/statistics", timeout=10)
    if not 200 <= response.status < 300:
        raise RuntimeError(f"Unexpected HTTP status {response.status}")
    data = json.loads(response.read().decode())
    if "Today" not in data:
        log.warning("Unknown response from Cloudlog %s. May not be connected correctly.", data)
    return data


def upload_to_cloudlog(base_url, api_key, station_id, payload):
    data = {
        "key": api_key,
        "station_profile_id": station_id,
        "type": "adif",
        "string": payload,
    }
    req = urllib.request.Request(f"{base_url}/index.php/api/qso")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        response = urllib.request.urlopen(req, json.dumps(data).encode("utf-8"), timeout=10)
        log.info("Sent QSO to cloudlog at %s, got response %s", base_url, response.read().decode())
        return True
    except Exception:
        log.exception("Failed to send ADIF to cloudlog")
        return False


class App(tk.Tk):
    # (label, step in Hz); 0 = one keyer step (~198 Hz)
    TUNE_STEPS = [("1 step", 0), ("1 kHz", 1000), ("10 kHz", 10000), ("100 kHz", 100000)]
    # Ignore polled frequency this long after local tuning, so the display does not jump back
    TUNE_HOLD_S = 1.5

    def __init__(self, config, cw, cloudlog_ok, keyer=None, memories_path=None):
        super().__init__()
        self.config_data = config
        self.cw = cw
        self.cloudlog_ok = cloudlog_ok
        self.keyer = keyer
        self.memories_path = memories_path
        self.memories = load_memories(memories_path) if memories_path else []

        self.freq_index = None
        self.last_tune = 0.0
        self.pending_set = None
        self.last_power_set = 0.0
        self.tuning = False

        self.title("QO100TX - CW Daemon Client")
        self.geometry("+10+20")

        self.call_var = tk.StringVar()
        self.rst_var = tk.StringVar(value="599")
        self.rcvd_var = tk.StringVar(value="599")
        self.loc_var = tk.StringVar()
        self.free_var = tk.StringVar()
        self.speed_var = tk.StringVar(value=str(config["speed_wpm"]))
        self.status_var = tk.StringVar()
        self.freq_var = tk.StringVar(value="--- keyer offline")
        self.freq_rx_var = tk.StringVar()
        self.step_var = tk.IntVar(value=1000)
        self.goto_var = tk.StringVar()
        self.memory_var = tk.StringVar()
        self.power_var = tk.StringVar()

        self._build_widgets()
        self._bind_keys()

        if self.keyer:
            self.worker = BackgroundWorker(self)
            self.poll_freq()

        self.cw.set_speed(config["speed_wpm"])
        if not cloudlog_ok:
            self.set_status("Cloudlog not available - QSOs will not be logged")

    def _build_widgets(self):
        pad = {"padx": 2, "pady": 2}

        tk.Button(self, text="CQ CQ (F1)", command=self.send_cq).grid(column=1, row=0, sticky="we", **pad)

        tk.Label(self, text="Call:").grid(column=1, row=1, **pad)
        call_entry = tk.Entry(self, textvariable=self.call_var, width=12)
        call_entry.grid(column=2, row=1, **pad)
        call_entry.focus_set()
        tk.Button(self, text="CP", command=self.copy_call).grid(column=3, row=1, **pad)
        tk.Label(self, text="RST:").grid(column=4, row=1, **pad)
        tk.Entry(self, textvariable=self.rst_var, width=3).grid(column=5, row=1, **pad)
        tk.Button(self, text="TX (F2)", command=self.send_rpt).grid(column=6, row=1, **pad)
        tk.Label(self, text="LOC:").grid(column=7, row=1, **pad)
        tk.Entry(self, textvariable=self.loc_var, width=6).grid(column=8, row=1, **pad)

        tk.Label(self, text="RCVD:").grid(column=4, row=2, **pad)
        tk.Entry(self, textvariable=self.rcvd_var, width=3).grid(column=5, row=2, **pad)

        tk.Button(self, text="73 73 (F3)", command=self.send_tu).grid(column=1, row=2, sticky="we", **pad)

        free_entry = tk.Entry(self, textvariable=self.free_var, width=20)
        free_entry.grid(column=2, row=3, **pad)
        free_entry.bind("<Return>", lambda e: self.send_free())
        tk.Button(self, text="TX (F5)", command=self.send_free).grid(column=3, row=3, **pad)

        tk.Button(self, text="de .. (F4)", command=self.send_de).grid(column=1, row=4, sticky="we", **pad)

        tk.Spinbox(self, from_=10, to=30, width=3, textvariable=self.speed_var).grid(column=2, row=5, **pad)
        tk.Button(self, text="SET", command=self.set_speed).grid(column=3, row=5, **pad)
        tk.Button(self, text="STOP (Esc)", fg="red", command=self.stop_tx).grid(column=6, row=5, **pad)

        tk.Button(self, text="Log QSO", command=self.log_qso).grid(column=1, row=6, sticky="we", **pad)

        if self.keyer:
            self._build_freq_widgets().grid(column=1, row=7, columnspan=8, sticky="we", **pad)

        tk.Label(self, textvariable=self.status_var, anchor="w").grid(
            column=1, row=8, columnspan=8, sticky="we", **pad)

    def _build_freq_widgets(self):
        pad = {"padx": 2, "pady": 2}
        frame = tk.LabelFrame(self, text="Transmitter (MHz)")

        tk.Button(frame, text="\u2212", width=2, command=lambda: self.tune_step(-1)).grid(column=0, row=0, **pad)
        freq_label = tk.Label(frame, textvariable=self.freq_var, font=("Courier", 18, "bold"), width=16)
        freq_label.grid(column=1, row=0, columnspan=3, **pad)
        tk.Button(frame, text="+", width=2, command=lambda: self.tune_step(1)).grid(column=4, row=0, **pad)
        tk.Label(frame, textvariable=self.freq_rx_var).grid(column=5, row=0, columnspan=3, sticky="w", **pad)

        # Mouse wheel over the frequency tunes (Button-4/5 on X11, MouseWheel elsewhere)
        freq_label.bind("<Button-4>", lambda e: self.tune_step(1))
        freq_label.bind("<Button-5>", lambda e: self.tune_step(-1))
        freq_label.bind("<MouseWheel>", lambda e: self.tune_step(1 if e.delta > 0 else -1))

        tk.Label(frame, text="Step:").grid(column=0, row=1, **pad)
        for col, (label, hz) in enumerate(self.TUNE_STEPS, start=1):
            tk.Radiobutton(frame, text=label, variable=self.step_var, value=hz).grid(column=col, row=1, **pad)

        goto_entry = tk.Entry(frame, textvariable=self.goto_var, width=12)
        goto_entry.grid(column=5, row=1, **pad)
        goto_entry.bind("<Return>", lambda e: self.goto_freq())
        tk.Button(frame, text="GO", command=self.goto_freq).grid(column=6, row=1, **pad)

        tk.Label(frame, text="Memory:").grid(column=0, row=2, **pad)
        self.memory_box = ttk.Combobox(frame, textvariable=self.memory_var, state="readonly", width=16)
        self.memory_box.grid(column=1, row=2, columnspan=2, sticky="we", **pad)
        self.memory_box.bind("<<ComboboxSelected>>", lambda e: self.recall_memory())
        tk.Button(frame, text="Save", command=self.save_memory).grid(column=3, row=2, **pad)
        tk.Button(frame, text="Delete", command=self.delete_memory).grid(column=4, row=2, **pad)
        self.refresh_memories()

        tk.Label(frame, text="Power:").grid(column=0, row=3, **pad)
        self.power_box = ttk.Combobox(frame, textvariable=self.power_var, state="readonly", width=6)
        self.power_box.grid(column=1, row=3, sticky="w", **pad)
        self.power_box.bind("<<ComboboxSelected>>", lambda e: self.set_power())
        self.tune_button = tk.Button(frame, text="TUNE", fg="red", command=self.toggle_tune)
        self.tune_button.grid(column=3, row=3, **pad)
        return frame

    def _bind_keys(self):
        self.bind("<F1>", lambda e: self.send_cq())
        self.bind("<F2>", lambda e: self.send_rpt())
        self.bind("<F3>", lambda e: self.send_tu())
        self.bind("<F4>", lambda e: self.send_de())
        self.bind("<F5>", lambda e: self.send_free())
        self.bind("<Escape>", lambda e: self.stop_tx())
        if self.keyer:
            self.bind("<Prior>", lambda e: self.tune_step(1))
            self.bind("<Next>", lambda e: self.tune_step(-1))

    def set_status(self, text):
        self.status_var.set(text)

    def call(self):
        return self.call_var.get().strip().upper()

    def macro(self, name):
        station = self.config_data["station"]
        return self.config_data["macros"][name].format(
            mycall=station["call"],
            name=station["name"],
            myloc=station["locator"],
            call=self.call(),
            rst=self.rst_var.get().strip(),
        )

    def send(self, text):
        if not text:
            return
        try:
            self.cw.send(text)
            self.set_status(f"Sent: {text}")
        except OSError as e:
            log.exception("UDP send failed")
            self.set_status(f"Send failed: {e}")

    def send_cq(self):
        self.send(self.macro("cq"))

    def send_rpt(self):
        self.send(self.macro("rpt"))

    def send_tu(self):
        self.send(self.macro("tu"))

    def send_de(self):
        self.send(self.macro("de"))

    def send_free(self):
        self.send(self.free_var.get().strip().upper())

    def copy_call(self):
        pyperclip.copy(self.call())

    def set_speed(self):
        try:
            self.cw.set_speed(int(self.speed_var.get()))
            self.set_status(f"Speed {self.speed_var.get()} WPM")
        except (ValueError, OSError) as e:
            self.set_status(f"Speed not set: {e}")

    def stop_tx(self):
        self.cw.abort()
        if self.keyer:
            self.stop_tune()

    # --- tune and power ---

    def keyer_command(self, name, label, done_status, done=None):
        def on_done(_, error):
            if error:
                log.warning("Keyer %s failed: %s", label, error)
                self.set_status(f"{label} failed: {error}")
            else:
                self.set_status(done_status)
            if done:
                done()
        self.worker.submit(lambda: self.keyer.command(name, label), on_done)

    def toggle_tune(self):
        """The keyer firmware sends a fixed 3 s carrier and cannot be interrupted meanwhile."""
        if self.tuning:
            return
        self.tuning = True
        self.tune_button.config(text="TUNE \u25cf", relief="sunken")
        self.set_status("TUNE - carrier on for 3 s")

        def done():
            self.tuning = False
            self.tune_button.config(text="TUNE", relief="raised")
        self.keyer_command("cmd_T", "Tune", "TUNE finished", done)

    def stop_tune(self):
        """Send Break: clears the keyer CW queue and stops any carrier (used by STOP/Esc)."""
        self.keyer_command("cmd_B", "Break", "Break - TX stopped")

    def update_power_display(self):
        self.power_box["values"] = [label for _, label in self.keyer.power_levels]
        label = dict(self.keyer.power_levels).get(self.keyer.power, "")
        self.power_var.set(label)

    def set_power(self):
        pos = self.power_box.current()
        if pos < 0:
            return
        value, label = self.keyer.power_levels[pos]
        self.last_power_set = time.monotonic()

        def on_done(_, error):
            self.last_power_set = time.monotonic()
            if error:
                log.warning("Setting power failed: %s", error)
                self.set_status(f"Power not set: {error}")
            else:
                self.set_status(f"Power {label}")
        self.worker.submit(lambda: self.keyer.set_power(value), on_done)

    # --- frequency ---

    def poll_freq(self):
        self.worker.submit(self.keyer.read_index, self._on_poll)

    def _on_poll(self, index, error):
        if error:
            log.debug("Keyer poll failed: %s", error)
            self.freq_index = None
            self.update_freq_display()
        else:
            if self.pending_set is None and time.monotonic() - self.last_tune > self.TUNE_HOLD_S:
                self.freq_index = index
                self.update_freq_display()
            if time.monotonic() - self.last_power_set > self.TUNE_HOLD_S:
                self.update_power_display()
        self.after(int(self.config_data["keyer_web"]["poll_s"] * 1000), self.poll_freq)

    def update_freq_display(self):
        if self.freq_index is None:
            self.freq_var.set("--- keyer offline")
            self.freq_rx_var.set("")
            return
        hz = self.keyer.freq_hz(self.freq_index)
        self.freq_var.set(format_mhz(hz))
        offset = self.config_data["adif"]["rx_offset_mhz"]
        self.freq_rx_var.set(f"RX {format_mhz(hz + offset * 1e6)}" if offset else "")

    def tune_to_index(self, index):
        if self.freq_index is None:
            self.set_status("Keyer offline - cannot tune")
            return
        self.freq_index = self.keyer.clamp(index)
        self.last_tune = time.monotonic()
        self.update_freq_display()
        # Coalesce fast tuning (mouse wheel) into one request
        if self.pending_set is None:
            self.pending_set = self.after(150, self._send_freq)

    def _send_freq(self):
        self.pending_set = None
        index = self.freq_index
        self.worker.submit(lambda: self.keyer.set_index(index), self._on_set)

    def _on_set(self, index, error):
        self.last_tune = time.monotonic()
        if error:
            log.warning("Setting frequency failed: %s", error)
            self.set_status(f"Tune failed: {error}")

    def tune_step(self, direction):
        if self.freq_index is None:
            return
        step_hz = self.step_var.get()
        if not step_hz:
            self.tune_to_index(self.freq_index + direction)
            return
        # Snap to the step grid, e.g. 2400.0217 + 1 kHz -> 2400.022
        hz = self.keyer.freq_hz(self.freq_index)
        units = math.floor(hz / step_hz) + 1 if direction > 0 else math.ceil(hz / step_hz) - 1
        index = self.keyer.index_for_hz(units * step_hz)
        # Grid point within keyer resolution of the current frequency: go one grid step further
        if index == self.freq_index:
            index = self.keyer.index_for_hz((units + direction) * step_hz)
        self.tune_to_index(index)

    def goto_freq(self):
        try:
            mhz = float(self.goto_var.get().replace(",", ".").replace(" ", ""))
        except ValueError:
            self.set_status("Enter frequency in MHz, e.g. 2400.050")
            return
        self.tune_to_index(self.keyer.index_for_hz(mhz * 1e6))

    def refresh_memories(self):
        self.memory_box["values"] = [self.memory_label(i) for i in self.memories]

    def memory_label(self, index):
        return format_mhz(self.keyer.freq_hz(index)) if self.keyer.step else str(index)

    def save_memory(self):
        if self.freq_index is None:
            self.set_status("Keyer offline - nothing to save")
            return
        if self.freq_index not in self.memories:
            self.memories = sorted(self.memories + [self.freq_index])
            save_memories(self.memories_path, self.memories)
        self.refresh_memories()
        self.memory_var.set(self.memory_label(self.freq_index))
        self.set_status(f"Saved {self.memory_label(self.freq_index)}")

    def selected_memory(self):
        pos = self.memory_box.current()
        return self.memories[pos] if pos >= 0 else None

    def recall_memory(self):
        index = self.selected_memory()
        if index is not None:
            self.tune_to_index(index)

    def delete_memory(self):
        index = self.selected_memory()
        if index is None:
            return
        self.memories.remove(index)
        save_memories(self.memories_path, self.memories)
        self.memory_var.set("")
        self.refresh_memories()
        self.set_status(f"Deleted {self.memory_label(index)}")

    # --- logging ---

    def adif_config(self):
        """ADIF settings with the current keyer frequency, if known."""
        adif_cfg = dict(self.config_data["adif"])
        if self.keyer is None or self.freq_index is None:
            if self.keyer:
                log.warning("Keyer frequency unknown, logging %s", adif_cfg["freq"])
            return adif_cfg
        mhz = self.keyer.freq_hz(self.freq_index) / 1e6
        adif_cfg["freq"] = f"{mhz:.6f}"
        if adif_cfg["rx_offset_mhz"]:
            adif_cfg["freq_rx"] = f"{mhz + adif_cfg['rx_offset_mhz']:.6f}"
        return adif_cfg

    def log_qso(self):
        call = self.call()
        if not call:
            self.set_status("Enter a call before logging")
            return
        adif = build_adif(
            call,
            self.loc_var.get().strip().upper(),
            self.rst_var.get().strip(),
            self.rcvd_var.get().strip(),
            self.adif_config(),
        )
        log.info("LOG QSO\n%s", adif)
        cl = self.config_data["cloudlog"]
        if not cl["url"]:
            self.set_status("Cloudlog URL not configured")
            return
        if upload_to_cloudlog(cl["url"], cl["api_key"], cl["station_id"], adif):
            self.set_status(f"Logged {call} ✓")
            self.call_var.set("")
            self.loc_var.set("")
        else:
            self.set_status(f"Logging {call} failed - see console")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="URL for CloudLog (overrides config).")
    parser.add_argument("api_key", nargs="?", help="CloudLog API key (overrides config).")
    parser.add_argument("station_id", nargs="?", help="CloudLog station ID (overrides config).")
    parser.add_argument("--config", default=Path(__file__).with_name("config.json"),
                        help="Path to JSON config file.")
    parser.add_argument("--verbose", action="store_true", help="Output debugging information.")
    args = parser.parse_args()

    log.setLevel("DEBUG" if args.verbose else "INFO")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    log.addHandler(handler)

    config = load_config(args.config)
    for key in ("url", "api_key", "station_id"):
        if getattr(args, key):
            config["cloudlog"][key] = getattr(args, key)
    config["cloudlog"]["url"] = config["cloudlog"]["url"].rstrip("/")

    cloudlog_ok = False
    if config["cloudlog"]["url"]:
        try:
            test_cloudlog(config["cloudlog"]["url"])
            cloudlog_ok = True
            log.info("Successfully tested connection to Cloudlog")
        except Exception:
            log.exception("Unable to connect to Cloudlog")
    else:
        log.warning("Cloudlog URL not configured")

    udp = config["udp"]
    log.info("UDP target %s:%s", udp["host"], udp["port"])
    cw = CwDaemon(udp["host"], udp["port"])

    keyer_cfg = config["keyer_web"]
    keyer = None
    if keyer_cfg["url"]:
        keyer = KeyerWeb(keyer_cfg["url"], keyer_cfg["apikey"], keyer_cfg["correction_hz"])
    memories_path = Path(args.config).with_name("memories.json")

    App(config, cw, cloudlog_ok, keyer, memories_path).mainloop()


if __name__ == "__main__":
    main()
