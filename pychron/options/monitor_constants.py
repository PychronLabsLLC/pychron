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
"""
Flux-monitor constant resolution.

Extracted from MonitorMixin as a composed value object. The mixin mixed
UI-bound Enums (``selected_monitor``, ``error_kind``) with knowledge of the
FLUX_CONSTANTS schema. The schema lookups live here now -- a small, dependency-
free object that can be unit-tested without constructing a traits Options
object -- and the mixin's Properties delegate to it.
"""
from uncertainties import ufloat

from pychron.pychron_constants import FLUX_CONSTANTS


class MonitorConstants:
    """Resolves the constants for a single flux monitor key."""

    def __init__(self, key):
        # mirrors the previous behavior: an unknown key raises KeyError
        self._dc = FLUX_CONSTANTS[key]

    @property
    def lambda_k(self):
        b = ufloat(*self._dc["lambda_b"])
        ec = ufloat(*self._dc["lambda_ec"])
        return b + ec

    @property
    def monitor_name(self):
        return self._dc.get("monitor_name", "")

    @property
    def monitor_age(self):
        return self._dc.get("monitor_age", 0)

    @property
    def monitor_material(self):
        return self._dc.get("monitor_material", "")


# ============= EOF =============================================
