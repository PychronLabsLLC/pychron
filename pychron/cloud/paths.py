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
"""Filesystem layout for the Pychron Cloud workstation onboarding (M7).

| Path                                | Purpose                              |
|-------------------------------------|--------------------------------------|
| ``~/.pychron/keys/pychron_<host>``  | ed25519 private key, mode 0600       |
| ``~/.pychron/keys/pychron_<host>.pub`` | public key                       |
| ``~/.pychron/known_hosts``          | scoped known_hosts file              |
| ``~/.pychron/registration.json``    | last server response (idempotency)   |
| ``~/.ssh/config``                   | system SSH config (block-managed)    |

All paths root at the user's home directory so re-onboarding is purely
local-state surgery; nothing in :mod:`pychron.paths.appdata_dir` is
touched. Cross-platform: ``os.path.expanduser`` resolves ``~`` to
``%USERPROFILE%`` on Windows and ``$HOME`` elsewhere.
"""

from __future__ import absolute_import

import os
import socket


def pychron_dir():
    return os.path.expanduser(os.path.join("~", ".pychron"))


def projects_dir():
    """Return ``~/Pychron/projects`` — root for per-repo DVC clones (P4)."""
    return os.path.expanduser(os.path.join("~", "Pychron", "projects"))


def project_clone_path(repo_name):
    return os.path.join(projects_dir(), repo_name)


def keys_dir():
    return os.path.join(pychron_dir(), "keys")


def known_hosts_path():
    return os.path.join(pychron_dir(), "known_hosts")


def registration_path():
    return os.path.join(pychron_dir(), "registration.json")


def ssh_config_path():
    return os.path.expanduser(os.path.join("~", ".ssh", "config"))


def host_slug():
    """Return a filesystem-safe slug derived from the local hostname."""
    raw = socket.gethostname() or "workstation"
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in raw)


def key_path(host=None):
    h = host or host_slug()
    return os.path.join(keys_dir(), "pychron_{}".format(h))


def public_key_path(host=None):
    return key_path(host) + ".pub"


def cloudsql_key_path(lab):
    """Path to the per-lab Cloud SQL service-account JSON key file.

    Lab name is filesystem-sanitized so a hostile / weird lab string
    cannot escape the keys directory. Falls back to ``default`` when
    no lab is supplied.
    """
    safe = "".join(c for c in (lab or "default") if c.isalnum() or c in "-_") or "default"
    return os.path.join(keys_dir(), "cloudsql_{}.json".format(safe))


def ensure_pychron_dirs():
    """Create ``~/.pychron`` and ``~/.pychron/keys`` if missing.

    The keys directory is locked down to mode 0700 on POSIX so secrets
    are not world-readable even before the keypair is written. No-op on
    Windows where POSIX mode bits do not apply.
    """
    pdir = pychron_dir()
    kdir = keys_dir()
    os.makedirs(kdir, exist_ok=True)
    if os.name == "posix":
        os.chmod(pdir, 0o700)
        os.chmod(kdir, 0o700)
    return kdir


# ============= EOF =============================================
