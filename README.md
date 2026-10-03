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
| Esc | Stop transmission |

`test.py` is a standalone UDP test script (sends a test message at 15 and 30 WPM).
