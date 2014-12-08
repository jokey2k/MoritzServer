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
from moritzprotocol.signals import thermostatstate_received

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
        self._has_send_budget = False

    def run(self):
        self._init_cul()
        while not self.stop_requested.isSet():
            # Process pending received messages (if any)
            read_line = self._read_result()
            if read_line is not None:
                com_logger.info("Got unhandled response from CUL: '%s'" % read_line)

            # send queued messages yet respecting send budget of 1%
            if not self.send_queue.empty() and self.has_send_budget:
                com_logger.debug("Processing queued outgoing message(s)")
                while not self.send_queue.empty():
                    com_logger.debug("Checking available budget (if not already done)")
                    if not self.has_send_budget:
                        break
                    com_logger.debug("Fetching message from queue")
                    out_msg = self.send_queue.get(True, 0.05)
                    if out_msg is None:
                        com_logger.debug("Failed fetching message due to thread lock, deferring")
                        break
                    com_logger.debug("Queueing command %s" % out_msg)
                    self.send_command(out_msg)

            # give the system 250ms to do something else, we're embedded....
            time.sleep(0.25)

    def join(self, timeout=None):
        self.stop_requested.set()
        super(CULComThread, self).join(timeout)

    def _init_cul(self):
        """Ensure CUL reports reception strength and does not do FS messages"""

        self.com_port = Serial(self.device_path)
        self._read_result()
        # get CUL FW version
        self.send_command("V")
        time.sleep(0.3)
        self.cul_version = self._read_result() or ""
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

        if self._has_send_budget:
            return self._has_send_budget
        self.send_command("X")
        for i in range(0,10):
            result = self._read_result()
            if result is None:
                time.sleep(0.2)
                continue
            if result[0:2] != "21":
                # we set X21 in the beginning and this should be our response now
                com_logger.debug("Received unrelated message for budget question: '%s'" % result)
                continue
            remaining_ms = int(result[3:].strip()) * 10
            if remaining_ms > 2000:
                self._has_send_budget = True
                com_logger.debug("Enough send budget: %s ms" % remaining_ms)
            else:
                com_logger.info("Currently no send budget. Only %s ms available and we need at least 2000 ms")
                break
        return self._has_send_budget

    def send_command(self, command):
        """Sends given command to CUL. Invalidates has_send_budget if command starts with Zs"""

        if command.startswith("Zs"):
            self._has_send_budget = False
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
                signal_strenth = received_msg[-2:]
                self.respond_to_message(message, signal_strenth)
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
                message_logger.info("responding to pair after factory reset")
                self.command_queue.put((resp_msg, {"devicetype": "Cube"}))
            elif msg.receiver_id == CUBE_ID:
                # pairing after battery replacement
                resp_msg = PairPongMessage()
                resp_msg.counter = 1
                resp_msg.sender_id = CUBE_ID
                resp_msg.receiver_id = msg.sender_id
                resp_msg.group_id = msg.group_id
                message_logger.info("responding to pair after battery replacement")
                self.command_queue.put((resp_msg, {"devicetype": "Cube"}))
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

        elif isinstance(msg, ThermostatStateMessage):
            with self.thermostat_states_lock:
                message_logger.info("thermostat state updated for 0x%X" % msg.sender_id)
                self.thermostat_states[msg.sender_id].update(msg.decoded_payload)
                self.thermostat_states[msg.sender_id]['last_updated'] = datetime.now()
                self.thermostat_states[msg.sender_id]['signal_strenth'] = signal_strenth
            thermostatstate_received.send(msg)

        elif isinstance(msg, AckMessage):
            if msg.receiver_id == CUBE_ID and msg.decoded_payload["state"] == "ok":
                with self.thermostat_states_lock:
                    message_logger.info("ack and thermostat state updated for 0x%X" % msg.sender_id)
                    self.thermostat_states[msg.sender_id].update(msg.decoded_payload)
                    self.thermostat_states[msg.sender_id]['last_updated'] = datetime.now()
                    self.thermostat_states[msg.sender_id]['signal_strenth'] = signal_strenth
