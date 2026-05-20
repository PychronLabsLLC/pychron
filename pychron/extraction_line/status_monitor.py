# ===============================================================================
# Copyright 2014 Jake Ross
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
from __future__ import absolute_import
import time
from threading import Event, Thread

from traits.api import Int, List

from pychron.globals import globalv
from pychron.loggable import Loggable


class StatusMonitor(Loggable):
    # valve_manager = None
    _stop_evt = None
    _finished_evt = None
    _clients = List
    _thread = None
    _thread_timeout = 5.0

    state_freq = Int(3)
    checksum_freq = Int(3)

    lock_freq = Int(5)
    owner_freq = Int(5)
    update_period = Int(1)

    def start(self, oid, vm):
        self.debug("start {}".format(oid))
        if not self._clients:
            p = self.update_period
            s, c, l, o = (
                self.state_freq,
                self.checksum_freq,
                self.lock_freq,
                self.owner_freq,
            )
            self.debug(
                "StatusMonitor period={}. "
                "Frequencies(state={}, checksum={}, lock={}, owner={})".format(
                    p, s, c, l, o
                )
            )
            # Clean up any existing thread before starting new one
            if self._thread is not None:
                self.debug("Cleaning up existing thread before restart")
                if self._thread.is_alive():
                    self.debug("Previous thread still alive, waiting for cleanup")
                    try:
                        self._thread.join(timeout=self._thread_timeout)
                    except Exception as e:
                        self.warning("Error joining previous thread: {}".format(e))
                self._thread = None

            if self._stop_evt:
                self._stop_evt.set()
                time.sleep(1.5 * self.update_period)
                # self._stop_evt.wait(self.update_period)

            self._stop_evt = Event()
            t = Thread(target=self._run, args=(vm,))
            t.setName("StatusMonitor({})".format(oid))
            t.setDaemon(True)
            t.start()
            self._thread = t
            self.debug("Thread started: {} (daemon={}, alive={})".format(
                t.getName(), t.isDaemon(), t.is_alive()))
        else:
            self.debug("Monitor already running")

        if oid not in self._clients:
            self._clients.append(oid)

    def isAlive(self):
        if self._stop_evt:
            return not self._stop_evt.isSet()

    def stop(self, oid, block=True):
        """Stop status monitor with comprehensive safety checks and instrumentation.
        
        Implements three-layer approach:
        1. Safety checks: try-except wrapper, thread state validation, timeout
        2. Debug instrumentation: detailed logging at each cleanup step
        3. Resource leak investigation: verify thread cleanup, check dangling resources
        """
        self.debug("stop {} (block={})".format(oid, block))
        
        try:
            self._clients.remove(oid)
        except ValueError:
            self.debug("Client {} not in active list (already removed)".format(oid))
            pass

        if not self._clients:
            self.debug("No remaining clients, initiating graceful shutdown")
            
            # LAYER 1: Safety Checks & Thread State Validation
            try:
                if self._stop_evt:
                    self.debug("Setting stop event")
                    self._stop_evt.set()
                    
                # Wait briefly for thread to notice stop event
                time.sleep(0.1)
                
                # Verify thread state before attempting join
                if self._thread is not None:
                    is_alive_before = self._thread.is_alive()
                    self.debug("Thread state before join: alive={}".format(is_alive_before))
                    
                    if is_alive_before:
                        # LAYER 3: Resource Investigation - verify thread cleanup
                        self.debug("Attempting graceful thread shutdown with timeout={}s".format(
                            self._thread_timeout))
                        
                        # LAYER 2: Debug Instrumentation - measure join duration
                        import time as time_module
                        join_start = time_module.time()
                        
                        try:
                            self._thread.join(timeout=self._thread_timeout)
                        except Exception as join_error:
                            self.warning("Exception during thread.join(): {}".format(join_error))
                            # Continue anyway - don't let join failure crash us
                        
                        join_duration = time_module.time() - join_start
                        is_alive_after = self._thread.is_alive()
                        
                        # LAYER 2: Log join completion status
                        self.debug(
                            "Thread join completed: duration={:.3f}s, "
                            "alive_before={}, alive_after={}".format(
                                join_duration, is_alive_before, is_alive_after)
                        )
                        
                        # LAYER 3: Verify resource cleanup
                        if is_alive_after:
                            self.warning(
                                "Thread still alive after join timeout. "
                                "Possible resource leak or blocked I/O."
                            )
                        else:
                            self.debug("Thread successfully terminated")
                    else:
                        self.debug("Thread was already dead")
                    
                    # LAYER 3: Resource tracking - clear thread reference
                    self._thread = None
                    self.debug("Thread reference cleared")
                else:
                    self.debug("No thread reference to clean up")
                
                # LAYER 2: Final state verification
                self.debug(
                    "Status monitor stopped: "
                    "clients={}, thread=None, stop_evt.is_set={}".format(
                        self._clients, 
                        self._stop_evt.is_set() if self._stop_evt else False
                    )
                )
                
                # Optional: additional blocking delay for resource flush
                if block:
                    self.debug("Applying post-shutdown flush delay: {:.1f}s".format(
                        1.5 * self.update_period))
                    time.sleep(1.5 * self.update_period)
                    self.debug("Post-shutdown flush complete")
            
            except Exception as shutdown_error:
                # LAYER 1: Comprehensive exception handling
                self.warning(
                    "Exception during monitor shutdown (proceeding anyway): "
                    "type={}, error={}".format(
                        type(shutdown_error).__name__, shutdown_error
                    )
                )
                # Attempt minimal cleanup even if something fails
                try:
                    self._thread = None
                except:
                    pass
        else:
            self.debug("Alive clients {} (not shutting down)".format(self._clients))

    def _run(self, vm):
        if vm is None:
            self.debug("No valve manager")
        else:
            i = 0
            while 1:
                time.sleep(self.update_period)
                if self._stop_evt.is_set():
                    break

                if self._iter(i, vm):
                    break

                if i > 100:
                    i = 0
                i += 1

        self.debug("Status monitor finished")

    def _iter(self, i, vm):
        if globalv.valve_debug:
            self.debug("status monitor iteration i={}".format(i))
        if self._stop_evt.is_set():
            self.debug("stop_event set. no more iterations")
            return True

        delay = self.update_period / 2.0
        if self.state_freq and not i % self.state_freq:
            if globalv.valve_debug:
                self.debug("load valve states")
            vm.load_valve_states()
            time.sleep(delay)

        if self.lock_freq and not i % self.lock_freq:
            if globalv.valve_debug:
                self.debug("load lock states")
            vm.load_valve_lock_states()
            time.sleep(delay)

        if self.owner_freq and not i % self.owner_freq:
            if globalv.valve_debug:
                self.debug("load owners")
            vm.load_valve_owners()
            time.sleep(delay)

        if self.checksum_freq and not i % self.checksum_freq:
            if not vm.state_checksum:
                self.debug("State checksum failed")

        return self._stop_evt.is_set()

        # if i > 100:
        #     i = 0
        # if not self._stop_evt.is_set():
        #     do_after(self.update_period * 1000, self._iter, i + 1, vm)


# ============= EOF =============================================
