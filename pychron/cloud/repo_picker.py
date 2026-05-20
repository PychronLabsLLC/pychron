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
"""Repo picker model for Pychron Cloud "Open Project" (M7 P4).

Headless model: fetches the lab's repo list from pychronAPI, filters
client-side, and clones the chosen repo through the workstation SSH
alias. Wired to a Traits view in a follow-up; the logic is kept here so
it can be unit-tested without a UI.
"""

from __future__ import absolute_import

import json
import logging
import os

from pychron.cloud.api_client import list_repositories
from pychron.cloud.paths import pychron_dir
from pychron.cloud.projects import clone_or_pull
from pychron.cloud.workstation_setup import load_registration

logger = logging.getLogger(__name__)


def _last_repo_cache_path():
    return os.path.join(pychron_dir(), "last_repo.json")


def load_last_repo():
    """Return the most recently opened repo identifier, or empty string."""
    path = _last_repo_cache_path()
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r") as f:
            return json.load(f).get("repository_identifier", "") or ""
    except (ValueError, OSError):
        return ""


def save_last_repo(repository_identifier):
    """Persist the repo identifier so the picker can pre-select it."""
    if not repository_identifier:
        return
    os.makedirs(pychron_dir(), exist_ok=True)
    path = _last_repo_cache_path()
    with open(path, "w") as f:
        json.dump({"repository_identifier": repository_identifier}, f)
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


class RepoPicker(object):
    """Model for the "Open Project" picker.

    The picker is intentionally stateless beyond what is needed for one
    open: a fresh instance per "Open Project" invocation is the expected
    usage pattern.
    """

    def __init__(self, api_base_url, api_token, lab_name, alias=None):
        self.api_base_url = api_base_url
        self.api_token = api_token
        self.lab_name = lab_name
        self._alias = alias

    @property
    def alias(self):
        if self._alias:
            return self._alias
        # Fall back to the stored registration so the caller doesn't have
        # to thread the alias through the prefs pane.
        reg = load_registration() or {}
        return (reg.get("ssh_host_alias") or {}).get("alias", "")

    def fetch(self):
        """Return the list of :class:`Repository` for the configured lab."""
        return list_repositories(self.api_base_url, self.api_token, self.lab_name)

    def open(self, repository):
        """Clone or pull ``repository`` into ``~/Pychron/projects/<name>``.

        ``repository`` may be a :class:`Repository` or a plain dict with
        ``repository_identifier`` and ``ssh_url`` keys.
        """
        if hasattr(repository, "repository_identifier"):
            name = repository.repository_identifier
            ssh_url = repository.ssh_url
            branch = repository.default_branch
        else:
            name = repository.get("repository_identifier", "")
            ssh_url = repository.get("ssh_url", "")
            branch = repository.get("default_branch", "main")

        path = clone_or_pull(name, ssh_url, self.alias, branch=branch)
        save_last_repo(name)
        return path


# ============= EOF =============================================
