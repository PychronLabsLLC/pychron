# ===============================================================================
# Copyright 2026 ross
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
from traits.api import Int

from pychron.hardware import get_float
from pychron.hardware.core.core_device import CoreDevice
from pychron.hardware.core.modbus import ModbusMixin


class EPC3000(CoreDevice, ModbusMixin):
    """
    Eurotherm / Carbolite EPC3000 series temperature controller
    (EPC3016, EPC3008, EPC3004) Modbus driver.

    Implements basic process-value (temperature) readout. EPC3000
    Modbus addresses are 2400-series compatible: register 1 holds
    the Process Value as a 16-bit signed integer scaled by the
    instrument's configured decimal places (e.g. DecP=1 -> divide
    raw value by 10).

    Pymodbus is used for transport; either Modbus TCP (Ethernet
    option) or Modbus RTU (RS232/RS485, EPC3008/3004 standard) may
    be configured.

    Example device config file (`EPC3000.cfg`) - Modbus TCP::

        [General]
        name=EPC3000

        [Communications]
        type=modbustcp
        host=192.168.1.50
        port=502
        timeout=2
        byteorder=big
        wordorder=little

        [Register]
        process_value=1
        setpoint=2
        output=3
        working_setpoint=5

        [Scaling]
        decimal_places=1

    Example device config file (`EPC3000.cfg`) - Modbus RTU::

        [General]
        name=EPC3000

        [Communications]
        type=modbus
        port=/dev/tty.usbserial-EPC
        baudrate=9600
        bytesize=8
        parity=NONE
        stopbits=1
        timeout=2
        slave_address=01

        [Register]
        process_value=1
        setpoint=2
        output=3
        working_setpoint=5

        [Scaling]
        decimal_places=1
    """

    process_value_address = Int(1)
    setpoint_address = Int(2)
    output_address = Int(3)
    working_setpoint_address = Int(5)
    decimal_places = Int(1)

    scan_func = "get_process_value"

    def load_additional_args(self, config):
        for attr in ("process_value", "setpoint", "output", "working_setpoint"):
            self.set_attribute(
                config,
                "{}_address".format(attr),
                "Register",
                attr,
                cast="int",
                optional=True,
            )
        self.set_attribute(
            config,
            "decimal_places",
            "Scaling",
            "decimal_places",
            cast="int",
            optional=True,
        )
        return True

    @get_float(default=0)
    def get_process_value(self, **kw):
        return self._read_scaled(self.process_value_address, **kw)

    @get_float(default=0)
    def get_setpoint(self, **kw):
        return self._read_scaled(self.setpoint_address, **kw)

    @get_float(default=0)
    def get_working_setpoint(self, **kw):
        return self._read_scaled(self.working_setpoint_address, **kw)

    @get_float(default=0)
    def get_output(self, **kw):
        return self._read_scaled(self.output_address, **kw)

    def _read_scaled(self, address, **kw):
        result = self._read_holding_registers(address=int(address), count=1, **kw)
        if result is None:
            return None
        try:
            raw = result.registers[0]
        except (AttributeError, IndexError):
            self.warning("invalid modbus result for address {}: {!r}".format(address, result))
            return None

        # 16-bit two's complement
        if raw & 0x8000:
            raw -= 0x10000

        scale = 10 ** self.decimal_places if self.decimal_places else 1
        return raw / scale


# ============= EOF =============================================
