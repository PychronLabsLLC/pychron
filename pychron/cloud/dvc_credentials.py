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
"""DVC connection-prefs persistence for device-flow enrollment.

After a successful device-code poll the workstation receives a
``database_url`` of the form
``postgresql://role:password@host:port/dbname``. This module parses
that URL and writes the result as a ``DVCConnectionItem`` favorite to
the ``pychron.dvc.connection`` Envisage preference node so the next
DVC startup picks up the new credentials without any manual paste.

Kept as pure functions on the Envisage prefs adapter so the unit tests
can exercise the CSV / favorites round-trip without spinning up the
full Traits / Envisage stack.
"""

from __future__ import absolute_import

import logging
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


# Order MUST match DVCConnectionItem.attributes in
# pychron/dvc/tasks/dvc_preferences.py. CSV is positional — we cannot
# pass kwargs to the on-disk format.
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

# Sentinel used to mark favorites added by the device-flow path so a
# re-enrollment for the same lab REPLACES rather than stacking entries.
CLOUD_FAV_PREFIX = "cloud-"


class DatabaseUrlParseError(ValueError):
    """Raised when ``database_url`` cannot be parsed into the fields a
    ``DVCConnectionItem`` needs."""


def parse_database_url(url):
    """Parse a ``postgresql://`` URL into the components a
    ``DVCConnectionItem`` needs.

    Returns a dict with keys ``host``, ``port`` (int or None),
    ``username``, ``password``, ``dbname``. Percent-encoded userinfo
    components (per RFC 3986) are decoded so the workstation gets the
    raw password the server-side admin tool actually generated.

    Raises :class:`DatabaseUrlParseError` on malformed input — the
    caller is expected to fall back to leaving prefs unchanged so the
    technician is not silently locked out.
    """
    if not url:
        raise DatabaseUrlParseError("empty url")
    parts = urlparse(url)
    if parts.scheme not in ("postgresql", "postgres"):
        raise DatabaseUrlParseError("expected postgresql:// scheme, got {!r}".format(parts.scheme))
    if not parts.hostname:
        raise DatabaseUrlParseError("url is missing host")
    dbname = parts.path.lstrip("/") if parts.path else ""
    if not dbname:
        raise DatabaseUrlParseError("url is missing database name")
    return {
        "host": parts.hostname,
        "port": parts.port,
        "username": unquote(parts.username) if parts.username else "",
        "password": unquote(parts.password) if parts.password else "",
        "dbname": dbname,
    }


def _row_to_csv(values):
    """Join the favorite's positional fields with commas. Mirrors
    :func:`pychron.core.helpers.strtools.to_csv_str` so the resulting
    CSV round-trips through ``DVCConnectionItem.__init__(attrs=...)``.

    A password that contains a literal comma would corrupt the CSV.
    The pychronAPI admin CLI uses a ``[a-zA-Z0-9]`` alphabet so this
    cannot happen for credentials minted via the device flow, but we
    raise loudly if it ever does so the caller knows the favorite is
    unsafe to write.
    """
    out = []
    for attr, value in zip(_DVC_CONNECTION_ATTRS, values):
        s = "" if value is None else str(value)
        if "," in s:
            raise DatabaseUrlParseError(
                "{} contains a literal comma which would corrupt the "
                "CSV-encoded favorites preference".format(attr)
            )
        out.append(s)
    return ",".join(out)


def build_dvc_connection_csv(
    parsed,
    name,
    organization="",
    meta_repo_name="",
    meta_repo_dir="",
    repository_root="",
):
    """Serialize a parsed ``database_url`` as a positional-CSV row that
    ``DVCConnectionItem(attrs=<csv>)`` can re-hydrate.

    Marked ``enabled=True`` and ``default=True`` so the next DVC
    startup picks the new entry without further user action.
    """
    if "host" not in parsed:
        raise DatabaseUrlParseError("parsed url is missing host")
    # DVCConnectionItem has no separate port attribute — the SQLAlchemy
    # URL builder in pychron/database/core/database_adapter.py:557
    # interpolates ``host`` directly into the connection string, so
    # encode port as ``host:port``. Skipping the port silently demotes
    # everything to the dialect default (5432 for postgresql) which
    # corrupts connections to non-default Cloud SQL ports.
    host = parsed.get("host", "")
    port = parsed.get("port")
    if host and port:
        host = "{}:{}".format(host, port)
    values = [
        name,  # name
        "postgresql",  # kind
        parsed.get("username", ""),  # username
        host,  # host (host[:port])
        parsed.get("dbname", ""),  # dbname
        parsed.get("password", ""),  # password
        "True",  # enabled
        "True",  # default
        "",  # path  (sqlite-only)
        organization,  # organization
        meta_repo_name,  # meta_repo_name
        meta_repo_dir,  # meta_repo_dir
        "5",  # timeout
        repository_root,  # repository_root
        "direct",  # connection_method
        "",  # cloudsql_instance_connection_name
        "public",  # cloudsql_ip_type
        "",  # cloudsql_service_account_email
        "",  # cloudsql_service_account_key_path
    ]
    return _row_to_csv(values)


def _favorite_name(row):
    """First field of a favorites CSV is the user-visible name. Used to
    de-duplicate when re-enrolling the same lab."""
    if not row:
        return ""
    return row.split(",", 1)[0]


def merge_dvc_connection_favorites(existing, new_row, replace_name):
    """Return the new favorites list with ``replace_name`` (if any
    matching row exists) replaced by ``new_row``, or with ``new_row``
    appended otherwise. Existing rows whose name matches but is not the
    replacement target are left alone — the user may have set up other
    connections by hand.

    Also strips the ``default=True`` flag from any other row that had
    it, since CSV position 8 (zero-indexed 7) is ``default``. We only
    want one default favorite at a time.
    """
    out = []
    replaced = False
    new_default = _row_field(new_row, 7) == "True"
    for row in existing or []:
        name = _favorite_name(row)
        if name == replace_name:
            out.append(new_row)
            replaced = True
            continue
        if new_default:
            row = _row_set_field(row, 7, "False")
        out.append(row)
    if not replaced:
        out.append(new_row)
    return out


def _row_field(row, idx):
    parts = row.split(",")
    if idx < len(parts):
        return parts[idx]
    return ""


def _row_set_field(row, idx, value):
    """Set the ``idx``-th comma-separated field of ``row`` to ``value``,
    extending the row with empty fields if it is shorter than ``idx``.

    Older saved favorites may have been written before
    ``DVCConnectionItem.attributes`` grew its current set of fields,
    so a short row is the common case rather than an exception.
    Silently dropping the update would leave a stale ``default=True``
    on a prior favorite when re-enrolling, demoting the new
    cloud-minted credential to non-default and breaking the
    no-manual-paste contract.
    """
    parts = row.split(",")
    while len(parts) <= idx:
        parts.append("")
    parts[idx] = value
    return ",".join(parts)


def apply_db_credentials_to_prefs(
    preferences,
    database_url,
    database_role=None,
    lab_name="",
    organization="",
    meta_repo_name="",
    meta_repo_dir="",
    repository_root="",
):
    """Write a parsed ``database_url`` into the
    ``pychron.dvc.connection.favorites`` pref node as a new (or
    replacing) ``DVCConnectionItem`` favorite.

    ``preferences`` is the Envisage preferences adapter -- anything
    with ``get(key, default=None)``, ``set(key, value)``, and
    ``flush()``. Tests pass a fake.

    Returns the canonical favorite name on success, or ``None`` when
    there is no credential to apply (``database_url`` is falsy).
    """
    if not database_url:
        return None
    parsed = parse_database_url(database_url)
    name = _favorite_name_for_lab(lab_name)
    new_row = build_dvc_connection_csv(
        parsed,
        name=name,
        organization=organization,
        meta_repo_name=meta_repo_name,
        meta_repo_dir=meta_repo_dir,
        repository_root=repository_root,
    )

    raw = preferences.get("pychron.dvc.connection.favorites", "") or ""
    existing = _split_favorites(raw)
    merged = merge_dvc_connection_favorites(existing, new_row, replace_name=name)
    preferences.set("pychron.dvc.connection.favorites", _join_favorites(merged))
    preferences.flush()
    logger.info(
        "applied DVC connection favorite name=%s host=%s db=%s role=%s",
        name,
        parsed.get("host", ""),
        parsed.get("dbname", ""),
        database_role or parsed.get("username", ""),
    )
    return name


def _favorite_name_for_lab(lab_name):
    safe = "".join(c for c in (lab_name or "default") if c.isalnum() or c in "-_")
    return "{}{}".format(CLOUD_FAV_PREFIX, safe or "default")


def _split_favorites(raw):
    """Envisage stores a List trait as a Python-repr-ish string. The
    ``FavoritesPreferencesHelper`` round-trips through
    ``self.favorites = [...]`` which Envisage serializes / deserializes
    on its own. When we read raw via ``preferences.get(...)`` we may
    see either a list (already deserialized) or a string we must
    parse.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        # Envisage's PreferencesHelper writes List traits as
        # repr-like strings — try literal_eval first.
        try:
            import ast

            parsed = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return [s]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [s]
    return [str(raw)]


def _join_favorites(items):
    """Inverse of :func:`_split_favorites`. Envisage will store this
    string into the preferences node and re-deserialize it on read."""
    return repr(list(items))
