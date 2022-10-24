# This file is executed on every boot (including wake-boot from deepsleep)
# import esp
# esp.osdebug(None)
import gc
import json
import os
import time
import machine
# import webrepl

#webrepl.start(password=wc.PASS)
gc.collect()

def config_save(config):
    with open('config.json', 'w') as f:
        json.dump(config, f)

def do_connect(hostname = False):
    import network
    # network config missing
    if not 'ssid' in config.keys():
        # start wifi manager library to get network config
        import wifimgr
        wlan = wifimgr.get_connection()
        if wlan is None:
            print("Could not initialize the network connection.")
            while True:
                pass  # you shall not pass
        # restart to use our own connection logic instead of wifimgr
        machine.reset()

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

        ap_strong = ('', -100)
        print('scanning for all access points to determine highest RSSI')
        for ap in sta_if.scan():
            if ap[0] == config['ssid'].encode():
                if ap[3] > ap_strong[1]:
                    print("found {} with strength {}".format(ap[1].hex(),ap[3]))
                    ap_strong = (ap[1], ap[3])
                else:
                    print("rejecting {} with strength {}".format(ap[1].hex(),ap[3]))
        # TODO handle "not found"
        sta_if.connect(config['ssid'],config['psk'], bssid=ap_strong[0])
        while not sta_if.isconnected():
            print('.', end = '')
            time.sleep(0.25)
    try:
        host = sta_if.config('hostname')
    except ValueError:
        # "hostname" is available in master, but not yet in June 2022 1.19.1 release
        host = sta_if.config('dhcp_hostname')
    print('Wifi connected as {}/{}, net={}, gw={}, dns={}'.format(
        host, *sta_if.ifconfig()))

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
hostname = False
if 'oauth-staged' in os.listdir():
    hostname = 'esp32-oauth'
do_connect(hostname=hostname)
# clear screen
#print("\033c")
if 'ota_code' in config:
    import micropython
    import senko
    # clear ota_code flag
    del config['ota_code']
    config_save(config)
    GITHUB_URL = "https://raw.githubusercontent.com/chaseadam/PlasticPlayerRedux/ota"
    # TODO check for OTA available and notify user
    # TODO what about libraries (possibly trigger firmware update?)
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    micropython.mem_info()
    OTA = senko.Senko(None, None, url=GITHUB_URL, files=["boot","main.py"])
    if OTA.update():
        print('Updated, rebooting!')
        reset()
    else:
        print('No OTA available')
