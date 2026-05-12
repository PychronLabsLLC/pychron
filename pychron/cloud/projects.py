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
"""Project (DVC repo) clone / pull manager for Pychron Cloud (M7 P4).

Per the M7 plan, per-project DVC clones live under
``~/Pychron/projects/<repo>``. Clone is via ``pychron-<lab>:owner/repo.git``
so transport reuses the SSH alias dropped by P2; no per-repo auth.

The functions here are deliberately thin wrappers around git so the
heavy lifting stays in :mod:`git` (already a dependency). This module
owns:

- destination path resolution
- "is this directory a clone of the right remote" check
- clone-or-pull idempotency
"""

from __future__ import absolute_import

import logging
import os

from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from pychron.cloud.paths import project_clone_path, projects_dir
from pychron.cloud.url_rewrite import rewrite_to_alias

logger = logging.getLogger(__name__)


class ProjectCloneError(Exception):
    """Raised when a clone or pull cannot complete."""


def ensure_projects_dir():
    pdir = projects_dir()
    os.makedirs(pdir, exist_ok=True)
    return pdir


def is_clone_of(path, expected_url):
    """Return True if ``path`` is a git repo whose origin matches ``expected_url``.

    Compared as raw strings — the caller is responsible for normalizing
    URLs (e.g. via :func:`rewrite_to_alias`) before passing them in.
    """
    try:
        repo = Repo(path)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False
    try:
        origin = repo.remote("origin")
    except ValueError:
        return False
    urls = list(origin.urls)
    return expected_url in urls


def clone_or_pull(repo_name, ssh_url, alias, branch=None):
    """Ensure ``~/Pychron/projects/<repo_name>`` is a clone of ``ssh_url``.

    The URL is rewritten through ``alias`` so transport rides the
    workstation's ``Host pychron-<lab>`` SSH config block.

    Behaviour:

    - Missing destination → clone.
    - Existing clone with matching origin → pull (fast-forward).
    - Existing clone with mismatched origin → :class:`ProjectCloneError`.
    - Existing path that is not a git repo → :class:`ProjectCloneError`.

    Returns the local clone path on success.
    """
    if not repo_name:
        raise ProjectCloneError("repo_name is empty")
    if not ssh_url:
        raise ProjectCloneError("ssh_url is empty")

    rewritten = rewrite_to_alias(ssh_url, alias)
    dest = project_clone_path(repo_name)
    ensure_projects_dir()

    if not os.path.exists(dest):
        try:
            kw = {}
            if branch:
                kw["branch"] = branch
            Repo.clone_from(rewritten, dest, **kw)
            return dest
        except GitCommandError as exc:
            raise ProjectCloneError("git clone {} → {} failed: {}".format(rewritten, dest, exc))

    if not is_clone_of(dest, rewritten):
        raise ProjectCloneError("{} exists but origin does not match {}".format(dest, rewritten))

    try:
        repo = Repo(dest)
        repo.remote("origin").pull()
        return dest
    except GitCommandError as exc:
        raise ProjectCloneError("git pull at {} failed: {}".format(dest, exc))


def list_local_projects():
    """Return repo names with a ``.git`` directory under ``projects_dir``."""
    pdir = projects_dir()
    if not os.path.isdir(pdir):
        return []
    out = []
    for name in sorted(os.listdir(pdir)):
        candidate = os.path.join(pdir, name)
        if os.path.isdir(os.path.join(candidate, ".git")):
            out.append(name)
    return out


# ============= EOF =============================================
