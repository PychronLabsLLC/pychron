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
"""DVC connection-prefs persistence for device-flow Cloud SQL IAM creds.

After a successful device-code poll the workstation receives a
``database_iam`` dict shaped::

    {
        "instance_connection_name": "project:region:instance",
        "database_name": "nmgrl",
        "service_account_email": "wkstn-x@project.iam.gserviceaccount.com",
        "service_account_key_json": "<full SA key file content>",
        "ip_type": "public" | "private" | "psc",
    }

This module:

  1. Writes ``service_account_key_json`` to
     ``~/.pychron/keys/cloudsql_<lab>.json`` with 0600 permissions on
     POSIX (Windows has no POSIX mode bits).
  2. Writes a ``DVCConnectionItem`` favorite to the
     ``pychron.dvc.connection`` Envisage preference node with
     ``connection_method=cloudsql_iam`` + the four ``cloudsql_*``
     fields populated. ``username`` / ``password`` are left empty —
     the Cloud SQL Python Connector exchanges the SA key for a
     short-lived OAuth token at every connect.

Pure-function helpers exposed for unit testing without spinning up
the full Traits / Envisage stack.
"""

from __future__ import absolute_import

import ast
import json
import logging
import os

from pychron.cloud.paths import cloudsql_key_path, ensure_pychron_dirs

logger = logging.getLogger(__name__)


# Order MUST match DVCConnectionItem.attributes in
# pychron/dvc/tasks/dvc_preferences.py. CSV is positional.
_DVC_CONNECTION_ATTRS = (
    "name",
    "kind",
    "username",
    "host",
    "dbname",
    "password",
    "enabled",
    "default",
    "path",
    "organization",
    "meta_repo_name",
    "meta_repo_dir",
    "timeout",
    "repository_root",
    "connection_method",
    "cloudsql_instance_connection_name",
    "cloudsql_ip_type",
    "cloudsql_service_account_email",
    "cloudsql_service_account_key_path",
)

# Sentinel name prefix used to mark favorites added by the device-flow
# IAM path. Re-enrolling the same lab REPLACES the prior cloud-* row.
CLOUD_FAV_PREFIX = "cloud-"

# CloudSQL routing modes per DVCConnectionItem.cloudsql_ip_type Enum.
_VALID_IP_TYPES = ("public", "private", "psc")


class IamCredentialsError(Exception):
    """Raised when an IAM bundle cannot be applied to prefs."""


def _validate_iam_bundle(bundle):
    """Lightweight shape check on the bridge response. Mirrors the
    server's pydantic validators so a malformed bundle fails fast on
    the client rather than landing a half-configured DVC favorite."""
    if not isinstance(bundle, dict):
        raise IamCredentialsError("database_iam payload is not a dict")
    for key in (
        "instance_connection_name",
        "database_name",
        "service_account_email",
        "service_account_key_json",
    ):
        v = bundle.get(key)
        if not isinstance(v, str) or not v:
            raise IamCredentialsError("database_iam is missing required field {}".format(key))
    ip_type = bundle.get("ip_type", "public") or "public"
    if ip_type not in _VALID_IP_TYPES:
        raise IamCredentialsError(
            "database_iam ip_type {!r} is not one of {}".format(ip_type, _VALID_IP_TYPES)
        )
    # Verify the SA key file looks plausible — same surface the server
    # validates. A workstation that writes a malformed SA key to disk
    # cannot connect to Cloud SQL anyway, and the failure will be
    # easier to diagnose at enrollment than at first DVC startup.
    try:
        key_payload = json.loads(bundle["service_account_key_json"])
    except json.JSONDecodeError as exc:
        raise IamCredentialsError(
            "database_iam service_account_key_json is not valid JSON: {}".format(exc)
        )
    if not isinstance(key_payload, dict) or key_payload.get("type") != "service_account":
        raise IamCredentialsError(
            "database_iam service_account_key_json is not a service_account key"
        )
    if (key_payload.get("client_email") or "").lower() != bundle["service_account_email"].lower():
        raise IamCredentialsError(
            "database_iam SA key client_email does not match service_account_email"
        )


def write_sa_key_file(lab_name, key_json):
    """Persist ``key_json`` to ``~/.pychron/keys/cloudsql_<lab>.json``.

    Returns the absolute path on success. Raises :class:`OSError`
    propagated from the filesystem on failure. The file is written
    with 0600 permissions on POSIX so it isn't world-readable. On
    Windows POSIX mode bits don't apply; the file inherits parent
    ACLs (the keys directory is created via ``ensure_pychron_dirs``
    which the caller is responsible for).
    """
    ensure_pychron_dirs()
    path = cloudsql_key_path(lab_name)
    # Atomic-ish write: write to temp then replace, so a crash mid-
    # write doesn't leave a partially-written key.
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(key_json)
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _row_to_csv(values):
    out = []
    for attr, value in zip(_DVC_CONNECTION_ATTRS, values):
        s = "" if value is None else str(value)
        if "," in s:
            raise IamCredentialsError(
                "{} contains a literal comma which would corrupt the "
                "CSV-encoded favorites preference".format(attr)
            )
        out.append(s)
    return ",".join(out)


def build_iam_dvc_csv(
    bundle,
    name,
    sa_key_file_path,
    organization="",
    meta_repo_name="",
    meta_repo_dir="",
    repository_root="",
):
    """Serialize an IAM bundle as a positional CSV row that
    ``DVCConnectionItem(attrs=<csv>, load_names=False)`` rehydrates.

    ``connection_method`` is set to ``cloudsql_iam``; ``username`` and
    ``password`` are empty (Cloud SQL Connector handles auth via the
    SA key). Marked ``enabled=True`` and ``default=True`` so the next
    DVC startup picks the new entry without further user action.
    """
    values = [
        name,  # name
        "postgresql",  # kind
        "",  # username (unused for IAM)
        "",  # host (unused for IAM)
        bundle["database_name"],  # dbname
        "",  # password (unused for IAM)
        "True",  # enabled
        "True",  # default
        "",  # path (sqlite-only)
        organization,  # organization
        meta_repo_name,  # meta_repo_name
        meta_repo_dir,  # meta_repo_dir
        "5",  # timeout
        repository_root,  # repository_root
        "cloudsql_iam",  # connection_method
        bundle["instance_connection_name"],  # cloudsql_instance_connection_name
        bundle.get("ip_type", "public") or "public",  # cloudsql_ip_type
        bundle["service_account_email"],  # cloudsql_service_account_email
        sa_key_file_path,  # cloudsql_service_account_key_path
    ]
    return _row_to_csv(values)


def _favorite_name_for_lab(lab_name):
    safe = "".join(c for c in (lab_name or "default") if c.isalnum() or c in "-_")
    return "{}{}".format(CLOUD_FAV_PREFIX, safe or "default")


def _row_field(row, idx):
    parts = row.split(",")
    if idx < len(parts):
        return parts[idx]
    return ""


def _row_set_field(row, idx, value):
    """Set the ``idx``-th comma-separated field, extending short rows
    with empty fields. A silent no-op on short rows would leave a
    stale ``default=True`` flag on legacy favorites and demote the
    new cloud-minted entry to non-default.
    """
    parts = row.split(",")
    while len(parts) <= idx:
        parts.append("")
    parts[idx] = value
    return ",".join(parts)


def _favorite_name(row):
    if not row:
        return ""
    return row.split(",", 1)[0]


def merge_iam_dvc_favorites(existing, new_row, replace_name):
    """Replace any row whose name == ``replace_name``, otherwise
    append. Demotes any other ``default=True`` favorite so only one
    default is active at a time.
    """
    out = []
    replaced = False
    new_default = _row_field(new_row, 7) == "True"
    for row in existing or []:
        if _favorite_name(row) == replace_name:
            out.append(new_row)
            replaced = True
            continue
        if new_default:
            row = _row_set_field(row, 7, "False")
        out.append(row)
    if not replaced:
        out.append(new_row)
    return out


def _split_favorites(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            parsed = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return [s]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [s]
    return [str(raw)]


def _join_favorites(items):
    return repr(list(items))


def apply_iam_credentials_to_prefs(
    preferences,
    bundle,
    lab_name="",
    organization="",
    meta_repo_name="",
    meta_repo_dir="",
    repository_root="",
):
    """End-to-end: validate bundle, write SA key file, push a
    ``cloudsql_iam`` DVCConnectionItem favorite into
    ``pychron.dvc.connection.favorites``.

    Returns the canonical favorite name on success, or ``None`` when
    there is no bundle to apply (``bundle`` is falsy / empty dict).

    Raises :class:`IamCredentialsError` on a malformed bundle so the
    caller can show the technician a clear failure rather than
    silently writing a half-configured favorite.
    """
    if not bundle:
        logger.info("apply_iam_credentials_to_prefs: no bundle, no-op")
        return None
    logger.info(
        "apply_iam_credentials_to_prefs: lab=%s organization=%s "
        "meta_repo_name=%s meta_repo_dir=%s repository_root=%s "
        "bundle_keys=%s",
        lab_name,
        organization,
        meta_repo_name,
        meta_repo_dir,
        repository_root,
        sorted(bundle.keys()),
    )
    _validate_iam_bundle(bundle)
    logger.info("apply_iam_credentials_to_prefs: bundle validated")
    name = _favorite_name_for_lab(lab_name)
    sa_path = write_sa_key_file(lab_name, bundle["service_account_key_json"])
    logger.info("apply_iam_credentials_to_prefs: SA key written to %s", sa_path)
    new_row = build_iam_dvc_csv(
        bundle,
        name=name,
        sa_key_file_path=sa_path,
        organization=organization,
        meta_repo_name=meta_repo_name,
        meta_repo_dir=meta_repo_dir,
        repository_root=repository_root,
    )

    raw = preferences.get("pychron.dvc.connection.favorites", "") or ""
    existing = _split_favorites(raw)
    logger.info(
        "apply_iam_credentials_to_prefs: %d existing favorite(s), " "replace_name=%s, raw_len=%d",
        len(existing),
        name,
        len(raw) if isinstance(raw, str) else -1,
    )
    merged = merge_iam_dvc_favorites(existing, new_row, replace_name=name)
    serialized = _join_favorites(merged)
    preferences.set("pychron.dvc.connection.favorites", serialized)
    preferences.flush()
    # Read back to confirm the write actually landed (envisage's
    # preferences node is single-threaded but a buggy backing store
    # would silently no-op the set).
    readback = preferences.get("pychron.dvc.connection.favorites", "") or ""
    if readback != serialized:
        logger.warning(
            "apply_iam_credentials_to_prefs: readback mismatch — "
            "wrote %d chars, read back %d chars",
            len(serialized),
            len(readback) if isinstance(readback, str) else -1,
        )
    logger.info(
        "applied DVC IAM favorite name=%s instance=%s db=%s sa=%s " "(favorites count: %d -> %d)",
        name,
        bundle["instance_connection_name"],
        bundle["database_name"],
        bundle["service_account_email"],
        len(existing),
        len(merged),
    )
    return name
