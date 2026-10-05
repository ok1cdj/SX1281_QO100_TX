"""
QO100TX - CW Daemon Client (Tk GUI).

Sends CW macros to a cwdaemon-compatible keyer over UDP and logs QSOs
to Cloudlog as ADIF. The logic lives in cwcore.py.
"""
import argparse
import logging
import queue
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

import pyperclip

from cwcore import ConfigError, Session, check_cloudlog, load_config, make_session

log = logging.getLogger("pyCWdclient")


class App(tk.Tk):
    def __init__(self, config, memories_path=None, cloudlog_ok=False):
        super().__init__()
        # Results from worker threads, handed over to the Tk thread by _dispatch()
        self.results = queue.Queue()
        self.session = make_session(config, self.results.put, self.call_later, memories_path, cloudlog_ok)
        self.keyer = self.session.keyer

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

        self.session.on_status = self.status_var.set
        self.session.on_freq = self.update_freq_display
        self.session.on_power = self.update_power_display
        self.session.on_memories = self.refresh_memories
        self._dispatch()
        self.session.start()

    def call_later(self, seconds, func):
        self.after(int(seconds * 1000), func)

    def _dispatch(self):
        while not self.results.empty():
            self.results.get()()
        self.after(100, self._dispatch)

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
        for col, (label, hz) in enumerate(Session.TUNE_STEPS, start=1):
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
        tk.Button(frame, text="DOTS (F6)", command=self.send_dots).grid(column=3, row=3, **pad)
        return frame

    def _bind_keys(self):
        self.bind("<F1>", lambda e: self.send_cq())
        self.bind("<F2>", lambda e: self.send_rpt())
        self.bind("<F3>", lambda e: self.send_tu())
        self.bind("<F4>", lambda e: self.send_de())
        self.bind("<F5>", lambda e: self.send_free())
        self.bind("<Escape>", lambda e: self.stop_tx())
        if self.keyer:
            self.bind("<F6>", lambda e: self.send_dots())
            self.bind("<Prior>", lambda e: self.tune_step(1))
            self.bind("<Next>", lambda e: self.tune_step(-1))

    def send_macro(self, name):
        self.session.send_macro(name, self.call_var.get(), self.rst_var.get())

    def send_cq(self):
        self.send_macro("cq")

    def send_rpt(self):
        self.send_macro("rpt")

    def send_tu(self):
        self.send_macro("tu")

    def send_de(self):
        self.send_macro("de")

    def send_free(self):
        self.session.send(self.free_var.get().strip().upper())

    def copy_call(self):
        pyperclip.copy(self.call_var.get().strip().upper())

    def set_speed(self):
        self.session.set_speed(self.speed_var.get())

    def stop_tx(self):
        self.session.stop_tx()

    def send_dots(self):
        self.session.send_dots()

    def tune_step(self, direction):
        self.session.tune_step(direction, self.step_var.get())

    def goto_freq(self):
        self.session.goto_freq(self.goto_var.get())

    def update_freq_display(self):
        self.freq_var.set(self.session.freq_text())
        self.freq_rx_var.set(self.session.rx_text())

    def update_power_display(self):
        self.power_box["values"] = self.session.power_labels()
        pos = self.session.power_position()
        self.power_var.set(self.session.power_labels()[pos] if pos >= 0 else "")

    def set_power(self):
        self.session.set_power(self.power_box.current())

    def refresh_memories(self):
        self.memory_box["values"] = self.session.memory_labels()

    def save_memory(self):
        pos = self.session.save_memory()
        if pos is not None:
            self.memory_var.set(self.session.memory_labels()[pos])

    def recall_memory(self):
        self.session.recall_memory(self.memory_box.current())

    def delete_memory(self):
        pos = self.memory_box.current()
        if pos >= 0:
            self.session.delete_memory(pos)
            self.memory_var.set("")

    def log_qso(self):
        def clear():
            self.call_var.set("")
            self.loc_var.set("")
        self.session.log_qso(self.call_var.get(), self.loc_var.get(), self.rst_var.get(),
                             self.rcvd_var.get(), clear)


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

    try:
        config = load_config(args.config)
    except ConfigError as e:
        sys.exit(str(e))
    for key in ("url", "api_key", "station_id"):
        if getattr(args, key):
            config["cloudlog"][key] = getattr(args, key).rstrip("/") if key == "url" else getattr(args, key)

    cloudlog_ok = check_cloudlog(config)
    memories_path = Path(args.config).with_name("memories.json")
    App(config, memories_path, cloudlog_ok).mainloop()


if __name__ == "__main__":
    main()
