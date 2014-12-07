from datetime import datetime
import unittest
from .messages import *


class MessageSampleInputTestCase(unittest.TestCase):
	def test_thermostat_state(self):
		sample = "Z0F61046008FFE90000000019002000CA"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, ThermostatStateMessage))
		self.assertEqual(msg.counter, 0x61)
		self.assertEqual(msg.flag, 0x4)
		self.assertEqual(msg.sender_id, 0x8FFE9)
		self.assertEqual(msg.receiver_id, 0x0)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.payload, '19002000CA')
		self.assertEqual(msg.decoded_payload, {
			'battery_low': False,
			'desired_temperature': 16.0,
			'dstsetting': False,
			'is_locked': False,
			'langateway': True,
			'measured_temperature': 20.2,
			'mode': 'manual',
			'rferror': False,
			'valve_position': 0
		})

	def test_set_temperature(self):
		sample = "Z0BB900401234560B3554004B"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, SetTemperatureMessage))
		self.assertEqual(msg.counter, 0xB9)
		self.assertEqual(msg.flag, 0x0)
		self.assertEqual(msg.sender_id, 0x123456)
		self.assertEqual(msg.receiver_id, 0x0B3554)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.payload, '4B')
		self.assertEqual(msg.decoded_payload, {
			'desired_temperature': 5.5,
			'mode': 'manual',
		})

	def test_set_temp_ack(self):
		sample = "Z0EB902020B3554123456000119000B"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, AckMessage))
		self.assertEqual(msg.counter, 0xB9)
		self.assertEqual(msg.flag, 0x02)
		self.assertEqual(msg.sender_id, 0x0B3554)
		self.assertEqual(msg.receiver_id, 0x123456)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.payload, '0119000B')
		self.assertEqual(msg.decoded_payload, {
			'battery_low': False,
			'desired_temperature': 5.5,
			'dstsetting': False,
			'is_locked': False,
			'langateway': True,
			'mode': 'manual',
			'rferror': False,
			'state': 'ok',
			'valve_position': 0,
		})

	def test_pair_ping(self):
		sample = "Z170004000E016C000000001001A04B455130393932343736"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, PairPingMessage))
		self.assertEqual(msg.counter, 0x0)
		self.assertEqual(msg.flag, 0x04)
		self.assertEqual(msg.sender_id, 0xE016C)
		self.assertEqual(msg.receiver_id, 0x0)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.decoded_payload, {
			'firmware_version': "V1.0",
			'device_type': "HeatingThermostat",
			'selftest_result': 0xA0,
			'pairmode': "pair",
			'device_serial': "KEQ0992476",
		})

	def test_pair_pong(self):
		sample = "Z0B0100011234560E016C0000"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, PairPongMessage))
		self.assertEqual(msg.counter, 0x1)
		self.assertEqual(msg.flag, 0x00)
		self.assertEqual(msg.sender_id, 0x123456)
		self.assertEqual(msg.receiver_id, 0xE016C)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.payload, "00")
		self.assertEqual(msg.decoded_payload, {
			'devicetype': "Cube",
		})

	def test_time_information_question(self):
		sample = "Z0A000A030E016C12345600"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, TimeInformationMessage))
		self.assertEqual(msg.counter, 0x00)
		self.assertEqual(msg.flag, 0x0A)
		self.assertEqual(msg.sender_id, 0xE016C)
		self.assertEqual(msg.receiver_id, 0x123456)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.payload, "")

	def test_time_information(self):
		sample = "Z0F0204031234560E016C000E0102E117"
		msg = MoritzMessage.decode_message(sample)
		self.assertTrue(isinstance(msg, TimeInformationMessage))
		self.assertEqual(msg.counter, 0x02)
		self.assertEqual(msg.flag, 0x04)
		self.assertEqual(msg.sender_id, 0x123456)
		self.assertEqual(msg.receiver_id, 0xE016C)
		self.assertEqual(msg.group_id, 0)
		self.assertEqual(msg.payload, "0E0102E117")
		self.assertEqual(msg.decoded_payload, datetime(2014, 12, 1, 2, 33, 23))

class MessageGeneralOutputTestCase(unittest.TestCase):
	def test_encoding_without_payload(self):
		expected_result = "Zs0AB900F11234560B355400"
		msg = WakeUpMessage()
		msg.counter = 0xB9
		msg.sender_id = 0x123456
		msg.receiver_id = 0x0B3554
		msg.group_id = 0
		encoded_message = msg.encode_message()
		self.assertEqual(encoded_message, expected_result)

	def test_encoding_with_payload(self):
		expected_result = "Zs0BB900401234560B3554004B"
		msg = SetTemperatureMessage()
		msg.counter = 0xB9
		msg.sender_id = 0x123456
		msg.receiver_id = 0x0B3554
		msg.group_id = 0
		payload = {
			'desired_temperature': 5.5,
			'mode': 'manual',
		}
		encoded_message = msg.encode_message(payload)
		self.assertEqual(encoded_message, expected_result)
		self.assertEqual(msg.payload, expected_result[-2:])

	def test_encoding_with_broken_payload(self):
		expected_result = "Zs0BB900401234560B3554004B"
		msg = SetTemperatureMessage()
		msg.counter = 0xB9
		msg.sender_id = 0x123456
		msg.receiver_id = 0x0B3554
		msg.group_id = 0
		payload = {
			'desiredtemperature': 5.5,
			'mode': 'manual',
		}
		with self.assertRaises(MissingPayloadParameterError):
			encoded_message = msg.encode_message(payload)


class MessageOutputSampleTestCase(unittest.TestCase):
	def test_set_temperature(self):
		msg = SetTemperatureMessage()
		msg.counter = 0xB9
		msg.sender_id = 0x123456
		msg.receiver_id = 0x0B3554
		msg.group_id = 0
		payload = {
			'desired_temperature': 5.5,
			'mode': 'manual',
		}
		self.assertEqual(msg.encode_message(payload=payload), "Zs0BB900401234560B3554004B")

	def test_set_timeinformation(self):
		msg = TimeInformationMessage()
		msg.counter = 0x02
		msg.sender_id = 0x123456
		msg.receiver_id = 0xE016C
		msg.group_id = 0x0
		payload = datetime(2014, 12, 1, 2, 33, 23)
		self.assertEqual(msg.encode_message(payload=payload), "Zs0F0204031234560E016C000E0102E117")
