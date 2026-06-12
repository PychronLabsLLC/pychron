# ===============================================================================
# Copyright 2024 Pychron Developers
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


from pyface.message_dialog import information
from pyface.tasks.action.task_action import TaskAction


SERVICE_PROTOCOL = "pychron.ausgeochem.earthbank_service.AusGeochemEarthBankService"


def _get_service(event):
    app = event.task.application
    return app.get_service(SERVICE_PROTOCOL)


class UploadAusGeochemAction(TaskAction):
    name = "Test AusGeochem EarthBank Connection..."

    def perform(self, event):
        service = _get_service(event)
        if service is None:
            information(None, "AusGeochem service is not available")
            return

        if service.test_connection():
            information(None, "Successfully connected to AusGeochem EarthBank")
        else:
            information(
                None,
                "AusGeochem EarthBank connection failed. Check credentials/logs.",
            )


class EarthBankLoginAction(TaskAction):
    name = "EarthBank Login..."

    def perform(self, event):
        service = _get_service(event)
        if service is None:
            information(None, "AusGeochem service is not available")
            return

        if service.login(prompt=True):
            information(None, "EarthBank login successful")
        else:
            information(None, "EarthBank login cancelled or failed")


# ============= EOF =============================================
