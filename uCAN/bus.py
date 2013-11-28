import can.message
from can.interfaces import socketcan_ctypes
import time
from uCAN.messages import HardwareId, Message, UnicastMessage, YARPMessage


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
            return None

        return None if self._handleMessage(message) else message

    def _receiveUntil(self, filter, time=time.time):
        start = time()
        remaining = self.timeout
        while remaining > 0:
            message = self._tryReceive(remaining)
            if message and filter(message):
                return message
            remaining = self.timeout - (time() - start)
        return None

    def receive(self):
        self._tryReceive()

    def getNodeFromNodeId(self, node_id):
        """Returns a NodeAddress instance for a given Node ID."""
        return NodeAddress(self, node_id)

    def getNodeFromHardwareId(self, hardware_id):
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
        response = self._receiveUntil(is_reply)
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

    def ping(self, node):
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
        response = self._receiveUntil(is_reply)
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
