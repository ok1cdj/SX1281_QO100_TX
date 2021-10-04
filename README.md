# SX1281_QO100_TX
QO-100 SAT CW Transmitter with OLED Display using 2.4 GHz LoRa module with TCXO by OM2JU and OK1CDJ

https://www.nicerf.com/products/detail/500mw-2-4ghz-lora-wireless-transceiver-module-lora1280f27-lora1281f27.html

Maybe some digi modes possible in the future (RTTY,  Hellschreiber )

*Maximal power output is 450mW. It is enought to work over satellite with 60cm DISH, but tested also with 35cm and helix feed.*

## Features
- Paddle input -IAMBIC keyer
- Straight key input
- Change frequency, power, keyer speed by rotary encoder
- Frequency callibration
- Beacon mode
- cwdaemon compatible UDP server on port 6789
- WiFi client or AP mode
- Web interface for Wifi config
- Web interafce for tuning, change speed and power - not fully functional yet


## Used libraries
Adafruit GFX Library

Adafruit_SSD1306

SX12XX Library - https://github.com/StuartsProjects/SX12XX-LoRa

ESPAsyncWebServer - https://github.com/me-no-dev/ESPAsyncWebServer

AsyncTCP - https://github.com/me-no-dev/AsyncTCP

