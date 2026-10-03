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

Not compiled or tested yet — to be tried on the spare board first.

```sh
git clone https://github.com/ok1cdj/SX1281_QO100_TX && cd SX1281_QO100_TX
git apply /path/to/pyCWdclient/firmware/wifi-keepalive.patch
```

## Building

- ESP32 Arduino core **2.x** (e.g. 2.0.17) — code uses `ledcSetup`/`ledcWriteTone(channel, …)`
  removed in 3.x; the patch uses `ARDUINO_EVENT_WIFI_STA_DISCONNECTED` (2.x API).
- Libraries: Adafruit GFX, Adafruit SSD1306, SX12XX-LoRa (StuartsProjects),
  ESPAsyncWebServer + AsyncTCP (if the me-no-dev originals fail, use the ESP32Async forks).
- Upload the `data/` folder to SPIFFS separately, otherwise the web UI is missing.
- Suggested order: build and flash the unmodified firmware, check display / web UI / Deco
  connection, then apply the patch. Serial monitor at 115200 shows disconnect reasons.

## Monitoring

`keyer_monitor.sh` pings the keyer every 5 s for 12 h, logs outages (3 lost pings) and
a 10-minute RTT summary to `keyer_monitor.log` next to the script (override with `LOG=`).
