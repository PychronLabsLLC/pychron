import threading
import time
import unittest

from pychron.core.wait.wait_control import WaitControl
from pychron.core.wait.wait_group import WaitGroup


class WaitGroupStartWaitTestCase(unittest.TestCase):
    """Integration: prove the experiment thread does NOT depend on Qt to make
    progress. These tests run with no QApplication, so any code path that
    requires Qt to fire would hang or fail."""

    def test_blocking_wait_completes_at_deadline_without_qt(self) -> None:
        wg = WaitGroup()
        wc = WaitControl()
        wg.controls = [wc]

        t0 = time.monotonic()
        outcome = wg.start_wait(wc, duration=0.2)
        elapsed = time.monotonic() - t0

        self.assertEqual(outcome, "completed")
        self.assertGreaterEqual(elapsed, 0.18)
        self.assertLess(elapsed, 0.6)

    def test_continue_from_other_thread_unblocks_wait_quickly(self) -> None:
        wg = WaitGroup()
        wc = WaitControl()
        wg.controls = [wc]

        def trigger():
            time.sleep(0.05)
            wc.continue_wait()

        threading.Thread(target=trigger, daemon=True).start()

        t0 = time.monotonic()
        outcome = wg.start_wait(wc, duration=10.0)
        elapsed = time.monotonic() - t0

        self.assertEqual(outcome, "continued")
        self.assertLess(elapsed, 0.5)

    def test_stop_from_other_thread_cancels_wait(self) -> None:
        wg = WaitGroup()
        wc = WaitControl()
        wg.controls = [wc]

        def trigger():
            time.sleep(0.05)
            wc.stop()

        threading.Thread(target=trigger, daemon=True).start()

        outcome = wg.start_wait(wc, duration=10.0)
        self.assertEqual(outcome, "canceled")
        self.assertTrue(wc.is_canceled())

    def test_nonblocking_returns_none(self) -> None:
        wg = WaitGroup()
        wc = WaitControl()
        wg.controls = [wc]

        result = wg.start_wait(wc, duration=10.0, block=False)
        self.assertIsNone(result)
        # Cleanup so the test doesn't leave a dangling running state.
        wc.stop()


if __name__ == "__main__":
    unittest.main()
