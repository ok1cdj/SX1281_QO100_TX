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
| PgUp / PgDn | Tune up / down by the selected step |

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

## Tune and power

`TUNE` sends a 3 s carrier (fixed in the keyer firmware; the keyer does not answer other requests
meanwhile). STOP / Esc aborts CW and sends Break, which clears the keyer's CW queue.
Power is selected from the levels offered by the keyer and follows changes made in its web UI.
