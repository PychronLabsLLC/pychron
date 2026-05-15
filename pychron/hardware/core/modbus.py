# ===============================================================================
# Copyright 2021 ross
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
from pymodbus.exceptions import ConnectionException


class ModbusMixin:
    """
    simple mapper of the Modbus commands
    """

    def _get_wordorder(self):
        if hasattr(self.communicator, "wordorder"):
            return self.communicator.wordorder.lower()
        return "little"

    def _read_float(self, register, *args, **kw):
        result = self._read_holding_registers(
            address=int(register), count=2, *args, **kw
        )
        return self._decode_float(result)

    def _read_int(self, register, *args, **kw):
        result = self._read_holding_registers(
            address=int(register), count=2, *args, **kw
        )
        if result and not result.isError():
            return self.communicator.convert_from_registers(
                result.registers,
                data_type=self.communicator.DATATYPE.INT32,
                word_order=self._get_wordorder(),
            )

    def _read_input_float(self, register, *args, **kw):
        result = self._read_input_registers(address=int(register), count=2, *args, **kw)
        return self._decode_float(result)

    def _read_input_int(self, register, *args, **kw):
        result = self._read_input_registers(address=int(register), count=2, *args, **kw)
        if result and not result.isError():
            return self.communicator.convert_from_registers(
                result.registers,
                data_type=self.communicator.DATATYPE.UINT32,
                word_order=self._get_wordorder(),
            )

    def _decode_float(self, result):
        if result and not result.isError():
            return self.communicator.convert_from_registers(
                result.registers,
                data_type=self.communicator.DATATYPE.FLOAT32,
                word_order=self._get_wordorder(),
            )

    def _get_payload(self, value, is_float=True):
        data_type = (
            self.communicator.DATATYPE.FLOAT32
            if is_float
            else self.communicator.DATATYPE.INT32
        )
        return self.communicator.convert_to_registers(
            value,
            data_type=data_type,
            word_order=self._get_wordorder(),
        )

    def _write_int(self, register, value, *args, **kw):
        payload = self._get_payload(value, is_float=False)
        self.debug(f"writing int register={register} payload={payload} value={value}")
        return self._write_registers(register, payload, *args, **kw)

    def _write_float(self, register, value, *args, **kw):
        payload = self._get_payload(value)
        self.debug(f"writing float register={register} payload={payload} value={value}")
        return self._write_registers(register, payload, *args, **kw)

    def _func(self, funcname, *args, **kw):
        if self.communicator:
            if kw.pop("verbose", False):
                self.debug(f"ModbusMixin: {funcname} {args} {kw}")

            try:
                return getattr(self.communicator, funcname)(*args, **kw)
            except ConnectionException as e:
                self.warning(f"modbus {funcname} connection lost: {e}")
                self.communicator.simulation = True
            except OSError as e:
                self.warning(f"modbus {funcname} socket error: {e}")
                self.communicator.simulation = True

    def _read_coils(self, *args, **kw):
        return self._func("read_coils", *args, **kw)

    def _write_coil(self, *args, **kw):
        return self._func("write_coil", *args, **kw)

    def _read_holding_registers(self, *args, **kw):
        return self._func("read_holding_registers", *args, **kw)

    def _read_input_registers(self, *args, **kw):
        return self._func("read_input_registers", *args, **kw)

    def _write_register(self, *args, **kw):
        return self._func("write_register", *args, **kw)

    def _write_registers(self, *args, **kw):
        return self._func("write_registers", *args, **kw)

# ============= EOF =============================================
