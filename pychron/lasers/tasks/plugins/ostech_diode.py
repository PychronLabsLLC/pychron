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

# ============= enthought library imports =======================

from envisage.ui.tasks.task_extension import TaskExtension
from pyface.action.group import Group
from pyface.tasks.action.schema_addition import SchemaAddition
from pychron.lasers.tasks.laser_preferences import (
    FusionsDiodePreferencesPane,
    OsTechDiodePreferencesPane,
)
from pychron.lasers.tasks.plugins.laser_plugin import FusionsPlugin, BaseLaserPlugin
from pychron.lasers.tasks.laser_task import OsTechDiodeTask

# ============= standard library imports ========================
# ============= local library imports  ==========================
from pychron.pychron_constants import FUSIONS_DIODE, OSTECH_DIODE


class OsTechDiodePlugin(BaseLaserPlugin):
    id = "pychron.ostech.diode"
    name = OSTECH_DIODE.replace(" ", "")

    klass = ("pychron.lasers.laser_managers.ostech_laser_manager", "OsTechDiodeManager")
    task_name = OSTECH_DIODE
    accelerator = "Ctrl+Shift+["

    # def _task_extensions_default(self):
    #
    #     exts = super(OsTechDiodePlugin, self)._task_extensions_default()
    #
    #     ext1 = TaskExtension(
    #         task_id='pychron.fusions.diode',
    #         actions=[SchemaAddition(id='calibration',
    #                                 factory=lambda: Group(
    #                                     # PowerMapAction(),
    #                                     # PowerCalibrationAction(),
    #                                     # PyrometerCalibrationAction(),
    #                                     PIDTuningAction()),
    #                                 path='MenuBar/Laser'),
    #                  # SchemaAddition(
    #                  #     factory=TestDegasAction,
    #                  #     path='MenuBar/Laser'),
    #                  # SchemaAddition(
    #                  #     factory=lambda: ExecutePatternAction(self._get_manager()),
    #                  #     path='MenuBar/Laser')
    #                  ])
    #
    #     return exts + [ext1]

    def _preferences_panes_default(self):
        return [OsTechDiodePreferencesPane]

    def _task_factory(self):
        t = OsTechDiodeTask(manager=self._get_manager(), application=self.application)
        return t


# ============= EOF =============================================
# SchemaAddition(id='fusions_diode_group',
#                                                    factory=lambda: GroupSchema(id='FusionsDiodeGroup'),
#                                                    path='MenuBar/Extraction'
#                                                    ),
#                                     SchemaAddition(id='fusions_diode_group',
#                                                   factory=lambda: Group(),
#                                                   path='MenuBar/Extraction'
#                                                   ),
# SchemaAddition(id='open_scan',
#               factory=factory_scan,
#               path='MenuBar/Laser'
#               #                                                 path='MenuBar/Extraction/FusionsDiodeGroup'
# ),
# SchemaAddition(id='open_autotune',
#               factory=factory_tune,
#               path='MenuBar/Laser'
#               #                                                 path='MenuBar/Extraction/FusionsDiodeGroup'
# ),
