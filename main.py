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

from machine import reset

# for PN532 
cs_pin = Pin(5, mode=Pin.OUT, value=1)

# oled
dc = Pin(17, mode=Pin.OUT)    # data/command
rst = Pin(16, mode=Pin.OUT)   # reset
cs = Pin(4, mode=Pin.OUT, value=1)   # chip select, some modules do not have a pin for this

# for ESP32
vspi = SPI(2, baudrate=100000, polarity=0, phase=0, bits=8, firstbit=0, sck=Pin(18), mosi=Pin(23), miso=Pin(19))

# NOTE: this library assumes it can "init" the spi bus with 10 * 1024 * 1024 rate, commented this out as had some difficulty with 10MHz and PN532 on same SPI bus
# no responses from PN532 after loading ssd1306.SSD1306_SPI() because it messes with the "rate" of the SPI bus
display = ssd1306.SSD1306_SPI(128, 32, vspi, dc, rst, cs)

display.fill(0)
display.text('booting', 0 , 0)
display.show()

print("PN532 init")
pn532 = PN532_SPI(vspi, cs_pin, debug=rc.DEBUG)

# neopixel https://docs.micropython.org/en/latest/esp32/quickref.html#neopixel-and-apa106-driver
#from machine import Pin
#from neopixel import NeoPixel
#
#pin = Pin(0, Pin.OUT)   # set GPIO0 to output to drive NeoPixels
#np = NeoPixel(pin, 8)   # create NeoPixel driver on GPIO0 for 8 pixels
#np[0] = (255, 255, 255) # set the first pixel to white
#np.write()              # write data to all pixels
#r, g, b = np[0]         # get first pixel colour

ic, ver, rev, support = pn532.firmware_version
print("Found PN532 with firmware version: {0}.{1}".format(ver, rev))

# Configure PN532 to communicate with MiFare cards
pn532.SAM_configuration()

db = {}
playing_end = None
playing_uri = None

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
                print("empty block contents, assuming empty")
                break
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
                        print("skipping count byte")
                        count_byte = False
                else:
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
            display.fill(0)
            display.text(resp['item']['name'], 0, 0)
            display.show()
            # we have current position and duration, so we should be able to "save" current playing
            # ticks_ms() should be fine as max ticks well in excess of 13 minutes (ticks_us() max value) https://forum.micropython.org/viewtopic.php?t=4652
            duration_ms = resp['item']['duration_ms']
            progress_ms = resp['progress_ms']
            remaining_ms = duration_ms - progress_ms
            # TODO schedule clearing these values
            playing_end = time.ticks_add(time.ticks_ms(), remaining_ms)

def run():
    global playing_end
    global playing_uri
    global display
    display.fill(0)
    display.text('Running', 0, 0)
    display.show()
    print("Running")
    spotify = spotify_client()
    display.text('NFC Read', 0, 9)
    display.show()
    print("Waiting for RFID/NFC card...")
    while True:
        # Check if a card is available to read
        uid = pn532.read_passive_target(timeout=1)
        print(".", end="")
        # experienced some column "drift" once when breadboarded, so maybe clear() ocassionally?
        display.scroll(1, 0)
        display.show()
        # Try again if no card is available.
        if uid is None:
            gc.collect()
            continue
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
                    break
            else:
                record = getRecord(str([x for x in uid] ))
                uri = record['uri']
            # memory allocation errors if we don't collect here
            gc.collect()

            # WARNING: esp32 specific and probably doesn't help with speed of TLS setup?
            if playing_end is None:
                syncPlayerStatus(spotify)
            if playing_uri == uri:
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
            time.sleep_ms(2000)
            # making this call immediately causes memory allocation error. Possibly 
            gc.collect()
            syncPlayerStatus(spotify)
        # occasional timeouts with ECONNABORTED, and HOSTUNREACHABLE, probably shout reset if that happens
        except OSError as e:
            print('Error: {}, Reason: {}'.format(e, "null"))
        except SpotifyWebApiError as e:
            print('Error: {}, Reason: {}'.format(e, e.reason))
        except KeyError as e:
            print('Tag not found in loaded DB')

def main():
    print("\033c")
    run()

if __name__ == '__main__':
    main()
