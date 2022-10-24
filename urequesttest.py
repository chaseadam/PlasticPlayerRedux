import urequests
import gc
# retry this after a "soft reset" by pressing CTRL-D
def foo(url):
    urequests.get(url)
# fails with NotImplementedError: Redirects not yet supported
try:
    foo('https://google.com')
except NotImplementedError:
    print('Not implemented, continuing...')
# fails with OSError: [Errno 12] ENOMEM
try:
    foo('https://raw.githubusercontent.com/chaseadam/PlasticPlayerRedux/main/main.py')
    print('Succeeded when expected to fail')
except OSError as e:
    print(e)
gc.collect()
# Succeeds after GC
# These occasionally fail, but consistently succeed
while True:
    gc.collect()
    try:
        foo('https://raw.githubusercontent.com/chaseadam/PlasticPlayerRedux/main/main.py')
        print('succeeded')
    except OSError as e:
        print(e)
