# https://docs.micropython.org/en/latest/reference/manifest.html#freeze
# The way the esp32 ports directories are structured, it is in the parent
# Include the board's default manifest.
include("$(PORT_DIR)/boards/manifest.py")
# Add a custom driver
package("spotify_web_api", base_path="./micropython-spotify-web-api")
#package("lcd", base_path="./python_lcd")
package("adafruit_pn532", base_path="./Adafruit_CircuitPython_PN532")
package("ndef", base_path="./micropython-ndeflib/src")
module("ssd1306.py")
module("wifimgr.py")
# Add aiorepl from micropython-lib
#require("aiorepl")

