# ===============================================================================
# Copyright 2022 ross
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
import json
import os
import time

from pychron.loggable import Loggable
from pychron.paths import paths


def clear_checkpoint(**kw):
    set_checkpoint(state='clear')


def set_checkpoint(**kw):
    cp = paths.checkpoint_file
    ctx = {'state': 'active', 'timestamp': time.time()}
    if os.path.isfile(cp):
        with open(cp, 'r') as rfile:
            obj = json.load(rfile)
            ctx.update(**obj)

    ctx.update(**kw)

    with open(cp, 'w') as wfile:
        json.dump(ctx, wfile)


class ExperimentRecovery(Loggable):
    def get_checkpoint(self):
        cp = paths.checkpoint_file
        if os.path.isfile(cp):
            with open(cp, 'r') as rfile:
                return json.load(rfile)

    def init(self, app):
        """
        This method is called by PyExperiment.


        1. check for a checkpoint file
        2. open the experiment.rem.txt file
        3. launch the experiment in autolaunch mode. This should launch without any questions, for example previous
        blank should be auto selected

        """
        self.debug('initializing ExperimentRecovery')
        checkpoint = self.get_checkpoint()
        min_auto_launch = 180
        if checkpoint:
            experiment = checkpoint.get('experiment')
            state = checkpoint.get('state')
            if state != 'clear':
                la = checkpoint.get('last_auto_launch')
                if la:
                    elapsed = time.time() - la
                    if elapsed < min_auto_launch:
                        self.critical('Pychron already tried to auto launch {} seconds ago, min launch time is {} '
                                      'seconds. There is likely a critical '
                                      'issue that needs to be resolved before continuing'.format(elapsed,
                                                                                                 min_auto_launch))
                        return

                self.debug('got experiment {} from checkpoint'.format(experiment))
                path = os.path.join(paths.experiment_rem_dir, experiment)

                task = app.get_task('pychron.experiment.task')
                if task.open(path):
                    task.window.open()
                    set_checkpoint(last_auto_launch=time.time())
                    task.auto_execute()

# ============= EOF =============================================
