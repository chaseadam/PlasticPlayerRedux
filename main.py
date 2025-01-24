import time
import micropython
# for oauth state between resets
import os
import json

from spotify_web_api import (
    spotify_client,
    SpotifyWebApiError,
)

from adafruit_pn532.spi import PN532_SPI
from machine import SPI, Pin
from micropython import const #, mem_info

import ndef

import ssd1306

import requests

from esp32 import Partition
from machine import reset
import errno


currentPartition = Partition(Partition.RUNNING)
nextPartition = currentPartition.get_next_update()

button_0 = Pin(0, Pin.IN, Pin.PULL_UP)
button_a = Pin(32, Pin.IN, Pin.PULL_UP)
button_b = Pin(33, Pin.IN, Pin.PULL_UP)

# for config page and update
import socket
import re

# neopixel https://docs.micropython.org/en/latest/esp32/quickref.html#neopixel-and-apa106-driver
from neopixel import NeoPixel

def config_save(config):
    with open('config.json', 'w') as f:
        json.dump(config, f)

# put these in global space
DEBUG = False
display = None
pn532 = None
np = None
def init_peripherals():
    global display
    global pn532
    global np

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
    pn532 = PN532_SPI(vspi, cs_pin, debug=DEBUG)
    
    pin = Pin(26, Pin.OUT)   # set GPIO0 to output to drive NeoPixels
    #pin = Pin(27, Pin.OUT)   # set GPIO0 to output to drive NeoPixels
    np = NeoPixel(pin, 1)   # create NeoPixel driver on GPIO0 for 8 pixels
    np[0] = (25, 25, 25) # set the first pixel to white
    np.write()              # write data to all pixels
    #r, g, b = np[0]         # get first pixel colour
    
    ic, ver, rev, support = pn532.firmware_version
    print("Found PN532 with firmware version: {0}.{1}".format(ver, rev))
    
    # Configure PN532 to communicate with MiFare cards
    pn532.SAM_configuration()


# urldecode for airtable url from HTML form
# https://forum.micropython.org/viewtopic.php?t=3076#p18183
# https://forum.micropython.org/viewtopic.php?t=3076#p54352
_hextobyte_cache = None

# TODO there is another unquote function in spotify library
def unquote(string):
    """unquote('abc%20def') -> b'abc def'."""
    global _hextobyte_cache

    # Note: strings are encoded as UTF-8. This is only an issue if it contains
    # unescaped non-ASCII characters, which URIs should not.
    if not string:
        return b''

    if isinstance(string, str):
        string = string.encode('utf-8')

    bits = string.split(b'%')
    if len(bits) == 1:
        return string

    res = [bits[0]]
    append = res.append

    # Build cache for hex to char mapping on-the-fly only for codes
    # that are actually used
    if _hextobyte_cache is None:
        _hextobyte_cache = {}

    for item in bits[1:]:
        try:
            code = item[:2]
            char = _hextobyte_cache.get(code)
            if char is None:
                char = _hextobyte_cache[code] = bytes([int(code, 16)])
            append(char)
            append(item[2:])
        except KeyError:
            append(b'%')
            append(item)

    return b''.join(res)

db = {}
playing_end = None
playing_uri = None
playing_title = None

def getDB():
    global db
    # TODO load from external source
    # TODO handle missing config (if we get here)
    # i.e. "https://api.airtable.com/v0/appaHNgIJQBNzJHh4/Spotify?view=Grid%20view" -H "Authorization: Bearer XXXX"
    # TypeError: unsupported type for __hash__: 'bytearray'
    # TypeError: unsupported type for __hash__: 'list'
    # Example entry
    #db[str('[7,6,121,177,154,116,77]')]      = {"uri": "spotify:album:4q1CvYn7xtCCGT5lzxlWx8", "note": "jaz"}
    headers = {"Authorization": "Bearer {}".format(config['airtable_token'])}
    r = requests.get(config['airtable'], headers = headers)
    for record in r.json()['records']:
        # TODO errors in handling this input are not handled well
        # WARNING: this reads the table into memory, could cause memory heap issues if too large
        # TODO: we do not use the "note" field at the moment, just use playing title from spotify
        # skip records which do not contain a "tag" field (usually empty)
        if 'tag' in record['fields']:
            db[str(record['fields']['tag'])] = {"uri": record['fields']['uri'], "note": record['fields']['note']}
    r.close()

def getRecord(uid):
    if not db and config['airtable']:
        getDB()
    print("Searching DB for " + uid)
    return db[uid]

# TODO make a library out of this, probably compatible with `with ... as` pattern?
def getNDEFMessageTLV():
    read_start = time.ticks_ms()
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
                # TODO these are constants available from the upstream library
                if DEBUG:
                    print("empty block contents, assuming empty")
                break
            if DEBUG:
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
                        if DEBUG:
                            print("skipping count byte")
                        count_byte = False
                else:
                    if DEBUG:
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
                        if DEBUG:
                            print("termination TLV")
                        break
            block_position += 1
        else:
            print("Read failed - did you remove the card?")
            # this will cause "IndexError: bytes index out of range" if passed to ndef
            tlv_NDEF_message_bytes = bytearray()
            break
    print("done reading in ", time.ticks_diff(read_start, time.ticks_ms()))
    return tlv_NDEF_message_bytes

def getNDEFspotify(ndef_payload):
    ndef_values = []
    # This produces a generator, so iterate until we find the record we want
    # TODO handle decoder errors
    ndef_records = ndef.message_decoder(ndef_payload)
    for r in ndef_records:
        # long form URN, but stored as "T": https://nfcpy.readthedocs.io/en/v0.13.6/topics/ndef.html#parsing-ndef
        if r.type == 'urn:nfc:wkt:T':
            ndef_values.append(r.text)
        elif r.type == 'urn:nfc:wkt:U':
            ndef_values.append(r.uri)
    if not ndef_values:
        print("no usable records found")
    return ndef_values

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

def web_page():
    # TODO fill in form with existing values
    # TODO add "exit config mode" button
    html = """<html><head> <title>Plastic Redux</title> <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="data:,"> <style>html{font-family: Helvetica; display:inline-block; margin: 0px auto; text-align: center;}
    h1{color: #0F3376; padding: 2vh;}p{font-size: 1.5rem;}.button{display: inline-block; background-color: #e7bd3b; border: none;
    border-radius: 4px; color: white; padding: 16px 40px; text-decoration: none; font-size: 30px; margin: 2px; cursor: pointer;}
    .button2{background-color: #4286f4;}</style></head><body>
    <p>To exit without taking action, power cycle the device.</p>
    <h1>ESP Web Server</h1>
    <form action="/" method="get">
        <label for="airtable">airtable</label>
        <input type="text" name="airtable" id="airtable">
        </br>
        <label for="airtable">airtable personal access token</label>
        <input type="text" name="airtable_token" id="airtable_token">
        </br>
        <label for="update_host">update_host</label>
        <input type="text" name="update_host" id="update_host">
        </br>
        <label for="update_port">update_port</label>
        <input type="text" name="update_port" id="update_port">
        </br>
        For Tidal Only:
        </br>
        <label for="update_port">Lyrion host</label>
        <input type="text" name="lyrion_host" id="lyrion_host">
        </br>
        <label for="update_port">Lyrion port</label>
        <input type="text" name="lyrion_port" id="lyrion_port">
        </br>
        <label for="update_port">squeezebox</label>
        <input type="text" name="squeezebox" id="squeezebox">
        </br>
        <button type="submit">submit</button>
    </form>
    Careful with these:
    <a href="/?otafirmware=True">OTA Firmware</a>
    <a href="/?otacode=True">OTA Code</a>
    </body></html>"""
    return html

# https://forum.micropython.org/viewtopic.php?t=3076#p54352
def unquote(string):
    """unquote('abc%20def') -> b'abc def'.

    Note: if the input is a str instance it is encoded as UTF-8.
    This is only an issue if it contains unescaped non-ASCII characters,
    which URIs should not.
    """
    if not string:
        return b''

    if isinstance(string, str):
        string = string.encode('utf-8')

    bits = string.split(b'%')
    if len(bits) == 1:
        return string

    res = bytearray(bits[0])
    append = res.append
    extend = res.extend

    for item in bits[1:]:
        try:
            append(int(item[:2], 16))
            extend(item[2:])
        except KeyError:
            append(b'%')
            extend(item)

    return bytes(res)

def run_server():
    # config page
    #TODO secure config page
    # https://docs.micropython.org/en/latest/esp8266/tutorial/network_tcp.html#simple-http-server
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    # allow reuse in case we want to enter config again after .close() before timeout
    # https://forum.micropython.org/viewtopic.php?t=10412
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    display.fill(0)
    display.text("CONF SERVER START", 0, 0)
    import network
    sta = network.WLAN(network.STA_IF)
    ip = sta.ifconfig()[0]
    display.text(ip, 0, 10)
    display.show()
    while True:
        cl, addr = s.accept()
        print('client connected from', addr)
        # CPython compatibility
        # https://docs.micropython.org/en/latest/library/socket.html?highlight=makefile
        cl_file = cl.makefile('rwb', 0)
        settings_updated = False
        while True:
            # Are there multiple "lines"? How do they split?
            # read till end line by line until end and throw away
            # If any other line has these values (i.e. referrer) then it will execute the config processing again
            line = cl_file.readline()
            if not line or line == b'\r\n':
                break
            print(line)
            if not "GET" in line:
                print('skipping non-GET line')
                continue
            if "otafirmware=True" in line:
                ota()
            elif "otacode=True" in line:
                display_status('Code OTA....')
                config['ota_code'] = True
                config_save(config)
                reset()
            # airtable
            # WARNING: assuming only one param, so no `&` in URL
            # `\s` to remove HTTP request details after URL
            airtable = re.search('airtable=([^& ]*)[&]*', line)
            # warning: this runs when you leave field empty as it is still passed and matches (but no group?)
            # this didn't fail on earlier micropython versions, but does now, so check if airtable is true?
            if airtable:
                if airtable.group(1):
                    config['airtable'] = unquote(airtable.group(1).decode()).decode()
                    airtable_token = re.search('airtable_token=([^& ]*)[&]*', line)
                    config['airtable_token'] = unquote(airtable_token.group(1).decode()).decode()
                    settings_updated = True
            # update host
            # update port
            update_host = re.search('update_host=([^& ]*)&*', line)
            if update_host:
                settings_updated = True
                update_port = re.search('update_port=([^& ]*)&*', line)
                # WARNING: assume we were passed port as well
                config['update_host'] = update_host.group(1)
                config['update_port'] = update_port.group(1)
            lyrion_host = re.search('lyrion_host=([^& ]*)&*', line)
            if lyrion_host:
                if lyrion_host.group(1):
                    lyrion_port = re.search('lyrion_port=([^& ]*)&*', line)
                    # WARNING: assume we were passed port as well
                    # WARNING: may have to URL decode this
                    squeezebox = re.search('squeezebox=([^& ]*)&*', line)
                    config['lyrion_host'] = lyrion_host.group(1)
                    config['lyrion_port'] = lyrion_port.group(1)
                    config['squeezebox'] = unquote(squeezebox.group(1))
        response = web_page()
        cl.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        cl.send(response)
        cl.close()
        if settings_updated:
            config_save(config)
            break
    s.close()

def run():
    global playing_end
    global playing_uri
    global display
    paused = False
    display_status('Running')
    print("Running")
    import network
    sta = network.WLAN(network.STA_IF)
    ip = sta.ifconfig()[0]
    # we added display handling to library, but OTA update does not force firmware or library updates yet, so make sure we support older library
    try:
        spotify = spotify_client(display=display)
    except TypeError:
        spotify = spotify_client()
    display_status('NFC Read')
    if "squeezebox" in config:
        display.text('lms:{}'.format(config["squeezebox"].replace(":","")), 0, 10)
    display.text(ip, 0, 20)
    display.show()
    display.hw_scroll_h()
    print("Waiting for RFID/NFC card...")
    # Make LED blue
    np[0] = (0,0,25)
    np.write()
    uid_last = None
    while True:
        # TODO find a way to interrupt on button press, so don't have to wait for NFC timeout
        # TODO add debouncing or "fire once", but for now, will use HTTP call delay and NFC timeout
        if not button_a.value():
            # check if both buttons pressed, start ota update
            # TODO add more intentional confirmation for OTA update
            if not button_b.value():
                print("config server")
                run_server()
                display_status('NFC Read')
            # TODO handle local playing context?
            elif not paused:
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
        # TODO more thorough self check would be good
        commit()
        # experienced some column "drift" once when breadboarded, so maybe clear() ocassionally?
        #display.scroll(1, 0)
        # show estimated song progress
        if playing_end:
            #display.rect(0,10,128,10,0,True)
            # TODO this isn't quite accurate enough (+5-10 seconds)
            playing_remaining = time.ticks_diff(playing_end, time.ticks_ms())
            # TODO display in seconds or minutes/seconds
            # TODO progress bar
            # TODO display total length number
            #display.text(str(playing_remaining), 0, 10)
            # is track over?
            if playing_remaining < 0:
                playing_end = False
                # Make LED red
                # TODO fade out over time
                np[0] = (25,0,0)
                np.write()
                #display.rect(0,10,128,10,0,True)
                # TODO reset the device screen to default?
                display.fill(0)
            display.show()
        # Try again if no card is available.
        if uid is None:
            gc.collect()
            continue
        elif uid == uid_last:
            # TODO, this happens if there was a read error, clear out on read error
            #print("ignoring nfc tag, prevent repeat")
            #time.sleep(1)
            continue
        # begin processing NFC tag info
        uid_last = uid
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
            display.fill(1)
            display.show()

            # Check message contents are not empty. If empty, failed to read or no message found
            uri = None
            # why was this a while? it made it hard to break out of when found a tag
            if ndef_message_bytes:
                tag_uris = getNDEFspotify(ndef_message_bytes)
                if tag_uris:
                    for tag in tag_uris:
                        print("processing tag")
                        # check if we have a handler
                        if 'spotify:' in tag:
                            uri = tag
                            display_status('Found Spotify NDEF')
                            break
                        elif 'tidal:' in tag:
                            uri = tag
                            tidal = True
                            display_status('Found Tidal NDEF')
                            break
                    if not uri:
                        print("no known URIs found")
            if not uri:
                print("searching DB")
                display_status('Search in DB')
                # check airtable if url in config
                if 'airtable' in config.keys():
                    record = getRecord(str([x for x in uid] ))
                    uri = record['uri']
                    display_status('Found Tag in DB')
                else:
                    #WARNING: this will trigger failure due to no `uri` value
                    print('no uri payload and no db configured')
                    # TODO show URI ID?
                    continue
            # memory allocation errors if we don't collect here
            gc.collect()
            if uri:
                if 'tidal:' in uri:
                    np[0] = (0,25,0)
                    np.write()
                    # note LMS "preserves" the shuffle state" from previous setting
                    #TODO
                    post_data = f'{{"id":1,"method":"slim.request","params":["{config['squeezebox']}",["playlist","play","{uri}"]]}}'
                    req = requests.post(f"http://{config['lyrion_host']}:{config['lyrion_port']}/jsonrpc.js", data = post_data)
                    req.close()
                    print("request sent to LMS")
                    ## for now, just say it was sent and clear, no status readout
                    display_status('Sent to Squeezebox')
                    time.sleep_ms(3000)
                    display_status("")
                    np[0] = (25,0,0)
                    np.write()

                # otherwise we are spotify
                else:
                    if playing_end is None:
                        # TODO option to always stomp on non-player controlled activity to speed up play?
                        syncPlayerStatus(spotify)
                    print(uri)

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

def ota():
    display.fill(0)
    display.text("OTA UPDATE START", 0, 0)
    display.show()
    try:
        update()
    except OSError as exc:
        if exc.errno == errno.ECONNRESET:
            display.text("failed connect", 0, 10)
        else:
            display.text("failed: {}".format(exc.errno), 0, 10)
        display.show()
        # TODO find proper way to halt
        exit
    switch()

# TODO: test connection stablility before updating
# TODO: handle no update config set
def update():
    SEC_SIZE = 4096
    buf = bytearray(SEC_SIZE)
    i = 0
    assert nextPartition.ioctl(5,0) == SEC_SIZE
    SEC_COUNT = nextPartition.ioctl(4,0)
    addr = socket.getaddrinfo(config['update_host'], config['update_port'])[0][-1]
    s = socket.socket()
    s.connect(addr)
    print("connected")
    while True:
        if i > SEC_COUNT:
            print("attempt to write more sectors than available")
        # .recv() sets max size, but does not wait for buffer to fill?
        # .readinto() is much more consistent with size and network traffic than .recv()
        # TODO .read() vs .readinto()
        # sometimes there is a large delay to this returning (when using with netcat server?)
        #s.readinto(buf, SEC_SIZE)
        buf = s.read(SEC_SIZE)
        if buf:
            if len(buf) < SEC_SIZE:
                print('adding padding to sector')
                buf = buf + bytes(b'\xff'*(4096 - len(buf)))
            assert len(buf) == 4096
            print('write block: {0}'.format(i))
            nextPartition.writeblocks(i, buf)
            i += 1
        else:
            break
    s.close()

def switch():
    nextPartition.set_boot()
    reset()

def commit():
    currentPartition.mark_app_valid_cancel_rollback()

# put in global space
config = None
def main():
    global config

    # TODO put oauth-saved state in config.json
    # TODO move credentials.json contents into this config
    print("load config")
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            config = {}
            config_save(config)
        else:
            print('unknown OSError {0}'.format(exc.errno))
            exit
    # Check OAuth stage to determine which mDNS hostname to use
    # clear screen
    #print("\033c")
    init_peripherals()
    run()

if __name__ == '__main__':
    main()
