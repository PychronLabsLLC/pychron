import threading
import time
import unittest

from pychron.core.wait.wait_state import (
    CANCELED,
    COMPLETED,
    CONTINUED,
    IDLE,
    RUNNING,
    WaitState,
)


def _run_in_thread(target, *args, **kw):
    """Start `target` in a daemon thread; return the thread."""
    t = threading.Thread(target=target, args=args, kwargs=kw, daemon=True)
    t.start()
    return t


class WaitStateBasicsTestCase(unittest.TestCase):
    def test_initial_outcome_is_idle(self) -> None:
        s = WaitState()
        self.assertEqual(s.outcome, IDLE)
        snap = s.snapshot()
        self.assertEqual(snap.outcome, IDLE)
        self.assertEqual(snap.remaining, 0.0)

    def test_start_transitions_to_running(self) -> None:
        s = WaitState()
        s.start(5.0, message="hello")

        self.assertEqual(s.outcome, RUNNING)
        snap = s.snapshot()
        self.assertEqual(snap.outcome, RUNNING)
        self.assertAlmostEqual(snap.remaining, 5.0, delta=0.05)
        self.assertEqual(snap.message, "hello")
        self.assertFalse(snap.paused)
        self.assertEqual(snap.duration, 5.0)


class WaitStateCompletionTestCase(unittest.TestCase):
    def test_wait_returns_completed_at_deadline(self) -> None:
        s = WaitState()
        s.start(0.2)

        t0 = time.monotonic()
        outcome = s.wait()
        elapsed = time.monotonic() - t0

        self.assertEqual(outcome, COMPLETED)
        # Wait should sleep ~duration; allow generous slack on slow CI.
        self.assertGreaterEqual(elapsed, 0.18)
        self.assertLess(elapsed, 0.6)

    def test_wait_returns_immediately_if_already_resolved(self) -> None:
        s = WaitState()
        s.start(10.0)
        s.request_continue()

        t0 = time.monotonic()
        outcome = s.wait()
        elapsed = time.monotonic() - t0

        self.assertEqual(outcome, CONTINUED)
        self.assertLess(elapsed, 0.05)


class WaitStateContinueTestCase(unittest.TestCase):
    def test_continue_interrupts_wait_quickly(self) -> None:
        s = WaitState()
        s.start(10.0)

        results: dict = {}

        def waiter():
            results["outcome"] = s.wait()
            results["elapsed"] = time.monotonic() - results["t0"]

        results["t0"] = time.monotonic()
        t = _run_in_thread(waiter)
        # Let the waiter actually enter wait().
        time.sleep(0.05)
        s.request_continue()
        t.join(timeout=1.0)

        self.assertFalse(t.is_alive(), "waiter did not return")
        self.assertEqual(results["outcome"], CONTINUED)
        self.assertLess(results["elapsed"], 0.3)

    def test_continue_after_completion_is_noop(self) -> None:
        s = WaitState()
        s.start(0.05)
        outcome = s.wait()
        self.assertEqual(outcome, COMPLETED)

        # Late continue should not flip outcome away from COMPLETED.
        s.request_continue()
        self.assertEqual(s.outcome, COMPLETED)


class WaitStateCancelTestCase(unittest.TestCase):
    def test_cancel_interrupts_wait(self) -> None:
        s = WaitState()
        s.start(10.0)

        results: dict = {}

        def waiter():
            results["outcome"] = s.wait()

        t = _run_in_thread(waiter)
        time.sleep(0.05)
        s.request_cancel()
        t.join(timeout=1.0)

        self.assertFalse(t.is_alive())
        self.assertEqual(results["outcome"], CANCELED)
        self.assertTrue(s.is_canceled())


class WaitStatePauseTestCase(unittest.TestCase):
    def test_pause_extends_deadline_by_pause_duration(self) -> None:
        s = WaitState()
        s.start(0.4)

        # Wait a bit, then pause, hold, then resume — total wait should be
        # approximately duration + pause_hold.
        t0 = time.monotonic()

        def runner():
            time.sleep(0.1)
            s.request_pause(True)
            time.sleep(0.3)         # held while paused; should not count
            s.request_pause(False)

        ctrl = _run_in_thread(runner)
        outcome = s.wait()
        elapsed = time.monotonic() - t0
        ctrl.join(timeout=1.0)

        self.assertEqual(outcome, COMPLETED)
        # Expect ~ 0.4 + 0.3 = 0.7s; allow slack.
        self.assertGreaterEqual(elapsed, 0.6)
        self.assertLess(elapsed, 1.2)

    def test_snapshot_remaining_is_frozen_while_paused(self) -> None:
        s = WaitState()
        s.start(2.0)
        time.sleep(0.05)
        s.request_pause(True)

        first = s.snapshot().remaining
        time.sleep(0.1)
        second = s.snapshot().remaining

        self.assertTrue(first > 0)
        self.assertAlmostEqual(first, second, delta=0.01)
        self.assertTrue(s.snapshot().paused)

    def test_continue_while_paused_resolves(self) -> None:
        s = WaitState()
        s.start(10.0)
        s.request_pause(True)

        results: dict = {}

        def waiter():
            results["outcome"] = s.wait()

        t = _run_in_thread(waiter)
        time.sleep(0.05)
        s.request_continue()
        t.join(timeout=1.0)

        self.assertFalse(t.is_alive(), "paused waiter did not wake on continue")
        self.assertEqual(results["outcome"], CONTINUED)


class WaitStateMessageTestCase(unittest.TestCase):
    def test_set_message_visible_in_snapshot(self) -> None:
        s = WaitState()
        s.start(1.0, message="initial")
        self.assertEqual(s.snapshot().message, "initial")

        s.set_message("updated")
        self.assertEqual(s.snapshot().message, "updated")

    def test_set_remaining_extends_deadline(self) -> None:
        s = WaitState()
        s.start(0.1)
        s.set_remaining(0.5)

        t0 = time.monotonic()
        outcome = s.wait()
        elapsed = time.monotonic() - t0

        self.assertEqual(outcome, COMPLETED)
        self.assertGreaterEqual(elapsed, 0.4)


class WaitStateConcurrencyTestCase(unittest.TestCase):
    def test_many_concurrent_button_presses_resolve_to_one_outcome(self) -> None:
        """Hammer continue/cancel from many threads; final outcome must be
        deterministic (whichever request_* won), and wait() must return."""
        s = WaitState()
        s.start(5.0)

        outcomes: list = []

        def waiter():
            outcomes.append(s.wait())

        t = _run_in_thread(waiter)
        time.sleep(0.02)

        threads = []
        for i in range(20):
            target = s.request_continue if i % 2 == 0 else s.request_cancel
            threads.append(_run_in_thread(target))
        for x in threads:
            x.join(timeout=1.0)
        t.join(timeout=1.0)

        self.assertFalse(t.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIn(outcomes[0], (CONTINUED, CANCELED))

    def test_restart_resets_to_running(self) -> None:
        s = WaitState()
        s.start(0.05)
        self.assertEqual(s.wait(), COMPLETED)

        s.start(0.05, message="round 2")
        self.assertEqual(s.snapshot().message, "round 2")
        self.assertEqual(s.outcome, RUNNING)
        self.assertEqual(s.wait(), COMPLETED)


if __name__ == "__main__":
    unittest.main()
