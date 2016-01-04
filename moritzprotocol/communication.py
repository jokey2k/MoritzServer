# -*- coding: utf-8 -*-
"""
    moritzprotocol.communication
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    There are two communication classes available which should run in their own thread.
    CULComThread performs low-level serial communication, CULMessageThread performs high-level
    communication and spawns a CULComThread for its low-level needs.

    Generally just use CULMessageThread unless you have a good reason not to.

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports
from collections import defaultdict
from datetime import datetime
import Queue
import threading
import time

# environment imports
import logbook
from serial import Serial

# custom imports
from moritzprotocol.exceptions import MoritzError
from moritzprotocol.messages import (
    MoritzMessage, MoritzError,
    PairPingMessage, PairPongMessage,
    TimeInformationMessage,
    SetTemperatureMessage, ThermostatStateMessage, AckMessage
)
from moritzprotocol.signals import thermostatstate_received, device_pair_accepted, device_pair_request

# local constants
com_logger = logbook.Logger("CUL Serial")
message_logger = logbook.Logger("CUL Messaging")

# Hardcodings based on FHEM recommendations
CUBE_ID = 0x123456
WALLTHERMO_ID = 0x123457
SHUTTERCONTACT_ID = 0x123458

class CULComThread(threading.Thread):
    """Low-level serial communication thread base"""

    def __init__(self, send_queue, read_queue, device_path):
        super(CULComThread, self).__init__()
        self.send_queue = send_queue
        self.read_queue = read_queue
        self.device_path = device_path
        self.pending_line = []
        self.stop_requested = threading.Event()
        self.cul_version = ""
        self._pending_budget = 0
        self._pending_message = None

    def run(self):
        self._init_cul()
        while not self.stop_requested.isSet():
            # Send budget request if we don't know it
            if self._pending_budget == 0:
                self.send_command("X")
                for i in range(10):
                    read_line = self._read_result()
                    if read_line is not None:
                        if read_line.startswith("21  "):
                            self._pending_budget = int(read_line[3:].strip()) * 10 or 1
                            com_logger.info("Got pending budget message: %sms" % self._pending_budget)
                        else:
                            com_logger.info("Got unhandled response from CUL: '%s'" % read_line)
                    if self._pending_budget > 0:
                        com_logger.debug("Finished fetching budget, having %sms now" % self._pending_budget)
                        break
                    time.sleep(0.05)

            # Process pending received messages (if any)
            read_line = self._read_result()
            if read_line is not None:
                if read_line.startswith("21  "):
                    self._pending_budget = int(read_line[3:].strip()) * 10 or 1
                    com_logger.info("Got pending budget: %sms" % self._pending_budget)
                else:
                    com_logger.info("Got unhandled response from CUL: '%s'" % read_line)

            if self._pending_message is None and not self.send_queue.empty():
                com_logger.debug("Fetching message from queue")
                self._pending_message = self.send_queue.get(True, 0.05)
                if self._pending_message is None:
                    com_logger.debug("Failed fetching message due to thread lock, deferring")

            # send queued messages yet respecting send budget of 1%
            if self._pending_message:
                com_logger.debug("Checking quota for outgoing message")
                if self._pending_budget > len(self._pending_message)*10:
                    com_logger.debug("Queueing pre-fetched command %s" % self._pending_message)
                    self.send_command(self._pending_message)
                    self._pending_message = None
                else:
                    self._pending_budget = 0
                    com_logger.debug("Not enough quota, re-check enforced")

            # give the system 200ms to do something else, we're embedded....
            time.sleep(0.2)

    def join(self, timeout=None):
        self.stop_requested.set()
        super(CULComThread, self).join(timeout)

    def _init_cul(self):
        """Ensure CUL reports reception strength and does not do FS messages"""

        self.com_port = Serial(self.device_path)
        self._read_result()
        # get CUL FW version
        def _get_cul_ver():
            self.send_command("V")
            time.sleep(0.3)
            self.cul_version = self._read_result() or ""
        for i in range(10):
            _get_cul_ver()
            if self.cul_version:
                com_logger.info("CUL reported version %s" % self.cul_version)
                break
            else:
                com_logger.info("No version from CUL reported?")
        if not self.cul_version:
            com_logger.info("No version from CUL reported. Closing and re-opening port")
            self.com_port.close()
            self.com_port = Serial(self.device_path)
            for i in range(10):
                _get_cul_ver()
                if self.cul_version:
                    com_logger.info("CUL reported version %s" % self.cul_version)
                else:
                    com_logger.info("No version from CUL reported?")
            com_logger.error("No version from CUL, cannot communicate")
            self.stop_requested.set()
            return

        # enable reporting of message strength
        self.send_command("X21")
        time.sleep(0.3)
        # receive Moritz messages
        self.send_command("Zr")
        time.sleep(0.3)
        # disable FHT mode by setting station to 0000
        self.send_command("T01")
        time.sleep(0.3)
        self._read_result()

    @property
    def has_send_budget(self):
        """Ask CUL if we have enough budget of the 1 percent rule left"""

        return self._pending_budget >= 2000

    def send_command(self, command):
        """Sends given command to CUL. Invalidates has_send_budget if command starts with Zs"""

        if command.startswith("Zs"):
            self._pending_budget = 0
        self.com_port.write(command + "\r\n")
        com_logger.debug("sent: %s" % command)

    def _read_result(self):
        """Reads data from port, if it's a Moritz message, forward directly, otherwise return to caller"""

        while self.com_port.inWaiting():
            self.pending_line.append(self.com_port.read(1))
            if self.pending_line[-1] == "\n":
                # remove newlines at the end
                completed_line = "".join(self.pending_line[:-2])
                com_logger.debug("received: %s" % completed_line)
                self.pending_line = []
                if completed_line.startswith("Z"):
                    self.read_queue.put(completed_line)
                else:
                    return completed_line


class CULMessageThread(threading.Thread):
    """High level message processing"""

    def __init__(self, command_queue, device_path):
        super(CULMessageThread, self).__init__()
        self.command_queue = command_queue
        self.thermostat_states = defaultdict(dict)
        self.thermostat_states_lock = threading.Lock()
        self.com_send_queue = Queue.Queue()
        self.com_receive_queue = Queue.Queue()
        self.com_thread = CULComThread(self.com_send_queue, self.com_receive_queue, device_path)
        self.stop_requested = threading.Event()
        self.pair_as_cube = True
        self.pair_as_wallthermostat = False
        self.pair_as_ShutterContact = False

    def run(self):
        self.com_thread.start()
        while not self.stop_requested.isSet():
            message = None
            try:
                received_msg = self.com_receive_queue.get(True, 0.05)
                message = MoritzMessage.decode_message(received_msg[:-2])
                signal_strength = int(received_msg[-2:], base=16)
                self.respond_to_message(message, signal_strength)
            except Queue.Empty:
                pass
            except MoritzError as e:
                message_logger.error("Message parsing failed, ignoring message '%s'. Reason: %s" % (received_msg, str(e)))

            try:
                msg, payload = self.command_queue.get(True, 0.05)
                raw_message = msg.encode_message(payload)
                message_logger.debug("send type %s" % msg)
                self.com_send_queue.put(raw_message)
            except Queue.Empty:
                pass

            time.sleep(0.3)

    def join(self, timeout=None):
        self.com_thread.join(timeout)
        self.stop_requested.set()
        super(CULMessageThread, self).join(timeout)

    def respond_to_message(self, msg, signal_strenth):
        """Internal function to respond to incoming messages where appropriate"""

        if isinstance(msg, PairPingMessage):
            message_logger.info("received PairPing")
            # Some peer wants to pair. Let's see...
            device_pair_request.send(self, msg=msg)
            if msg.receiver_id == 0x0:
                # pairing after factory reset
                if not (self.pair_as_cube or self.pair_as_wallthermostat or self.pair_as_ShutterContact):
                    message_logger.info("Pairing to new device but we should ignore it")
                    return
                resp_msg = PairPongMessage()
                resp_msg.counter = 1
                resp_msg.sender_id = CUBE_ID
                resp_msg.receiver_id = msg.sender_id
                resp_msg.group_id = msg.group_id
                if self.com_thread.has_send_budget:
                    message_logger.info("responding to pair after factory reset")
                    self.command_queue.put((resp_msg, {"devicetype": "Cube"}))
                    device_pair_accepted.send(self, resp_msg=resp_msg)
                else:
                    message_logger.info("NOT responding to pair after factory reset as no send budget to be on time")
                return
            elif msg.receiver_id == CUBE_ID:
                # pairing after battery replacement
                resp_msg = PairPongMessage()
                resp_msg.counter = 1
                resp_msg.sender_id = CUBE_ID
                resp_msg.receiver_id = msg.sender_id
                resp_msg.group_id = msg.group_id
                if self.com_thread.has_send_budget:
                    message_logger.info("responding to pair after battery replacement")
                    self.command_queue.put((resp_msg, {"devicetype": "Cube"}))
                    device_pair_accepted.send(self, resp_msg=resp_msg)
                else:
                    message_logger.info("NOT responding to pair after battery replacement as no send budget to be on time")
                return
            else:
                # pair to someone else after battery replacement, don't care
                message_logger.info("pair after battery replacement sent to other device 0x%X, ignoring" % msg.receiver_id)
                return

        elif isinstance(msg, TimeInformationMessage):
            if not msg.payload and msg.receiver_id == CUBE_ID:
                # time information requested
                resp_msg = TimeInformationMessage()
                resp_msg.counter = 1
                resp_msg.sender_id = CUBE_ID
                resp_msg.receiver_id = msg.sender_id
                resp_msg.group_id = msg.group_id
                message_logger.info("time information requested by 0x%X, responding" % msg.sender_id)
                self.command_queue.put((resp_msg, datetime.now()))
                return

        elif isinstance(msg, ThermostatStateMessage):
            with self.thermostat_states_lock:
                message_logger.info("thermostat state updated for 0x%X" % msg.sender_id)
                self.thermostat_states[msg.sender_id].update(msg.decoded_payload)
                self.thermostat_states[msg.sender_id]['last_updated'] = datetime.now()
                self.thermostat_states[msg.sender_id]['signal_strenth'] = signal_strenth
            thermostatstate_received.send(self, msg=msg)
            return

        elif isinstance(msg, AckMessage):
            if msg.receiver_id == CUBE_ID and msg.decoded_payload["state"] == "ok":
                thermostatstate_received.send(self, msg=msg)
                with self.thermostat_states_lock:
                    message_logger.info("ack and thermostat state updated for 0x%X" % msg.sender_id)
                    self.thermostat_states[msg.sender_id].update(msg.decoded_payload)
                    self.thermostat_states[msg.sender_id]['last_updated'] = datetime.now()
                    self.thermostat_states[msg.sender_id]['signal_strenth'] = signal_strenth
                return

        message_logger.warning("Unhandled Message of type %s, contains %s" % (msg.__class__.__name__, str(msg)))

