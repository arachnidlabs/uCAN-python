import can.message
from can.interfaces import socketcan_ctypes
import time
from uCAN.messages import HardwareId, Message, UnicastMessage, YARPMessage, RAPMessage


class NodeAddress(object):
    def __init__(self, bus, node_id):
        self.bus = bus
        self.node_id = node_id


def _encodeMessage(message):
    return can.message.Message(
        arbitration_id=message.encodeHeader().uint,
        data=message.encodeBody().bytes)


class Bus(object):
    handlers = {}

    def __init__(self, bus, hardware_id):
        if isinstance(bus, basestring):
            bus = socketcan_ctypes.Bus(bus)
        self.bus = bus
        self.hardware_id = HardwareId(hardware_id)
        self.node_id = None
        self.on_new_node_id = None
        self.timeout = 1.0
        self.promiscuous = False

        # RAP variables
        self.register_map = {}

    def start(self, default_node_id=None, now=time.time):
        if not default_node_id:
            default_node_id = ord(self.hardware_id.hwid[-1])
        default_node_id &= 0x7F

        self.node_id = 0xFF
        # See if there's a nameserver out there to assign us a node ID
        node = self.getNodeFromHardwareId(self.hardware_id, now=now)
        if node:
            self.node_id = node.node_id

        # If we weren't assigned one, ping nodes until we find a free ID
        while self.node_id == 0xFF:
            if not self.ping(NodeAddress(self, default_node_id), now=now):
                self.node_id = default_node_id
            else:
                default_node_id = (default_node_id + 1) & 0x7F

    def send(self, message):
        self.bus.send(_encodeMessage(message))

    def _handleMessage(self, message):
        return Bus.handlers.get(type(message), lambda self, message: False)(self, message)

    def _tryReceive(self, timeout=None):
        message = self.bus.recv(timeout)
        if not message:
            return None
        if message.is_remote_frame or not message.id_type or message.is_error_frame:
            # Ignore these types of messages
            return None

        message = Message.decode(message.arbitration_id, message.data)

        # Ignore messages not addressed to us
        if isinstance(message, UnicastMessage) and \
           message.recipient != self.node_id and \
           message.recipient != UnicastMessage.BROADCAST_RECIPIENT:
            if self.promiscuous:
                return message
            else:
                return None

        return None if self._handleMessage(message) else message

    def _receiveUntil(self, filter, now=time.time):
        start = now()
        remaining = self.timeout
        while remaining > 0:
            message = self._tryReceive(remaining)
            if message and filter(message):
                return message
            remaining = self.timeout - (now() - start)
        return None

    def receive(self):
        self._tryReceive()

    def getNodeFromNodeId(self, node_id):
        """Returns a NodeAddress instance for a given Node ID."""
        return NodeAddress(self, node_id)

    def getNodeFromHardwareId(self, hardware_id, now=time.time):
        """Returns a NodeAddress instance for a given Node ID, or None if the node is not found."""
        # TODO: Implement hardware ID caching
        hardware_id = HardwareId(hardware_id)
        self.send(YARPMessage(
            sender=self.node_id,
            recipient=YARPMessage.BROADCAST_RECIPIENT,
            query=True,
            response=False,
            hardware_id=hardware_id))

        def is_reply(message):
            return (isinstance(message, YARPMessage) and message.hardware_id == hardware_id and
                    message.query and message.response)
        response = self._receiveUntil(is_reply, now=now)
        return response and NodeAddress(self, response.sender)

    def _handleYARP(self, message):
        if message.query and not message.response:
            # Ping message
            if message.recipient != 0xFF and message.recipient != self.node_id:
                # Addressed to someone else
                return False
            if message.hardware_id and message.hardware_id != self.hardware_id:
                # Addressed to someone else by hwid
                return False

            self.send(YARPMessage(
                sender=self.node_id,
                recipient=message.sender,
                query=True,
                response=True,
                hardware_id=self.hardware_id,
                priority=message.priority))
            return True
        elif not message.query and not message.response:
            # Address assignment
            if message.hardware_id != self.hardware_id:
                # Addressed to someone else
                return False
            self.node_id = message.new_node_id
            self.onAddressChange(self.node_id)
    handlers[YARPMessage] = _handleYARP

    def onAddressChange(self, node_id):
        """Called when a node's address changes."""
        pass

    def ping(self, node, now=time.time):
        """Pings a node to check if it's up.

        Arguments:
            node: A Node object.

        Returns:
            A hardware address, if the node is found, or None if not.
        """
        self.send(YARPMessage(
            sender=self.node_id,
            recipient=node.node_id,
            query=True,
            response=False))

        def is_reply(message):
            return (isinstance(message, YARPMessage) and message.sender == node.node_id and
                    message.query and message.response)
        response = self._receiveUntil(is_reply, now=now)
        return response and response.hardware_id

    def setAddress(self, hardware_id, node_id):
        """Sets the node ID of a node.

        Arguments:
            hardware_id: The Hardware ID of the node to change the address of.
            node_id: The new node ID for the target node.
        """
        hardware_id = HardwareId(hardware_id)
        self.send(YARPMessage(
            sender=self.node_id,
            recipient=YARPMessage.BROADCAST_RECIPIENT,
            query=False,
            response=False,
            hardware_id=hardware_id,
            new_node_id=node_id))

    def _handleRAP(self, message):
        if message.response:
            return False

        read_handler, write_handler = self.register_map.get(message.page, (None, None))

        if message.write:
            self._handleRAPWrite(message.sender, write_handler, message.page, message.register, message.data)
        else:
            self._handleRAPRead(message.sender, read_handler, message.page, message.register, message.size)
    handlers[RAPMessage] = _handleRAP

    def _handleRAPRead(self, sender, handler, page, register, size):
        if handler:
            data = [handler(self, page, (register + i) % 256) for i in range(size)]
        else:
            data = ['\0'] * size

        self.send(RAPMessage(
            sender=self.node_id,
            recipient=sender,
            write=False,
            response=True,
            page=page,
            register=register,
            data=data))

    def _handleRAPWrite(self, sender, handler, page, register, data):
        if not handler:
            return

        for i in range(len(data)):
            handler(self, page, (register + i) % 256, data[i])

    def configureRegisters(self, page, read_handler, write_handler):
        """Configures read and write handlers for a RAP register page.

        Arguments:
          page: A page number, between 0 and 255 inclusive.
          read_handler: A function to handle reads from this page.
            This function will be called with the arguments (bus, page, register), and is expected
            to return a single character string for the value of that register.
          write_handler: A function to handle writes to this page.
            This function will be called with the arguments (bus, page, register, data), where data
            is a single character string.
        """
        self.register_map[page] = (read_handler, write_handler)

    def readRegisters(self, node, page, register, length, now=time.time):
        """Reads one or more registers from a remote node, returning them as a raw string.

        Arguments:
          node: The Node to send the read request to.
          page: The page number to read from.
          register: The starting register number to read from.
          length: The number of bytes to read, maximum 6.

        Returns:
          A raw string containing register data, or None if no response was received in time.
        """
        if length > 6:
            raise ValueError("Read too long: Only a maximum of 6 bytes may be read at once.")

        self.send(RAPMessage(
            sender=self.node_id,
            recipient=node.node_id,
            write=False,
            response=False,
            page=page,
            register=register,
            size=length))

        def is_reply(message):
            return isinstance(message, RAPMessage) and message.sender == node.node_id and \
                message.response and not message.write and message.page == page and \
                message.register == register
        message = self._receiveUntil(is_reply, now=now)
        return message and message.data

    def writeRegisters(self, node, page, register, data):
        """Writes one or more registers on a remote node.

        Arguments:
          node: The node to send the write to.
          page: The page number to write to.
          register: The starting register to write to.
          data: The data to write, maximum 6 bytes.
        """
        if len(data) > 6:
            raise ValueError("Write too long; only a maximum of 6 bytes may be written at once.")

        self.send(RAPMessage(
            sender=self.node_id,
            recipient=node.node_id,
            write=True,
            response=False,
            page=page,
            register=register,
            data=data))
