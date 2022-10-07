# This file is executed on every boot (including wake-boot from deepsleep)
# import esp
# esp.osdebug(None)
import gc
# import webrepl
import replconf as rc
from time import sleep

#webrepl.start(password=wc.PASS)
gc.collect()
