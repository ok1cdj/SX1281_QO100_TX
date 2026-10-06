# pyCWdclient

Tk GUI client for [cwdaemon](https://github.com/acerion/cwdaemon) compatible keyers (e.g. an ESP32 keyer)
for CW operation via QO-100. Sends CW macros over UDP and logs QSOs to [Cloudlog](https://github.com/magicbug/Cloudlog) as ADIF.

## Setup

```sh
pip install -r requirements.txt
cp config.example.json config.json   # edit IP, station, macros, Cloudlog
python pyCWdclient.py
```

Cloudlog credentials can also be given on the command line (they override the config):

```sh
python pyCWdclient.py <url> <api_key> <station_id>
```

## Macros

Placeholders: `{mycall}`, `{name}`, `{myloc}` (from `station`), `{call}`, `{rst}` (from the GUI).

## Keys

| Key | Action |
|-----|--------|
| F1 | CQ |
| F2 | Report (`rpt` macro) |
| F3 | TU 73 |
| F4 | de .. |
| F5 / Enter | Send free text |
| Esc | Stop transmission (CW abort + keyer Break) |
| F6 | Dots (keyer) |
| PgUp / PgDn | Tune up / down by the selected step |

## Pythonista (iPad / iPhone)

`pyCWdclient_ios.py` is the same client with a touch UI for [Pythonista 3](http://omz-software.com/pythonista/).
The logic (cwdaemon, keyer, tuning, memories, ADIF, Cloudlog) is shared in `cwcore.py`;
`pyCWdclient.py` is the Tk frontend.

1. Copy `cwcore.py`, `pyCWdclient_ios.py` and your `config.json` into one Pythonista folder
   (e.g. via iCloud Drive / the Files app). No extra packages are needed.
2. Run `pyCWdclient_ios.py`. Allow *Local Network* access for Pythonista when iOS asks
   (Settings → Pythonista → Local Network), otherwise UDP and the keyer are unreachable.
3. Memories are stored in `memories.json` next to the config, separately from the desktop.

Memories: *Save* stores the current frequency, *Memories* lists them — tap to tune, swipe left
to delete. With a hardware keyboard: Esc = STOP, ⌘1–⌘4 = CQ / Report / TU 73 / de ..,
⌘D = Dots, ⌘↑ / ⌘↓ = tune, ⌘L = Log QSO.

`test.py` is a standalone UDP test script (sends a test message at 15 and 30 WPM).

## Frequency

If `keyer_web.url` is set, the TX frequency is read from the QO-100 TX keyer web page
(`frq_index × STEP`, polled every `poll_s` seconds), shown in the app and logged with each QSO.
`FREQ_RX` is TX + `adif.rx_offset_mhz` (8089.5 MHz for the QO-100 NB transponder).
If the keyer is unreachable, `adif.freq` is logged.

Tuning: `−`/`+` buttons, mouse wheel over the frequency or PgUp/PgDn, with a selectable step
(one keyer step ≈ 198 Hz, 1/10/100 kHz; kHz steps snap to the grid). Type a frequency in MHz
and press GO/Enter to jump to it. Memories are saved to `memories.json` next to the config.

`keyer_web.correction_hz` corrects the TCXO offset: set it to
*real frequency (SDR/GPS) − frequency shown with correction 0*.

## Dots and power

`DOTS` (F6) makes the keyer send a series of dots (25× E) for tuning onto the transponder.
STOP / Esc aborts CW and sends Break, which clears the keyer's CW queue.
Power is selected from the levels offered by the keyer and follows changes made in its web UI.

## Feld Hell

The CW / Hell switch (F7, ⌘H on the iPad) sends macros and free text in Feld Hell instead of
CW. Hell text goes to the keyer over its web API (`/hell?cmd=send`, needs `keyer_web` and
keyer firmware v1.7+); messages sent while the keyer is still transmitting are appended.
STOP sends Break, which also stops Hell. QSOs logged in Hell mode get `MODE=HELL`.

### Receiving (Tk on Linux)

The *Feld Hell RX* panel decodes Feld Hell from audio, e.g. a WebSDR playing in the
browser. It needs `numpy` and `parec` (PulseAudio / PipeWire); without them the panel is
hidden. Audio is taken from `hell_rx.source`, by default `@DEFAULT_MONITOR@` = whatever plays
in the default output. A different source can be chosen in `pavucontrol` → Recording.

Start RX, click the signal in the waterfall (0–3 kHz) to set the tone, adjust Gain for
contrast and Slant % if the text leans. Each column is drawn twice on top of each other, as in
fldigi, so a full character is always readable in one of the copies.

`python3 hellrx.py firmware/SX1281_QO100_TX/Settings.h out.pgm "TEXT"` decodes a generated
test signal offline (font read from the keyer firmware).
