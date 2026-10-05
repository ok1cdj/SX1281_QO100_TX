# SX1281_QO100_TX
QO-100 SAT CW Transmitter with OLED Display using 2.4 GHz LoRa module with TCXO by OM2JU and OK1CDJ

https://www.nicerf.com/products/detail/500mw-2-4ghz-lora-wireless-transceiver-module-lora1280f27-lora1281f27.html

Only one DIGI mode possible - SLOW Hellschreiber - need bigger dish than 80cm - only beacon implemented yet 

*Maximal power output is 450mW. It is enought to work over satellite with 60cm DISH, but tested also with 35cm and helix feed.*

## Features
- Paddle input -IAMBIC keyer
- Straight key input
- Change frequency, power, keyer speed by rotary encoder
- Frequency callibration
- Beacon mode
- cwdaemon compatible UDP server on port 6789
- WiFi client or AP mode
- Web interface for WiFi config
- Web interafce for tuning, change speed and power
- New: PTT output on ESP32 module pin-12. This is logic signal, one must add external NPN/MOSFET. Configurable delay.
- Wi-Fi keep-alive: modem sleep off, automatic reconnect (fixes drop-outs with mesh APs such as TP-Link Deco)
- Firmware and web files update over Wi-Fi (OTA) - see below

![alt text](https://raw.githubusercontent.com/ok1cdj/SX1281_QO100_TX/main/img/QO100-tx-purple.png)


## Used libraries
Adafruit GFX Library

Adafruit_SSD1306

SX12XX Library - https://github.com/StuartsProjects/SX12XX-LoRa

ESPAsyncWebServer - https://github.com/me-no-dev/ESPAsyncWebServer

AsyncTCP - https://github.com/me-no-dev/AsyncTCP

## Building with PlatformIO
`platformio.ini` builds with Arduino-ESP32 core 2.0.17 (core 3.x is not supported). The web
interface lives in `data/` and goes to the SPIFFS partition.

```sh
pio run -t upload        # firmware over USB
pio run -t uploadfs      # web files over USB
```

## OTA update
Open `http://<keyer IP>/update?apikey=<APIKEY>`, choose *Firmware* (`firmware.bin`) or
*Web files* (`spiffs.bin`) and press Update. The keyer restarts after a successful upload;
settings are kept. With PlatformIO:

```sh
KEYER_APIKEY=1111 pio run -e ota -t upload   --upload-port <keyer IP>
KEYER_APIKEY=1111 pio run -e ota -t uploadfs --upload-port <keyer IP>
```

There is no automatic rollback - a firmware that does not start needs a USB flash
(hold BOOT, press EN).

## User interface
![alt text](https://raw.githubusercontent.com/ok1cdj/SX1281_QO100_TX/main/img/QO100-tx.png)

