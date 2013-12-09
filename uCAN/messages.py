import bitstring
import enum


class HardwareId(object):
    def __init__(self, x):
        if isinstance(x, str) and len(x) == 7:
            self.hwid = x
        elif isinstance(x, basestring):
            self.hwid = ''.join(y.decode('hex') for y in x.split(':'))
        elif isinstance(x, HardwareId):
            self.hwid = x.hwid
        else:
            raise ValueError("Don't know how to interpret %r as a hardware ID" % (x,))

    def __unicode__(self):
        return ':'.join(x.encode('hex') for x in self.hwid)

    def __str__(self):
        return str(unicode(self))

    def __eq__(self, other):
        return self.hwid == HardwareId(other).hwid

    def __ne__(self, other):
        return self.hwid != HardwareId(other).hwid

    def __hash__(self):
        return hash(self.hwid)


class Priority(enum.IntEnum):
    emergency = 0
    high = 1
    normal = 2
    low = 3


class Message(object):
    def __init__(self, protocol, priority=Priority.normal, sender=None):
        self.priority = priority
        self.protocol = protocol
        self.sender = sender

    def encodeHeader(self, subfields):
        return bitstring.pack('uint:2, bits:19, uint:8', self.priority, subfields, self.sender)

    def encodeBody(self):
        raise NotImplementedError()

    @classmethod
    def decode(cls, header, body):
        if isinstance(header, (int, long)):
            header = bitstring.BitString(uint=header, length=29)
        if isinstance(body, (str, bytearray)):
            body = bitstring.BitString(bytes=body)

        priority = header.read('uint:2')
        broadcast = header.read('bool')
        if broadcast:
            message = BroadcastMessage.decode(priority, header, body)
        else:
            message = UnicastMessage.decode(priority, header, body)
        message.sender = header.read('uint:8')
        return message


class BroadcastMessage(Message):
    broadcast_protocols = {}

    @classmethod
    def decode(cls, priority, header, body):
        protocol = header.read('uint:4')
        return cls.broadcast_protocols.get(protocol, UnknownBroadcastMessage).decode(priority, protocol, header, body)

    def encodeHeader(self, subfields):
        return super(BroadcastMessage, self).encodeHeader(
            bitstring.pack('bool, uint:4, bits:14', True, self.protocol, subfields))


class UnknownBroadcastMessage(BroadcastMessage):
    def __init__(self, protocol, subfields, body, **kwargs):
        super(UnknownBroadcastMessage, self).__init__(protocol, **kwargs)
        self.subfields = subfields
        self.body = body

    @classmethod
    def decode(cls, priority, protocol, header, body):
        subfields = header.read('bits:14')
        return cls(protocol, subfields, body, priority=priority)

    def encodeHeader(self):
        return super(UnknownBroadcastMessage, self).encodeHeader(self.subfields)

    def encodeBody(self):
        return self.body


class UnicastMessage(Message):
    BROADCAST_RECIPIENT = 0xFF

    unicast_protocols = {}

    def __init__(self, protocol, recipient=None, **kwargs):
        super(UnicastMessage, self).__init__(protocol, **kwargs)
        self.recipient = recipient

    @classmethod
    def decode(cls, priority, header, body):
        protocol = header.read('uint:4')
        ret = cls.unicast_protocols.get(protocol, UnknownUnicastMessage).decode(priority, protocol, header, body)
        ret.recipient = header.read('uint:8')
        return ret

    def encodeHeader(self, subfields):
        return super(UnicastMessage, self).encodeHeader(
            bitstring.pack('bool, uint:4, bits:6, uint:8', False, self.protocol, subfields, self.recipient))


class UnknownUnicastMessage(UnicastMessage):
    def __init__(self, protocol, subfields, body, **kwargs):
        super(UnknownUnicastMessage, self).__init__(protocol, **kwargs)
        self.subfields = subfields
        self.body = body

    @classmethod
    def decode(cls, priority, protocol, header, body):
        subfields = header.read('bits:6')
        return cls(protocol, subfields, body, priority=priority)

    def encodeHeader(self):
        return super(UnknownUnicastMessage, self).encodeHeader(self.subfields)

    def encodeBody(self):
        return self.body


class YARPMessage(UnicastMessage):
    PROTOCOL_NUMBER = 0

    def __init__(self, query, response, hardware_id=None, new_node_id=None, **kwargs):
        super(YARPMessage, self).__init__(0, **kwargs)
        self.query = query
        self.response = response
        self.hardware_id = hardware_id and HardwareId(hardware_id)
        self.new_node_id = new_node_id

    @classmethod
    def decode(cls, priority, protocol, header, body):
        query = header.read('bool')
        response = header.read('bool')
        has_hwid = header.read('bool')
        header.read('pad:3')

        hardware_id = None
        if has_hwid:
            hardware_id = HardwareId(body.read('bytes:7'))

        new_node_id = None
        if not response and not query:
            new_node_id = body.read('uint:8')

        return cls(query, response, hardware_id, new_node_id, priority=priority)

    def encodeHeader(self):
        return super(YARPMessage, self).encodeHeader(
            bitstring.pack("bool, bool, bool, pad:3", self.query, self.response, self.hardware_id is not None))

    def encodeBody(self):
        if not self.response and not self.query:
            return bitstring.pack("bytes:7, uint:8", self.hardware_id.hwid, self.new_node_id)
        elif self.hardware_id is not None:
            return bitstring.pack("bytes:7", self.hardware_id.hwid)
        else:
            return bitstring.BitString()
UnicastMessage.unicast_protocols[YARPMessage.PROTOCOL_NUMBER] = YARPMessage


class RAPMessage(UnicastMessage):
    PROTOCOL_NUMBER = 1

    def __init__(self, write, response, page, register, data=None, size=None, **kwargs):
        super(RAPMessage, self).__init__(RAPMessage.PROTOCOL_NUMBER, **kwargs)
        self.write = write
        self.response = response
        self.page = page
        self.register = register
        if data:
            self.data = data
        if size:
            self._size = size

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, value):
        if self._data:
            raise ValueError("Cannot explicitly set size when data is provided")
        else:
            self._size = value

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value
        self._size = len(value)

    @classmethod
    def decode(cls, priority, protocol, header, body):
        write = header.read('bool')
        response = header.read('bool')
        header.read('pad:1')
        size = header.read('uint:3')

        page = body.read('uint:8')
        register = body.read('uint:8')
        data = body.read('bytes')

        return cls(write, response, page, register, data, size=size, priority=priority)

    def encodeHeader(self):
        return super(RAPMessage, self).encodeHeader(
            bitstring.pack("bool, bool, pad:1, uint:3", self.write, self.response, self.size))

    def encodeBody(self):
        if self.write or self.response:
            return bitstring.pack("uint:8, uint:8, bytes", self.page, self.register, self.data)
        else:
            return bitstring.pack("uint:8, uint:8", self.page, self.register)
UnicastMessage.unicast_protocols[RAPMessage.PROTOCOL_NUMBER] = RAPMessage
