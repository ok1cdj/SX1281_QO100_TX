"""
QO100TX - CW Daemon Client for Pythonista (iPad / iPhone).

Copy this file, cwcore.py and config.json into one Pythonista folder and run
this file. The logic lives in cwcore.py, shared with the Tk client.
"""
import faulthandler
import heapq
import itertools
import logging
import queue
import threading
import time
from pathlib import Path

import clipboard
import console
import ui

from cwcore import ConfigError, Session, WebSdrTuner, check_wavelog, load_config, make_session

log = logging.getLogger("pyCWdclient")

ROW_H = 44
FREQ_H = 64
PAD = 6
STOP_COLOR = "#d32f2f"
SPEED_MIN, SPEED_MAX = 10, 40
SDR_MAX_FRACTION = 0.55          # the SDR takes at most this part of the screen height


class Loop:
    """
    Event loop thread that runs all Session code, with timers.

    UI actions only post work here and return at once. Views are updated from
    this thread, which Pythonista allows. objc_util.on_main_thread and ui.delay
    are not used: with them Pythonista crashed when tuning.
    """

    def __init__(self):
        self.jobs = queue.Queue()
        self.timers = []                 # heap of (due, seq, func)
        self.seq = itertools.count()
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def post(self, func):
        """Run func in the loop thread; callable from any thread."""
        self.jobs.put(func)

    def call_later(self, seconds, func):
        due = time.monotonic() + seconds
        self.post(lambda: heapq.heappush(self.timers, (due, next(self.seq), func)))

    def stop(self):
        self.running = False
        self.post(lambda: None)

    def _run(self):
        while self.running:
            timeout = max(0.0, self.timers[0][0] - time.monotonic()) if self.timers else None
            try:
                self._call(self.jobs.get(timeout=timeout))
            except queue.Empty:
                pass
            while self.running and self.timers and self.timers[0][0] <= time.monotonic():
                self._call(heapq.heappop(self.timers)[2])

    @staticmethod
    def _call(func):
        try:
            func()
        except Exception:
            log.exception("Error in %r", func)


def button(title, action, color=None):
    b = ui.Button(title=title, action=action)
    b.border_width = 1
    b.corner_radius = 6
    b.font = ("<system-bold>", 17)
    if color:
        b.background_color = color
        b.tint_color = "white"
    return b


def label(text="", size=17, align=ui.ALIGN_LEFT, font="<system>"):
    return ui.Label(text=text, font=(font, size), alignment=align)


def field(text="", placeholder="", caps=True, keyboard=ui.KEYBOARD_DEFAULT, delegate=None):
    f = ui.TextField(text=text, placeholder=placeholder)
    f.autocapitalization_type = ui.AUTOCAPITALIZE_ALL if caps else ui.AUTOCAPITALIZE_NONE
    f.autocorrection_type = False
    f.spellchecking_type = False
    f.keyboard_type = keyboard
    f.clear_button_mode = "while_editing"
    if delegate:
        f.delegate = delegate
    return f


class ReturnKey:
    """TextField delegate: the return key runs an action instead of only ending editing."""

    def __init__(self, action):
        self.action = action

    def textfield_should_return(self, textfield):
        textfield.end_editing()
        self.action(textfield)
        return True


class MemoryList:
    """
    TableView data source / delegate: tap recalls, swipe left deletes.

    Keeps its own copy of the labels so the table stays consistent on the UI
    thread while the session changes in the loop thread.
    """

    def __init__(self, labels, loop, session, on_pick):
        self.labels = list(labels)
        self.loop = loop
        self.session = session
        self.on_pick = on_pick

    def tableview_number_of_rows(self, tv, section):
        return len(self.labels)

    def tableview_cell_for_row(self, tv, section, row):
        cell = ui.TableViewCell()
        cell.text_label.text = self.labels[row]
        cell.text_label.font = ("Menlo", 20)
        return cell

    def tableview_did_select(self, tv, section, row):
        self.loop.post(lambda: self.session.recall_memory(row))
        self.on_pick()

    def tableview_can_delete(self, tv, section, row):
        return True

    def tableview_delete(self, tv, section, row):
        self.labels.pop(row)
        self.loop.post(lambda: self.session.delete_memory(row))
        tv.reload()


class MainView(ui.View):
    def __init__(self, config, memories_path):
        self.name = "QO100TX - CW"
        self.background_color = "white"
        self.config = config
        self.loop = Loop()
        # wavelog_ok=True: the check runs in the background and reports a failure itself
        self.session = make_session(config, self.loop.post, self.loop.call_later, memories_path,
                                    wavelog_ok=True)
        self.keyer = self.session.keyer

        self.scroll = ui.ScrollView(flex="WH")
        self.add_subview(self.scroll)
        self.rows = []
        # Web SDR under the controls while the SDR button is on
        self.sdr = None
        self.sdr_loaded = False
        self.sdr_tuner = WebSdrTuner(config["websdr"]) if config["websdr"]["url"] else None
        self._build()

        self.session.on_status = self.set_status
        self.session.on_freq = self.update_freq
        self.session.on_power = self.update_power
        self.loop.post(self.session.start)
        threading.Thread(target=self._check_wavelog, daemon=True).start()

    # --- layout ---

    def row(self, height, *items):
        """items: (view, weight) pairs laid out left to right."""
        for view, _ in items:
            self.scroll.add_subview(view)
        self.rows.append((height, items))

    def layout(self):
        if self.sdr:
            sdr_h = min(self.config["websdr"]["height"], self.height * SDR_MAX_FRACTION)
            self.scroll.frame = (0, 0, self.width, self.height - sdr_h)
            self.sdr.frame = (0, self.height - sdr_h, self.width, sdr_h)
        else:
            self.scroll.frame = self.bounds
        width = self.width - 2 * PAD
        y = PAD
        for height, items in self.rows:
            total = sum(weight for _, weight in items)
            avail = width - PAD * (len(items) - 1)
            x = PAD
            for view, weight in items:
                w = avail * weight / total
                view.frame = (x, y, w, height)
                x += w + PAD
            y += height + PAD
        self.scroll.content_size = (self.width, y)

    def act(self, func):
        """Button action that runs func in the loop thread."""
        return lambda _sender=None: self.loop.post(func)

    def _build(self):
        s = self.session
        act = self.act
        if self.keyer:
            self.freq_label = label("--- keyer offline", 34, ui.ALIGN_CENTER, "Menlo-Bold")
            self.row(FREQ_H,
                     (button("−", act(lambda: self.tune(-1))), 1),
                     (self.freq_label, 5),
                     (button("+", act(lambda: self.tune(1))), 1))
            self.rx_label = label("", 17, ui.ALIGN_CENTER, "Menlo")
            self.step_ctl = ui.SegmentedControl(segments=[name for name, _ in Session.TUNE_STEPS])
            self.step_ctl.selected_index = 1   # 1 kHz
            self.row(ROW_H, (self.rx_label, 1), (self.step_ctl, 1))

            self.goto_field = field(placeholder="MHz, e.g. 2400.050", caps=False,
                                    keyboard=ui.KEYBOARD_DECIMAL_PAD, delegate=ReturnKey(act(self.goto)))
            self.row(ROW_H,
                     (self.goto_field, 3),
                     (button("GO", act(self.goto)), 1),
                     (button("Memories", self.show_memories), 2),
                     (button("Save", act(s.save_memory)), 1))

            self.power_ctl = ui.SegmentedControl(segments=["--"], action=self.set_power)
            self.row(ROW_H,
                     (label("Power mW"), 1),
                     (self.power_ctl, 5),
                     (button("DOTS", act(s.send_dots)), 2))

            self.mode_ctl = ui.SegmentedControl(segments=[Session.MODE_LABELS[m] for m in Session.MODES],
                                                action=self.set_mode)
            self.mode_ctl.selected_index = 0
            cal = button("Cal", self.act(self.calibrate)) if self.sdr_tuner and self.sdr_tuner.calibrates() else label("")
            self.row(ROW_H, (label("Mode"), 1), (self.mode_ctl, 3), (cal, 2), (self.sdr_button(), 2))
        elif self.sdr_tuner:
            self.row(ROW_H, (label(""), 6), (self.sdr_button(), 2))

        self.row(ROW_H,
                 (button("CQ", act(lambda: self.macro("cq"))), 1),
                 (button("RPT", act(lambda: self.macro("rpt"))), 1),
                 (button("73", act(lambda: self.macro("tu"))), 1),
                 (button("de ..", act(lambda: self.macro("de"))), 1))

        self.call_field = field(placeholder="Call")
        self.loc_field = field(placeholder="Locator")
        self.row(ROW_H,
                 (label("Call"), 1), (self.call_field, 3),
                 (button("Copy", act(self.copy_call)), 1),
                 (label("LOC"), 1), (self.loc_field, 2))

        self.rst_field = field("599", keyboard=ui.KEYBOARD_NUMBER_PAD)
        self.rcvd_field = field("599", keyboard=ui.KEYBOARD_NUMBER_PAD)
        self.row(ROW_H,
                 (label("RST"), 1), (self.rst_field, 1),
                 (label("RCVD"), 1), (self.rcvd_field, 1),
                 (button("Log QSO", act(self.log_qso)), 2))

        self.free_field = field(placeholder="Free text", delegate=ReturnKey(act(self.send_free)))
        self.row(ROW_H, (self.free_field, 5), (button("TX", act(self.send_free)), 1))

        wpm = self.config["speed_wpm"]
        self.speed_label = label(f"{wpm} WPM", 17, ui.ALIGN_CENTER)
        self.speed_slider = ui.Slider(continuous=True, action=self.speed_changed)
        self.speed_slider.value = (wpm - SPEED_MIN) / (SPEED_MAX - SPEED_MIN)
        self.row(ROW_H, (self.speed_slider, 4), (self.speed_label, 1),
                 (button("SET", act(lambda: s.set_speed(self.speed()))), 1))

        self.row(ROW_H * 1.5, (button("STOP", act(s.stop_tx), STOP_COLOR), 1))

        self.status_label = label("", 15)
        self.status_label.number_of_lines = 2
        self.row(ROW_H, (self.status_label, 1))

    def sdr_button(self):
        if not self.sdr_tuner:
            return label("")
        return button("SDR", self.toggle_sdr)

    def toggle_sdr(self, _sender):
        if self.sdr is None:
            self.sdr_loaded = False
            self.sdr = ui.WebView()
            self.sdr.delegate = self
            self.add_subview(self.sdr)
            # Audio starts after the first tap into the page (WebAudio needs a user gesture on iOS)
            self.sdr.load_url(self.sdr_tuner.url(self.session.rx_hz()))
        else:
            # Removing the page also stops its audio
            self.remove_subview(self.sdr)
            self.sdr = None
        self.layout()

    def calibrate(self):
        """Loop thread. Transmit (DOTS), tune the SDR by hand onto your signal, then Cal."""
        sdr = self.sdr
        if not (sdr and self.sdr_loaded):
            self.set_status("Cal: open SDR, send DOTS, tune the SDR onto your signal, Cal")
            return
        value = sdr.eval_js(f"String({self.sdr_tuner.read_js()})")
        try:
            sdr_hz = float(value)
        except (TypeError, ValueError):
            self.set_status(f"Cal: cannot read the SDR frequency ({value!r})")
            return
        diff = self.session.calibration_diff(sdr_hz)
        if diff is None:
            return
        try:
            console.alert("Calibrate", f"Your signal on the SDR is {diff:+d} Hz from the computed RX. "
                          f"Correct the TX frequency by {diff:+d} Hz?", "Correct")
        except KeyboardInterrupt:      # Cancel
            return
        self.session.apply_calibration(diff)

    def webview_did_finish_load(self, webview):
        # Scripts sent before the page has loaded are lost, so the first tuning waits for this
        if webview is self.sdr and not self.sdr_loaded:
            self.sdr_loaded = True
            if self.keyer:
                self.loop.post(self.update_freq)

    # --- hardware keyboard ---

    def get_key_commands(self):
        commands = [
            {"input": "esc", "title": "Stop"},
            {"input": "1", "modifiers": "cmd", "title": "CQ"},
            {"input": "2", "modifiers": "cmd", "title": "Report"},
            {"input": "3", "modifiers": "cmd", "title": "TU 73"},
            {"input": "4", "modifiers": "cmd", "title": "de .."},
            {"input": "l", "modifiers": "cmd", "title": "Log QSO"},
        ]
        if self.keyer:
            commands += [
                {"input": "d", "modifiers": "cmd", "title": "Dots"},
                {"input": "h", "modifiers": "cmd", "title": "CW / Hell"},
                {"input": "up", "modifiers": "cmd", "title": "Tune up"},
                {"input": "down", "modifiers": "cmd", "title": "Tune down"},
            ]
        return commands

    def key_command(self, sender):
        actions = {
            "esc": self.session.stop_tx,
            "1": lambda: self.macro("cq"),
            "2": lambda: self.macro("rpt"),
            "3": lambda: self.macro("tu"),
            "4": lambda: self.macro("de"),
            "l": self.log_qso,
            "d": self.session.send_dots,
            "h": self.toggle_mode,
            "up": lambda: self.tune(1),
            "down": lambda: self.tune(-1),
        }
        action = actions.get(sender["input"])
        if action:
            self.loop.post(action)

    # --- actions (run in the loop thread) ---

    def set_status(self, text):
        self.status_label.text = text

    def macro(self, name):
        self.session.send_macro(name, self.call_field.text, self.rst_field.text)

    def send_free(self):
        self.session.send(self.free_field.text.strip().upper())

    def toggle_mode(self):
        mode = "HELL" if self.session.mode == "CW" else "CW"
        if self.session.set_mode(mode):
            self.mode_ctl.selected_index = Session.MODES.index(mode)

    def copy_call(self):
        call = self.call_field.text.strip().upper()
        if call:
            clipboard.set(call)
            self.set_status(f"Copied {call}")

    def speed(self):
        return round(SPEED_MIN + self.speed_slider.value * (SPEED_MAX - SPEED_MIN))

    def log_qso(self):
        def clear():
            self.call_field.text = ""
            self.loc_field.text = ""
        self.session.log_qso(self.call_field.text, self.loc_field.text, self.rst_field.text,
                             self.rcvd_field.text, clear)

    def tune(self, direction):
        self.session.tune_step(direction, Session.TUNE_STEPS[self.step_ctl.selected_index][1])

    def goto(self):
        self.session.goto_freq(self.goto_field.text)

    # --- actions on the UI thread ---

    def speed_changed(self, _):
        self.speed_label.text = f"{self.speed()} WPM"

    def set_power(self, sender):
        pos = sender.selected_index
        self.loop.post(lambda: self.session.set_power(pos))

    def set_mode(self, sender):
        mode = Session.MODES[sender.selected_index]
        self.loop.post(lambda: self.session.set_mode(mode))

    def show_memories(self, sender):
        if not self.session.memories:
            self.set_status("No memories - tune and press Save")
            return
        tv = ui.TableView(frame=(0, 0, 320, 400))
        tv.name = "Memories (swipe to delete)"
        tv.data_source = tv.delegate = MemoryList(self.session.memory_labels(), self.loop, self.session, tv.close)
        x, y = ui.convert_point((sender.width / 2, sender.height), sender, None)
        tv.present("popover", popover_location=(x, y))

    # --- session callbacks (loop thread) ---

    def update_freq(self):
        self.freq_label.text = self.session.freq_text()
        self.rx_label.text = self.session.rx_text()
        sdr = self.sdr       # the UI thread may remove it meanwhile
        if sdr and self.sdr_loaded:
            js = self.sdr_tuner.tune_js(self.session.rx_hz())
            if js:
                sdr.eval_js(js)

    def update_power(self):
        labels = self.session.power_labels()
        if labels and list(self.power_ctl.segments) != labels:
            self.power_ctl.segments = labels
        self.power_ctl.selected_index = self.session.power_position()

    def _check_wavelog(self):
        if not check_wavelog(self.config):
            self.loop.post(lambda: self.set_status("Wavelog not available - QSOs will not be logged"))

    def will_close(self):
        self.session.running = False
        self.loop.stop()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    config_path = Path(__file__).with_name("config.json")
    # A native crash takes Pythonista down without a traceback; this records where Python was.
    faulthandler.enable(open(config_path.with_name("crash.log"), "w"), all_threads=True)
    try:
        config = load_config(config_path)
    except ConfigError as e:
        console.alert("Config error", str(e), "OK", hide_cancel_button=True)
        return
    view = MainView(config, config_path.with_name("memories.json"))
    view.present("fullscreen")


if __name__ == "__main__":
    main()
