# ===============================================================================
# Copyright 2013 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
"""WaitGroup: collection of WaitControls plus a blocking wait coordinator.

After the 2026 rewrite, blocking is implemented directly on top of
WaitState (pure threading). The Qt event loop is not on the critical
path, so safety timeouts, faulthandler dumps, and synchronous
cross-thread calls (`wait=True`) are no longer needed.
"""

# ============= enthought library imports =======================
from threading import Event, current_thread, main_thread
from typing import Any as TypingAny, Callable, Optional

from traits.api import Any, HasTraits, List, Property

# ============= local library imports  ==========================
from pychron.core.ui.gui import invoke_in_main_thread
from pychron.core.wait.wait_control import WaitControl


class WaitGroup(HasTraits):
    controls = List
    active_control = Any
    single = Property(depends_on="controls[]")

    def _get_single(self) -> bool:
        return len(self.controls) == 1

    def _controls_default(self) -> list[WaitControl]:
        return [WaitControl()]

    def _active_control_default(self) -> WaitControl:
        return self.controls[0]

    # ------------------------------------------------------------------
    # Cross-thread helper
    # ------------------------------------------------------------------

    def _invoke_on_main_thread(
        self,
        func: Callable[..., TypingAny],
        *args: TypingAny,
        wait: bool = False,
        **kw: TypingAny,
    ) -> Optional[TypingAny]:
        """Run `func` on the main thread.

        With `wait=False` (default), fire-and-forget. With `wait=True`,
        block until `func` returns. Synchronous waits are still used for
        UI-only operations (e.g. swapping the active page in a notebook)
        where the caller needs the result; they are NEVER used inside the
        blocking wait path, so they cannot deadlock the experiment thread.
        """
        if current_thread() is main_thread():
            return func(*args, **kw)

        if not wait:
            invoke_in_main_thread(func, *args, **kw)
            return None

        done = Event()
        result: dict[str, TypingAny] = {}

        def runner() -> None:
            try:
                result["value"] = func(*args, **kw)
            finally:
                done.set()

        invoke_in_main_thread(runner)
        done.wait()
        return result.get("value")

    # ------------------------------------------------------------------
    # Control management (UI-side, synchronous helpers OK here)
    # ------------------------------------------------------------------

    def pop(self, control: Optional[WaitControl] = None) -> None:
        self._invoke_on_main_thread(self._pop, control, wait=True)

    def _pop(self, control: Optional[WaitControl] = None) -> None:
        if len(self.controls) > 1:
            if control:
                if control in self.controls:
                    self.controls.remove(control)
            else:
                self.controls.pop()
            self.active_control = self.controls[-1]

    def stop(self) -> None:
        self._invoke_on_main_thread(self._stop, wait=True)

    def _stop(self) -> None:
        for ci in self.controls:
            ci.stop()

    def ensure_control(self, control: WaitControl) -> WaitControl:
        return self._invoke_on_main_thread(self._ensure_control, control, wait=True)

    def _ensure_control(self, control: WaitControl) -> WaitControl:
        if control not in self.controls:
            self.controls.append(control)
        self.active_control = control
        return control

    def set_active_page_name(self, page_name: str) -> None:
        self._invoke_on_main_thread(self._set_active_page_name, page_name, wait=True)

    def _set_active_page_name(self, page_name: str) -> None:
        if self.active_control is not None:
            self.active_control.page_name = page_name

    def add_control(self, **kw: TypingAny) -> WaitControl:
        if "page_name" not in kw:
            kw["page_name"] = "Wait {:02d}".format(len(self.controls))
        w = WaitControl(**kw)
        self._invoke_on_main_thread(self._ensure_control, w, wait=True)
        return w

    def get_wait_control(self, **kw: TypingAny) -> WaitControl:
        return self._invoke_on_main_thread(self._get_wait_control, wait=True, **kw)

    def _get_wait_control(self, **kw: TypingAny) -> WaitControl:
        control = self.active_control
        if control is None or control.is_active():
            control = self.add_control(**kw)
        return control

    # ------------------------------------------------------------------
    # The blocking wait — pure threading, no Qt dependency
    # ------------------------------------------------------------------

    def start_wait(
        self,
        control: WaitControl,
        *,
        duration: float | None = None,
        message: str | None = None,
        paused: bool = False,
        block: bool = True,
    ) -> str | None:
        """Begin a wait on `control`.

        Returns the final outcome (`"completed"`, `"continued"`, or
        `"canceled"`) when block=True; returns None when block=False.

        The blocking wait runs on the calling thread via WaitState.wait(),
        which uses a threading.Event with timeout. The Qt event loop is
        not required for progress: a starved main thread will only delay
        the on-screen countdown, never the experiment.
        """
        state = control.state
        eff_duration = float(duration) if duration is not None else float(control.duration)

        control.debug(
            "wait_group start_wait page={} duration={} message={} paused={} block={} thread={}".format(
                control.page_name,
                eff_duration,
                message,
                paused,
                block,
                current_thread().name,
            )
        )

        # Start state on this (experiment) thread so timing begins
        # immediately and is independent of Qt event-loop responsiveness.
        eff_message = message if message is not None else control.message
        state.page_name = control.page_name
        state.start(eff_duration, eff_message)
        if paused:
            state.request_pause(True)

        # Reset display traits and start polling on the main thread.
        # Fire-and-forget: even if the main thread is busy, the wait
        # below proceeds independently.
        invoke_in_main_thread(
            control._begin_view, eff_duration, eff_message, paused
        )

        if not block:
            return None

        outcome = state.wait()
        control.debug(
            "wait_group wait complete page={} outcome={} thread={}".format(
                control.page_name, outcome, current_thread().name
            )
        )
        # Make sure the UI converges to the final state even if the polling
        # timer didn't get a chance to run after resolution.
        invoke_in_main_thread(control._sync_from_state)
        return outcome


# ============= EOF =============================================
