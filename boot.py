import network, uasyncio
from esp import espnow
from mesh import Mesh


w0 = network.WLAN(network.STA_IF)
w0.active(True)

e = espnow.ESPNow()
e.init()

mesh = Mesh(e)

uasyncio.run(mesh.main())
uasyncio.get_event_loop().run_forever()
