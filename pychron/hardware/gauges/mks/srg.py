# ===============================================================================
# Copyright 2020 ross
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
from pychron.hardware import get_float
from pychron.hardware.core.core_device import CoreDevice


class MKSSRG(CoreDevice):
    """
    MKS SRG-3 Spinning Rotor Gauge RS-232 driver.

    Implements basic pressure readout using the SRG-3 instrument
    command language (postfix notation, CR-terminated commands).
    The `VAL` command returns the most recent measured pressure as
    a real number in scientific format (e.g. ` 1.2345E-05`).

    Default serial config per manual: 9600 baud, 8 data bits, no
    parity, 1 stop bit, no handshake.

    Example device config file (`MKSSRG.cfg`)::

        [General]
        name=SRG3

        [Communications]
        type=serial
        port=/dev/tty.usbserial-SRG3
        baudrate=9600
        bytesize=8
        parity=NONE
        stopbits=1
        timeout=2
        read_delay=50
    """

    scheme = "ascii"

    def initialize(self, *args, **kw):
        if self.communicator:
            # SRG-3 input terminated by CR, replies by CRLF (manual sec 2.3)
            self.communicator.write_terminator = "chr(10)"
            self.communicator.terminator = "CRLF"
        # clear any pending input/prompt
        self.ask("idy")
        return True

    @get_float(default=0)
    def get_pressure(self, **kw):
        return self.read_pressure(**kw)

    def read_pressure(self, verbose=False):
        resp = self.ask("val", verbose=verbose)
        return self._parse_real(resp)

    def get_unit_label(self, verbose=False):
        return self.ask("ulb", verbose=verbose)

    def _parse_real(self, resp):
        if resp is None:
            return None
        # strip prompt chars and whitespace; SRG-3 reals look like " 1.2345E-05"
        resp = resp.strip().lstrip(">").lstrip("?").strip()
        try:
            return float(resp)
        except (TypeError, ValueError) as e:
            self.warning("failed parsing SRG-3 pressure response {!r}: {}".format(resp, e))
            return None


# ============= EOF =============================================
