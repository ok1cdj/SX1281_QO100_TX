"""
QO100TX - CW Daemon Client.

Sends CW macros to a cwdaemon-compatible keyer over UDP and logs QSOs
to Cloudlog as ADIF.
"""
import argparse
import copy
import json
import logging
import socket
import sys
import tkinter as tk
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

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
    "adif": {
        "band": "13cm",
        "band_rx": "3cm",
        "freq": "2400.025",
        "freq_rx": "",
        "sat_name": "QO-100",
        "sat_mode": "S/X",
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
    def __init__(self, config, cw, cloudlog_ok):
        super().__init__()
        self.config_data = config
        self.cw = cw
        self.cloudlog_ok = cloudlog_ok

        self.title("QO100TX - CW Daemon Client")
        self.geometry("+10+20")

        self.call_var = tk.StringVar()
        self.rst_var = tk.StringVar(value="599")
        self.rcvd_var = tk.StringVar(value="599")
        self.loc_var = tk.StringVar()
        self.free_var = tk.StringVar()
        self.speed_var = tk.StringVar(value=str(config["speed_wpm"]))
        self.status_var = tk.StringVar()

        self._build_widgets()
        self._bind_keys()

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
        tk.Button(self, text="STOP (Esc)", fg="red", command=self.cw.abort).grid(column=6, row=5, **pad)

        tk.Button(self, text="Log QSO", command=self.log_qso).grid(column=1, row=6, sticky="we", **pad)

        tk.Label(self, textvariable=self.status_var, anchor="w").grid(
            column=1, row=7, columnspan=8, sticky="we", **pad)

    def _bind_keys(self):
        self.bind("<F1>", lambda e: self.send_cq())
        self.bind("<F2>", lambda e: self.send_rpt())
        self.bind("<F3>", lambda e: self.send_tu())
        self.bind("<F4>", lambda e: self.send_de())
        self.bind("<F5>", lambda e: self.send_free())
        self.bind("<Escape>", lambda e: self.cw.abort())

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
            self.config_data["adif"],
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

    App(config, cw, cloudlog_ok).mainloop()


if __name__ == "__main__":
    main()
