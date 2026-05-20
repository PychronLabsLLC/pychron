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
"""SSH config + known_hosts writers for Pychron Cloud (M7 P2).

Two file mutations:

- Append a single ``known_hosts_line`` to a Pychron-scoped known_hosts
  file under ``~/.pychron/known_hosts`` so we never edit the user's
  global ``~/.ssh/known_hosts``.
- Insert / replace a block-managed ``Host pychron-<lab>`` stanza in
  ``~/.ssh/config``. The block is delimited by sentinel comments so we
  can rewrite it idempotently without touching anything else in the
  user's config.
"""

from __future__ import absolute_import

import os
import re

from pychron.cloud.paths import (
    ensure_pychron_dirs,
    known_hosts_path,
    ssh_config_path,
)


BEGIN_MARKER = "# BEGIN pychron-cloud:{alias}"
END_MARKER = "# END pychron-cloud:{alias}"


def append_known_hosts_line(line, path=None):
    """Append ``line`` to the Pychron known_hosts file if absent.

    Returns True if the file was modified, False if the line was already
    present (exact match, ignoring trailing whitespace).
    """
    if not line:
        return False
    line = line.strip()
    ensure_pychron_dirs()
    path = path or known_hosts_path()

    existing = ""
    if os.path.isfile(path):
        with open(path, "r") as f:
            existing = f.read()
    for existing_line in existing.splitlines():
        if existing_line.strip() == line:
            return False

    with open(path, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")
    if os.name == "posix":
        os.chmod(path, 0o600)
    return True


def render_host_block(alias, real_host, port, identity_file, known_hosts_file):
    """Render the ``Host <alias>`` block (without sentinels)."""
    return (
        "Host {alias}\n"
        "    HostName {real_host}\n"
        "    Port {port}\n"
        "    User git\n"
        "    IdentityFile {identity_file}\n"
        "    IdentitiesOnly yes\n"
        "    UserKnownHostsFile {known_hosts_file}\n"
    ).format(
        alias=alias,
        real_host=real_host,
        port=port,
        identity_file=identity_file,
        known_hosts_file=known_hosts_file,
    )


def _block_pattern(alias):
    begin = re.escape(BEGIN_MARKER.format(alias=alias))
    end = re.escape(END_MARKER.format(alias=alias))
    # Non-greedy across newlines including the trailing newline of the
    # END marker so a clean rewrite leaves no orphan blank lines.
    return re.compile(r"(?:^|\n)" + begin + r"\n.*?\n" + end + r"\n?", re.DOTALL)


def upsert_ssh_config_block(
    alias,
    real_host,
    port,
    identity_file,
    known_hosts_file,
    path=None,
):
    """Insert or replace the Pychron Cloud block in ``~/.ssh/config``.

    Idempotent: if an existing block for ``alias`` matches the rendered
    content exactly, the file is not rewritten and ``False`` is
    returned. Returns ``True`` when the file is modified.
    """
    path = path or ssh_config_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
        if os.name == "posix":
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass

    body = render_host_block(
        alias=alias,
        real_host=real_host,
        port=port,
        identity_file=identity_file,
        known_hosts_file=known_hosts_file,
    )
    new_block = "{begin}\n{body}{end}\n".format(
        begin=BEGIN_MARKER.format(alias=alias),
        body=body,
        end=END_MARKER.format(alias=alias),
    )

    existing = ""
    if os.path.isfile(path):
        with open(path, "r") as f:
            existing = f.read()

    pattern = _block_pattern(alias)
    match = pattern.search(existing)

    if match:
        current = match.group(0).lstrip("\n")
        if current.rstrip("\n") == new_block.rstrip("\n"):
            return False
        # Replace in place, preserving the leading newline (if any) so
        # we do not collapse adjacent unrelated blocks.
        replaced = (
            existing[: match.start()]
            + ("\n" if existing[: match.start()].endswith("\n") or match.start() == 0 else "\n")
            + new_block
            + existing[match.end() :]
        )
        # Normalize: avoid leading newline on a fresh file.
        if match.start() == 0 and replaced.startswith("\n"):
            replaced = replaced.lstrip("\n")
        new_content = replaced
    else:
        sep = ""
        if existing and not existing.endswith("\n"):
            sep = "\n"
        elif existing and not existing.endswith("\n\n"):
            sep = "\n"
        new_content = existing + sep + new_block

    with open(path, "w") as f:
        f.write(new_content)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return True


def remove_ssh_config_block(alias, path=None):
    """Remove the block for ``alias`` from ``~/.ssh/config``.

    Returns ``True`` if a block was removed, ``False`` otherwise.
    """
    path = path or ssh_config_path()
    if not os.path.isfile(path):
        return False
    with open(path, "r") as f:
        existing = f.read()
    pattern = _block_pattern(alias)
    new_content, n = pattern.subn("", existing)
    if n == 0:
        return False
    new_content = new_content.lstrip("\n")
    with open(path, "w") as f:
        f.write(new_content)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return True


# ============= EOF =============================================
