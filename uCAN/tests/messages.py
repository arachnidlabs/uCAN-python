import bitstring
from uCAN import messages
import unittest

sample_hwid = "\x01\x23\x45\x67\x89\xAB"


class HardwareIdTest(unittest.TestCase):
    def testHardwareId(self):
        hwid = messages.HardwareId(sample_hwid)
        self.assertEquals(sample_hwid, hwid)
        self.assertEquals(hwid, sample_hwid)
        self.assertEquals(str(hwid), "01:23:45:67:89:ab")
        self.assertEquals(hwid, "01:23:45:67:89:ab")
        self.assertNotEquals(hwid, "01:23:45:67:89:ac")
        self.assertEquals(messages.HardwareId("01:23:45:67:89:ab"), hwid)
        self.assertNotEquals(messages.HardwareId("01:23:45:67:89:ac"), hwid)
        self.assertEquals(hwid, messages.HardwareId(hwid))


class MessagesTest(unittest.TestCase):
    def testYARP(self):
        yarp = messages.YARPMessage(sender=0x12, recipient=0x34, query=True, response=False, hardware_id=sample_hwid)
        header = bitstring.BitString(uint=0x10283412, length=29)
        body = bitstring.BitString(bytes=sample_hwid)

        self.assertEquals(yarp.encodeHeader(), header)
        self.assertEquals(yarp.encodeBody(), body)

        yarp = messages.Message.decode(header, body)
        self.assert_(isinstance(yarp, messages.YARPMessage))
        self.assertEquals(yarp.sender, 0x12)
        self.assertEquals(yarp.recipient, 0x34)
        self.assertTrue(yarp.query)
        self.assertFalse(yarp.response)
        self.assertEquals(yarp.hardware_id, sample_hwid)
        self.assertEquals(yarp.new_node_id, None)
        self.assertEquals(yarp.encodeHeader(), header)

    def testDecodeEncodeRAP(self):
        rap = messages.RAPMessage(sender=0x12, recipient=0x34, write=True, response=False, page=0, register=42, data='foo')
        header = bitstring.BitString(uint=0x10633412, length=29)
        body = bitstring.BitString('0x002a666f6f')

        self.assertEquals(rap.encodeHeader(), header)
        self.assertEquals(rap.encodeBody(), body)

        rap = messages.Message.decode(header, body)
        self.assert_(isinstance(rap, messages.RAPMessage))
        self.assertTrue(rap.write)
        self.assertFalse(rap.response)
        self.assertEquals(rap.page, 0)
        self.assertEquals(rap.register, 42)
        self.assertEquals(rap.data, 'foo')
        self.assertEquals(rap.size, 3)

if __name__ == '__main__':
    unittest.main()
