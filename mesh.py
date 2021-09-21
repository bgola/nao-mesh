import network
import uasyncio
import time
import struct
import urandom

BROADCAST = b'\xff\xff\xff\xff\xff\xff'
MAC_ADDR_LENGTH = len(BROADCAST)
PEER_TIMEOUT = 1000000000

class Mesh:
    def __init__(self, espnow):
        self.peers = dict()
        self.espnow = espnow
        self.mac_addr = network.WLAN().config('mac')
        self.stream_reader = uasyncio.StreamReader(self.espnow)
        self.timesync_offset = 0
        self.timesync_peer = b''
        self.timesync_tasks = []

        self._message_handlers = {
                Message.ADVERTISEMENT: self.on_advertisement,
                Message.TIMESYNC_REPLY: self.on_timesync_reply,
                Message.TIMESYNC_REQUEST: self.on_timesync_request,
        }
        # TODO: reverse peers
        self.add_peer(BROADCAST)
        self.timesync_tasks.append(Task(self.blink, 1500, self.time_ns))
        self.timesync_tasks[0].start()

    def blink(self):
        print(" " * int(urandom.random()*20), "blink!")

    def time_ns(self):
        return time.time_ns() + self.timesync_offset

    def add_peer(self, addr):
        try:
            self.espnow.add_peer(addr)
        except OSError as e:
            if e.args[1] != ESP_ERR_ESPNOW_EXIST:
                raise e

    def send(self, message):
        timestamp = self.time_ns() 
        self.espnow.send(message.receiver, message.as_bytearray(timestamp))

    async def advertise(self):
        while True:
            msg = Message(
                    kind=Message.ADVERTISEMENT, sender=self.mac_addr, receiver=BROADCAST,
                    data=self.peers.keys())
            self.send(msg)
            await uasyncio.sleep_ms(500)

    async def check_messages(self):
        while True:
            raw_package = await self.stream_reader.read(-1)
            msg = Message(raw_package)
            self._message_handlers[msg.kind](msg)

    async def remove_dead_peers(self):
        while True:
            now = self.time_ns()
            for host, peer in self.peers.items():
                if now - peer['last_seen'] > PEER_TIMEOUT:
                    del self.peers[host]
                    self.espnow.del_peer(host)
                    if self.timesync_peer == host:
                        self.timesync_peer = b''
                        self.get_new_timesync_peer()
                    print("removed: ", host)
            await uasyncio.sleep_ms(200)

    def get_new_timesync_peer(self):
        if not self.peers:
            return

        max_peers = 0
        chosen_peer = b''
        for addr, peer in self.peers.items():
            if len(peer['peers']) > max_peers:
                max_peers = len(peer['peers'])
                chosen_peer = addr
        self.send_timesync_request(addr)

    def on_advertisement(self, message):
        if message.host not in self.peers:
            self.on_new_reacheable_peer(message)

        # Update the list of unreacheable peers
        self.peers[message.host]['last_seen']= self.time_ns()
        self.peers[message.host]['peers'] =  message.data

    def on_timesync_reply(self, message):
        number_peers = len(self.peers)

        if message.host not in self.peers:
            self.add_peer(message.host)
            self.send_timesync_request(message.host)
            self.espnow.del_peer(message.host)
            return

        number_host_peers = len(self.peers[message.host]['peers'])
        do_offset = struct.unpack('I', message.host[2:]) > struct.unpack('I', self.mac_addr[2:])
        if number_host_peers > number_peers or (number_host_peers == number_peers and do_offset):
            now = self.time_ns()
            offset = (message.data[1] - message.data[0])/2 + (message.timestamp - now)/2
            trip_delay = (now - message.data[0]) - (message.timestamp - message.data[1])
            self.timesync_offset += int(offset)
            self.timesync_peer = message.host
            if offset > 50000000:
                self.send_timesync_request(message.host)
                return
            self.new_timesync_adjusted()

    def new_timesync_adjusted(self):
        print("Adjusting offset to ", self.timesync_offset, " with ", self.timesync_peer)
        for task in self.timesync_tasks:
            task.reset()

    def on_timesync_request(self, message):
        if message.host not in self.peers:
            return
        time_received = self.time_ns()
        self.send_timesync_reply(message, time_received)

    def send_timesync_request(self, host):
        msg = Message(kind=Message.TIMESYNC_REQUEST, sender=self.mac_addr, receiver=host)
        self.send(msg)

    def send_timesync_reply(self, original_message, time_received):
        original_timestamp = original_message.timestamp
        msg = Message(
                kind=Message.TIMESYNC_REPLY, sender=self.mac_addr, receiver=original_message.host, 
                data=(original_timestamp, time_received))
        self.send(msg)

    def on_new_reacheable_peer(self, message):
        time_received = self.time_ns()
        self.add_peer(message.host)
        self.peers[message.host] = {'last_seen': self.time_ns(), 'peers': []}
        if not self.timesync_peer:
            self.send_timesync_request(message.host)

    async def main(self):
        uasyncio.create_task(self.advertise())
        uasyncio.create_task(self.check_messages())
        uasyncio.create_task(self.remove_dead_peers())

class Message:
    ADVERTISEMENT = 0
    TIMESYNC_REPLY = 1
    TIMESYNC_REQUEST = 2

    def __init__(self, raw_data=b'', host=b'', sender=b'', receiver=b'', timestamp=None, kind=-1, data=None):
        self.raw_data = raw_data
        self.host = host
        self.sender = sender
        self.receiver = receiver
        self.timestamp = timestamp
        self.kind = kind
        self.data = data

        if raw_data:
            self._parse_raw_data()

    def as_bytearray(self, timestamp=None):
        if timestamp == None:
            if self.timestamp != None:
                timestamp = self.timestamp
            else:
                timestamp = time.time_ns()

        raw_data = self.sender + self.receiver + struct.pack('Q', timestamp) + bytearray([self.kind])
        
        if self.kind == Message.ADVERTISEMENT and self.data:
            raw_data = raw_data + sum(self.data, b'')
        elif self.kind == Message.TIMESYNC_REPLY:
            # data is a tuple with (original_sender_timestamp, message_received_timestamp)
            raw_data = raw_data + sum((struct.pack('Q', time) for time in self.data), b'')
        return raw_data

    def _parse_raw_data(self):
        try:
            self.host, self.sender, self.receiver, timestamp, self.kind, payload = (
                    self.raw_data[2:8], self.raw_data[8:14], self.raw_data[14:20],
                    self.raw_data[20:28], self.raw_data[28], self.raw_data[29:]
                    )
        except IndexError as err:
            # Got bad message?
            print("Got a bad message: ", self.raw_data)
        else:
            self._parse_timestamp(timestamp)
            self._parse_payload(payload)

    def _parse_timestamp(self, timestamp):
        self.timestamp = struct.unpack('Q', timestamp)[0]

    def _parse_payload(self, payload):
        if self.kind == Message.ADVERTISEMENT:
            self.data = [ payload[i:i + MAC_ADDR_LENGTH] for i in range(0, len(payload), MAC_ADDR_LENGTH) ]
            return

        if self.kind == Message.TIMESYNC_REPLY:
            self.data = struct.unpack('QQ', payload)
            return

    def __repr__(self):
        return self.raw_data, self.host, self.sender, self.receiver, self.timestamp, self.kind, self.data


class Task:
    def __init__(self, task, interval, clock):
        self.task = task
        self.interval = interval
        self.clock = clock
        self._uasyncio_task = None

    def start(self):
        async def loop_task():
            try:
                while True:
                    self.task()
                    wait_time = (self.interval * 1000000) - (self.clock() % (self.interval * 1000000))
                    await uasyncio.sleep_ms(wait_time//1000000)
            except uasyncio.CancelledError:
                pass
        self._uasyncio_task = uasyncio.create_task(loop_task())

    def reset(self):
        self._uasyncio_task.cancel()
        self.start()
