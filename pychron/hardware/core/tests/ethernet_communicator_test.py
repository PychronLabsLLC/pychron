import unittest
import json
import tempfile
from pathlib import Path
from typing import Optional
from unittest import mock

from pychron.hardware.core.checksum_helper import computeCRC

_IMPORT_ERROR: Optional[ModuleNotFoundError] = None
try:
    from pychron.hardware.core.communicators.ethernet_communicator import (
        EthernetCommunicator,
        MessageFrame,
        TCPHandler,
        UDPHandler,
    )
except ModuleNotFoundError as exc:
    EthernetCommunicator = None  # type: ignore[assignment, misc]
    MessageFrame = None  # type: ignore[assignment, misc]
    TCPHandler = None  # type: ignore[assignment, misc]
    UDPHandler = None  # type: ignore[assignment, misc]
    _IMPORT_ERROR = exc

from pychron.experiment.telemetry.context import TelemetryContext
from pychron.experiment.telemetry.recorder import TelemetryRecorder
from pychron.experiment.telemetry.span import set_global_recorder


class _FakeSocket:
    def __init__(self, recv_chunks=None):
        self.recv_chunks = list(recv_chunks or [])
        self.sent = []
        self.closed = False

    def sendall(self, payload):
        self.sent.append(payload)

    def recv(self, datasize):
        if self.recv_chunks:
            chunk = self.recv_chunks.pop(0)
            if isinstance(chunk, Exception):
                raise chunk
            return chunk
        return b""

    def recvfrom(self, datasize):
        if self.recv_chunks:
            return self.recv_chunks.pop(0), ("127.0.0.1", 1000)
        return b"", ("127.0.0.1", 1000)

    def close(self):
        self.closed = True


@unittest.skipIf(_IMPORT_ERROR is not None, "Traits stack not available")
class EthernetCommunicatorTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "ethernet-io.jsonl"
        self.recorder = TelemetryRecorder(self.log_path)
        TelemetryContext.clear()
        TelemetryContext.set_queue_id("queue_1")
        TelemetryContext.set_trace_id("trace_1")
        TelemetryContext.set_run_id("run_1")
        set_global_recorder(self.recorder)

    def tearDown(self):
        self.recorder.close()
        self.temp_dir.cleanup()
        TelemetryContext.clear()
        set_global_recorder(None)

    def test_tcp_handler_uses_sendall(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket()

        handler.send_packet("PING")

        self.assertEqual(handler.sock.sent, [b"PING"])

    def test_udp_handler_respects_message_frame(self):
        payload = b"0004TEST"
        handler = UDPHandler()
        handler.sock = _FakeSocket(recv_chunks=[payload])
        handler.message_frame = MessageFrame(message_len=True, nmessage_len=4)

        response = handler.get_packet(message_frame=handler.message_frame)

        self.assertEqual(response, "TEST")

    def test_message_frame_accumulates_multiple_chunks(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"0008AB", b"CDEFGH"])
        frame = MessageFrame(message_len=True, nmessage_len=4)

        response = handler.get_packet(message_frame=frame)

        self.assertEqual(response, "ABCDEFGH")

    def test_message_frame_header_split_across_chunks(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"00", b"04TE", b"ST"])
        frame = MessageFrame(message_len=True, nmessage_len=4)

        response = handler.get_packet(message_frame=frame)

        self.assertEqual(response, "TEST")

    def test_message_frame_invalid_length_header_returns_none(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"ZZZZTEST"])
        frame = MessageFrame(message_len=True, nmessage_len=4)

        response = handler.get_packet(message_frame=frame)

        self.assertIsNone(response)

    def test_readline_accumulates_until_terminator(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"A", b"B", b"\r", b"\n"])

        response = handler.readline(b"\r\n")

        self.assertEqual(response, "AB")

    def test_readline_preserves_partial_line_across_timeout(self):
        import socket as socket_module

        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"PAR", socket_module.timeout(), b"TIAL", b"\r\n"])

        with self.assertRaises(socket_module.timeout):
            handler.readline(b"\r\n")

        response = handler.readline(b"\r\n")

        self.assertEqual(response, "PARTIAL")

    def test_checksum_frame_accepts_valid_crc(self):
        payload = b"TEST"
        crc = computeCRC(payload).encode("utf-8")
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[payload + crc])
        frame = MessageFrame(checksum=True, nchecksum=4)

        response = handler.get_packet(message_frame=frame)

        self.assertEqual(response, "TEST")

    def test_checksum_frame_rejects_invalid_crc(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"TEST0000"])
        frame = MessageFrame(checksum=True, nchecksum=4)

        response = handler.get_packet(message_frame=frame)

        self.assertIsNone(response)

    def test_invalid_utf8_returns_none(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"\xff\xfe"])

        response = handler.get_packet()

        self.assertIsNone(response)

    def test_select_read_accumulates_chunks(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"HEL", b"LO#\r\n"])

        with mock.patch(
            "pychron.hardware.core.communicators.ethernet_communicator.select.select",
            return_value=([handler.sock], [], []),
        ):
            response = handler.select_read()

        self.assertEqual(response, "HELLO")

    def test_select_read_returns_none_when_peer_closes(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket(recv_chunks=[b"partial"])

        with mock.patch(
            "pychron.hardware.core.communicators.ethernet_communicator.select.select",
            return_value=([handler.sock], [], []),
        ):
            response = handler.select_read()

        self.assertIsNone(response)

    def test_select_read_returns_none_when_not_readable(self):
        handler = TCPHandler()
        handler.sock = _FakeSocket()

        with mock.patch(
            "pychron.hardware.core.communicators.ethernet_communicator.select.select",
            return_value=([], [], []),
        ):
            response = handler.select_read()

        self.assertIsNone(response)

    def test_reset_closes_read_and_write_handlers(self):
        communicator = EthernetCommunicator()
        communicator.handler = TCPHandler()
        write_sock = _FakeSocket()
        communicator.handler.sock = write_sock
        communicator.read_handler = UDPHandler()
        read_sock = _FakeSocket()
        communicator.read_handler.sock = read_sock

        communicator.reset()

        self.assertTrue(write_sock.closed)
        self.assertTrue(read_sock.closed)
        self.assertIsNone(communicator.handler)
        self.assertIsNone(communicator.read_handler)

    def test_message_frame_use_warns_deprecation_once(self):
        communicator = EthernetCommunicator(name="spec_comm")
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.simulation = False
        communicator.write_terminator = "\r"
        communicator.log_response = lambda *args, **kw: None
        communicator._ask = lambda *args, **kw: "OK"
        warnings = []
        communicator.warning = lambda msg: warnings.append(msg)

        frame = MessageFrame(message_len=True, nmessage_len=4)
        communicator.ask("GetData", verbose=False, message_frame=frame, retries=1)
        communicator.ask("GetData", verbose=False, message_frame=frame, retries=1)

        self.assertEqual(len(warnings), 1)
        self.assertIn("deprecated", warnings[0])

    def test_no_deprecation_warning_without_message_frame(self):
        communicator = EthernetCommunicator(name="spec_comm")
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.simulation = False
        communicator.write_terminator = "\r"
        communicator.log_response = lambda *args, **kw: None
        communicator._ask = lambda *args, **kw: "OK"
        warnings = []
        communicator.warning = lambda msg: warnings.append(msg)

        communicator.ask("GetData", verbose=False, retries=1)

        self.assertEqual(warnings, [])

    def test_ask_records_start_and_end_device_io_events(self):
        communicator = EthernetCommunicator(name="spec_comm")
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.simulation = False
        communicator.write_terminator = "\r"
        communicator.log_response = lambda *args, **kw: None
        communicator._ask = lambda *args, **kw: "OK"

        result = communicator.ask("GetData", verbose=False)

        self.recorder.flush()
        with open(self.log_path) as rfile:
            events = [json.loads(line) for line in rfile.readlines()]

        self.assertEqual(result, "OK")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["payload"]["stage"], "start")
        self.assertEqual(events[1]["payload"]["stage"], "end")
        self.assertEqual(events[1]["payload"]["success"], True)

    def test_repeated_failures_call_health_failure_callback(self):
        communicator = EthernetCommunicator(name="spec_comm")
        failures = []
        communicator.health_failure_callback = lambda operation, **kw: failures.append(
            (operation, kw.get("error"))
        )
        communicator._ask = lambda *args, **kw: None
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.simulation = False
        communicator.write_terminator = "\r"
        communicator.log_response = lambda *args, **kw: None

        communicator.ask("GetData", verbose=False)

        self.assertEqual(failures[-1][0], "ask")
        self.assertIn("Connection refused", failures[-1][1])

    def test_on_connect_fires_for_new_handler_with_guard(self):
        communicator = EthernetCommunicator(name="spec_comm")
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        connects = []

        def on_connect(handler):
            connects.append(handler)
            # re-entrant get_handler must not fire the hook again
            communicator.get_handler()

        communicator.on_connect = on_connect

        fake_handler = TCPHandler()
        fake_handler.sock = _FakeSocket()
        fake_handler.address = ("127.0.0.1", 8000)

        with mock.patch.object(TCPHandler, "open_socket", lambda self_, addrs, **kw: None):
            handler = communicator.get_handler()

        self.assertEqual(len(connects), 1)
        self.assertIs(connects[0], handler)

    def test_select_read_with_failed_handler_returns_none(self):
        communicator = EthernetCommunicator(name="spec_comm")
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.get_handler = lambda *args, **kw: None

        self.assertIsNone(communicator.select_read())

    def test_read_handler_does_not_clobber_write_handler(self):
        communicator = EthernetCommunicator(name="spec_comm")
        communicator.kind = "UDP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.read_port = 8001

        write_handler = TCPHandler()
        write_handler.sock = _FakeSocket()
        write_handler.address = ("127.0.0.1", 8000)
        communicator.handler = write_handler

        read_handler = communicator.get_read_handler(write_handler)

        self.assertIsNot(read_handler, write_handler)
        self.assertIs(communicator.read_handler, read_handler)
        self.assertIs(communicator.handler, write_handler)
        if read_handler:
            read_handler.end()

    def test_successful_write_calls_health_success_callback(self):
        communicator = EthernetCommunicator(name="spec_comm")
        successes = []
        communicator.health_success_callback = lambda operation, **kw: successes.append(operation)
        communicator.kind = "TCP"
        communicator.host = "127.0.0.1"
        communicator.port = 8000
        communicator.handler = TCPHandler()
        communicator.handler.sock = _FakeSocket()
        communicator.handler.address = ("127.0.0.1", 8000)
        communicator.log_tell = lambda *args, **kw: None

        communicator.tell("PING", verbose=False)

        self.assertEqual(successes[-1], "tell")


if __name__ == "__main__":
    unittest.main()
