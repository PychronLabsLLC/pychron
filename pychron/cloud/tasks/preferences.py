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
from pyface.api import GUI
from traits.api import Bool, Button, File, Password, Str
from traitsui.api import Color, Group, HGroup, ImageEditor, Item, VGroup, View

from pychron.cloud.api_client import (
    CloudAPIError,
    CloudAuthError,
    CloudDeviceCodeDenied,
    CloudDeviceCodeExpired,
    CloudNetworkError,
    whoami,
)
from pychron.cloud.keyring_store import (
    delete_token,
    get_token,
    set_token,
)
from pychron.cloud.qr import make_qr_for_device_code
from pychron.cloud.workstation_setup import (
    DeviceEnrollmentCancelled,
    KeyringWriteFailedError,
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

    # Device-code enrollment (RFC 8628-style). The technician clicks
    # ``enroll_via_device_code_button``; the workstation contacts
    # pychronAPI, displays ``_pending_user_code`` + ``_pending_verification_url``
    # for the technician to read out to the admin, and polls in a
    # background thread until the admin approves.
    enroll_via_device_code_button = Button("Start device-code enrollment")
    cancel_enrollment_button = Button("Cancel enrollment")
    _pending_user_code = Str
    _pending_verification_url = Str
    # PNG path for the verification-URL QR. Admin scans it from the
    # workstation screen with their phone instead of typing the URL +
    # user_code by hand. Empty string until the server returns the
    # `verification_url_complete` payload.
    _pending_qr_path = File
    _pending_active = Bool(False)
    _should_cancel_enrollment = Bool(False)

    # Surfaced on KeyringWriteFailedError so the technician can paste
    # the (still-in-memory) token into a password manager. Cleared
    # whenever a fresh enrollment starts.
    _recovery_token = Str
    _recovery_lab = Str

    _remote_status = Str
    _remote_status_color = Color

    def _remote_status_color_default(self):
        return normalize_color_name("red")

    def _initialize(self, *args, **kw):
        super(CloudPreferences, self)._initialize(*args, **kw)
        self._load_token_from_keyring()

    def _is_preference_trait(self, trait_name):
        # api_token must never be written to the .cfg — it lives in the OS
        # keyring. The transient remote-status, enrollment progress, and
        # lifecycle-button traits also stay out.
        if trait_name in (
            "api_token",
            "_remote_status",
            "_remote_status_color",
            "test_connection",
            "reonboard_button",
            "revoke_button",
            "switch_lab_button",
            "enroll_via_device_code_button",
            "cancel_enrollment_button",
            "_pending_user_code",
            "_pending_verification_url",
            "_pending_qr_path",
            "_pending_active",
            "_should_cancel_enrollment",
            "_recovery_token",
            "_recovery_lab",
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

    # -- device-code enrollment ---------------------------------------

    def _enroll_via_device_code_button_fired(self):
        """Kick off a device-code grant in a background thread.

        The worker thread updates ``_pending_user_code`` and
        ``_pending_verification_url`` so the technician can read them
        out to the admin, then polls until completion.
        """
        if self._pending_active:
            return
        self._remote_status_color = normalize_color_name("red")
        if not self.api_base_url:
            self._remote_status = "Set API Base URL first"
            return

        self._should_cancel_enrollment = False
        self._pending_user_code = ""
        self._pending_verification_url = ""
        self._pending_qr_path = ""
        self._recovery_token = ""
        self._recovery_lab = ""
        self._pending_active = True
        self._remote_status = "Starting enrollment..."
        self._remote_status_color = normalize_color_name("orange")

        import threading

        threading.Thread(
            target=self._enrollment_worker,
            name="pychron-cloud-device-code",
            daemon=True,
        ).start()

    def _on_device_code_user_code(
        self, user_code, verification_url, verification_url_complete, expires_at
    ):
        """Worker-thread callback: surface the user_code + URL + QR in the pane.

        Trait writes from non-UI threads are dispatched to the UI thread
        by the Pyface event loop, so the operator sees the code as soon
        as the server returns it. QR generation runs on this thread
        (small file, ~hundreds of microseconds for a typical URL); a
        failure is non-fatal — the typed code + URL still work.
        """
        self._pending_user_code = user_code
        self._pending_verification_url = verification_url
        try:
            self._pending_qr_path = make_qr_for_device_code(
                verification_url_complete, host_slug=self.lab_name or "default"
            )
        except Exception as exc:
            logger.warning("device-code QR generation failed: %s", exc)
            self._pending_qr_path = ""
        self._remote_status = "Show {} to admin at {}".format(user_code, verification_url)
        self._remote_status_color = normalize_color_name("orange")

    def _enrollment_worker(self):
        api_base_url = self.api_base_url
        try:
            setup = WorkstationSetup.from_device_code(
                api_base_url,
                on_user_code=self._on_device_code_user_code,
                should_cancel=lambda: self._should_cancel_enrollment,
            )
        except DeviceEnrollmentCancelled:
            GUI.invoke_later(self._apply_enrollment_terminal, "Enrollment cancelled", "red")
            return
        except CloudDeviceCodeDenied:
            GUI.invoke_later(
                self._apply_enrollment_terminal,
                "Admin denied — ask for a new request",
                "red",
            )
            return
        except CloudDeviceCodeExpired:
            GUI.invoke_later(self._apply_enrollment_terminal, "Code expired — start over", "red")
            return
        except CloudAuthError:
            GUI.invoke_later(self._apply_enrollment_terminal, "Auth rejected", "red")
            return
        except CloudNetworkError as exc:
            logger.warning("device-code enrollment transport failure: %s", exc)
            GUI.invoke_later(self._apply_enrollment_terminal, "Unreachable", "red")
            return
        except KeyringWriteFailedError as exc:
            # Server already minted; we hold the only copy. Hand the
            # plaintext to the UI thread for display — and DO NOT log
            # the exception (its message intentionally omits the token
            # but defense-in-depth: log only the type name).
            logger.warning(
                "device-code enrollment keyring write failed: %s",
                type(exc).__name__,
            )
            GUI.invoke_later(self._apply_keyring_recovery, exc.lab_name, exc.api_token)
            return
        except (CloudAPIError, WorkstationSetupError) as exc:
            logger.warning("device-code enrollment failed: %s", type(exc).__name__)
            GUI.invoke_later(self._apply_enrollment_terminal, "Enrollment failed", "red")
            return

        GUI.invoke_later(self._apply_enrollment_success, setup)

    def _apply_enrollment_success(self, setup):
        """Run on the UI thread. Persistent-trait writes (api_base_url,
        lab_name) fire BasePreferencesHelper listeners that call into
        Envisage's preferences node, which expects single-threaded
        access — so we dispatch them here rather than from the worker.
        """
        self.api_base_url = setup.api_base_url
        self.lab_name = setup.lab_name
        self._load_token_from_keyring()
        self._remote_status = "Enrolled as {}".format(setup.lab_name)
        self._remote_status_color = normalize_color_name("green")
        self._reset_pending()

    def _apply_enrollment_terminal(self, message, color):
        self._remote_status = message
        self._remote_status_color = normalize_color_name(color)
        self._reset_pending()

    def _apply_keyring_recovery(self, lab_name, api_token):
        """Display the still-in-memory token so the technician can copy
        it into a password manager. This is the recovery path for the
        single-use polling secret being already consumed server-side
        but not persisted locally.
        """
        self._recovery_lab = lab_name
        self._recovery_token = api_token
        self._remote_status = (
            "Keyring write failed — copy the token below and store it "
            "manually before closing this window"
        )
        self._remote_status_color = normalize_color_name("red")
        self._reset_pending()

    def _reset_pending(self):
        self._pending_user_code = ""
        self._pending_verification_url = ""
        self._pending_qr_path = ""
        self._pending_active = False
        self._should_cancel_enrollment = False

    def _cancel_enrollment_button_fired(self):
        if not self._pending_active:
            return
        self._should_cancel_enrollment = True
        self._remote_status = "Cancelling..."

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
        enroll = VGroup(
            HGroup(
                Item(
                    "enroll_via_device_code_button",
                    show_label=False,
                    enabled_when="not _pending_active",
                    tooltip="Contact pychronAPI for a single-use device code, "
                    "then read the displayed code to your lab admin. They will "
                    "approve from any phone or laptop browser; this workstation "
                    "polls until they do.",
                ),
                Item(
                    "cancel_enrollment_button",
                    show_label=False,
                    enabled_when="_pending_active",
                ),
            ),
            HGroup(
                Item(
                    "_pending_user_code",
                    style="readonly",
                    label="Code",
                    visible_when="_pending_active",
                ),
                Item(
                    "_pending_verification_url",
                    style="readonly",
                    label="Approve at",
                    visible_when="_pending_active",
                ),
            ),
            HGroup(
                Item(
                    "_pending_qr_path",
                    show_label=False,
                    editor=ImageEditor(),
                    tooltip="Scan with the admin's phone to open the "
                    "verification page with the user_code pre-filled.",
                    visible_when="_pending_qr_path != ''",
                ),
            ),
            HGroup(
                Item(
                    "_recovery_token",
                    style="readonly",
                    label="RECOVERY TOKEN",
                    tooltip="Keyring write failed — copy this token into a "
                    "password manager before closing the window. The polling "
                    "secret is single-use, so this is the only copy.",
                    visible_when="_recovery_token != ''",
                ),
                Item(
                    "_recovery_lab",
                    style="readonly",
                    label="for lab",
                    visible_when="_recovery_token != ''",
                ),
            ),
            show_border=True,
            label="Enroll via Device Code",
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
        return View(Group(creds, enroll, lifecycle))


# ============= EOF =============================================
