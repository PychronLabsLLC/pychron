# ===============================================================================
# Copyright 2014 Jake Ross
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

# ============= enthought library imports =======================
from traits.api import CInt, Str, Bool

# ============= standard library imports ========================
# ============= local library imports  ==========================
from pychron.has_communicator import HasCommunicator
from pychron.loggable import Loggable


class CommunicationStrategy:
    """
    Configures a device's communicator for a particular transport.

    Strategies are stateless: they operate on the ``device`` passed to
    ``setup``, reading the connection traits (port, host, baudrate, ...) the
    device defines. This is the composition replacement for the former
    ``SerialDeviceMixin`` / ``EthernetDeviceMixin`` inheritance.
    """

    def setup(self, device, **kw):
        raise NotImplementedError


class SerialCommunicationStrategy(CommunicationStrategy):
    def setup(self, device, **kw):
        ec = device.build_communicator("serial")
        if ec is None:
            return
        ec.port = device.port
        ec.baudrate = device.baudrate
        ec.read_delay = device.read_delay
        ec.set_parity(device.parity)
        ec.set_stopbits(device.stopbits)
        return ec.open(timeout=device.timeout)


class EthernetCommunicationStrategy(CommunicationStrategy):
    def setup(self, device, write_terminator=None, read_terminator=None, force=False):
        if write_terminator is None:
            write_terminator = device.write_terminator

        if read_terminator is None:
            read_terminator = device.read_terminator

        ret = True
        if force or device.communicator is None:
            ec = device.build_communicator("ethernet")
            if ec is None:
                return
            ec.host = device.host
            ec.port = device.port
            ec.kind = device.kind
            ec.use_end = device.use_end
            ec.message_frame = device.message_frame
            ec.write_terminator = write_terminator
            ec.read_terminator = read_terminator
            ec.timeout = device.timeout
            ret = ec.open()
            if device.communicator:
                device.communicator.report()

        return ret


class RemoteDeviceMixin(Loggable, HasCommunicator):
    connected = False

    kind = Str
    message_frame = Str
    use_end = Bool
    timeout = CInt
    write_terminator = chr(10)
    read_terminator = ""

    # transport behavior is composed, not inherited. Set to a
    # CommunicationStrategy instance by the concrete device class.
    communication_strategy = None

    def open(self):
        return self.setup_communicator()

    def opened(self):
        pass

    def shutdown(self):
        self.close_communicator()

    def setup_communicator(self, *args, **kw):
        if self.communication_strategy is None:
            raise NotImplementedError
        return self.communication_strategy.setup(self, *args, **kw)

    def _ask(self, *args, **kw):
        if not self.communicator:
            self.setup_communicator()

        if self.communicator:
            return self.communicator.ask(*args, **kw)


# ============= EOF =============================================
