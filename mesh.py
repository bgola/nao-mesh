"""
Advertise:
    - send list of reacheable peers
"""

import network
import uasyncio
import time
import struct

BROADCAST = b'\xff\xff\xff\xff\xff\xff'
MAC_ADDR_LENGTH = len(BROADCAST)
PEER_TIMEOUT = 1000

def get_time_ms():
    return time.time_ns() // 1000000

class Mesh:
    def __init__(self, espnow):
        # ourPeer -> [unreacheable peers...]
        self.peers = dict()
        self.espnow = espnow
        self.mac_addr = network.WLAN().config('mac')
        self.stream_reader = uasyncio.StreamReader(self.espnow)

        # TODO: check if BROADCAST is already there
        try:
            self.espnow.add_peer(BROADCAST)
        except OSError as e:
            if e.args[1] != ESP_ERR_ESPNOW_EXIST:
                raise e

        # TODO: reverse peers

    def send(self, message):
        self.espnow.send(message.receiver, message.as_bytearray())

    async def advertise(self):
        while True:
            msg = Message(
                    kind=Message.ADVERTISEMENT, sender=self.mac_addr, receiver=BROADCAST,
                    timestamp=get_time_ms(), data=self.peers.keys())
            self.send(msg)
            await uasyncio.sleep_ms(500)

    async def check_messages(self):
        while True:
            raw_package = await self.stream_reader.read(-1)
            msg = Message(raw_package)
            if msg.kind == Message.ADVERTISEMENT:
                self.on_advertisement(msg)
            await uasyncio.sleep_ms(100)

    async def remove_dead_peers(self):
        while True:
            now = get_time_ms()
            for host, peer in self.peers.items():
                if now - peer['last_seen'] > PEER_TIMEOUT:
                    del self.peers[host]
                    print("removed: ", host)
            await uasyncio.sleep_ms(200)

    def on_advertisement(self, message):
        if message.host not in self.peers:
            self.on_new_reacheable_peer(message.host, message.data)

        # Update the list of unreacheable peers
        self.peers[message.host] = {'last_seen': get_time_ms(), 'peers': message.data}
        print(self.peers)

    def on_new_reacheable_peer(self, host, peers):
        pass

    async def main(self):
        uasyncio.create_task(self.advertise())
        uasyncio.create_task(self.check_messages())
        uasyncio.create_task(self.remove_dead_peers())


class Message:
    ADVERTISEMENT = 0

    def __init__(self, raw_data=b'', host=b'', sender=b'', receiver=b'', timestamp=0, kind=-1, data=None):
        self.raw_data = raw_data
        self.host = host
        self.sender = sender
        self.receiver = receiver
        self.timestamp = timestamp
        self.kind = kind
        self.data = data

        if raw_data:
            self._parse_raw_data()

    def as_bytearray(self):
        raw_data = self.sender + self.receiver + struct.pack('I', self.timestamp) + bytearray([self.kind])
        if self.kind == Message.ADVERTISEMENT and self.data:
            raw_data = raw_data + sum(self.data, b'')
        return raw_data

    def _parse_raw_data(self):
        try:
            self.host, self.sender, self.receiver, timestamp, self.kind, payload = (
                    self.raw_data[2:8], self.raw_data[8:14], self.raw_data[14:20],
                    self.raw_data[20:24], self.raw_data[24], self.raw_data[25:]
                    )
        except IndexError as err:
            # Got bad message?
            print("Got a bad message: ", self.raw_data)
        else:
            self._parse_timestamp(timestamp)
            self._parse_payload(payload)

    def _parse_timestamp(self, timestamp):
        self.timestamp = struct.unpack('I', timestamp)[0]

    def _parse_payload(self, payload):
        if self.kind == Message.ADVERTISEMENT:
            self.data = [ payload[i:i + MAC_ADDR_LENGTH] for i in range(0, len(payload), MAC_ADDR_LENGTH) ]

    def __repr__(self):
        return self.raw_data, self.host, self.sender, self.receiver, self.timestamp, self.kind, self.data
