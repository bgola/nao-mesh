"""
Advertise: 
    - send list of reacheable peers
"""

import uasyncio

BROADCAST = b'\xff\xff\xff\xff\xff\xff'
MAC_ADDR_LENGTH = len(BROADCAST)

class Mesh:
    def __init__(self, espnow):
        # ourPeer -> [unreacheable peers...]
        self.peers = dict()
        self.espnow = espnow
        self.stream_reader = uasyncio.StreamReader(self.espnow)

        # TODO: check if BROADCAST is already there
        try:
            self.espnow.add_peer(BROADCAST)
        except OSError as e:
            if e.args[1] != ESP_ERR_ESPNOW_EXIST:
                raise e

        # TODO: reverse peers

    async def advertise(self):
        while True:
            msg = bytearray([Message.ADVERTISEMENT]) + sum(list(self.peers.keys()), b'')
            self.espnow.send(BROADCAST, msg, False)
            await uasyncio.sleep_ms(500)

    async def check_messages(self):
        while True:
            raw_package = await self.stream_reader.read(-1)
            mesh_msg = Message(raw_package)
            if mesh_msg.kind == Message.ADVERTISEMENT:
                self.on_advertisement(mesh_msg)
            await uasyncio.sleep_ms(100)
    
    def on_advertisement(self, mesh_msg):
        if mesh_msg.host not in self.peers:
            self.on_new_reacheable_peer(mesh_msg.host, mesh_msg.data)

        # Update the list of unreacheable peers
        self.peers[mesh_msg.host] = mesh_msg.data

    def on_new_reacheable_peer(self, host, peers):
        print(self.peers)

    async def main(self):
        uasyncio.create_task(self.advertise())
        uasyncio.create_task(self.check_messages())


class Message:
    ADVERTISEMENT = 0

    def __init__(self, raw_data):
        self.raw_data = raw_data
        self.host, self.kind, self.data = self._parse_raw_data()
   
    def _parse_raw_data(self):
        host, kind, payload = self.raw_data[2:8], self.raw_data[8], self.raw_data[9:]
        data = None
        if kind == Message.ADVERTISEMENT:
            data = [ payload[i:i + MAC_ADDR_LENGTH] for i in range(0, len(payload), MAC_ADDR_LENGTH) ]
        return host, kind, data

    def __repr__(self):
        return self.raw_data, self.kind, self.host, self.data
