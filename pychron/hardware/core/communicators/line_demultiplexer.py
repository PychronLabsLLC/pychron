# ===============================================================================
# Copyright 2026 Jake Ross
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
"""Reader-thread demultiplexer for line-oriented instrument streams.

Some instruments (e.g. the Isotopx NGX) interleave asynchronous event pushes
with command responses on a single TCP stream. Reading that stream from
multiple call sites races: an ``ask`` issued during an acquisition can consume
an event line as its response, and concurrent reads interleave bytes.

``LineDemultiplexer`` gives the stream a single owner. A daemon thread reads
complete lines (terminator-delimited) and routes them: lines starting with
``event_prefix`` go to an event queue, everything else is treated as a command
response. ``ask`` pairs each write with the next response line; consumers of
asynchronous events poll ``get_event``.
"""

import socket
import time
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable, Optional


class LineDemultiplexer:
    def __init__(
        self,
        handler: Any,
        terminator: str = "#\r\n",
        event_prefix: str = "#EVENT",
        warning: Optional[Callable[[str], None]] = None,
        on_reconnect: Optional[Callable[[], Any]] = None,
    ):
        """
        @param handler: ethernet Handler owning the socket (TCPHandler/UDPHandler)
        @param terminator: line terminator delimiting both responses and events
        @param event_prefix: lines starting with this are routed to the event queue
        @param warning: callable used to surface warnings (e.g. Loggable.warning)
        @param on_reconnect: called from the reader thread when the connection
            drops; should return a fresh handler, or None if reconnection failed.
            The callback may write session setup commands (e.g. Login) directly
            to the new handler; their responses are drained before the next ask.
        """
        self._handler = handler
        self._terminator = terminator.encode("utf-8") if isinstance(terminator, str) else terminator
        self._event_prefix = event_prefix
        self._responses: Queue = Queue()
        self._events: Queue = Queue()
        self._write_lock = Lock()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._warning = warning or (lambda msg: None)
        self._on_reconnect = on_reconnect

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="line-demux")
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)
        self._thread = None

    def set_handler(self, handler: Any) -> None:
        self._handler = handler

    def ask(self, payload: str, timeout: float = 3.0) -> Optional[str]:
        """Send payload, return the next non-event line (or None on timeout)."""
        with self._write_lock:
            self._drain(self._responses)
            handler = self._handler
            if handler is None:
                return None
            try:
                handler.send_packet(payload)
            except (socket.error, OSError) as e:
                self._warning(f"demux send failed: {e}")
                return None
            try:
                return self._responses.get(timeout=timeout)
            except Empty:
                return None

    def tell(self, payload: str) -> bool:
        with self._write_lock:
            handler = self._handler
            if handler is None:
                return False
            try:
                handler.send_packet(payload)
                return True
            except (socket.error, OSError) as e:
                self._warning(f"demux send failed: {e}")
                return False

    def get_event(self, timeout: float = 1.0) -> Optional[str]:
        try:
            return self._events.get(timeout=timeout)
        except Empty:
            return None

    def clear_events(self) -> None:
        self._drain(self._events)

    # private
    def _drain(self, q: Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except Empty:
                break

    def _run(self) -> None:
        while not self._stop_event.is_set():
            handler = self._handler
            if handler is None or handler.sock is None:
                if not self._reconnect():
                    time.sleep(0.25)
                continue

            try:
                line = handler.readline(self._terminator)
            except socket.timeout:
                continue
            except (socket.error, OSError) as e:
                self._warning(f"demux read failed: {e}")
                self._handler = None
                continue

            if line is None:
                continue

            if line == "":
                # peer closed the connection
                self._warning("demux: connection closed by peer")
                self._handler = None
                continue

            if line.startswith(self._event_prefix):
                self._events.put(line)
            else:
                self._responses.put(line)

    def _reconnect(self) -> bool:
        cb = self._on_reconnect
        if cb is None:
            return False
        try:
            handler = cb()
        except BaseException as e:
            self._warning(f"demux reconnect failed: {e}")
            return False

        if handler is None:
            return False

        self._handler = handler
        return True


# ============= EOF =============================================
