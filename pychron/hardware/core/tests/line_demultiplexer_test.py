import socket
import time
import unittest
from queue import Empty, Queue

from pychron.hardware.core.communicators.line_demultiplexer import LineDemultiplexer


class _ScriptedHandler:
    """Fake socket handler. Lines pushed via push() are returned by readline;
    canned responses are released when send_packet is called, emulating a
    device that replies to commands while also pushing async events."""

    def __init__(self, responses=None):
        self.sock = object()
        self.sent = []
        self.canned = list(responses or [])
        self._pending = Queue()

    def push(self, line):
        self._pending.put(line)

    def send_packet(self, payload):
        self.sent.append(payload)
        if self.canned:
            self._pending.put(self.canned.pop(0))

    def readline(self, terminator):
        try:
            return self._pending.get(timeout=0.02)
        except Empty:
            raise socket.timeout()


def _wait_for(predicate, timeout=2.0):
    st = time.time()
    while time.time() - st < timeout:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class LineDemultiplexerTestCase(unittest.TestCase):
    def setUp(self):
        self.demux = None

    def tearDown(self):
        if self.demux is not None:
            self.demux.stop()

    def _start(self, handler, **kw):
        self.demux = LineDemultiplexer(handler, **kw)
        self.demux.start()
        return self.demux

    def test_routes_events_and_responses(self):
        handler = _ScriptedHandler(responses=["OK#\r\n"])
        demux = self._start(handler)
        handler.push("#EVENT:ACQ,NOM,1,2,12:00:00.000,1.0#\r\n")

        response = demux.ask("GetValveStatus\r")
        event = demux.get_event(timeout=2)

        self.assertEqual(response, "OK#\r\n")
        self.assertEqual(event, "#EVENT:ACQ,NOM,1,2,12:00:00.000,1.0#\r\n")
        self.assertEqual(handler.sent, ["GetValveStatus\r"])

    def test_ask_drains_stale_responses(self):
        handler = _ScriptedHandler(responses=["FRESH#\r\n"])
        demux = self._start(handler)

        handler.push("STALE#\r\n")
        self.assertTrue(_wait_for(lambda: not demux._responses.empty()))

        response = demux.ask("Cmd\r")

        self.assertEqual(response, "FRESH#\r\n")

    def test_ask_timeout_returns_none(self):
        handler = _ScriptedHandler()
        demux = self._start(handler)

        response = demux.ask("Cmd\r", timeout=0.1)

        self.assertIsNone(response)

    def test_events_do_not_satisfy_ask(self):
        handler = _ScriptedHandler(responses=["#EVENT:ACQ,NOM,1#\r\n"])
        demux = self._start(handler)

        response = demux.ask("Cmd\r", timeout=0.2)

        self.assertIsNone(response)
        self.assertEqual(demux.get_event(timeout=1), "#EVENT:ACQ,NOM,1#\r\n")

    def test_reconnects_after_peer_close(self):
        first = _ScriptedHandler()
        second = _ScriptedHandler()
        reconnects = []

        def on_reconnect():
            reconnects.append(True)
            return second

        demux = self._start(first, on_reconnect=on_reconnect)
        first.push("")  # peer closed

        self.assertTrue(_wait_for(lambda: reconnects))
        second.push("#EVENT:ACQ,after#\r\n")
        self.assertEqual(demux.get_event(timeout=2), "#EVENT:ACQ,after#\r\n")

    def test_stop_terminates_reader(self):
        handler = _ScriptedHandler()
        demux = self._start(handler)
        self.assertTrue(demux.running)

        demux.stop()

        self.assertFalse(demux.running)

    def test_clear_events(self):
        handler = _ScriptedHandler()
        demux = self._start(handler)
        handler.push("#EVENT:one#\r\n")
        self.assertTrue(_wait_for(lambda: not demux._events.empty()))

        demux.clear_events()

        self.assertIsNone(demux.get_event(timeout=0.1))


if __name__ == "__main__":
    unittest.main()
