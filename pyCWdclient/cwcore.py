"""
QO100TX - CW Daemon Client core (no GUI).

cwdaemon UDP client, QO-100 TX keyer web client, frequency/memory/power logic,
ADIF and Wavelog. Used by the Tk frontend (pyCWdclient.py) and the Pythonista
frontend (pyCWdclient_ios.py).
"""
import copy
import functools
import json
import logging
import math
import queue
import re
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

log = logging.getLogger("pyCWdclient")

DEFAULT_CONFIG = {
    "udp": {"host": "192.168.1.200", "port": 6789},
    "station": {"call": "MYCALL", "name": "NAME", "locator": "AA00AA"},
    "speed_wpm": 20,
    "macros": {
        "cq": "CQ CQ de {mycall} {mycall} K",
        "rpt": "{call} HI UR {rst} NAME {name} loc {myloc} K",
        "tu": "TU 73 de {mycall}",
        "de": "de {mycall} {mycall}",
    },
    # Wavelog logbook (Cloudlog works too - same API); "cloudlog" in old configs is still read
    "wavelog": {"url": "", "api_key": "", "station_id": ""},
    # Keyer web UI; if url is set, TX frequency is shown, tunable and logged.
    # correction_hz = real frequency (SDR/GPS) - frequency computed by the keyer
    # (calibration.json next to the config, written by Calibrate, takes precedence)
    "keyer_web": {"url": "http://192.168.1.200/", "apikey": "1111", "poll_s": 3, "correction_hz": 0},
    # Feld Hell receiver (Tk GUI on Linux): PulseAudio source for parec;
    # @DEFAULT_MONITOR@ = what plays in the default output (SDR in the headphones)
    "hell_rx": {"source": "@DEFAULT_MONITOR@", "tone_hz": 1000},
    # Web SDR shown under the controls; type "websdr" (PA3FWM, e.g. BATC; .../m.html = its
    # mobile page) or "openwebrx".
    # follow = retune the SDR to the RX frequency when the keyer is tuned; url "" = off
    # span_khz = zoom the waterfall to about this width around it (0 = leave the zoom alone)
    "websdr": {"url": "https://eshail.batc.org.uk/nb/m.html", "type": "websdr", "mode": "cw",
               "follow": True, "span_khz": 10, "height": 420},
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


class ConfigError(Exception):
    pass


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
            user = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid config {path}: {e.msg} at line {e.lineno}, column {e.colno}")
    if "cloudlog" in user and "wavelog" not in user:
        log.warning("Config key 'cloudlog' is deprecated, rename it to 'wavelog'")
        user["wavelog"] = user.pop("cloudlog")
    config = merge(DEFAULT_CONFIG, user)
    config["wavelog"]["url"] = config["wavelog"]["url"].rstrip("/")
    if config["websdr"]["type"] not in WEB_SDR_TYPES:
        raise ConfigError(f"websdr.type must be one of {', '.join(WEB_SDR_TYPES)}")
    return config


def when_ready(condition, body, prefer="true", prefer_s=10):
    """
    JS that runs body once condition is true; retunes may arrive while the page still loads.
    If prefer is given, it also waits up to prefer_s seconds for that.
    """
    tries = round(prefer_s / 0.3)
    return (f"(function run(n) {{ if (!({condition}) || (!({prefer}) && n < {tries})) "
            f"{{ setTimeout(function () {{ run(n + 1); }}, 300); return; }} {body} }})(0);")


class PaWebSdr:
    """
    PA3FWM WebSDR (e.g. BATC QO-100 NB): ?tune=<kHz><mode>, setfreqif() in the page.
    When the audio starts, the page retunes to its own frequency and in CW ends up 750 Hz
    low, so it is tuned again after that (allloadeddone), or after 10 s if audio does not start.
    Zoom: the waterfall is 1024 px of samplerate / 2^zoom kHz; wfset_freq() also centres it.
    """

    sets_mode_in_url = True

    @staticmethod
    def url(base, hz, mode):
        return f"{base}?tune={hz / 1e3:.3f}{mode}" if hz else base

    # Frequency shown in the page (in CW the carrier, the passband is offset), in Hz
    read_js = "nominalfreq() * 1000"
    calibrates = True

    @staticmethod
    def tune_js(hz, mode=None, span_khz=0):
        khz = f"{hz / 1e3:.3f}"
        body = f"setfreqif('{khz}');"
        if span_khz:
            body += (f" var e = bi[band]; var z = Math.round(Math.log2(e.samplerate / {span_khz})); "
                     f"wfset_freq(band, Math.min(Math.max(z, 0), e.maxzoom), {khz});")
        return when_ready("window.bi && window.waterfallapplet && waterfallapplet[band2id(band)]", body,
                          prefer="window.allloadeddone")


class PaWebSdrMobile:
    """
    PA3FWM WebSDR mobile page (m.html): no URL parameters, so the mode is set with the
    first retune; freqsubmit() takes the frequency as shown (in CW the page shifts it).
    The first tuning waits until the waterfall has started (the page sets zoom 1 then);
    before that the waterfall start tunes back to the page's default frequency.
    Zoom: bandinfo[band].zoom, kept by the page and centred on every retune.
    """

    sets_mode_in_url = False
    read_js = PaWebSdr.read_js
    calibrates = True

    @staticmethod
    def url(base, hz, mode):
        return base

    @staticmethod
    def tune_js(hz, mode=None, span_khz=0):
        body = ""
        condition = "document.freqform && window.freqsubmit && bandinfo[band].zoom > 0"
        if mode:
            body += (f"var m = document.getElementById('modesel'); m.value = {json.dumps(mode.upper())}; "
                     "setmode_sel(m); ")
        if span_khz:
            body += ("var e = bandinfo[band]; "
                     f"var z = Math.round(Math.log2(e.samplerate * waterfallapplet[0].width / 1024 / {span_khz})); "
                     "e.zoom = Math.min(Math.max(z, 0), e.maxzoom); ")
        body += f"document.freqform.frequency.value = '{hz / 1e3:.3f}'; freqsubmit(document.freqform);"
        return when_ready(condition, body)


class OpenWebRx:
    """
    OpenWebRX: #freq=<Hz>,mod=<mode>; the page retunes on hashchange (within the current
    profile). A hash without mod resets the mode, so a retune only replaces freq in the hash
    the page keeps up to date. Zoom: zoom_set() centres on the receiver. Older versions have
    a zoom_levels list of zoom factors, newer ones logarithmic levels up to the maximum.
    Not used for calibration: unlike BATC, its receiver is not known to be GPS locked.
    """

    sets_mode_in_url = True
    read_js = ("(function () { var d = $('#openwebrx-panel-receiver').demodulatorPanel(); "
               "return d.getDemodulator().get_offset_frequency() + d.center_freq; })()")
    calibrates = False

    @staticmethod
    def url(base, hz, mode):
        return f"{base}#freq={hz:.0f},mod={mode}" if hz else base

    @staticmethod
    def tune_js(hz, mode=None, span_khz=0):
        js = (f"(function () {{ var h = window.location.hash.substring(1); "
              f"window.location.hash = /freq=\\d+/.test(h) ? h.replace(/freq=\\d+/, 'freq={hz:.0f}') : 'freq={hz:.0f}'; }})();")
        if not span_khz:
            return js
        # hashchange is handled after this script, so zoom a moment later
        return js + " setTimeout(function () { " + when_ready(
            "typeof zoom_set == 'function' && typeof bandwidth != 'undefined' && bandwidth",
            f"var want = bandwidth / {span_khz * 1e3:.0f}; "
            "if (typeof zoom_levels != 'undefined' && zoom_levels.length) { "
            "var best = 0; for (var i = 1; i < zoom_levels.length; i++) "
            "if (Math.abs(Math.log(zoom_levels[i] / want)) < Math.abs(Math.log(zoom_levels[best] / want))) best = i; "
            "zoom_set(best); } else { "
            "var maxc = get_zoom_coeff_from_hps(zoom_max_level_hps); want = Math.min(Math.max(want, 1), maxc); "
            "zoom_set(Math.log(want) / Math.log(maxc) * zoom_levels_count); }") + " }, 200);"


WEB_SDR_TYPES = {"websdr": PaWebSdr, "openwebrx": OpenWebRx}


class WebSdrTuner:
    """
    Builds the SDR URL and the JS that retunes it, once per frequency change.

    The mode is only set when the page opens (by the URL, or by the first retune for pages
    without URL parameters); later retunes keep whatever mode the user picked in the page.
    With span_khz the waterfall is zoomed to about that width around the frequency.
    """

    def __init__(self, websdr_cfg):
        self.cfg = websdr_cfg
        self.kind = WEB_SDR_TYPES[websdr_cfg["type"]]
        if self.kind is PaWebSdr and websdr_cfg["url"].endswith("m.html"):
            self.kind = PaWebSdrMobile
        self.last_hz = None
        self.first = False

    def url(self, hz):
        """URL to open the page with; resets what was sent to the page."""
        url = self.kind.url(self.cfg["url"], hz, self.cfg["mode"])
        # The page is tuned once more when loaded: the URL cannot do it all (mode, zoom, BATC CW)
        self.first = True
        self.last_hz = None
        return url

    def tune_js(self, hz):
        """JS to run in the page, or None if nothing changed or following is off."""
        if hz is None or hz == self.last_hz or not (self.cfg["follow"] or self.first):
            return None
        self.last_hz = hz
        mode = self.cfg["mode"] if self.first and not self.kind.sets_mode_in_url else None
        self.first = False
        return self.kind.tune_js(hz, mode, self.cfg["span_khz"])

    def read_js(self):
        """JS expression for the frequency the page is tuned to, in Hz."""
        return self.kind.read_js

    def calibrates(self):
        return self.kind.calibrates


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


def build_adif(call, locator, rst_sent, rst_rcvd, adif_cfg, when=None, mode="CW"):
    when = when or datetime.now(timezone.utc)
    fields = [
        ("BAND", adif_cfg["band"]),
        ("BAND_RX", adif_cfg["band_rx"]),
        ("CALL", call),
        ("GRIDSQUARE", locator),
        ("MODE", mode),
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

    def hell_send(self, text):
        """Send text once in Feld Hell; appended to the text the keyer is sending."""
        response = self._get("/hell", cmd="send", txt=text).strip()
        if response not in ("TX", "stopped"):
            raise RuntimeError(f"Keyer answered {response!r}")

    def command(self, name, label):
        """Press a keyer form button, e.g. ("cmd_D", "Dots") or ("cmd_B", "Break")."""
        self._get("/", **{name: label})

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
    """
    Runs blocking calls one at a time in a thread.

    post(fn) must run fn on the GUI thread; it is called from the worker thread.
    """

    def __init__(self, post):
        self.post = post
        self.jobs = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, func, callback):
        self.jobs.put((func, callback))

    def _run(self):
        while True:
            func, callback = self.jobs.get()
            try:
                result, error = func(), None
            except Exception as e:
                result, error = None, e
            self.post(functools.partial(callback, result, error))


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


def load_calibration(path):
    """correction_hz saved by the SDR calibration, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            return int(json.load(f)["correction_hz"])
    except FileNotFoundError:
        return None
    except (ValueError, KeyError, TypeError):
        log.exception("Invalid calibration file %s", path)
        return None


def save_calibration(path, correction_hz):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"correction_hz": correction_hz,
                   "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}, f, indent=2)


def test_wavelog(base_url):
    """
    Check that we can make a request to the given Wavelog URL.
    """
    response = urllib.request.urlopen(f"{base_url}/index.php/api/statistics", timeout=10)
    if not 200 <= response.status < 300:
        raise RuntimeError(f"Unexpected HTTP status {response.status}")
    data = json.loads(response.read().decode())
    if "Today" not in data:
        log.warning("Unknown response from Wavelog %s. May not be connected correctly.", data)
    return data


def check_wavelog(config):
    """True if Wavelog is configured and answers."""
    url = config["wavelog"]["url"]
    if not url:
        log.warning("Wavelog URL not configured")
        return False
    try:
        test_wavelog(url)
        log.info("Successfully tested connection to Wavelog")
        return True
    except Exception:
        log.exception("Unable to connect to Wavelog")
        return False


def upload_to_wavelog(base_url, api_key, station_id, payload):
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
        log.info("Sent QSO to Wavelog at %s, got response %s", base_url, response.read().decode())
        return True
    except Exception:
        log.exception("Failed to send ADIF to Wavelog")
        return False


def make_session(config, post, call_later, memories_path=None, wavelog_ok=False):
    """Create cwdaemon and keyer clients from config and wrap them in a Session."""
    udp = config["udp"]
    log.info("UDP target %s:%s", udp["host"], udp["port"])
    cw = CwDaemon(udp["host"], udp["port"])
    keyer_cfg = config["keyer_web"]
    keyer = None
    calibration_path = Path(memories_path).with_name("calibration.json") if memories_path else None
    if keyer_cfg["url"]:
        correction_hz = keyer_cfg["correction_hz"]
        calibrated = load_calibration(calibration_path) if calibration_path else None
        if calibrated is not None:
            log.info("Frequency correction %+d Hz from %s (config: %+d Hz)", calibrated, calibration_path, correction_hz)
            correction_hz = calibrated
        keyer = KeyerWeb(keyer_cfg["url"], keyer_cfg["apikey"], correction_hz)
    session = Session(config, cw, post, call_later, keyer, memories_path, wavelog_ok)
    session.calibration_path = calibration_path
    return session


class Session:
    """
    Operating logic shared by the GUIs. All methods run on the GUI thread.

    post(fn): run fn on the GUI thread (called from worker threads).
    call_later(seconds, fn): run fn on the GUI thread after a delay.
    The GUI sets the on_* callbacks to refresh its widgets.
    """

    # (label, step in Hz); 0 = one keyer step (~198 Hz)
    TUNE_STEPS = [("1 step", 0), ("1 kHz", 1000), ("10 kHz", 10000), ("100 kHz", 100000)]
    # Ignore polled frequency this long after local tuning, so the display does not jump back
    TUNE_HOLD_S = 1.5
    # TX modes; HELL (Feld Hell) is sent by the keyer web API, so it needs keyer_web
    MODES = ["CW", "HELL"]
    MODE_LABELS = {"CW": "CW", "HELL": "Hell"}

    def __init__(self, config, cw, post, call_later, keyer=None, memories_path=None, wavelog_ok=False):
        self.config = config
        self.cw = cw
        self.post = post
        self.call_later = call_later
        self.keyer = keyer
        self.memories_path = memories_path
        self.calibration_path = None    # set by make_session
        self.labels_have_step = False
        self.memories = load_memories(memories_path) if memories_path else []
        self.wavelog_ok = wavelog_ok

        self.freq_index = None
        self.last_tune = 0.0
        self.pending_set = False
        self.last_power_set = 0.0
        self.running = False
        self.mode = "CW"

        self.on_status = lambda text: None
        self.on_freq = lambda: None
        self.on_power = lambda: None
        self.on_memories = lambda: None

        self.worker = BackgroundWorker(post) if keyer else None

    def start(self):
        self.running = True
        self.cw.set_speed(self.config["speed_wpm"])
        if not self.wavelog_ok:
            self.set_status("Wavelog not available - QSOs will not be logged")
        if self.keyer:
            self.poll_freq()

    def stop(self):
        self.running = False

    def set_status(self, text):
        self.on_status(text)

    # --- CW ---

    def macro(self, name, call, rst):
        station = self.config["station"]
        return self.config["macros"][name].format(
            mycall=station["call"],
            name=station["name"],
            myloc=station["locator"],
            call=call.strip().upper(),
            rst=rst.strip(),
        )

    def set_mode(self, mode):
        if mode == "HELL" and not self.keyer:
            self.set_status("Feld Hell needs keyer_web in config")
            return False
        self.mode = mode
        self.set_status(f"Mode {mode}")
        return True

    def send(self, text):
        if not text:
            return
        if self.mode == "HELL":
            self.send_hell(text)
            return
        try:
            self.cw.send(text)
            self.set_status(f"Sent: {text}")
        except OSError as e:
            log.exception("UDP send failed")
            self.set_status(f"Send failed: {e}")

    def send_hell(self, text):
        def on_done(_, error):
            if error:
                log.warning("Hell send failed: %s", error)
                self.set_status(f"Hell send failed: {error}")
            else:
                self.set_status(f"Hell: {text}")
        log.info("Sending Hell - %s", text)
        # Space between messages, the keyer appends them while sending
        self.worker.submit(lambda: self.keyer.hell_send(text + " "), on_done)

    def send_macro(self, name, call="", rst=""):
        self.send(self.macro(name, call, rst))

    def set_speed(self, wpm):
        try:
            self.cw.set_speed(int(wpm))
            self.set_status(f"Speed {int(wpm)} WPM")
        except (ValueError, OSError) as e:
            self.set_status(f"Speed not set: {e}")

    def stop_tx(self):
        self.cw.abort()
        if self.keyer:
            self.send_break()

    # --- dots and power ---

    def keyer_command(self, name, label, done_status):
        def on_done(_, error):
            if error:
                log.warning("Keyer %s failed: %s", label, error)
                self.set_status(f"{label} failed: {error}")
            else:
                self.set_status(done_status)
        self.worker.submit(lambda: self.keyer.command(name, label), on_done)

    def send_dots(self):
        """Series of dots (25x E) for tuning onto the transponder; STOP ends it."""
        self.keyer_command("cmd_D", "Dots", "DOTS - STOP to end")

    def send_break(self):
        """Break: clears the keyer CW queue and stops any carrier (used by STOP)."""
        self.keyer_command("cmd_B", "Break", "Break - TX stopped")

    def power_labels(self):
        return [label for _, label in self.keyer.power_levels]

    def power_position(self):
        """Position of the current power level in power_labels(), or -1."""
        values = [value for value, _ in self.keyer.power_levels]
        return values.index(self.keyer.power) if self.keyer.power in values else -1

    def set_power(self, pos):
        if not 0 <= pos < len(self.keyer.power_levels):
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
        if self.running:
            self.worker.submit(self.keyer.read_index, self._on_poll)

    def _on_poll(self, index, error):
        if error:
            log.debug("Keyer poll failed: %s", error)
            self.freq_index = None
            self.on_freq()
        else:
            if not self.labels_have_step:
                # Memory labels made before the first poll show bare indexes, not MHz
                self.labels_have_step = True
                self.on_memories()
            if not self.pending_set and time.monotonic() - self.last_tune > self.TUNE_HOLD_S:
                self.freq_index = index
                self.on_freq()
            if time.monotonic() - self.last_power_set > self.TUNE_HOLD_S:
                self.on_power()
        self.call_later(self.config["keyer_web"]["poll_s"], self.poll_freq)

    def freq_text(self):
        if self.freq_index is None:
            return "--- keyer offline"
        return format_mhz(self.keyer.freq_hz(self.freq_index))

    def rx_hz(self):
        """Downlink frequency in Hz, or None (keyer offline or no rx_offset_mhz)."""
        offset = self.config["adif"]["rx_offset_mhz"]
        if self.freq_index is None or not offset:
            return None
        return self.keyer.freq_hz(self.freq_index) + offset * 1e6

    def rx_text(self):
        hz = self.rx_hz()
        return f"RX {format_mhz(hz)}" if hz else ""

    def tune_to_index(self, index):
        if self.freq_index is None:
            self.set_status("Keyer offline - cannot tune")
            return
        self.freq_index = self.keyer.clamp(index)
        self.last_tune = time.monotonic()
        self.on_freq()
        # Coalesce fast tuning (mouse wheel, repeated taps) into one request
        if not self.pending_set:
            self.pending_set = True
            self.call_later(0.15, self._send_freq)

    def _send_freq(self):
        self.pending_set = False
        index = self.freq_index
        self.worker.submit(lambda: self.keyer.set_index(index), self._on_set)

    def _on_set(self, index, error):
        self.last_tune = time.monotonic()
        if error:
            log.warning("Setting frequency failed: %s", error)
            self.set_status(f"Tune failed: {error}")

    def tune_step(self, direction, step_hz):
        if self.freq_index is None:
            return
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

    def goto_freq(self, text):
        try:
            mhz = float(text.replace(",", ".").replace(" ", ""))
        except ValueError:
            self.set_status("Enter frequency in MHz, e.g. 2400.050")
            return
        if self.freq_index is None:
            self.set_status("Keyer offline - cannot tune")
            return
        self.tune_to_index(self.keyer.index_for_hz(mhz * 1e6))

    # --- memories ---

    def memory_label(self, index):
        return format_mhz(self.keyer.freq_hz(index)) if self.keyer.step else str(index)

    def memory_labels(self):
        return [self.memory_label(i) for i in self.memories]

    # --- calibration against the SDR ---

    # A bigger difference means the SDR is not tuned to our own signal
    CALIBRATION_MAX_HZ = 50000

    def calibration_diff(self, sdr_hz):
        """
        sdr_hz: where the SDR page is tuned, by hand, to our own carrier. Returns the
        difference to the computed RX frequency in Hz, or None (status says why).
        """
        rx_hz = self.rx_hz()
        if rx_hz is None:
            self.set_status("Calibration needs the keyer frequency and adif.rx_offset_mhz")
            return None
        if self.calibration_path is None:
            self.set_status("Calibration: nowhere to save it")
            return None
        diff = round(sdr_hz - rx_hz)
        if abs(diff) > self.CALIBRATION_MAX_HZ:
            self.set_status(f"Calibration: SDR is {diff / 1e3:+.1f} kHz off - tune it onto your signal")
            return None
        return diff

    def apply_calibration(self, diff):
        """Shift the frequency correction by diff Hz and save it to calibration.json."""
        self.keyer.correction_hz += diff
        save_calibration(self.calibration_path, self.keyer.correction_hz)
        log.info("Calibrated: correction %+d Hz (%+d Hz)", self.keyer.correction_hz, diff)
        self.set_status(f"Calibrated: correction {self.keyer.correction_hz:+d} Hz ({diff:+d} Hz)")
        self.on_freq()
        self.on_memories()

    def save_memory(self):
        """Save the current frequency; returns its position in memories or None."""
        if self.freq_index is None:
            self.set_status("Keyer offline - nothing to save")
            return None
        if self.freq_index not in self.memories:
            self.memories = sorted(self.memories + [self.freq_index])
            save_memories(self.memories_path, self.memories)
        self.on_memories()
        self.set_status(f"Saved {self.memory_label(self.freq_index)}")
        return self.memories.index(self.freq_index)

    def recall_memory(self, pos):
        if 0 <= pos < len(self.memories):
            self.tune_to_index(self.memories[pos])

    def delete_memory(self, pos):
        if not 0 <= pos < len(self.memories):
            return
        index = self.memories.pop(pos)
        save_memories(self.memories_path, self.memories)
        self.on_memories()
        self.set_status(f"Deleted {self.memory_label(index)}")

    # --- logging ---

    def adif_config(self):
        """ADIF settings with the current keyer frequency, if known."""
        adif_cfg = dict(self.config["adif"])
        if self.keyer is None or self.freq_index is None:
            if self.keyer:
                log.warning("Keyer frequency unknown, logging %s", adif_cfg["freq"])
            return adif_cfg
        mhz = self.keyer.freq_hz(self.freq_index) / 1e6
        adif_cfg["freq"] = f"{mhz:.6f}"
        if adif_cfg["rx_offset_mhz"]:
            adif_cfg["freq_rx"] = f"{mhz + adif_cfg['rx_offset_mhz']:.6f}"
        return adif_cfg

    def log_qso(self, call, locator, rst_sent, rst_rcvd, on_logged):
        """Upload the QSO to Wavelog in the background; on_logged() runs on success."""
        call = call.strip().upper()
        if not call:
            self.set_status("Enter a call before logging")
            return
        adif = build_adif(call, locator.strip().upper(), rst_sent.strip(), rst_rcvd.strip(), self.adif_config(),
                          mode=self.mode)
        log.info("LOG QSO\n%s", adif)
        cl = self.config["wavelog"]
        if not cl["url"]:
            self.set_status("Wavelog URL not configured")
            return
        self.set_status(f"Logging {call}...")

        def done(ok):
            if ok:
                self.set_status(f"Logged {call} ✓")
                on_logged()
            else:
                self.set_status(f"Logging {call} failed - see console")

        def upload():
            ok = upload_to_wavelog(cl["url"], cl["api_key"], cl["station_id"], adif)
            self.post(functools.partial(done, ok))
        threading.Thread(target=upload, daemon=True).start()
