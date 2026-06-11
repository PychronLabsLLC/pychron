import unittest
from typing import Optional
from unittest import mock

_IMPORT_ERROR: Optional[ModuleNotFoundError] = None
try:
    from pychron.hardware.isotopx_spectrometer_controller import NGXController
except ModuleNotFoundError as exc:
    NGXController = None  # type: ignore[assignment, misc]
    _IMPORT_ERROR = exc


class _FakeHandler:
    def __init__(self, lines=None):
        self.sent = []
        self.lines = list(lines or [])

    def send_packet(self, payload):
        self.sent.append(payload)

    def readline(self, terminator):
        if self.lines:
            return self.lines.pop(0)
        return None


@unittest.skipIf(_IMPORT_ERROR is not None, "Traits stack not available")
class NGXControllerValveRetryTestCase(unittest.TestCase):
    def _make_controller(self, responses):
        controller = NGXController(name="ngx")
        warnings = []
        controller.warning = lambda msg: warnings.append(msg)
        controller.debug = lambda msg: None
        asks = []

        def fake_ask(cmd, *args, **kw):
            asks.append(cmd)
            return responses.pop(0) if responses else None

        controller._ask = fake_ask
        return controller, asks, warnings

    def test_valve_command_retries_until_valid(self):
        controller, asks, warnings = self._make_controller(
            ["#EVENT:ACQ,junk", "#EVENT:ACQ,junk", "OPEN"]
        )

        with mock.patch("pychron.hardware.isotopx_spectrometer_controller.time.sleep"):
            resp = controller.ask("GetValveStatus V1")

        self.assertEqual(resp, "OPEN")
        self.assertEqual(len(asks), 3)
        self.assertEqual(warnings, [])

    def test_valve_command_retries_are_bounded(self):
        controller, asks, warnings = self._make_controller(["junk"] * 10)

        with mock.patch("pychron.hardware.isotopx_spectrometer_controller.time.sleep"):
            resp = controller.ask("OpenValve V1")

        # initial attempt + max_valve_retries
        self.assertEqual(len(asks), 1 + controller.max_valve_retries)
        self.assertEqual(resp, "junk")
        self.assertEqual(len(warnings), 1)
        self.assertIn("failed to return a valid response", warnings[0])

    def test_non_valve_command_does_not_retry(self):
        controller, asks, warnings = self._make_controller(["#EVENT:ACQ,junk"])

        resp = controller.ask("GETMASS")

        self.assertEqual(len(asks), 1)
        self.assertEqual(resp, "#EVENT:ACQ,junk")
        self.assertEqual(warnings, [])

    def test_none_response_does_not_retry(self):
        controller, asks, warnings = self._make_controller([None])

        with mock.patch("pychron.hardware.isotopx_spectrometer_controller.time.sleep"):
            resp = controller.ask("CloseValve V1")

        self.assertIsNone(resp)
        self.assertEqual(len(asks), 1)


@unittest.skipIf(_IMPORT_ERROR is not None, "Traits stack not available")
class NGXControllerSessionTestCase(unittest.TestCase):
    def test_handle_connect_sends_login_and_consumes_response(self):
        controller = NGXController(name="ngx")
        controller.username = "user"
        controller.password = "pw"
        controller.debug = lambda msg: None

        class _Comm:
            write_terminator = "\r"

        controller._communicator = _Comm()
        controller.communicator = _Comm()
        handler = _FakeHandler(lines=["E00#\r\n"])

        controller._handle_connect(handler)

        self.assertEqual(handler.sent, ["Login user,pw\r"])
        self.assertEqual(handler.lines, [])

    def test_handle_connect_skips_without_credentials(self):
        controller = NGXController(name="ngx")
        controller.username = ""
        handler = _FakeHandler()

        controller._handle_connect(handler)

        self.assertEqual(handler.sent, [])


if __name__ == "__main__":
    unittest.main()
