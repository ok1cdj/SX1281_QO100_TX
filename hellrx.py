"""
Feld Hell receiver (Linux desktop only).

Audio comes from PulseAudio via parec; by default from @DEFAULT_MONITOR@, the
monitor of the default output (whatever the SDR plays into the headphones).

Feld Hell: 245 pixels/s, 14 pixels per column (bottom to top), on/off keyed tone.
The audio is mixed down at the tone frequency and integrated over each pixel;
the magnitude is one grey pixel. Columns are drawn twice on top of each other,
as in fldigi, so a character is readable whatever the column phase is.
"""
import logging
import shutil
import subprocess
import threading

import numpy as np

log = logging.getLogger("pyCWdclient")

PIXEL_RATE = 245.0          # Feld Hell half-pixels per second
COLUMN = 14                 # pixels per column
SAMPLE_RATE = 7840          # 32 samples per pixel
FFT_SIZE = 1024
WATERFALL_MAX_HZ = 3000


def available():
    return shutil.which("parec") is not None


class HellDecoder:
    """Turns audio samples into Hell columns and a spectrum. Not thread safe."""

    def __init__(self, tone_hz=1000.0, sample_rate=SAMPLE_RATE):
        self.fs = sample_rate
        self.tone_hz = tone_hz
        self.slant = 0.0            # pixel rate correction, relative (e.g. 0.001 = +0.1 %)
        self.phase = 0.0            # mixer phase, radians
        self.pos = 0.0              # position of the next pixel boundary, in samples from the chunk start
        self.acc = 0j               # mixed signal accumulated for the current pixel
        self.acc_n = 0
        self.column = []            # magnitudes of the column being built
        self.level = 1e-3           # AGC: decaying peak of pixel magnitudes
        self.tail = np.zeros(0, dtype=np.float32)   # last samples for the spectrum

    def samples_per_pixel(self):
        return self.fs / (PIXEL_RATE * (1.0 + self.slant))

    def process(self, x):
        """x: float samples. Returns a list of finished columns (arrays of COLUMN values 0..1)."""
        n = len(x)
        t = np.arange(n)
        w = 2 * np.pi * self.tone_hz / self.fs
        mixed = x * np.exp(-1j * (self.phase + w * t))
        self.phase = (self.phase + w * n) % (2 * np.pi)
        self.tail = np.concatenate((self.tail, x))[-FFT_SIZE:]

        columns = []
        spp = self.samples_per_pixel()
        start = 0
        while True:
            end = int(round(self.pos))
            if end > n:
                break
            self.acc += mixed[start:end].sum()
            self.acc_n += end - start
            self._pixel(abs(self.acc) / max(self.acc_n, 1), columns)
            self.acc, self.acc_n = 0j, 0
            start = end
            self.pos += spp
        self.acc += mixed[start:].sum()
        self.acc_n += n - start
        self.pos -= n
        return columns

    def _pixel(self, mag, columns):
        self.level = max(self.level * 0.9995, mag)
        self.column.append(mag / self.level)
        if len(self.column) == COLUMN:
            columns.append(np.array(self.column))
            self.column = []

    def spectrum(self):
        """Magnitude in dB of 0..WATERFALL_MAX_HZ, or None before enough samples."""
        if len(self.tail) < FFT_SIZE:
            return None
        spec = np.abs(np.fft.rfft(self.tail * np.hanning(FFT_SIZE)))
        top = int(WATERFALL_MAX_HZ * FFT_SIZE / self.fs)
        return 20 * np.log10(spec[:top] + 1e-9)


class HellReceiver:
    """
    Captures audio with parec in a thread and keeps the received image and the
    waterfall as numpy arrays; the GUI copies them with snapshot().
    """

    def __init__(self, source="@DEFAULT_MONITOR@", tone_hz=1000.0, width=600, waterfall_rows=40):
        self.source = source
        self.decoder = HellDecoder(tone_hz)
        self.width = width
        self.lock = threading.Lock()
        # Image: two stacked copies of each column, top row first
        self.image = np.zeros((2 * COLUMN, width), dtype=np.float32)
        self.waterfall = np.zeros((waterfall_rows, width), dtype=np.float32)
        self.proc = None
        self.thread = None
        self.error = None

    @property
    def tone_hz(self):
        return self.decoder.tone_hz

    def set_tone(self, hz):
        with self.lock:
            self.decoder.tone_hz = float(min(max(hz, 100), WATERFALL_MAX_HZ))

    def set_slant(self, rel):
        with self.lock:
            self.decoder.slant = rel

    def clear(self):
        with self.lock:
            self.image[:] = 0

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running():
            return
        cmd = ["parec", f"--device={self.source}", f"--rate={SAMPLE_RATE}", "--channels=1",
               "--format=s16le", "--raw", "--latency-msec=50", "--client-name=pyCWdclient Hell RX"]
        log.info("Hell RX: %s", " ".join(cmd))
        self.error = None
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None

    def _run(self):
        proc = self.proc
        chunk = SAMPLE_RATE // 20 * 2        # 50 ms of s16 samples
        while True:
            data = proc.stdout.read(chunk)
            if not data:
                break
            x = np.frombuffer(data[:len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
            with self.lock:
                self.feed(x)
        if proc.poll() not in (None, 0, -15):
            self.error = proc.stderr.read().decode(errors="replace").strip() or f"parec exit {proc.returncode}"
            log.warning("Hell RX: %s", self.error)

    def feed(self, x):
        """Decode samples into the image and waterfall (call with lock held)."""
        for col in self.decoder.process(x):
            self.image = np.roll(self.image, -1, axis=1)
            column = col[::-1]                  # bit 0 is the bottom
            self.image[:COLUMN, -1] = column
            self.image[COLUMN:, -1] = column
        spec = self.decoder.spectrum()
        if spec is not None:
            row = np.interp(np.linspace(0, len(spec) - 1, self.width), np.arange(len(spec)), spec)
            row = np.clip((row - row.max() + 60) / 60, 0, 1)   # 60 dB range below the peak
            self.waterfall = np.roll(self.waterfall, 1, axis=0)
            self.waterfall[0] = row

    def snapshot(self):
        with self.lock:
            return self.image.copy(), self.waterfall.copy(), self.decoder.tone_hz


def to_pgm(img, gain=1.0, scale=1):
    """Grey image 0..1 (black = no signal) as binary PGM, text drawn dark on light."""
    pix = (255 - np.clip(img * gain, 0, 1) * 255).astype(np.uint8)
    if scale > 1:
        pix = pix.repeat(scale, axis=0).repeat(scale, axis=1)
    h, w = pix.shape
    return b"P5 %d %d 255\n" % (w, h) + pix.tobytes()


# --- test signal ---

def load_font(settings_h):
    """Read the Feld Hell glyph table from the keyer firmware Settings.h."""
    import re
    src = open(settings_h, encoding="utf-8", errors="replace").read()
    font = {}
    for m in re.finditer(r"\{'(\\'|.)',\s*\{([^}]*)\}\}", src):
        ch = m.group(1).replace("\\'", "'")
        font[ch] = [int(v, 16) for v in m.group(2).split(",")]
    return font


def hell_signal(text, font, tone_hz=1000.0, fs=SAMPLE_RATE, rate_error=0.0, noise=0.0, seed=1):
    """Audio of text keyed as the keyer does it, with optional pixel rate error and noise."""
    bits = []
    for ch in text.upper():
        for col in font.get(ch, font[" "]):
            bits += [(col >> y) & 1 for y in range(COLUMN)]
    spp = fs / (PIXEL_RATE * (1 + rate_error))
    n = int(len(bits) * spp)
    keyed = np.array(bits, dtype=np.float32)[np.minimum((np.arange(n) / spp).astype(int), len(bits) - 1)]
    x = 0.5 * keyed * np.sin(2 * np.pi * tone_hz * np.arange(n) / fs)
    if noise:
        x += np.random.default_rng(seed).normal(0, noise, n)
    return x.astype(np.float32)


if __name__ == "__main__":
    # Offline test: python3 hellrx.py <Settings.h> <out.pgm> [text]
    import sys
    font = load_font(sys.argv[1])
    text = sys.argv[3] if len(sys.argv) > 3 else " CQ CQ DE MYCALL 599 +K "
    rx = HellReceiver(tone_hz=1000, width=len(text) * 7 + 10)
    x = hell_signal(text, font, tone_hz=1000, rate_error=0.0, noise=0.2)
    rx.feed(x)
    img, wf, _ = rx.snapshot()
    open(sys.argv[2], "wb").write(to_pgm(np.vstack([img, np.zeros((4, img.shape[1])), wf]), scale=3))
