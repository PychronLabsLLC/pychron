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
"""Rewrite Forgejo SSH URLs onto the workstation's per-lab SSH alias.

The pychronAPI handshake (M7 P2) drops a ``Host pychron-<lab>`` block in
``~/.ssh/config`` that pins the IdentityFile, port, and known_hosts. To
push/pull through that block git must clone via ``pychron-<lab>:owner/
repo.git`` rather than ``git@forgejo.example:owner/repo.git`` — same
remote, different transport keying.

This module's only job is the URL surgery. Two input forms are
supported:

- SCP-style: ``[user@]host:path`` → ``alias:path``
- ssh:// URI: ``ssh://[user@]host[:port]/path`` → ``alias:path``

Anything else (already alias-formed, https://, file://, ...) is
returned unchanged.
"""

from __future__ import absolute_import

import re

_SCP_RE = re.compile(r"^(?:(?P<user>[^@]+)@)?(?P<host>[^:/\s]+):(?P<path>[^:].*)$")
_SSH_RE = re.compile(r"^ssh://(?:(?P<user>[^@]+)@)?(?P<host>[^:/\s]+)(?::\d+)?/(?P<path>.+)$")


def rewrite_to_alias(ssh_url, alias):
    """Return ``alias:<path>`` for a Forgejo-style SSH URL, else input.

    ``alias`` is the value from ``Host pychron-<lab>`` in ``~/.ssh/config``
    (e.g. ``pychron-nmgrl``). Empty alias is treated as a no-op so callers
    can pass through unconditionally.
    """
    if not ssh_url or not alias:
        return ssh_url

    # Already alias-formed (no host segment, just "<alias>:path"). Treat
    # any token whose left side matches the alias as a pass-through.
    if ssh_url.startswith("{}:".format(alias)):
        return ssh_url

    m = _SSH_RE.match(ssh_url)
    if m:
        return "{}:{}".format(alias, m.group("path"))

    # SCP form requires a ":" before any "/" — anything with "://" is a
    # URI scheme (https://, file://, ...) and must pass through unchanged.
    if "://" in ssh_url:
        return ssh_url

    m = _SCP_RE.match(ssh_url)
    if m:
        return "{}:{}".format(alias, m.group("path"))

    return ssh_url


# ============= EOF =============================================
