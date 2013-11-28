import can
import unittest
from uCAN import bus, messages


sample_hwid = "\x01\x23\x45\x67\x89\xAB"
sample_hwid_2 = "\x01\x23\x45\x67\x89\xAC"


class TestBus(can.bus.BusABC):
    def __init__(self, messages):
        self.receive_queue = messages
        self.receive_queue.reverse()
        self.send_queue = []
        super(TestBus, self).__init__()

    def recv(self, timeout=None):
        try:
            return self.receive_queue.pop()
        except IndexError:
            return None

    def send(self, msg):
        self.send_queue.append(msg)

    def __iter__(self):
        while self.receive_queue:
            yield self.receive_queue.pop()


class YARPTest(unittest.TestCase):
    def testSend(self):
        tb = TestBus([])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.send(messages.YARPMessage(query=True, response=False, sender=0x10, recipient=0x20))
        self.assertEquals(len(tb.send_queue), 1)
        message = messages.Message.decode(tb.send_queue[0].arbitration_id, tb.send_queue[0].data)
        self.assertTrue(isinstance(message, messages.YARPMessage))

    def testReceive(self):
        tb = TestBus([
            # This will be automatically responded to, and not returned
            bus._encodeMessage(messages.YARPMessage(
                query=True, response=False, sender=0x20, recipient=0x10)),
            # This will be returned from _tryReceive
            bus._encodeMessage(messages.YARPMessage(
                query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid)),
            # This ought to be ignored - it's not for us
            bus._encodeMessage(messages.YARPMessage(
                query=True, response=True, sender=0x20, recipient=0x11, hardware_id=sample_hwid))
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        # First receive returns nothing, but transmits a ping reply
        self.assertEquals(ubus._tryReceive(), None)
        self.assertEquals(len(tb.send_queue), 1)
        message = messages.Message.decode(tb.send_queue[0].arbitration_id, tb.send_queue[0].data)
        self.assertTrue(isinstance(message, messages.YARPMessage))
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0x20)
        self.assertTrue(message.query)
        self.assertTrue(message.response)
        self.assertEquals(message.hardware_id, ubus.hardware_id)

        # Second message is returned to us
        message = ubus._tryReceive()
        self.assertTrue(isinstance(message, messages.YARPMessage))

        # Third message is dropped
        self.assertEquals(ubus._tryReceive(), None)

    def testReceiveUntil(self):
        times = [0.25, 0.0]

        def fakeTime():
            return times.pop()

        tb = TestBus([None, bus._encodeMessage(messages.YARPMessage(
            query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid))])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertTrue(isinstance(ubus._receiveUntil(lambda msg: msg is not None, time=fakeTime),
                                   messages.YARPMessage))
        self.assertEquals(len(times), 0)

        times = [1.25, 0.75, 0.0]
        self.assertEquals(ubus._receiveUntil(lambda msg: False, time=fakeTime), None)
        self.assertEquals(len(times), 0)

    def testGetNodeFromHardwareId(self):
        tb = TestBus([
            bus._encodeMessage(messages.YARPMessage(
                query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid_2)),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertEquals(ubus.getNodeFromHardwareId(sample_hwid_2).node_id, 0x20)
        self.assertEquals(len(tb.send_queue), 1)
        message = messages.Message.decode(tb.send_queue[0].arbitration_id, tb.send_queue[0].data)
        self.assertTrue(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0xFF)
        self.assertEquals(message.hardware_id, sample_hwid_2)

        self.assertEquals(ubus.getNodeFromHardwareId("11:11:11:11:11:11"), None)

    def testPing(self):
        tb = TestBus([
            bus._encodeMessage(messages.YARPMessage(
                query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid_2)),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertEquals(ubus.ping(ubus.getNodeFromNodeId(0x20)), sample_hwid_2)
        self.assertEquals(len(tb.send_queue), 1)
        message = messages.Message.decode(tb.send_queue[0].arbitration_id, tb.send_queue[0].data)
        self.assertTrue(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0x20)
        self.assertEquals(message.hardware_id, None)

        self.assertEquals(ubus.getNodeFromHardwareId("11:11:11:11:11:11"), None)

    def testSetAddress(self):
        class MyBus(bus.Bus):
            def onAddressChange(self, node_id):
                self.addressChanged = True

        tb = TestBus([
            bus._encodeMessage(messages.YARPMessage(
                query=False, response=False, sender=0x20, recipient=0xFF, hardware_id=sample_hwid, new_node_id=0x11))
        ])
        ubus = MyBus(tb, sample_hwid)
        ubus.node_id = 0x10

        # Test setting an address
        ubus.setAddress(sample_hwid_2, 0x12)
        self.assertEquals(len(tb.send_queue), 1)
        message = messages.Message.decode(tb.send_queue[0].arbitration_id, tb.send_queue[0].data)
        self.assertTrue(isinstance(message, messages.YARPMessage))
        self.assertFalse(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0xFF)
        self.assertEquals(message.hardware_id, sample_hwid_2)
        self.assertEquals(message.new_node_id, 0x12)

        # Test having an address set
        ubus.receive()
        self.assertEquals(ubus.node_id, 0x11)
        self.assertEquals(ubus.addressChanged, True)


if __name__ == '__main__':
    unittest.main()
