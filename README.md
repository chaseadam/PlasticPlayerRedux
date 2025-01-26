
## Features
### Tags
* URI stored in NFC tag
* Airtable "database" of tags to URIs

### Spotify
at this time, Spotify configuration is required even if you don't use it

any spotify URIs will play to spotify

### Tidal (on Lyrion)
any tidal URIs play to Lyrion

Configure vi configuration interface

Assumes Lyrion Music Server with Tidal configured

### Player Control
Button A = Next Track

Button B = Pause/Resume

### Configuration server
Hold down both buttons simultaneously

### Factory reset
Note: no screen output, only serial output

* Hold down button A and button B
* Power On
* Release Buttons
* Press button 0

## Building

Moved all libraries to frozen in image via manifest.py

```
make BOARD=ESP32_GENERIC BOARD_VARIANT=OTA FROZEN_MANIFEST=${HOME}/git/PlasticPlayerRedux/manifest.py
```

update submodules with: [1]

```
git submodule update --remote --merge
```

## OTA firmware update
Raw socket update by piping binary into `nc`

```
nc -vvvl 8888 < build-ESP32_GENERIC-OTA/micropython.bin
```

## TLS Memory Errors

TLS memory allocation errors are very common and dependent on micropython version and ESP IDF

Known working "out of the box": ESP-IDF 5.0.5 with Micropython tip (5114f2c)

Non-working combinations: IDF 5.0.6, 5.2.1, 5.2.0

Some are more consistent than others.

Latest working combination is tip Micropython with IDF 5.4 with adjusted MICROPY_GC_INITIAL_HEAP_SIZE [2]

```
➜  esp32 git:(master) ✗ idf.py --version
ESP-IDF v5.4
➜  esp32 git:(master) git describe --dirty
v1.24.0-224-ga4ab84768
```

```
diff --git a/ports/esp32/mpconfigport.h b/ports/esp32/mpconfigport.h
index b5b7d63a5..c5af73959 100644
--- a/ports/esp32/mpconfigport.h
+++ b/ports/esp32/mpconfigport.h
@@ -31,7 +31,7 @@
 // and still have enough internal RAM to start WiFi and make a HTTPS request.
 #ifndef MICROPY_GC_INITIAL_HEAP_SIZE
 #if CONFIG_IDF_TARGET_ESP32
-#define MICROPY_GC_INITIAL_HEAP_SIZE        (56 * 1024)
+#define MICROPY_GC_INITIAL_HEAP_SIZE        (52 * 1024)
 #elif CONFIG_IDF_TARGET_ESP32S2 && !CONFIG_SPIRAM
 #define MICROPY_GC_INITIAL_HEAP_SIZE        (36 * 1024)
 #else
```

[1]: https://stackoverflow.com/a/21195182/9140788
[2]: https://github.com/micropython/micropython/issues/16650
