import can
import unittest
from uCAN import bus, messages


sample_hwid = "\x01\x23\x45\x67\x89\xAB\xCD"
sample_hwid_2 = "\x01\x23\x45\x67\x89\xAB\xCE"


class TestBus(can.bus.BusABC):
    def __init__(self):
        self.receive_queue = []
        self.send_queue = []
        super(TestBus, self).__init__()

    def recv(self, timeout=None):
        try:
            return self.receive_queue.pop(0)
        except IndexError:
            return None

    def send(self, msg):
        self.send_queue.append(msg)

    def __iter__(self):
        while self.receive_queue:
            yield self.receive_queue.pop()

    def getSentMessage(self):
        msg = self.send_queue.pop(0)
        return messages.Message.decode(msg.arbitration_id, msg.data)

    def addReceivedMessages(self, msgs):
        for msg in msgs:
            self.receive_queue.append(msg and bus._encodeMessage(msg))


def fakeTime(times):
    def now():
        return times.pop(0)
    return now


class YARPTest(unittest.TestCase):
    def testSend(self):
        tb = TestBus()
        ubus = bus.Bus(tb, sample_hwid)
        ubus.send(messages.YARPMessage(query=True, response=False, sender=0x10, recipient=0x20))
        self.assertEquals(len(tb.send_queue), 1)
        self.assertTrue(isinstance(tb.getSentMessage(), messages.YARPMessage))

    def testReceive(self):
        tb = TestBus()
        tb.addReceivedMessages([
            # This will be automatically responded to, and not returned
            messages.YARPMessage(query=True, response=False, sender=0x20, recipient=0x10),
            # This will be returned from _tryReceive
            messages.YARPMessage(query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid),
            # This ought to be ignored - it's not for us
            messages.YARPMessage(query=True, response=True, sender=0x20, recipient=0x11, hardware_id=sample_hwid),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        # First receive returns nothing, but transmits a ping reply
        self.assertEquals(ubus._tryReceive(), None)
        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
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

        tb = TestBus()
        tb.addReceivedMessages([
            None,
            messages.YARPMessage(query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid)
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertTrue(isinstance(ubus._receiveUntil(lambda msg: msg is not None, now=fakeTime),
                                   messages.YARPMessage))
        self.assertEquals(len(times), 0)

        times = [1.25, 0.75, 0.0]
        self.assertEquals(ubus._receiveUntil(lambda msg: False, now=fakeTime), None)
        self.assertEquals(len(times), 0)

    def testGetNodeFromHardwareId(self):
        tb = TestBus()
        tb.addReceivedMessages([
            messages.YARPMessage(query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid_2),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertEquals(ubus.getNodeFromHardwareId(sample_hwid_2).node_id, 0x20)
        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
        self.assertTrue(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0xFF)
        self.assertEquals(message.hardware_id, sample_hwid_2)

        self.assertEquals(ubus.getNodeFromHardwareId("11:11:11:11:11:11:11"), None)

    def testPing(self):
        tb = TestBus()
        tb.addReceivedMessages([
            messages.YARPMessage(query=True, response=True, sender=0x20, recipient=0x10, hardware_id=sample_hwid_2),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertEquals(ubus.ping(ubus.getNodeFromNodeId(0x20)), sample_hwid_2)
        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
        self.assertTrue(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0x20)
        self.assertEquals(message.hardware_id, None)

        self.assertEquals(ubus.getNodeFromHardwareId("11:11:11:11:11:11:11"), None)

    def testSetAddress(self):
        class MyBus(bus.Bus):
            def onAddressChange(self, node_id):
                self.addressChanged = True

        tb = TestBus()
        tb.addReceivedMessages([
            messages.YARPMessage(query=False, response=False, sender=0x20, recipient=0xFF, hardware_id=sample_hwid,
                                 new_node_id=0x11),
        ])
        ubus = MyBus(tb, sample_hwid)
        ubus.node_id = 0x10

        # Test setting an address
        ubus.setAddress(sample_hwid_2, 0x12)
        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
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

    def testStartup(self):
        """Test the start up procedure for a uCAN node."""
        # No address assigner, one conflict, no previous address
        tb = TestBus()
        tb.addReceivedMessages([
            None,
            # Ping response from something with our desired address
            messages.YARPMessage(query=True, response=True, sender=0x4D,
                                 recipient=0xFF, hardware_id=sample_hwid_2)
        ])
        ubus = bus.Bus(tb, sample_hwid)

        ubus.start(now=fakeTime([0.0, 1.0, 1.0, 1.1, 1.1, 2.1]))
        self.assertEquals(len(tb.send_queue), 3)

        # Node requests an assigned ID
        message = tb.getSentMessage()
        self.assert_(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0xFF)
        self.assertEquals(message.recipient, 0xFF)
        self.assertEquals(message.hardware_id, sample_hwid)

        # Node checks for others using its ID, which defaults to last byte of hwid
        message = tb.getSentMessage()
        self.assert_(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0xFF)
        self.assertEquals(message.recipient, 0x4D)
        self.assertEquals(message.hardware_id, None)

        # Node checks for others using the next ID in the sequence
        message = tb.getSentMessage()
        self.assert_(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0xFF)
        self.assertEquals(message.recipient, 0x4E)
        self.assertEquals(message.hardware_id, None)

    def testStartupDefaultAddress(self):
        tb = TestBus()
        ubus = bus.Bus(tb, sample_hwid)
        ubus.start(0x12)

        self.assertEquals(ubus.node_id, 0x12)

    def testStartupCentrallyAssigned(self):
        tb = TestBus()
        tb.addReceivedMessages([
            # Centrally assigned address
            messages.YARPMessage(query=True, response=True, sender=0xAA,
                                 recipient=0xFF, hardware_id=sample_hwid)
        ])
        ubus = bus.Bus(tb, sample_hwid)

        ubus.start()
        self.assertEquals(len(tb.send_queue), 1)

        # Node requests an assigned ID
        message = tb.getSentMessage()
        self.assert_(isinstance(message, messages.YARPMessage))
        self.assertTrue(message.query)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0xFF)
        self.assertEquals(message.recipient, 0xFF)
        self.assertEquals(message.hardware_id, sample_hwid)

        self.assertEquals(ubus.node_id, 0xAA)


class RAPTest(unittest.TestCase):
    def testSendWrite(self):
        tb = TestBus()
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        ubus.writeRegisters(ubus.getNodeFromNodeId(0x20), 0, 42, "foo")
        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
        self.assertTrue(isinstance(message, messages.RAPMessage))
        self.assertTrue(message.write)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0x20)
        self.assertEquals(message.page, 0)
        self.assertEquals(message.register, 42)
        self.assertEquals(message.data, "foo")
        self.assertEquals(message.size, 3)

    def testSendRead(self):
        tb = TestBus()
        tb.addReceivedMessages([
            messages.RAPMessage(sender=0x20, recipient=0x10, write=False, response=True, page=0, register=42,
                                data="foo"),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertEquals(ubus.readRegisters(ubus.getNodeFromNodeId(0x20), 0, 42, 3), "foo")
        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
        self.assertTrue(isinstance(message, messages.RAPMessage))
        self.assertFalse(message.write)
        self.assertFalse(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0x20)
        self.assertEquals(message.page, 0)
        self.assertEquals(message.register, 42)
        self.assertEquals(message.size, 3)

    def testReadWrite(self):
        tb = TestBus()
        tb.addReceivedMessages([
            messages.RAPMessage(sender=0x20, recipient=0x10, write=True, response=False, page=0, register=254,
                                data="foo"),
            messages.RAPMessage(sender=0x20, recipient=0x10, write=False, response=False, page=0, register=254,
                                size=4),
        ])
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        registers = ['\0'] * 256

        def readReg(bus, page, addr):
            return registers[addr]

        def writeReg(bus, page, addr, data):
            registers[addr] = data
        ubus.configureRegisters(0, readReg, writeReg)

        ubus.receive()
        ubus.receive()

        self.assertEquals(registers[254], 'f')
        self.assertEquals(registers[255], 'o')
        self.assertEquals(registers[0], 'o')

        self.assertEquals(len(tb.send_queue), 1)
        message = tb.getSentMessage()
        self.assertTrue(isinstance(message, messages.RAPMessage))
        self.assertFalse(message.write)
        self.assertTrue(message.response)
        self.assertEquals(message.sender, 0x10)
        self.assertEquals(message.recipient, 0x20)
        self.assertEquals(message.page, 0)
        self.assertEquals(message.register, 254)
        self.assertEquals(message.size, 4)
        self.assertEquals(message.data, 'foo\0')

    def testSendOverlengthRead(self):
        tb = TestBus()
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertRaises(ValueError, ubus.readRegisters, ubus.getNodeFromNodeId(0x20), 0, 0, 8)

    def testSendOverlengthWrite(self):
        tb = TestBus()
        ubus = bus.Bus(tb, sample_hwid)
        ubus.node_id = 0x10

        self.assertRaises(ValueError, ubus.writeRegisters, ubus.getNodeFromNodeId(0x20), 0, 0, "foobarbaz")


if __name__ == '__main__':
    unittest.main()
