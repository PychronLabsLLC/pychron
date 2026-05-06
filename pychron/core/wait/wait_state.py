# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
# ===============================================================================
"""Thread-safe wait state.

The truth for one wait: how long, how much is left, whether the user has
asked to continue/cancel/pause. Owned by the experiment thread; the UI
reads snapshots and posts requests but never blocks experiment progress.

Deliberately has no Qt or Traits dependency. Timing correctness must not
depend on the GUI event loop being responsive.
"""
import time
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Optional


# Outcome values
IDLE = "idle"
RUNNING = "running"
COMPLETED = "completed"   # deadline reached
CONTINUED = "continued"   # user clicked Continue
CANCELED = "canceled"     # programmatic stop or user cancel


@dataclass(frozen=True)
class WaitSnapshot:
    """Immutable view of WaitState for the UI to render."""
    page_name: str
    remaining: float
    duration: float
    message: str
    paused: bool
    outcome: str


class WaitState:
    """Thread-safe state for a single wait.

    The experiment thread calls `start()` then blocks on `wait()`.
    The UI calls `snapshot()` to repaint and `request_*()` to act on
    button clicks. All cross-thread coordination is via a Lock + Event.
    """

    def __init__(self, page_name: str = "Wait") -> None:
        self.page_name = page_name
        self._lock = Lock()
        self._interrupt = Event()

        # All fields below are guarded by _lock.
        self._duration: float = 0.0
        self._deadline: float = 0.0       # monotonic time
        self._paused_at: Optional[float] = None
        self._message: str = ""
        self._outcome: str = IDLE

    # ------------------------------------------------------------------
    # Experiment-thread API
    # ------------------------------------------------------------------

    def start(self, duration: float, message: str = "") -> None:
        """Begin a new wait. Resets any prior state."""
        now = time.monotonic()
        with self._lock:
            self._duration = float(duration)
            self._deadline = now + float(duration)
            self._paused_at = None
            self._message = message
            self._outcome = RUNNING
            self._interrupt.clear()

    def wait(self) -> str:
        """Block the calling thread until the wait resolves.

        Returns the final outcome (COMPLETED, CONTINUED, or CANCELED).
        Wakes early on continue/cancel/pause/resume via the interrupt event.
        """
        while True:
            with self._lock:
                outcome = self._outcome
                if outcome != RUNNING:
                    return outcome
                if self._paused_at is not None:
                    timeout: Optional[float] = None
                else:
                    timeout = self._deadline - time.monotonic()
                    if timeout <= 0:
                        self._outcome = COMPLETED
                        return COMPLETED

            # Released the lock — block until interrupted or timeout.
            self._interrupt.wait(timeout=timeout)
            self._interrupt.clear()

    # ------------------------------------------------------------------
    # UI-thread API (non-blocking)
    # ------------------------------------------------------------------

    def snapshot(self) -> WaitSnapshot:
        """Cheap read of current state. Safe from any thread."""
        with self._lock:
            if self._outcome == IDLE:
                remaining = self._duration
            elif self._paused_at is not None:
                remaining = max(0.0, self._deadline - self._paused_at)
            elif self._outcome == RUNNING:
                remaining = max(0.0, self._deadline - time.monotonic())
            else:
                remaining = 0.0
            return WaitSnapshot(
                page_name=self.page_name,
                remaining=remaining,
                duration=self._duration,
                message=self._message,
                paused=self._paused_at is not None,
                outcome=self._outcome,
            )

    def request_continue(self) -> None:
        with self._lock:
            if self._outcome == RUNNING:
                self._outcome = CONTINUED
        self._interrupt.set()

    def request_cancel(self) -> None:
        with self._lock:
            if self._outcome == RUNNING:
                self._outcome = CANCELED
        self._interrupt.set()

    def request_pause(self, paused: bool) -> None:
        """Pause or resume the countdown. Pausing freezes remaining time;
        resuming extends the deadline by the pause duration."""
        with self._lock:
            now = time.monotonic()
            if paused and self._paused_at is None:
                self._paused_at = now
            elif not paused and self._paused_at is not None:
                self._deadline += now - self._paused_at
                self._paused_at = None
        self._interrupt.set()

    def set_message(self, message: str) -> None:
        with self._lock:
            self._message = message

    def set_remaining(self, remaining: float) -> None:
        """Adjust the deadline so `remaining` seconds are left from now.

        Used by callers that want to extend or shorten an in-flight wait
        (e.g. countdown displays driven from outside)."""
        now = time.monotonic()
        with self._lock:
            self._deadline = now + float(remaining)
            if self._paused_at is not None:
                # Keep paused; reframe so resume gives `remaining` left.
                self._paused_at = now
        self._interrupt.set()

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    @property
    def outcome(self) -> str:
        with self._lock:
            return self._outcome

    def is_running(self) -> bool:
        return self.outcome == RUNNING

    def is_canceled(self) -> bool:
        return self.outcome == CANCELED

    def is_continued(self) -> bool:
        return self.outcome == CONTINUED


# ============= EOF =============================================
