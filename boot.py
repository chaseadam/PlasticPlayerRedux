# This file is executed on every boot (including wake-boot from deepsleep)
# import esp
# esp.osdebug(None)
import gc
# import webrepl
import replconf as rc

def do_connect():
    import network
    # disable AP mode not needed anymore?
    network.WLAN(network.AP_IF).active(False)
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        print('connecting to network...')
        sta_if.active(True)
        sta_if.connect(rc.ssid,rc.password)
        while not sta_if.isconnected():
            pass
    print('network config:', sta_if.ifconfig())

do_connect()
#webrepl.start(password=wc.PASS)
gc.collect()
