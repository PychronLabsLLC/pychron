import unittest

from pychron.hardware.pychron_device import (
    SerialCommunicationStrategy,
    EthernetCommunicationStrategy,
)


class _FakeCommunicator:
    def __init__(self):
        self.open_calls = []
        self.reported = False
        # serial attrs
        self.port = None
        self.baudrate = None
        self.read_delay = None
        self.parity = None
        self.stopbits = None
        # ethernet attrs
        self.host = None
        self.kind = None
        self.use_end = None
        self.message_frame = None
        self.write_terminator = None
        self.read_terminator = None
        self.timeout = None

    def set_parity(self, v):
        self.parity = v

    def set_stopbits(self, v):
        self.stopbits = v

    def open(self, **kw):
        self.open_calls.append(kw)
        return True

    def report(self):
        self.reported = True


class _FakeDevice:
    def __init__(self, communicator=None, build_result=None):
        self.communicator = communicator
        self._build_result = build_result if build_result is not None else _FakeCommunicator()
        self.build_calls = []

        # connection traits read by the strategies
        self.port = 0
        self.baudrate = 9600
        self.read_delay = 25
        self.parity = "N"
        self.stopbits = "1"
        self.host = "localhost"
        self.kind = "FusionsCO2"
        self.use_end = True
        self.message_frame = "\n"
        self.write_terminator = "\n"
        self.read_terminator = ""
        self.timeout = 3

    def build_communicator(self, comtype):
        self.build_calls.append(comtype)
        self.communicator = self._build_result
        return self._build_result


class SerialCommunicationStrategyTestCase(unittest.TestCase):
    def test_builds_serial_communicator(self):
        device = _FakeDevice()
        device.port = "COM1"

        ret = SerialCommunicationStrategy().setup(device)

        self.assertTrue(ret)
        self.assertEqual(device.build_calls, ["serial"])

    def test_configures_communicator_from_device_traits(self):
        device = _FakeDevice()
        device.port = "COM1"
        device.baudrate = 19200
        device.read_delay = 50
        device.parity = "E"
        device.stopbits = "2"

        ec = device.build_communicator("serial")
        device.build_calls = []
        SerialCommunicationStrategy().setup(device)

        self.assertEqual(ec.port, "COM1")
        self.assertEqual(ec.baudrate, 19200)
        self.assertEqual(ec.read_delay, 50)
        self.assertEqual(ec.parity, "E")
        self.assertEqual(ec.stopbits, "2")

    def test_opens_with_timeout(self):
        device = _FakeDevice()
        device.timeout = 7

        ec = device.build_communicator("serial")
        SerialCommunicationStrategy().setup(device)

        self.assertEqual(ec.open_calls, [{"timeout": 7}])

    def test_returns_none_when_build_fails(self):
        device = _FakeDevice()
        device.build_communicator = lambda comtype: None

        ret = SerialCommunicationStrategy().setup(device)

        self.assertIsNone(ret)


class EthernetCommunicationStrategyTestCase(unittest.TestCase):
    def test_builds_ethernet_communicator_when_none(self):
        device = _FakeDevice(communicator=None)

        ret = EthernetCommunicationStrategy().setup(device)

        self.assertTrue(ret)
        self.assertEqual(device.build_calls, ["ethernet"])

    def test_configures_communicator_from_device_traits(self):
        device = _FakeDevice(communicator=None)
        device.host = "192.168.0.5"
        device.port = 8080
        device.kind = "ArgusVI"
        device.use_end = False
        device.message_frame = "\r"
        device.timeout = 9

        ec = EthernetCommunicationStrategy().setup(device) and device.communicator

        self.assertEqual(ec.host, "192.168.0.5")
        self.assertEqual(ec.port, 8080)
        self.assertEqual(ec.kind, "ArgusVI")
        self.assertEqual(ec.use_end, False)
        self.assertEqual(ec.message_frame, "\r")
        self.assertEqual(ec.timeout, 9)

    def test_terminator_override(self):
        device = _FakeDevice(communicator=None)

        EthernetCommunicationStrategy().setup(
            device, write_terminator="\r\n", read_terminator="\r\n"
        )

        self.assertEqual(device.communicator.write_terminator, "\r\n")
        self.assertEqual(device.communicator.read_terminator, "\r\n")

    def test_terminator_defaults_from_device(self):
        device = _FakeDevice(communicator=None)
        device.write_terminator = "W"
        device.read_terminator = "R"

        EthernetCommunicationStrategy().setup(device)

        self.assertEqual(device.communicator.write_terminator, "W")
        self.assertEqual(device.communicator.read_terminator, "R")

    def test_skips_build_when_already_connected(self):
        existing = _FakeCommunicator()
        device = _FakeDevice(communicator=existing)

        ret = EthernetCommunicationStrategy().setup(device)

        self.assertTrue(ret)
        self.assertEqual(device.build_calls, [])
        self.assertEqual(existing.open_calls, [])

    def test_force_rebuilds_when_already_connected(self):
        existing = _FakeCommunicator()
        device = _FakeDevice(communicator=existing)

        EthernetCommunicationStrategy().setup(device, force=True)

        self.assertEqual(device.build_calls, ["ethernet"])

    def test_reports_after_open(self):
        device = _FakeDevice(communicator=None)

        EthernetCommunicationStrategy().setup(device)

        self.assertTrue(device.communicator.reported)

    def test_returns_none_when_build_fails(self):
        device = _FakeDevice(communicator=None)
        device.build_communicator = lambda comtype: None

        ret = EthernetCommunicationStrategy().setup(device)

        self.assertIsNone(ret)


if __name__ == "__main__":
    unittest.main()
