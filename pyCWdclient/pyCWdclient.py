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

try:
    import hellrx
except ImportError:     # numpy missing - no Hell receiver
    hellrx = None

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
        self.mode_var = tk.StringVar(value="CW")

        self._build_widgets()
        self._bind_keys()

        self.session.on_status = self.status_var.set
        self.session.on_freq = self.update_freq_display
        self.session.on_power = self.update_power_display
        self.session.on_memories = self.refresh_memories
        if self.hell_rx:
            self.protocol("WM_DELETE_WINDOW", self.close)
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
        if self.keyer:
            mode_frame = tk.Frame(self)
            mode_frame.grid(column=4, row=5, columnspan=2, **pad)
            for mode in Session.MODES:
                tk.Radiobutton(mode_frame, text=mode.title(), variable=self.mode_var, value=mode,
                               command=self.set_mode).pack(side="left")

        tk.Button(self, text="Log QSO", command=self.log_qso).grid(column=1, row=6, sticky="we", **pad)

        if self.keyer:
            self._build_freq_widgets().grid(column=1, row=7, columnspan=8, sticky="we", **pad)

        tk.Label(self, textvariable=self.status_var, anchor="w").grid(
            column=1, row=8, columnspan=8, sticky="we", **pad)

        self.hell_rx = None
        if hellrx and hellrx.available():
            self._build_hell_rx().grid(column=1, row=9, columnspan=8, sticky="we", **pad)

    # Feld Hell receiver: image columns are drawn HELL_SCALE times bigger
    HELL_COLUMNS = 350
    HELL_SCALE = 2

    def _build_hell_rx(self):
        pad = {"padx": 2, "pady": 2}
        cfg = self.session.config["hell_rx"]
        self.hell_rx = hellrx.HellReceiver(cfg["source"], cfg["tone_hz"], width=self.HELL_COLUMNS)
        width = self.HELL_COLUMNS * self.HELL_SCALE
        frame = tk.LabelFrame(self, text="Feld Hell RX")

        self.hell_btn = tk.Button(frame, text="Start RX", width=8, command=self.toggle_hell_rx)
        self.hell_btn.grid(column=0, row=0, **pad)
        self.hell_tone_var = tk.StringVar()
        tk.Label(frame, textvariable=self.hell_tone_var, width=10).grid(column=1, row=0, **pad)
        tk.Label(frame, text="Gain:").grid(column=2, row=0, **pad)
        self.hell_gain = tk.Scale(frame, from_=0.5, to=4, resolution=0.1, orient="horizontal",
                                  showvalue=False, length=100)
        self.hell_gain.set(1.5)
        self.hell_gain.grid(column=3, row=0, **pad)
        tk.Label(frame, text="Slant %:").grid(column=4, row=0, **pad)
        self.hell_slant_var = tk.StringVar(value="0.0")
        slant = tk.Spinbox(frame, from_=-2, to=2, increment=0.05, width=5, textvariable=self.hell_slant_var,
                           command=self.set_hell_slant)
        slant.bind("<Return>", lambda e: self.set_hell_slant())
        slant.grid(column=5, row=0, **pad)
        tk.Button(frame, text="Clear", command=self.hell_rx.clear).grid(column=6, row=0, **pad)

        # Waterfall 0..3 kHz, click to set the tone
        self.hell_wf_img = tk.PhotoImage(width=width, height=40)
        self.hell_wf = tk.Canvas(frame, width=width, height=40, highlightthickness=0, cursor="crosshair")
        self.hell_wf.create_image(0, 0, image=self.hell_wf_img, anchor="nw")
        self.hell_marker = self.hell_wf.create_line(0, 0, 0, 40, fill="red")
        self.hell_wf.bind("<Button-1>", lambda e: self.set_hell_tone(e.x))
        self.hell_wf.grid(column=0, row=1, columnspan=7, **pad)

        height = 2 * hellrx.COLUMN * self.HELL_SCALE
        self.hell_img = tk.PhotoImage(width=width, height=height)
        tk.Label(frame, image=self.hell_img, borderwidth=0).grid(column=0, row=2, columnspan=7, **pad)
        self._show_hell_tone()
        return frame

    def toggle_hell_rx(self):
        if self.hell_rx.running():
            self.hell_rx.stop()
            self.hell_btn.config(text="Start RX")
        else:
            self.hell_rx.start()
            self.hell_btn.config(text="Stop RX")
            self._update_hell_rx()

    def _update_hell_rx(self):
        if not self.hell_rx.running():
            self.hell_btn.config(text="Start RX")
            if self.hell_rx.error:
                self.status_var.set(f"Hell RX: {self.hell_rx.error}")
            return
        img, wf, _ = self.hell_rx.snapshot()
        self.hell_img.configure(data=hellrx.to_pgm(img, self.hell_gain.get(), self.HELL_SCALE), format="PPM")
        # Waterfall bright on dark: to_pgm draws high values dark
        wf = (1 - wf).repeat(self.HELL_SCALE, axis=1)
        self.hell_wf_img.configure(data=hellrx.to_pgm(wf), format="PPM")
        self.after(100, self._update_hell_rx)

    def set_hell_tone(self, x):
        width = self.HELL_COLUMNS * self.HELL_SCALE
        self.hell_rx.set_tone(x / width * hellrx.WATERFALL_MAX_HZ)
        self._show_hell_tone()

    def _show_hell_tone(self):
        hz = self.hell_rx.tone_hz
        x = hz / hellrx.WATERFALL_MAX_HZ * self.HELL_COLUMNS * self.HELL_SCALE
        self.hell_wf.coords(self.hell_marker, x, 0, x, 40)
        self.hell_tone_var.set(f"{hz:.0f} Hz")

    def set_hell_slant(self):
        try:
            self.hell_rx.set_slant(float(self.hell_slant_var.get()) / 100)
        except ValueError:
            pass

    def close(self):
        self.hell_rx.stop()
        self.destroy()

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
            self.bind("<F7>", lambda e: self.toggle_mode())
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

    def set_mode(self):
        if not self.session.set_mode(self.mode_var.get()):
            self.mode_var.set(self.session.mode)

    def toggle_mode(self):
        self.mode_var.set("HELL" if self.session.mode == "CW" else "CW")
        self.set_mode()

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
