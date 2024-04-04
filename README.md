Push libraries to microcontroller storage:

```
ampy put micropython-ndeflib/src/ndef
ampy put Adafruit_CircuitPython_PN532/adafruit_pn532
ampy put micropython-spotify-web-api/spotify_web_api
ampy put python_lcd/lcd/esp32_gpio_lcd.py
ampy put python_lcd/lcd/lcd_api.py
```

update submodules with: [1]

```
git submodule update --remote --merge
```

TLS memory allocation errors are very common and dependent on micropython version and ESP IDF
latest "known working" combination is: ESP-IDF 5.0.5 with Micropython tip (5114f2c).

Non-working combinations: IDF 5.0.6, 5.2.1, 5.2.0

[1]: https://stackoverflow.com/a/21195182/9140788
