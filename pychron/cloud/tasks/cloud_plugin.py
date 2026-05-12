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
"""Envisage plugin that contributes the Pychron Cloud preferences pane."""

from __future__ import absolute_import

from pychron.cloud.tasks.preferences import CloudPreferencesPane
from pychron.envisage.tasks.base_task_plugin import BaseTaskPlugin


class CloudPlugin(BaseTaskPlugin):
    id = "pychron.cloud.plugin"
    name = "PychronCloud"

    def _preferences_panes_default(self):
        return [CloudPreferencesPane]

    def _preferences_default(self):
        return self._preferences_factory("cloud")


# ============= EOF =============================================
