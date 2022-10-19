import time

from spotify_web_api import (
    spotify_client,
    SpotifyWebApiError,
)

from adafruit_pn532.spi import PN532_SPI
from machine import SPI, Pin
from micropython import const #, mem_info

import ndef

import ssd1306

import urequests as requests
import replconf as rc

# TODO debugging, remove
from machine import reset
import os

button_a = Pin(32, Pin.IN, Pin.PULL_UP)
button_b = Pin(33, Pin.IN, Pin.PULL_UP)

# for PN532 
cs_pin = Pin(5, mode=Pin.OUT, value=1)

# oled
dc = Pin(17, mode=Pin.OUT)    # data/command
rst = Pin(16, mode=Pin.OUT)   # reset
cs = Pin(4, mode=Pin.OUT, value=1)   # chip select, some modules do not have a pin for this

# for ESP32
vspi = SPI(2, baudrate=1000000, polarity=0, phase=0, bits=8, firstbit=0, sck=Pin(18), mosi=Pin(23), miso=Pin(19))

# NOTE: this library assumes it can "init" the spi bus with 10 * 1024 * 1024 rate, commented this out as had some difficulty with 10MHz and PN532 on same SPI bus
# no responses from PN532 after loading ssd1306.SSD1306_SPI() because it messes with the "rate" of the SPI bus
display = ssd1306.SSD1306_SPI(128, 32, vspi, dc, rst, cs)

display.fill(0)
display.text('booting', 0 , 0)
display.show()

print("PN532 init")
pn532 = PN532_SPI(vspi, cs_pin, debug=rc.DEBUG)

# neopixel https://docs.micropython.org/en/latest/esp32/quickref.html#neopixel-and-apa106-driver
from neopixel import NeoPixel

pin = Pin(27, Pin.OUT)   # set GPIO0 to output to drive NeoPixels
np = NeoPixel(pin, 1)   # create NeoPixel driver on GPIO0 for 8 pixels
np[0] = (25, 25, 25) # set the first pixel to white
np.write()              # write data to all pixels
#r, g, b = np[0]         # get first pixel colour

ic, ver, rev, support = pn532.firmware_version
print("Found PN532 with firmware version: {0}.{1}".format(ver, rev))

# Configure PN532 to communicate with MiFare cards
pn532.SAM_configuration()

db = {}
playing_end = None
playing_uri = None
playing_title = None

def do_connect(hostname = False):
    import network
    # disable AP mode not needed anymore?
    network.WLAN(network.AP_IF).active(False)
    sta_if = network.WLAN(network.STA_IF)
    mac = sta_if.config('mac')
    host = 'esp32-' + ''.join('{:02x}'.format(b) for b in mac[3:])
    # override host if in "OAUTH" mode to set static mDNS auth host
    # WARNING: using any hostname using a domain (i.e. .local) which is not under explicit control can lead to hijacking
    # WARNING: possibility of collision during auth, but use documentation
    if hostname:
        host = hostname
    if not sta_if.isconnected():
        print('setting hostname...')
        sta_if.active(True)
        # hostname must be set after .active()
        # if this is called too soon after .active() we get a queue error:
        # esp-idf/components/freertos/queue.c:743 (xQueueGenericSend)- assert failed!
        time.sleep(0.25)
        try:
            sta_if.config(hostname = host)
        except ValueError:
            # "hostname" is available in master, but not yet in June 2022 1.19.1 release
            sta_if.config(dhcp_hostname = host)

        print('connecting to network...')
        # TODO remove hard coded BSSID and figure out how to connect to the "strongest" signal
        sta_if.connect(rc.ssid,rc.password, bssid=rc.bssid)
        while not sta_if.isconnected():
            pass
    try:
        host = sta_if.config('hostname')
    except ValueError:
        # "hostname" is available in master, but not yet in June 2022 1.19.1 release
        host = sta_if.config('dhcp_hostname')
    print('Wifi connected as {}/{}, net={}, gw={}, dns={}'.format(
        host, *sta_if.ifconfig()))

def getDB():
    global db
    # TODO load from external source
    # i.e. "https://api.airtable.com/v0/appaHNgIJQBNzJHh4/Spotify?view=Grid%20view" -H "Authorization: Bearer XXXX"
    # TypeError: unsupported type for __hash__: 'bytearray'
    # TypeError: unsupported type for __hash__: 'list'
    # Example entry
    #db[str('[7,6,121,177,154,116,77]')]      = {"uri": "spotify:album:4q1CvYn7xtCCGT5lzxlWx8", "note": "jaz"}
    r = requests.get(rc.airtable)
    for record in r.json()['records']:
        # TODO errors in handling this input are not handled well
        # WARNING: this reads the table into memory, could cause memory heap issues if too large
        # TODO: we do not use the "note" field at the moment, just use playing title from spotify
        # skip records which do not contain a "tag" field (usually empty)
        if 'tag' in record['fields']:
            db[str(record['fields']['tag'])] = {"uri": record['fields']['uri'], "note": record['fields']['note']}
    r.close()

def getRecord(uid):
    if not db:
        getDB()
    print("Searching DB for " + uid)
    return db[uid]

# TODO make a library out of this, probably compatible with `with ... as` pattern?
def getNDEFMessageTLV():
    # assuming last block is 0x2B
    # start at block 0x04 because that is where data starts
    block_position = 4
    termination = False
    tlv_NDEF_message_bytes = bytearray()
    tlv_message_type = 0
    message_byte_count = 0
    while not termination:
        ntag2xx_block = pn532.ntag2xx_read_block(block_position)
        if ntag2xx_block is not None:
            # test if empty tag
            if ntag2xx_block == bytearray([0,0,0,0]):
                # TODO there is another common pattern which may be worth shortcutting [0,0,0,FE]
                if rc.DEBUG:
                    print("empty block contents, assuming empty")
                break
            if rc.DEBUG:
                print(
                        "read block ", block_position,
                    [hex(x) for x in ntag2xx_block],
                )
            # find TLV (Tag Length Value) block
            # WARNING: assuming 1 byte format for Length
            for i, x in enumerate(ntag2xx_block):
                # in the middle of a TLV block?
                if message_byte_count:
                    # possibly better approach is to "pad" the bytes and chop off the first one before returning
                    # skip first entry as that is the "count" byte
                    if not count_byte:
                        if tlv_message_type == 0x03:
                            tlv_NDEF_message_bytes.append(x)
                        message_byte_count -= 1
                    else:
                        if rc.DEBUG:
                            print("skipping count byte")
                        count_byte = False
                else:
                    if rc.DEBUG:
                        print("looking for start of TLV")
                    tlv_message_type = x
                    # ignore any NULL TLV:
                    if x == 0x00:
                        continue
                    # lock control TLV
                    # we expect this to always be first
                    elif x == 0x01:
                        # get next byte for number of bytes to grab
                        message_byte_count = ntag2xx_block[i+1]
                        count_byte = True
                        continue
                    # NDEF Message Payload (there should only be one of these)
                    elif x == 0x03:
                        # get next byte for number of bytes to grab
                        message_byte_count = ntag2xx_block[i+1]
                        count_byte = True
                        continue
                    # terminator TLV
                    elif x == 0xFE:
                        # no other messages have a 0 byte count)
                        termination = True
                        if rc.DEBUG:
                            print("termination TLV")
                        break
            block_position += 1
        else:
            print("Read failed - did you remove the card?")
            # this will cause "IndexError: bytes index out of range" if passed to ndef
            tlv_NDEF_message_bytes = bytearray()
            break
    return tlv_NDEF_message_bytes

def getNDEFspotify(ndef_payload):
    ndef_value = None
    # This produces a generator, so iterate until we find the record we want
    # TODO handle decoder errors
    ndef_records = ndef.message_decoder(ndef_payload)
    for r in ndef_records:
        # long form URN, but stored as "T": https://nfcpy.readthedocs.io/en/v0.13.6/topics/ndef.html#parsing-ndef
        if r.type == 'urn:nfc:wkt:T':
            ndef_value = r.text
        elif r.type == 'urn:nfc:wkt:U':
            ndef_value = r.uri
        if 'spotify:' in ndef_value:
            break
    else:
        print("no usable records found")
        ndef_value = None
    return ndef_value

def syncPlayerStatus(client):
    # https://api.spotify.com/v1/me/player
    # .device.id
    # .progress_ms
    # .item.duration_ms
    # .is_playing
    # .context.uri (.context only present if used a context_uri to start playing)
    global playing_end
    global playing_uri
    global playing_title
    resp = client.player()
    # TODO add handling of "not playing" status because we are likely to run into this state often? (set timeout via end_time?)
    print("checking player payload")
    # can return 204 response if not currently active
    if resp is not None:
        if resp['is_playing']:
            print("player is playing, set globals")
            #TODO match deviceid
            # check if playing a context_uri
            if resp['context']:
                playing_uri = resp['context']['uri']
                # there is no way to know where we are in a context so set to end of current track to check "is_playing" value again
            else:
                playing_uri = resp['item']['uri']
            playing_title = resp['item']['name']
            display_status(playing_title)
            # we have current position and duration, so we should be able to "save" current playing
            # ticks_ms() should be fine as max ticks well in excess of 13 minutes (ticks_us() max value) https://forum.micropython.org/viewtopic.php?t=4652
            duration_ms = resp['item']['duration_ms']
            progress_ms = resp['progress_ms']
            remaining_ms = duration_ms - progress_ms
            # TODO schedule clearing these values
            playing_end = time.ticks_add(time.ticks_ms(), remaining_ms)

def display_status(msg):
    global display
    display.fill(0)
    display.text(msg, 0, 0)
    display.show()

def run():
    global playing_end
    global playing_uri
    global display
    paused = False
    display_status('Running')
    print("Running")
    spotify = spotify_client()
    display_status('NFC Read')
    print("Waiting for RFID/NFC card...")
    # Make LED blue
    np[0] = (0,0,25)
    np.write()
    while True:
        # TODO find a way to interrupt on button press, so don't have to wait for NFC timeout
        # TODO add debouncing or "fire once", but for now, will use HTTP call delay and NFC timeout
        if not button_a.value():
            # TODO handle local playing context?
            if not paused:
                # always immediately send pause command to not delay pausing if needed?
                spotify.pause()
                print("pausing")
                paused = True
            else:
                # should we resume? (can we tell if we always call pause first?)
                # play
                print("resuming")
                spotify.resume()
                # reset local state
                time.sleep_ms(2000)
                gc.collect()
                # TODO check to see if this handles partially complete songs
                syncPlayerStatus(spotify)
        if not button_b.value():
            print("next song")
            # next
            spotify.next()
            # reset local state
            time.sleep_ms(2000)
            gc.collect()
            syncPlayerStatus(spotify)
        # Check if a card is available to read
        uid = pn532.read_passive_target(timeout=1)
        print(".", end="")
        # experienced some column "drift" once when breadboarded, so maybe clear() ocassionally?
        #display.scroll(1, 0)
        # show estimated song progress
        if playing_end:
            display.rect(0,10,128,10,0,True)
            # TODO this isn't quite accurate enough (+5-10 seconds)
            playing_remaining = time.ticks_diff(playing_end, time.ticks_ms())
            # TODO display in seconds or minutes/seconds
            # TODO progress bar
            # TODO display total length number
            display.text(str(playing_remaining), 0, 10)
            # is track over?
            if playing_remaining < 0:
                playing_end = False
                # Make LED red
                # TODO fade out over time
                np[0] = (25,0,0)
                np.write()
                display.rect(0,10,128,10,0,True)
                # TODO reset the device screen to default?
                display.fill(0)
            display.show()
        # Try again if no card is available.
        if uid is None:
            gc.collect()
            continue
        #display_status('Looking up Tag')
        #print("Found card with UID:", [hex(i) for i in uid])
        # output uid in format matching espruino library for input into PlasticPlayer JSON
        print("Found card with UID:", [x for x in uid])
        try:
            # TODO add lookup from UID to URI
            # Plastic Player JSON indicates an array of 7 byte values
            # TODO try using `with ... as` pattern to help with memory?
            # good candidate for a generator?
            ndef_message_bytes = getNDEFMessageTLV()
            # Check message contents are not empty. If empty, failed to read or no message found
            while ndef_message_bytes:
                tag_uri = getNDEFspotify(ndef_message_bytes)
                if tag_uri:
                    uri = tag_uri
                    display_status('Found Spotify NDEF')
                    break
            else:
                record = getRecord(str([x for x in uid] ))
                uri = record['uri']
                display_status('Found Tag in DB')
            # memory allocation errors if we don't collect here
            gc.collect()

            # WARNING: esp32 specific and probably doesn't help with speed of TLS setup?
            if playing_end is None:
                # TODO option to always stomp on non-player controlled activity to speed up play?
                syncPlayerStatus(spotify)
            if playing_uri == uri:
                display_status(playing_title)
                # TODO use this logic in NFC read loop to update screen with playing track
                playing_remaining = time.ticks_diff(playing_end, time.ticks_ms())
                # this may not be exact, possibly add a gap or "resync"?
                if playing_remaining > 0:
                    print("we think this uri is currently playing with time remaining", playing_remaining )
                    # prevent fast cycling if there is a lot of time left
                    if playing_remaining > 10000:
                        time.sleep_ms(5000)
                    continue
            #else:
            #    print(playing_uri)
            #    print(record['uri'])
            print("Play: ", uri)
            # WARNING: will not "start" playing a non-playing webplayer (on first load only, will unpause previously playing webplayer) possibly bug in web player
            ticks_start = time.ticks_ms()
            # one call for "context" uri (album, playlist) and different for "non-context" (e.g. track)
            display_status('Sending to Spotify')
            # Make LED green
            np[0] = (0,25,0)
            np.write()
            if 'track' in uri:
                spotify.play(uris=[uri])
            else:
                spotify.play(context_uri=uri)
            # clear end time to trigger syncPlayerStatus on next tag found if needed
            # TODO add some small "defaults" to playing_end (i.e. assume all songs are at least 10 seconds)
            playing_end = None
            print("Spotify `play` API call time: ", time.ticks_diff(time.ticks_ms(), ticks_start))
            # screen updates when we sync, so sync now
            # this may not be up to date yet. wait or use URI to lookup value (from local cache?)
            # TODO replace this sleep
            # without this sleep, we show the previously playing track
            time.sleep_ms(2000)
            gc.collect()
            # making this call immediately causes memory allocation error, so we added gc.collect() before
            syncPlayerStatus(spotify)
        # occasional timeouts with ECONNABORTED, and HOSTUNREACHABLE, probably shout reset if that happens
        except OSError as e:
            print('Error: {}, Reason: {}'.format(e, "null"))
        except SpotifyWebApiError as e:
            print('Error: {}, Reason: {}'.format(e, e.reason))
        except KeyError as e:
            # show error and tag ID so it can be used in airtable DB
            print('Tag not found in loaded DB')
            display.fill(0)
            display.text('tag not in db', 0, 0)
            # split between two lines, 16 char each line
            # warning: max theoretical length is 35 exceeds actual space of 32 chars
            uid_str = str([x for x in uid])
            display.text(uid_str[:16], 0 , 10)
            display.text(uid_str[16:], 0 , 20)
            display.show()

def main():
    # Check OAuth stage to determine which mDNS hostname to use
    hostname = False
    if 'oauth-staged' in os.listdir():
        hostname = 'esp32-oauth'
    do_connect(hostname=hostname)
    print("\033c")
    run()

if __name__ == '__main__':
    main()
