# documented originally in https://github.com/orgs/micropython/discussions/9579
# this will write the contents returned by socket connection to the "next" partition
from esp32 import Partition
import socket
from time import sleep
from machine import reset
import replconf as rc

currentPartition = Partition(Partition.RUNNING)
nextPartition = currentPartition.get_next_update()

def do_connect(hostname = False):
    import network
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        sta_if.active(True)
        if not rc.bssid:
            ap_strong = ('', -100)
            print('scanning for all access points to determine highest RSSI')
            for ap in sta_if.scan():
                if ap[0] == rc.ssid.encode():
                    if ap[3] > ap_strong[1]:
                        print("found {} with strength {}".format(ap[1].hex(),ap[3]))
                        ap_strong = (ap[1], ap[3])
                    else:
                        print("rejecting {} with strength {}".format(ap[1].hex(),ap[3]))
            # TODO handle "not found"
        else:
            print("using hard coded bssid")
            ap_strong = (rc.bssid, 0)
        print('connecting to network...')
        sta_if.connect(rc.ssid,rc.password, bssid=ap_strong[0])
        while not sta_if.isconnected():
            print('.', end = '')
            sleep(0.25)
    try:
        host = sta_if.config('hostname')
    except ValueError:
        # "hostname" is available in master, but not yet in June 2022 1.19.1 release
        host = sta_if.config('dhcp_hostname')
    print('Wifi connected as {}/{}, net={}, gw={}, dns={}'.format(
        host, *sta_if.ifconfig()))

# TODO: test connection stablility before updating
def update():
    SEC_SIZE = 4096
    buf = bytearray(SEC_SIZE)
    i = 0
    assert nextPartition.ioctl(5,0) == SEC_SIZE
    SEC_COUNT = nextPartition.ioctl(4,0)
    addr = socket.getaddrinfo(rc.update_host, rc.update_port)[0][-1]
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
            print(i)
            print(len(buf))
            if len(buf) < SEC_SIZE:
                print('adding padding to sector')
                buf = buf + bytes(b'\xff'*(4096 - len(buf)))
            nextPartition.writeblocks(i, buf)
            i += 1
        else:
            break
    s.close()

def switch():
    nextPartition.set_boot()
    import machine; machine.reset()

def commit():
    currentPartition.mark_app_valid_cancel_rollback()
