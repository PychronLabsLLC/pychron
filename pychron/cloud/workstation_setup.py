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
"""Workstation onboarding orchestrator (M7 P2).

End-to-end flow:

1. Ensure ``~/.pychron/keys/pychron_<host>`` keypair exists (generate if
   missing).
2. POST the public key to pychronAPI
   ``/api/v1/forgejo/workstations/ssh-keys``.
3. Persist the response to ``~/.pychron/registration.json`` for future
   runs.
4. Append the returned ``known_hosts_line`` to ``~/.pychron/known_hosts``.
5. Insert / replace the ``Host pychron-<lab>`` block in ``~/.ssh/config``.

Idempotency rules:

- Re-running with a valid local keypair AND a stored registration is a
  no-op for the local filesystem (the SSH config block is rewritten only
  if it has drifted).
- If the server returns
  :class:`pychron.cloud.api_client.CloudFingerprintRejected`, the local
  keypair is rotated (regenerated) and the call retried once. This
  handles the case where the server-side row was wiped (M3 reaper) but
  the local key persists.
- Any other server / transport error aborts the run and surfaces a typed
  exception to the caller.
"""

from __future__ import absolute_import

import json
import logging
import os
import time

from pychron.cloud.api_client import (
    CloudAPIError,
    CloudDeviceCodeDenied,
    CloudDeviceCodeExpired,
    CloudDeviceCodePending,
    CloudFingerprintRejected,
    CloudNetworkError,
    poll_device_code,
    register_ssh_key,
    revoke_workstation_token,
    start_device_code,
)
from pychron.cloud.keyring_store import set_token as keyring_set_token
from pychron.cloud.paths import (
    ensure_pychron_dirs,
    host_slug,
    known_hosts_path,
    project_clone_path,
    projects_dir,
    public_key_path,
    registration_path,
    key_path as default_key_path,
)
from pychron.cloud.ssh_config import (
    append_known_hosts_line,
    remove_ssh_config_block,
    upsert_ssh_config_block,
)
from pychron.cloud.ssh_keygen import (
    ensure_keypair,
    generate_keypair,
    read_public_key,
)

logger = logging.getLogger(__name__)

# Retry budget for transient poll failures. The server-side mint
# (Forgejo bot create + ssh-key add) is a multi-step network
# operation that occasionally trips on upstream timeouts. The
# device-code row stays approved + unconsumed when the mint rolls
# back, so the workstation can retry without re-bothering the admin.
# After this many CONSECUTIVE transient failures we give up and
# surface the error so the operator knows something is broken.
_POLL_TRANSIENT_RETRY_LIMIT = 6


class WorkstationSetupError(Exception):
    """Raised when onboarding cannot complete."""


class DeviceEnrollmentCancelled(WorkstationSetupError):
    """The polling loop returned because ``should_cancel`` went True.

    Raised so the UI can distinguish a user-cancelled enrollment (offer
    to start over) from a server-side denial / expiry (offer to ask the
    admin for a new approval).
    """


class KeyringWriteFailedError(WorkstationSetupError):
    """OS keyring write failed during enrollment.

    The polling secret is single-use, so by the time this fires the
    server has already minted credentials and the workstation has the
    only copy in memory. ``api_token`` and ``lab_name`` are exposed as
    attributes so the UI can render them for the technician to paste
    into a password manager. The exception's ``__str__`` deliberately
    OMITS the token to keep it out of log files — callers must reach
    into the attributes if they want to display it.
    """

    def __init__(self, lab_name, api_token):
        super().__init__(
            "could not save api_token to OS keyring; UI must surface "
            "the token for manual capture"
        )
        self.lab_name = lab_name
        self.api_token = api_token


class WorkstationSetup(object):
    """Onboard the current workstation against a pychronAPI lab.

    The constructor takes the bound preference values directly so this
    class is decoupled from the Traits / Envisage stack and unit-testable
    without a running application.
    """

    def __init__(self, api_base_url, api_token, lab_name, host=None):
        self.api_base_url = api_base_url
        self.api_token = api_token
        self.lab_name = lab_name
        self.host = host or host_slug()
        # Populated by :meth:`from_device_code` when the bridge has
        # staged a credential for this api_token. ``database_url`` /
        # ``database_role`` carry a Postgres role + connection URL;
        # ``database_iam`` carries a Cloud SQL IAM bundle. All ``None``
        # means HTTP-only — DVC connection prefs are left untouched.
        self.database_url = None
        self.database_role = None
        self.database_iam = None
        # Default-MetaData repo metadata so the prefs pane can write
        # ``pychron.dvc.connection`` favorites with the right org +
        # meta_repo_name without re-deriving them from
        # ``registration.json``.
        self.default_metadata_repo = None

    # -- device-code enrollment ----------------------------------------

    @classmethod
    def from_device_code(
        cls,
        api_base_url,
        on_user_code,
        should_cancel=None,
        host=None,
        sleep=time.sleep,
    ):
        """Orchestrate an RFC 8628-style device-code enrollment end-to-end.

        Sequence:

        1. ``ensure_pychron_dirs`` + ``ensure_keypair`` (matches
           :meth:`run` — re-uses any existing local keypair).
        2. ``POST /api/v1/forgejo/device-codes`` to get a polling secret +
           the short user_code the technician will read out to the admin.
        3. Invoke ``on_user_code(user_code, verification_url,
           verification_url_complete, expires_at)`` exactly once. The UI
           is expected to display the code and the URL.
        4. Poll on ``interval_seconds`` until one of:

           * **success** — admin approved; persist registration,
             SSH-config, known_hosts, and OS-keyring token; return a
             populated :class:`WorkstationSetup`.
           * **denied** — :class:`CloudDeviceCodeDenied` re-raised.
           * **expired** — :class:`CloudDeviceCodeExpired` re-raised.
           * **cancelled** — ``should_cancel()`` returned True →
             :class:`DeviceEnrollmentCancelled`.

        The ``sleep`` parameter is dependency-injected so tests can pass
        a no-op without burning real wall time.
        """
        if not api_base_url:
            raise WorkstationSetupError("api_base_url is empty")
        host = host or host_slug()

        ensure_pychron_dirs()
        ensure_keypair(host)
        public_key = read_public_key(host)

        start = start_device_code(api_base_url, public_key, host)
        on_user_code(
            start.user_code,
            start.verification_url,
            start.verification_url_complete,
            start.expires_at,
        )

        interval = max(1, int(start.interval_seconds or 5))
        cancel = should_cancel or (lambda: False)
        transient_failures = 0

        while True:
            if cancel():
                raise DeviceEnrollmentCancelled("enrollment cancelled by user")
            try:
                success = poll_device_code(api_base_url, start.device_code)
            except CloudDeviceCodePending:
                transient_failures = 0
                sleep(interval)
                continue
            except CloudDeviceCodeDenied:
                raise
            except CloudDeviceCodeExpired:
                raise
            except CloudFingerprintRejected:
                raise
            except (CloudNetworkError, CloudAPIError) as exc:
                # 5xx / network blip during the mint rolls back the
                # device_code on the server (still approved + unconsumed),
                # so re-polling is the right move. Retry with the same
                # cadence; bail after ``_POLL_TRANSIENT_RETRY_LIMIT``
                # consecutive failures so a persistent outage doesn't
                # spin forever.
                transient_failures += 1
                if transient_failures > _POLL_TRANSIENT_RETRY_LIMIT:
                    logger.warning(
                        "device-code poll: %d consecutive transient failures, " "giving up: %s",
                        transient_failures,
                        exc,
                    )
                    raise
                logger.info(
                    "device-code poll transient failure %d/%d: %s",
                    transient_failures,
                    _POLL_TRANSIENT_RETRY_LIMIT,
                    exc,
                )
                sleep(interval)
                continue
            break

        if not success.api_token:
            raise WorkstationSetupError("server did not return an api_token")
        if not success.lab:
            raise WorkstationSetupError("server did not return a lab name")

        api_base_url = success.api_base_url or api_base_url
        setup = cls(
            api_base_url=api_base_url,
            api_token=success.api_token,
            lab_name=success.lab,
            host=host,
        )
        setup.database_url = success.database_url
        setup.database_role = success.database_role
        setup.database_iam = success.database_iam
        setup.default_metadata_repo = success.default_metadata_repo
        setup._persist_registration(success.ssh_key)
        setup._apply_ssh_config(success.ssh_key)

        # Stash the token in the OS keyring last. A failure here would
        # normally be silent (the helper logs + returns False), but in
        # the device-code flow the polling secret is single-use, so a
        # silent loss leaves the technician unable to recover. Raise a
        # typed error carrying the token on attributes (NOT in str())
        # so the UI can present it for manual capture without leaking
        # it to log files.
        if not keyring_set_token(success.lab, success.api_token):
            raise KeyringWriteFailedError(lab_name=success.lab, api_token=success.api_token)
        return setup

    # -- public entry --------------------------------------------------

    def run(self):
        """Run the full onboarding sequence. Returns the registration dict."""
        if not self.api_base_url:
            raise WorkstationSetupError("api_base_url is empty")
        if not self.api_token:
            raise WorkstationSetupError("api_token is empty")
        if not self.lab_name:
            raise WorkstationSetupError("lab_name is empty")

        ensure_pychron_dirs()
        ensure_keypair(self.host)
        registration = self._register_with_retry()
        self._persist_registration(registration)
        self._apply_ssh_config(registration)
        return registration.raw

    # -- steps ---------------------------------------------------------

    def _register_with_retry(self):
        public_key = read_public_key(self.host)
        title = "pychron-{}".format(self.host)
        try:
            return register_ssh_key(self.api_base_url, self.api_token, public_key, title=title)
        except CloudFingerprintRejected as exc:
            logger.warning("pychronAPI rejected key fingerprint, rotating local key: %s", exc)
            generate_keypair(self.host)
            public_key = read_public_key(self.host)
            return register_ssh_key(self.api_base_url, self.api_token, public_key, title=title)

    def _persist_registration(self, registration):
        path = registration_path()
        with open(path, "w") as f:
            json.dump(registration.raw, f, indent=2, sort_keys=True)
        if os.name == "posix":
            os.chmod(path, 0o600)

    def _apply_ssh_config(self, registration):
        if registration.known_hosts_line:
            append_known_hosts_line(registration.known_hosts_line)
        if registration.alias:
            from pychron.cloud.paths import known_hosts_path

            upsert_ssh_config_block(
                alias=registration.alias,
                real_host=registration.real_host,
                port=registration.port or 22,
                identity_file=default_key_path(self.host),
                known_hosts_file=known_hosts_path(),
            )

    # -- P6: re-onboard / revoke ---------------------------------------

    def reonboard(self):
        """Force-rotate the local keypair and re-register with pychronAPI.

        Server is expected to replace the prior row keyed by token (per
        plan / M3 server contract). The local SSH config block is
        rewritten to match whatever alias the server returns — handles
        the case where the lab's host alias changed too.
        """
        if not (self.api_base_url and self.api_token and self.lab_name):
            raise WorkstationSetupError("reonboard requires api_base_url, api_token, and lab_name")
        ensure_pychron_dirs()
        # Remove the previous SSH config block before regenerating so a
        # mid-flight failure leaves no stale alias pointing at a dead key.
        prior_alias = _alias_from_registration(load_registration())
        if prior_alias:
            remove_ssh_config_block(prior_alias)

        generate_keypair(self.host)
        registration = self._register_with_retry()
        self._persist_registration(registration)
        self._apply_ssh_config(registration)
        return registration.raw

    def revoke_and_wipe(self):
        """Revoke the server-side token then erase all local artifacts.

        Idempotent. A revoke failure is surfaced to the caller; local
        wipe still runs after a transport-level failure to avoid leaving
        the workstation half-onboarded.
        """
        revoke_error = None
        try:
            revoke_workstation_token(self.api_base_url, self.api_token)
        except CloudAPIError as exc:
            logger.warning("token revoke failed: %s", exc)
            revoke_error = exc

        wipe_local_state(self.host, registered_alias=None)

        if revoke_error is not None:
            raise revoke_error

    # -- helpers -------------------------------------------------------

    def public_key_path(self):
        return public_key_path(self.host)


def _alias_from_registration(reg):
    if not reg:
        return ""
    alias = (reg.get("ssh_host_alias") or {}).get("alias", "")
    return alias or ""


def wipe_local_state(host=None, registered_alias=None, wipe_projects=False):
    """Remove every artifact written by P2 (and optionally P4 clones).

    Used by ``revoke_and_wipe`` and by "Switch lab" (with
    ``wipe_projects=True``). The keyring token is *not* removed here —
    that lives next to the prefs / lab name and is the responsibility
    of the caller (the prefs pane) which knows the lab name.

    Parameters:
        host: hostname slug for the local key file. Defaults to the
            current machine.
        registered_alias: explicit alias to scrub from ``~/.ssh/config``.
            If absent, falls back to the alias in
            ``~/.pychron/registration.json``.
        wipe_projects: also delete ``~/Pychron/projects/`` (destructive
            "Switch lab" path).
    """
    host = host or host_slug()
    alias = registered_alias or _alias_from_registration(load_registration())

    # Local keypair.
    for path in (default_key_path(host), public_key_path(host)):
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                logger.warning("could not remove %s: %s", path, exc)

    # SSH config block.
    if alias:
        try:
            remove_ssh_config_block(alias)
        except OSError as exc:
            logger.warning("could not edit ssh config: %s", exc)

    # Pychron-scoped known_hosts: discard wholesale — it is only ever
    # populated by P2 and we cannot safely pick one line out of it
    # without the registration metadata (which we may have just deleted).
    if os.path.isfile(known_hosts_path()):
        try:
            os.remove(known_hosts_path())
        except OSError as exc:
            logger.warning("could not remove %s: %s", known_hosts_path(), exc)

    # Persisted registration + last-repo cache.
    if os.path.isfile(registration_path()):
        try:
            os.remove(registration_path())
        except OSError as exc:
            logger.warning("could not remove %s: %s", registration_path(), exc)

    last_repo = os.path.join(os.path.dirname(registration_path()), "last_repo.json")
    if os.path.isfile(last_repo):
        try:
            os.remove(last_repo)
        except OSError as exc:
            logger.warning("could not remove %s: %s", last_repo, exc)

    if wipe_projects and os.path.isdir(projects_dir()):
        import shutil

        try:
            shutil.rmtree(projects_dir())
        except OSError as exc:
            logger.warning("could not wipe %s: %s", projects_dir(), exc)


def switch_lab(host=None):
    """Destructive "Switch lab" wipe per plan P6.

    Removes the workstation keypair, ssh config block, known_hosts,
    persisted registration, last-repo cache, AND every per-repo clone
    under ``~/Pychron/projects/``. The caller is responsible for:

    1. Confirming the destructive intent with the user.
    2. Removing the keyring token entry for the *old* lab.
    3. Re-running the P1 → P2 → P3 sequence against the new lab.
    """
    wipe_local_state(host=host, wipe_projects=True)


def load_registration():
    """Return the persisted registration dict, or ``None`` if absent / unreadable."""
    path = registration_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (ValueError, OSError) as exc:
        logger.warning("could not read %s: %s", path, exc)
        return None


# ============= EOF =============================================
