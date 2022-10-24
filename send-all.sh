for FILE in boot.py main.py ssd1306.py senko.py wifimgr.py
do
	ampy put ${FILE}
done
#cd python_lcd/
#ampy put lcd
#cd -
cd micropython-ndeflib/src/
ampy put ndef
cd -
cd Adafruit_CircuitPython_PN532/
ampy put adafruit_pn532
cd -
cd micropython-spotify-web-api/
ampy put spotify_web_api
cd -
