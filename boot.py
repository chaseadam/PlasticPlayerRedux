# This file is executed on every boot (including wake-boot from deepsleep)
# import esp
# esp.osdebug(None)
import gc
# import webrepl
import replconf as rc
from time import sleep

def do_connect():
    # placeholder for oauth cycle to modify mdns value
    auth = False
    import network
    # disable AP mode not needed anymore?
    network.WLAN(network.AP_IF).active(False)
    sta_if = network.WLAN(network.STA_IF)
    mac = sta_if.config('mac')
    host = 'esp32-' + ''.join('{:02x}'.format(b) for b in mac[3:])
    # override host if in "OAUTH" mode to set static mDNS auth host
    # WARNING: using any hostname using a domain (i.e. .local) which is not under explicit control can lead to hijacking
    # WARNING: possibility of collision during auth, but use documentation
    if auth:
        host = 'esp32-oauth'

    if not sta_if.isconnected():
        print('setting hostname...')
        sta_if.active(True)
        # hostname must be set after .active()
        # if this is called too soon after .active() we get a queue error:
        # esp-idf/components/freertos/queue.c:743 (xQueueGenericSend)- assert failed!
        sleep(0.25)
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
# maybe move this to main.py to avoid lockout if there is a fault (i.e. setting hostname too soon)
do_connect()
#webrepl.start(password=wc.PASS)
gc.collect()
