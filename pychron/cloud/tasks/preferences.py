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
"""Preferences pane for the Pychron Cloud (pychronAPI) integration (M7 P1).

Adds a "Pychron Cloud" pane with:

- ``enable_pychron_cloud`` feature flag (Bool)
- ``api_base_url`` (Str, persisted to .cfg)
- ``lab_name`` (Str, persisted to .cfg)
- ``api_token`` (Password, *not* persisted to .cfg — kept in OS keyring)
- A "Test Connection" button that calls ``/api/v1/forgejo/whoami`` and
  surfaces the returned scopes/lab so the operator can confirm the token
  can actually register a workstation SSH key (P2).
"""

from __future__ import absolute_import

import logging

from envisage.ui.tasks.preferences_pane import PreferencesPane
from traits.api import Bool, Button, Password, Str
from traitsui.api import Color, Group, HGroup, Item, VGroup, View

from pychron.cloud.api_client import (
    CloudAPIError,
    CloudAuthError,
    CloudNetworkError,
    whoami,
)
from pychron.cloud.keyring_store import (
    delete_token,
    get_token,
    set_token,
)
from pychron.cloud.workstation_setup import (
    WorkstationSetup,
    WorkstationSetupError,
    switch_lab as wipe_for_switch_lab,
)
from pychron.core.confirmation import confirmation_dialog
from pychron.core.helpers.color_utils import normalize_color_name
from pychron.core.ui.custom_label_editor import CustomLabel
from pychron.envisage.tasks.base_preferences_helper import (
    BasePreferencesHelper,
    test_connection_item,
)

logger = logging.getLogger(__name__)


class CloudPreferences(BasePreferencesHelper):
    """Preferences for the pychronAPI workstation onboarding flow."""

    preferences_path = "pychron.cloud"

    enable_pychron_cloud = Bool(False)
    api_base_url = Str
    lab_name = Str
    api_token = Password

    test_connection = Button
    reonboard_button = Button("Re-onboard workstation")
    revoke_button = Button("Revoke this workstation")
    switch_lab_button = Button("Switch lab (destructive)")
    _remote_status = Str
    _remote_status_color = Color

    def _remote_status_color_default(self):
        return normalize_color_name("red")

    def _initialize(self, *args, **kw):
        super(CloudPreferences, self)._initialize(*args, **kw)
        self._load_token_from_keyring()

    def _is_preference_trait(self, trait_name):
        # api_token must never be written to the .cfg — it lives in the OS
        # keyring. The transient remote-status traits and the lifecycle
        # buttons also stay out.
        if trait_name in (
            "api_token",
            "_remote_status",
            "_remote_status_color",
            "test_connection",
            "reonboard_button",
            "revoke_button",
            "switch_lab_button",
        ):
            return False
        return super(CloudPreferences, self)._is_preference_trait(trait_name)

    def _load_token_from_keyring(self):
        token = get_token(self.lab_name)
        if token != self.api_token:
            self.trait_setq(api_token=token)

    def _lab_name_changed(self, old, new):
        # Different lab → different keyring slot. Pull whatever is stored
        # there so the user sees the right token without re-entering it.
        if old != new:
            self._load_token_from_keyring()

    def _api_token_changed(self, old, new):
        if not self.lab_name:
            # No lab → nowhere to file it. Do not silently drop.
            self._remote_status = "Set lab_name first"
            self._remote_status_color = normalize_color_name("red")
            return
        if new:
            set_token(self.lab_name, new)
        elif old:
            delete_token(self.lab_name)

    def _test_connection_fired(self):
        self._remote_status_color = normalize_color_name("red")
        if not self.api_base_url:
            self._remote_status = "No URL"
            return
        if not self.api_token:
            self._remote_status = "No token"
            return
        try:
            info = whoami(self.api_base_url, self.api_token)
        except CloudAuthError:
            self._remote_status = "401 Unauthorized"
            return
        except CloudNetworkError as exc:
            logger.warning("cloud whoami transport failure: %s", exc)
            self._remote_status = "Unreachable"
            return
        except CloudAPIError as exc:
            logger.warning("cloud whoami failure: %s", exc)
            self._remote_status = "Invalid"
            return

        if self.lab_name and info.lab and info.lab != self.lab_name:
            self._remote_status = "Lab mismatch ({})".format(info.lab)
            return
        if not info.can_register_ssh_key():
            self._remote_status = "Missing scope (have: {})".format(",".join(info.scopes) or "none")
            self._remote_status_color = normalize_color_name("orange")
            return

        self._remote_status = "OK ({} / {})".format(info.kind or "?", info.lab or "?")
        self._remote_status_color = normalize_color_name("green")

    # -- P6 buttons ---------------------------------------------------

    def _build_setup(self):
        return WorkstationSetup(
            api_base_url=self.api_base_url,
            api_token=self.api_token,
            lab_name=self.lab_name,
        )

    def _reonboard_button_fired(self):
        self._remote_status_color = normalize_color_name("red")
        if not (self.api_base_url and self.api_token and self.lab_name):
            self._remote_status = "Need URL, token, and lab"
            return
        try:
            self._build_setup().reonboard()
        except CloudAuthError:
            self._remote_status = "401 Unauthorized — re-enter token"
            return
        except (CloudAPIError, WorkstationSetupError) as exc:
            logger.warning("re-onboard failed: %s", exc)
            self._remote_status = "Re-onboard failed"
            return
        self._remote_status = "Re-onboarded"
        self._remote_status_color = normalize_color_name("green")

    def _revoke_button_fired(self):
        self._remote_status_color = normalize_color_name("red")
        if not confirmation_dialog(
            "Revoke this workstation? The pychronAPI token and SSH key will "
            "be deleted on the server, and all local cloud credentials will "
            "be removed. Per-repo clones under ~/Pychron/projects/ are kept.",
            title="Revoke workstation",
        ):
            return
        try:
            self._build_setup().revoke_and_wipe()
        except CloudAPIError as exc:
            # revoke_and_wipe wipes locally even when the revoke call
            # fails; surface the server-side failure but mark the local
            # state as cleaned up.
            logger.warning("server revoke failed (local state wiped): %s", exc)
            self._remote_status = "Local wiped; server revoke failed"
        else:
            self._remote_status = "Revoked"
            self._remote_status_color = normalize_color_name("green")
        # Clear the keyring slot for this lab so the token is not
        # silently restored on next pane open.
        if self.lab_name:
            delete_token(self.lab_name)
        self.trait_setq(api_token="")

    def _switch_lab_button_fired(self):
        self._remote_status_color = normalize_color_name("red")
        if not confirmation_dialog(
            "Switching the lab is destructive. The local SSH key, "
            "~/.pychron state, and ALL clones under ~/Pychron/projects/ "
            "will be deleted. The keyring token for the current lab will "
            "also be removed. Continue?",
            title="Switch lab",
        ):
            return
        # Capture the lab name we are leaving before clearing prefs so we
        # can target the right keyring slot.
        old_lab = self.lab_name
        wipe_for_switch_lab()
        if old_lab:
            delete_token(old_lab)
        self.trait_setq(api_token="", lab_name="", api_base_url="")
        self._remote_status = "Wiped; configure new lab above"
        self._remote_status_color = normalize_color_name("orange")


class CloudPreferencesPane(PreferencesPane):
    model_factory = CloudPreferences
    category = "Pychron Cloud"

    def traits_view(self):
        creds = VGroup(
            Item(
                "enable_pychron_cloud",
                tooltip="Master feature flag for the pychronAPI workstation "
                "onboarding flow (M7). When off, no cloud calls are made.",
                label="Enabled",
            ),
            Item(
                "api_base_url",
                tooltip="Base URL of the pychronAPI service, e.g. "
                "https://pychron-api-xyz-uc.a.run.app",
                resizable=True,
                label="API Base URL",
            ),
            Item(
                "lab_name",
                tooltip="Lab name as registered in pychronAPI (matches the "
                "lab prefix in the API token, e.g. 'nmgrl' from "
                "pcy_nmgrl_<random>).",
                label="Lab",
            ),
            Item(
                "api_token",
                tooltip="API token shaped pcy_<lab>_<random>. Stored in the "
                "OS keyring, never in the .cfg file. The token must carry "
                "the workstations:register_ssh_key scope.",
                resizable=True,
                label="API Token",
            ),
            HGroup(
                test_connection_item(),
                CustomLabel(
                    "_remote_status",
                    width=240,
                    color_name="_remote_status_color",
                ),
            ),
            show_border=True,
            label="Pychron Cloud (pychronAPI)",
        )
        lifecycle = VGroup(
            HGroup(
                Item("reonboard_button", show_label=False),
                Item("revoke_button", show_label=False),
                Item("switch_lab_button", show_label=False),
            ),
            show_border=True,
            label="Workstation Lifecycle",
        )
        return View(Group(creds, lifecycle))


# ============= EOF =============================================
