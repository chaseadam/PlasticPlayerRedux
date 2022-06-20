Push libraries to microcontroller storage:

```
ampy put micropython-ndeflib/src/ndef
ampy put Adafruit_CircuitPython_PN532/adafruit_pn532
ampy put micropython-spotify-web-api/spotify_web_api
```

update submodules with: [1]

```
git submodule update --remote --merge
```

[1]: https://stackoverflow.com/a/21195182/9140788
