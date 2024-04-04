#cd python_lcd/
#ampy put lcd
#cd -
cd micropython-ndeflib/src/
mpremote ${MPREMOTE_PORT} cp -r ndef :
cd -
cd Adafruit_CircuitPython_PN532/
mpremote ${MPREMOTE_PORT} cp -r adafruit_pn532 :
cd -
cd micropython-spotify-web-api/
mpremote ${MPREMOTE_PORT} cp -r spotify_web_api :
cd -
# There is a setup process which stalls "boot.py". mpremote appears to soft reset after uploading and does not interrupt boot.py
# add boot file last
for FILE in boot.py main.py ssd1306.py senko.py wifimgr.py
do
    mpremote ${MPREMOTE_PORT} cp ${FILE} :
done
