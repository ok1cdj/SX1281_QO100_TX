# Keyer firmware notes

Firmware: https://github.com/ok1cdj/SX1281_QO100_TX (analysed at commit `0c33c4a`, version v1.5).

## Problem

After switching to a TP-Link Deco X50 mesh the keyer drops off Wi-Fi, also when not transmitting
(IoT network, IP reservation and fixed node already set). Ping RTT to the keyer is ~100 ms
(min 13, avg 109, max 185 ms) — typical for ESP32 modem sleep.

## Findings in `SX1281_QO100_TX.ino`

1. **Wi-Fi power save is on** — no `WiFi.setSleep(false)`, so the default modem sleep is used.
   Deco drops such stations.
2. **No reconnect handling** — `WiFi.begin()` is called once in `setup()`, the connection is
   never checked afterwards. Only the ESP32 core auto-reconnect is used, which does not recover
   from all disconnect reasons. If Wi-Fi fails at boot, the keyer stays in AP mode `QO100TX`.
3. **TUNE** (`cmd_T`) is `startCW(); delay(3000); stopCW();` inside the web handler: fixed 3 s
   carrier, the web server does not answer meanwhile, Break cannot interrupt it.
4. The web UI JavaScript sends the *previous* frequency index when tuning (`fnReq(val)` instead
   of `newVal`), so the keyer lags one step behind the page.

## Patch — `wifi-keepalive.patch`

- `WiFi.setSleep(false)` after connecting
- `WiFi.setAutoReconnect(true)`, `WiFi.persistent(false)`
- `WiFiKeepAlive()` in `loop()`: reconnect every 10 s while disconnected
- disconnect reason printed on serial (`WiFi disconnected, reason N`)

Tested 2026-10-05 on the spare board (v1.5 + patch): joins the Deco IoT network and stays up
past the 5 minutes after which the original v1.1 used to drop; long-term test running.

```sh
git clone https://github.com/ok1cdj/SX1281_QO100_TX && cd SX1281_QO100_TX
git apply /path/to/pyCWdclient/firmware/wifi-keepalive.patch
```

## Local copy vs. upstream

`~/Arduino/SX1281_QO100_TX` (files from 2022-07-26) = upstream **v1.1**: `.ino` matches commit
`a897fc2`, `Settings.h` `a398baa`, `data/index.html` `4fce136` (2021-11-08). Only
`UDP_Test_script.py` differs (target IP). The keyer in the dish serves the v1.1 web page
(no M1–M4 buttons), so it most likely runs this version.

Upstream since then: v1.2 configurable rotary encoder direction, v1.3–v1.5 Iambic-B keying,
PTT fix, configurable messages M1–M4 in the web UI. Wi-Fi code, `/frq`, `pwr`, Tune and Break
are the same, so pyCWdclient works with both.

The patch also applies to v1.1 (hunk 1 with fuzz, placed correctly before `loop()`) and builds.

## Building

- ESP32 Arduino core **2.x** (e.g. 2.0.17) — code uses `ledcSetup`/`ledcWriteTone(channel, …)`
  removed in 3.x; the patch uses `ARDUINO_EVENT_WIFI_STA_DISCONNECTED` (2.x API).
- Libraries: Adafruit GFX, Adafruit SSD1306, SX12XX-LoRa (StuartsProjects),
  ESPAsyncWebServer + AsyncTCP (if the me-no-dev originals fail, use the ESP32Async forks).
- Upload the `data/` folder to SPIFFS separately, otherwise the web UI is missing.
- Suggested order: build and flash the unmodified firmware, check display / web UI / Deco
  connection, then apply the patch. Serial monitor at 115200 shows disconnect reasons.

## PlatformIO

`platformio.ini` here builds the firmware (espressif32@6.9.0 = Arduino core 2.0.17, esp32dev,
ESP32Async web server libs). Verified 2026-10-03: upstream and patched build OK
(Flash 69 %, RAM 14 %), SPIFFS image builds.

```sh
cd firmware
git clone https://github.com/ok1cdj/SX1281_QO100_TX && cd SX1281_QO100_TX   # ignored by this repo
cp ../platformio.ini . && git apply ../wifi-keepalive.patch ../ota.patch
pio run                 # build
pio run -t upload       # flash firmware
pio run -t uploadfs     # flash web UI (data/ -> SPIFFS); settings in NVS are kept
pio device monitor      # serial 115200, shows "WiFi disconnected, reason N"
```

Flashing over USB: the board's CH9102 (`/dev/ttyACM0`) does not auto-reset into the bootloader —
hold BOOT and press EN (or replug USB) before each upload. `uploadfs` at the default 460800 baud
failed once with "serial noise"; 115200 works:
`esptool.py --chip esp32 --port /dev/ttyACM0 --baud 115200 write_flash 0x290000 .pio/build/esp32dev/spiffs.bin`

## OTA — `ota.patch`

Adds `POST /ota?apikey=KEY[&target=fs]` (multipart file) and makes the upstream `/update` page
work (file upload with progress; choose Firmware or Web files). Firmware goes to the other OTA app
slot of the default esp32dev partition table; `spiffs.bin` (or `target=fs`) rewrites the web files.
TX is stopped before writing, the keyer restarts 1 s after a successful upload. Settings in NVS
are kept. Only one USB flash is needed to get it on a board, then:

```sh
KEYER_APIKEY=1111 pio run -e ota -t upload      # firmware over Wi-Fi
KEYER_APIKEY=1111 pio run -e ota -t uploadfs    # web files over Wi-Fi
```

(`upload_port` in `[env:ota]` is the spare board 192.168.99.190 — override with
`--upload-port 192.168.99.109` for the keyer in the dish.) Or open `http://<keyer>/update?apikey=KEY`.
Tested 2026-10-05 on the spare board: both firmware and SPIFFS over Wi-Fi OK.

No rollback: the Arduino core bootloader does not verify that a new image starts. A firmware that
crashes before Wi-Fi is up can only be fixed over USB — test every build on the spare board first.

## Monitoring

`keyer_monitor.sh [host]` (default: the keyer in the dish, 192.168.99.109) pings the keyer every 5 s for 12 h, logs outages (3 lost pings) and
a 10-minute RTT summary to `keyer_monitor.log` next to the script (override with `LOG=`).
