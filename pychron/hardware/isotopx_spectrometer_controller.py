# ===============================================================================
# Copyright 2011 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================


# ============= enthought library imports =======================
from traits.api import Str, Bool, HasTraits
from apptools.preferences.preference_binding import bind_preference

# ============= standard library imports ========================
from threading import Lock
import socket
import time

# ============= local library imports  ==========================

from pychron.hardware.core.core_device import CoreDevice
from pychron.hardware.core.communicators.line_demultiplexer import LineDemultiplexer

NGX_TERMINATOR = "#\r\n"
VALVE_COMMANDS = ("GetValveStatus", "OpenValve", "CloseValve")
VALVE_RESPONSES = ("E00", "OPEN", "CLOSED")


class NGXController(CoreDevice):
    username = Str("")
    password = Str("")
    lock = None
    canceled = False
    triggered = False
    protect_detector = False

    # route all socket reads through a single reader thread that separates
    # asynchronous #EVENT pushes from command responses. opt-in until
    # validated on hardware; enable with use_demux=True in the device config
    use_demux = Bool(False)
    max_valve_retries = 3
    _demux = None

    def load_additional_args(self, config):
        self.set_attribute(
            config,
            "use_demux",
            "Communications",
            "use_demux",
            cast="boolean",
            optional=True,
            default=False,
        )
        return True

    def select_read(self, *args, **kw):
        return self.communicator.select_read(*args, **kw)

    def ask(self, cmd, *args, **kw):
        resp = self._ask(cmd, *args, **kw)
        if any((cmd.startswith(t) for t in VALVE_COMMANDS)):
            # the instrument pushes #EVENT lines on the same stream; without
            # demultiplexing an event line can arrive in place of the valve
            # response, so retry a bounded number of times
            for i in range(self.max_valve_retries):
                if resp is None or resp.strip() in VALVE_RESPONSES:
                    break
                self.debug(f"retrying valve command {cmd} (attempt {i + 1}, got {resp.strip()})")
                time.sleep(0.5)
                resp = self._ask(cmd, *args, **kw)

            if resp is not None and resp.strip() not in VALVE_RESPONSES:
                self.warning(
                    f"valve command {cmd} failed to return a valid response "
                    f"after {self.max_valve_retries} retries: {resp.strip()}"
                )

        return resp

    def _ask(self, cmd, *args, **kw):
        demux = self._demux
        if demux is not None and demux.running:
            timeout = kw.get("timeout") or self.communicator.timeout or 3
            payload = f"{cmd}{self.communicator.write_terminator}"
            resp = demux.ask(payload, timeout=timeout)
            if kw.get("verbose", True):
                self.communicator.log_response(payload, resp)
            return resp

        return super(NGXController, self).ask(cmd, *args, **kw)

    def read_event(self, timeout=1.0):
        """Next asynchronous #EVENT line, or None. Only available with demux."""
        demux = self._demux
        if demux is not None and demux.running:
            return demux.get_event(timeout=timeout)

    def has_demux(self):
        demux = self._demux
        return demux is not None and demux.running

    def set_acquisition_buffer(self, flag):
        flag = "1" if flag else "0"
        self.debug(f"set acquisition buffer {flag}")
        self.ask(f"SAB {flag}")

    def begin_acquisition(self):
        self.canceled = False
        self.triggered = True

    def stop_acquisition(self):
        self.triggered = False
        self.debug("stop acquisition")
        self.ask("StopAcq")
        self.canceled = True
        time.sleep(0.25)

    def clear_canceled(self):
        self.canceled = False

    def set(self, *args, **kw):
        return HasTraits.set(self, *args, **kw)

    def initialize(self, *args, **kw):
        ret = super(NGXController, self).initialize(*args, **kw)
        if not ret:
            return False

        self.communicator.strip = False
        self.lock = Lock()

        bind_preference(self, "username", "pychron.spectrometer.ngx.username")
        bind_preference(self, "password", "pychron.spectrometer.ngx.password")

        resp = self.communicator.readline()
        self.debug(f"*********** initial response from NGX: {resp}")
        if resp:
            self.info(f"NGX-{resp}")
            self.ask(f"Login {self.username},{self.password}")
        else:
            self.warning("no initial response from NGX; skipping Login")

        # re-Login automatically whenever the communicator reconnects
        self.communicator.on_connect = self._handle_connect

        if self.use_demux:
            self._start_demux()

        return True

    # private
    def _handle_connect(self, handler):
        """Session setup on a fresh connection (called from the communicator).

        Writes directly to the handler: using ask() here would re-enter the
        communicator and, with use_end set, tear down the connection that is
        being established.
        """
        if not self.username:
            return
        self.debug("re-establishing NGX session (Login)")
        try:
            handler.send_packet(
                f"Login {self.username},{self.password}{self.communicator.write_terminator}"
            )
            # consume the login response so it is not mistaken for the
            # response to the command that triggered the reconnect
            handler.readline(NGX_TERMINATOR.encode("utf-8"))
        except (socket.error, OSError) as e:
            self.warning(f"NGX re-login failed: {e}")

    def _start_demux(self):
        handler = self.communicator.get_handler()
        if handler is None:
            self.warning("cannot start NGX demux; no connection")
            return

        self._demux = LineDemultiplexer(
            handler,
            terminator=NGX_TERMINATOR,
            event_prefix="#EVENT",
            warning=self.warning,
            on_reconnect=self._demux_reconnect,
        )
        self._demux.start()
        self.info("NGX line demultiplexer started")

    def _demux_reconnect(self):
        """Build a fresh handler for the demux reader thread after a drop."""
        comm = self.communicator
        with comm.lock:
            comm.reset()
            handler = comm.get_handler()
        # get_handler fires on_connect, which re-Logins on the new handler
        return handler


# ============= EOF =============================================
