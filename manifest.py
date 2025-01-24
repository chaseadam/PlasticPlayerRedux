# Include the board's default manifest.
include("$(PORT_DIR)/boards/manifest.py")
# Add a custom driver
package("spotify_web_api", base_path="./micropython-spotify-web-api")
#package("lcd", base_path="./python_lcd")
package("adafruit_pn532", base_path="./Adafruit_CircuitPython_PN532")
package("ndef", base_path="./micropython-ndeflib/src")
# Add aiorepl from micropython-lib
#require("aiorepl")

