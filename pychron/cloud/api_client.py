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
"""Minimal client for pychronAPI Forgejo workstation onboarding.

P1 only exposes ``whoami`` so the preferences pane can validate that the
user-supplied token can actually be used to register an SSH key. P2 will
add the ``ssh-keys`` registration call.
"""

from __future__ import absolute_import

import requests

from pychron.globals import globalv

DEFAULT_TIMEOUT = 10


class CloudAPIError(Exception):
    """Base error for pychronAPI calls."""


class CloudAuthError(CloudAPIError):
    """Token rejected (401)."""


class CloudPermissionError(CloudAPIError):
    """Token authenticated but lacks scope (403)."""


class CloudFingerprintRejected(CloudAPIError):
    """Server rejected the public key (e.g. duplicate fingerprint).

    Caller is expected to rotate the local keypair and retry.
    """


class CloudDeviceCodePending(CloudAPIError):
    """Device-code poll: admin has not approved yet (HTTP 425).

    Workstation should sleep ``interval_seconds`` and poll again.
    """


class CloudDeviceCodeDenied(CloudAPIError):
    """Device-code poll: admin explicitly denied the request (HTTP 403).

    Terminal — workstation must stop polling and ask the admin to start
    a new request.
    """


class CloudDeviceCodeExpired(CloudAPIError):
    """Device-code poll terminal failure (HTTP 410).

    Server collapses several lifecycle states into a uniform
    ``expired_token`` to deny enumeration oracles, so the client can't
    distinguish ``not_found`` / ``expired`` / ``already_consumed`` /
    ``lab_vanished`` / ``scope_mismatch`` either. Workstation must stop
    polling and start over.
    """


class CloudDeviceCodeMintFailed(CloudAPIError):
    """Device-code poll: server hit an internal error during mint (HTTP 500/502).

    The mint side-effect (bot creation, key registration) typically
    consumes the device_code even when it errors out, so re-polling
    just yields a 410. Treat as terminal so the UI can prompt for a
    fresh enrollment instead of burning the retry budget.
    """


class CloudNetworkError(CloudAPIError):
    """Transport-level failure (DNS, TCP, TLS, timeout, non-JSON body)."""


class WhoAmI(object):
    """Result of ``GET /api/v1/forgejo/whoami``."""

    __slots__ = ("kind", "scopes", "lab", "raw")

    def __init__(self, kind, scopes, lab, raw):
        self.kind = kind
        self.scopes = list(scopes or [])
        self.lab = lab
        self.raw = raw

    def has_scope(self, scope):
        return scope in self.scopes

    def can_register_ssh_key(self):
        return self.has_scope("workstations:register_ssh_key")


def _join(base_url, path):
    return base_url.rstrip("/") + path


def whoami(base_url, token, timeout=DEFAULT_TIMEOUT):
    """Call ``GET /api/v1/forgejo/whoami`` and return :class:`WhoAmI`.

    Raises :class:`CloudAuthError` on 401, :class:`CloudNetworkError` on
    transport/decode failure, and :class:`CloudAPIError` on any other
    non-2xx response.
    """
    if not base_url:
        raise CloudAPIError("api_base_url is empty")
    if not token:
        raise CloudAuthError("api_token is empty")

    url = _join(base_url, "/api/v1/forgejo/whoami")
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, verify=globalv.cert_file)
    except requests.RequestException as exc:
        raise CloudNetworkError("whoami transport failure: {}".format(exc))

    if resp.status_code == 401:
        raise CloudAuthError("token rejected (401)")
    if resp.status_code != 200:
        raise CloudAPIError("whoami returned HTTP {}: {}".format(resp.status_code, resp.text[:200]))

    try:
        body = resp.json()
    except ValueError as exc:
        raise CloudNetworkError("whoami returned non-JSON body: {}".format(exc))

    return WhoAmI(
        kind=body.get("kind", ""),
        scopes=body.get("scopes", []),
        lab=body.get("lab", ""),
        raw=body,
    )


class SSHKeyRegistration(object):
    """Result of ``POST /api/v1/forgejo/workstations/ssh-keys``.

    Mirrors the M3 server contract: the bot user is opaque to the
    workstation; the alias block is the only thing the client uses to
    rewrite ``~/.ssh/config``.
    """

    __slots__ = (
        "bot_username",
        "fingerprint",
        "default_metadata_repo",
        "ssh_host_alias",
        "raw",
    )

    def __init__(
        self,
        bot_username,
        fingerprint,
        default_metadata_repo,
        ssh_host_alias,
        raw,
    ):
        self.bot_username = bot_username
        self.fingerprint = fingerprint
        self.default_metadata_repo = default_metadata_repo
        self.ssh_host_alias = ssh_host_alias or {}
        self.raw = raw

    @property
    def alias(self):
        return self.ssh_host_alias.get("alias", "")

    @property
    def real_host(self):
        return self.ssh_host_alias.get("real_host", "")

    @property
    def port(self):
        return self.ssh_host_alias.get("port", 22)

    @property
    def known_hosts_line(self):
        return self.ssh_host_alias.get("known_hosts_line", "")


class Repository(object):
    """One row from ``GET /api/v1/forgejo/labs/{name}/repositories`` (P4)."""

    __slots__ = (
        "repository_identifier",
        "ssh_url",
        "https_url",
        "default_branch",
        "description",
        "raw",
    )

    def __init__(
        self,
        repository_identifier,
        ssh_url,
        https_url,
        default_branch="main",
        description="",
        raw=None,
    ):
        self.repository_identifier = repository_identifier
        self.ssh_url = ssh_url
        self.https_url = https_url
        self.default_branch = default_branch or "main"
        self.description = description or ""
        self.raw = raw or {}


def list_repositories(base_url, token, lab_name, timeout=DEFAULT_TIMEOUT):
    """GET ``/api/v1/forgejo/labs/{lab_name}/repositories``.

    Returns a list of :class:`Repository`. Server contract assumed (see
    plan note in ``docs/architecture/forgejo-cloud-onboarding.md`` —
    file as M9 prereq if missing).

    Maps ``404`` on the lab to an empty list rather than an exception so
    the UI can show a "no repos yet" state without distinguishing
    transport vs. empty.
    """
    if not base_url:
        raise CloudAPIError("api_base_url is empty")
    if not token:
        raise CloudAuthError("api_token is empty")
    if not lab_name:
        raise CloudAPIError("lab_name is empty")

    url = _join(base_url, "/api/v1/forgejo/labs/{}/repositories".format(lab_name))
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, verify=globalv.cert_file)
    except requests.RequestException as exc:
        raise CloudNetworkError("list_repositories transport failure: {}".format(exc))

    if resp.status_code == 401:
        raise CloudAuthError("token rejected (401)")
    if resp.status_code == 403:
        raise CloudPermissionError("token lacks scope to list repos (403)")
    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        raise CloudAPIError(
            "list_repositories returned HTTP {}: {}".format(resp.status_code, resp.text[:200])
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise CloudNetworkError("list_repositories returned non-JSON body: {}".format(exc))

    items = body.get("repositories", body) if isinstance(body, dict) else body
    if not isinstance(items, list):
        raise CloudNetworkError("list_repositories payload is not a list: {!r}".format(type(items)))

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            Repository(
                repository_identifier=item.get("repository_identifier", "") or item.get("name", ""),
                ssh_url=item.get("ssh_url", "") or item.get("clone_url_ssh", ""),
                https_url=item.get("https_url", "") or item.get("clone_url_https", ""),
                default_branch=item.get("default_branch", "main"),
                description=item.get("description", ""),
                raw=item,
            )
        )
    return out


def register_ssh_key(base_url, token, public_key, title=None, timeout=DEFAULT_TIMEOUT):
    """POST a workstation public key to pychronAPI.

    ``public_key`` must be a single OpenSSH-format line (``ssh-ed25519
    <base64> <comment>``). ``title`` is an optional server-side label
    for the key — defaults to the comment field of the public key.

    Maps server status codes to typed errors:

    - 200/201 → :class:`SSHKeyRegistration`
    - 401 → :class:`CloudAuthError`
    - 403 → :class:`CloudPermissionError`
    - 409/422 (duplicate / unusable key) → :class:`CloudFingerprintRejected`
    - other 4xx/5xx → :class:`CloudAPIError`
    - transport / non-JSON → :class:`CloudNetworkError`
    """
    if not base_url:
        raise CloudAPIError("api_base_url is empty")
    if not token:
        raise CloudAuthError("api_token is empty")
    if not public_key:
        raise CloudAPIError("public_key is empty")

    url = _join(base_url, "/api/v1/forgejo/workstations/ssh-keys")
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"public_key": public_key.strip()}
    if title:
        payload["title"] = title

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            verify=globalv.cert_file,
        )
    except requests.RequestException as exc:
        raise CloudNetworkError("ssh-key register transport failure: {}".format(exc))

    if resp.status_code == 401:
        raise CloudAuthError("token rejected (401)")
    if resp.status_code == 403:
        raise CloudPermissionError("token lacks workstations:register_ssh_key scope (403)")
    if resp.status_code in (409, 422):
        raise CloudFingerprintRejected(
            "server rejected key (HTTP {}): {}".format(resp.status_code, resp.text[:200])
        )
    if resp.status_code not in (200, 201):
        raise CloudAPIError(
            "ssh-key register returned HTTP {}: {}".format(resp.status_code, resp.text[:200])
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise CloudNetworkError("ssh-key register returned non-JSON body: {}".format(exc))

    return SSHKeyRegistration(
        bot_username=body.get("bot_username", ""),
        fingerprint=body.get("fingerprint", ""),
        default_metadata_repo=body.get("default_metadata_repo", ""),
        ssh_host_alias=body.get("ssh_host_alias") or {},
        raw=body,
    )


class DeviceCodeStart(object):
    """Result of ``POST /api/v1/forgejo/device-codes``.

    The ``device_code`` is the polling secret; the ``user_code`` is the
    short admin-typed code shown in the workstation UI alongside the
    ``verification_url``. Both plaintext fields are returned exactly
    once — only hashes are persisted server-side.
    """

    __slots__ = (
        "device_code",
        "user_code",
        "verification_url",
        "verification_url_complete",
        "expires_at",
        "interval_seconds",
        "raw",
    )

    def __init__(
        self,
        device_code,
        user_code,
        verification_url,
        verification_url_complete,
        expires_at,
        interval_seconds,
        raw,
    ):
        self.device_code = device_code
        self.user_code = user_code
        self.verification_url = verification_url
        self.verification_url_complete = verification_url_complete
        self.expires_at = expires_at
        self.interval_seconds = interval_seconds
        self.raw = raw


class DeviceCodePollSuccess(object):
    """Successful device-code poll. The minted ``api_token`` is plaintext
    and is returned exactly once; the caller must persist it to the OS
    keyring before losing the reference. ``ssh_key`` is the same shape
    that :func:`register_ssh_key` returns so the orchestrator can reuse
    the existing persist/apply path.

    ``database_iam`` carries a per-workstation Cloud SQL IAM bundle
    when the off-cluster admin tool has staged one via the bridge's
    bootstrap-only ``/internal/workstation-iam-credentials`` endpoint.
    Shape (dict): ``instance_connection_name``, ``database_name``,
    ``service_account_email``, ``service_account_key_json``,
    ``ip_type``. ``None`` means no bundle is pending — the workstation
    runs HTTP-only mode. The staging row is DELETED on this read; the
    SA key is not recoverable later.
    """

    __slots__ = (
        "api_token",
        "lab",
        "api_base_url",
        "default_metadata_repo",
        "ssh_host_alias",
        "ssh_key",
        "database_iam",
        "raw",
    )

    def __init__(
        self,
        api_token,
        lab,
        api_base_url,
        default_metadata_repo,
        ssh_host_alias,
        ssh_key,
        raw,
        database_iam=None,
    ):
        self.api_token = api_token
        self.lab = lab
        self.api_base_url = api_base_url
        self.default_metadata_repo = default_metadata_repo
        self.ssh_host_alias = ssh_host_alias or {}
        self.ssh_key = ssh_key
        self.database_iam = database_iam or None
        self.raw = raw


def start_device_code(base_url, public_key, hostname, timeout=DEFAULT_TIMEOUT):
    """POST a workstation public key to start a device-code grant.

    Endpoint is unauthenticated. Maps:

    - 201 → :class:`DeviceCodeStart`
    - 400 → :class:`CloudFingerprintRejected` (malformed pubkey)
    - other 4xx/5xx → :class:`CloudAPIError`
    - transport / non-JSON → :class:`CloudNetworkError`
    """
    if not base_url:
        raise CloudAPIError("api_base_url is empty")
    if not public_key:
        raise CloudAPIError("public_key is empty")
    if not hostname:
        raise CloudAPIError("hostname is empty")

    url = _join(base_url, "/api/v1/forgejo/device-codes")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"public_key": public_key.strip(), "hostname": hostname}

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            verify=globalv.cert_file,
        )
    except requests.RequestException as exc:
        raise CloudNetworkError("device-code start transport failure: {}".format(exc))

    if resp.status_code == 400:
        raise CloudFingerprintRejected("server rejected key (HTTP 400): {}".format(resp.text[:200]))
    if resp.status_code != 201:
        raise CloudAPIError(
            "device-code start returned HTTP {}: {}".format(resp.status_code, resp.text[:200])
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise CloudNetworkError("device-code start returned non-JSON body: {}".format(exc))

    # Strip the secret from `raw` before exposing it. Callers who
    # serialize DeviceCodeStart.raw for debugging would otherwise leak
    # both the device_code (polling secret) and user_code into logs/disk.
    safe_raw = {k: v for k, v in body.items() if k not in ("device_code", "user_code")}
    return DeviceCodeStart(
        device_code=body.get("device_code", ""),
        user_code=body.get("user_code", ""),
        verification_url=body.get("verification_url", ""),
        verification_url_complete=body.get("verification_url_complete", ""),
        expires_at=body.get("expires_at", ""),
        interval_seconds=int(body.get("interval_seconds") or 5),
        raw=safe_raw,
    )


def poll_device_code(base_url, device_code, timeout=DEFAULT_TIMEOUT):
    """Poll a device-code grant. Unauthenticated — the device_code is the credential.

    Maps:

    - 200 → :class:`DeviceCodePollSuccess`
    - 425 → :class:`CloudDeviceCodePending` (keep polling)
    - 403 → :class:`CloudDeviceCodeDenied` (terminal — admin denied)
    - 410 → :class:`CloudDeviceCodeExpired` (terminal — uniform server response
      for not-found / expired / already-consumed / lab-vanished /
      scope-mismatch)
    - 400 → :class:`CloudFingerprintRejected`
    - other 4xx/5xx → :class:`CloudAPIError`
    - transport / non-JSON → :class:`CloudNetworkError`
    """
    if not base_url:
        raise CloudAPIError("api_base_url is empty")
    if not device_code:
        raise CloudAPIError("device_code is empty")

    url = _join(base_url, "/api/v1/forgejo/device-codes/poll")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"device_code": device_code}

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            verify=globalv.cert_file,
        )
    except requests.RequestException as exc:
        raise CloudNetworkError("device-code poll transport failure: {}".format(exc))

    if resp.status_code == 425:
        raise CloudDeviceCodePending("authorization_pending")
    if resp.status_code == 403:
        raise CloudDeviceCodeDenied("access_denied")
    if resp.status_code == 410:
        raise CloudDeviceCodeExpired("expired_token")
    if resp.status_code == 400:
        raise CloudFingerprintRejected("server rejected key (HTTP 400): {}".format(resp.text[:200]))
    if resp.status_code in (500, 502):
        raise CloudDeviceCodeMintFailed(
            "device-code poll returned HTTP {} (mint failure): {}".format(
                resp.status_code, resp.text[:200]
            )
        )
    if resp.status_code != 200:
        raise CloudAPIError(
            "device-code poll returned HTTP {}: {}".format(resp.status_code, resp.text[:200])
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise CloudNetworkError("device-code poll returned non-JSON body: {}".format(exc))

    ssh_key_payload = body.get("ssh_key") or {}
    ssh_key = SSHKeyRegistration(
        bot_username=ssh_key_payload.get("bot_username", ""),
        fingerprint=ssh_key_payload.get("fingerprint", ""),
        default_metadata_repo=ssh_key_payload.get("default_metadata_repo", ""),
        ssh_host_alias=ssh_key_payload.get("ssh_host_alias") or body.get("ssh_host_alias") or {},
        raw=ssh_key_payload,
    )

    # Strip the plaintext token AND the database_iam bundle (which
    # embeds a service-account private key) from `raw` before
    # exposing it. Callers who serialize `raw` for debugging would
    # otherwise leak both the bearer secret and the SA key into
    # logs/disk.
    safe_raw = {k: v for k, v in body.items() if k not in ("api_token", "database_iam")}

    return DeviceCodePollSuccess(
        api_token=body.get("api_token", ""),
        lab=body.get("lab", ""),
        api_base_url=body.get("api_base_url", "") or base_url,
        default_metadata_repo=body.get("default_metadata_repo"),
        ssh_host_alias=body.get("ssh_host_alias") or {},
        ssh_key=ssh_key,
        raw=safe_raw,
        database_iam=body.get("database_iam") or None,
    )


def revoke_workstation_token(base_url, token, timeout=DEFAULT_TIMEOUT):
    """Revoke the calling token via ``DELETE /api/v1/forgejo/tokens/self``.

    Server cascades the revocation to the registered SSH key (M8 reaper).
    Returns True on a 2xx; treats 401 / 404 as already-revoked (idempotent
    revoke) and returns True so the caller can proceed with local
    cleanup. Other non-2xx → :class:`CloudAPIError`.
    """
    if not base_url:
        raise CloudAPIError("api_base_url is empty")
    if not token:
        # Nothing to revoke — treat as success so the caller can still
        # wipe local state.
        return True

    url = _join(base_url, "/api/v1/forgejo/tokens/self")
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Accept": "application/json",
    }
    try:
        resp = requests.delete(url, headers=headers, timeout=timeout, verify=globalv.cert_file)
    except requests.RequestException as exc:
        raise CloudNetworkError("revoke transport failure: {}".format(exc))

    if 200 <= resp.status_code < 300:
        return True
    if resp.status_code in (401, 404):
        # Token already invalid or unknown — server-side state is what
        # we wanted anyway.
        return True
    raise CloudAPIError("revoke returned HTTP {}: {}".format(resp.status_code, resp.text[:200]))


# ============= EOF =============================================
