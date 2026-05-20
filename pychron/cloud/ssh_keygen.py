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
"""ed25519 keypair generation for Pychron Cloud workstations (M7 P2).

Generates an OpenSSH-format private key + a single-line public key.
Idempotent — :func:`ensure_keypair` returns the existing pair if both
files exist; only generates on a miss.
"""

from __future__ import absolute_import

import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pychron.cloud.paths import (
    ensure_pychron_dirs,
    host_slug,
    key_path,
    public_key_path,
)


def _comment(host):
    return "pychron-{}".format(host)


def generate_keypair(host=None):
    """Generate a fresh ed25519 keypair, overwriting any existing files.

    Returns ``(private_path, public_path)``.
    """
    ensure_pychron_dirs()
    host = host or host_slug()
    priv_path = key_path(host)
    pub_path = public_key_path(host)

    private_key = Ed25519PrivateKey.generate()
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    # Write private key first with 0600 so it is never briefly world-
    # readable.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600
    fd = os.open(priv_path, flags, mode)
    try:
        os.write(fd, priv_bytes)
    finally:
        os.close(fd)
    if os.name == "posix":
        os.chmod(priv_path, 0o600)

    pub_line = pub_bytes.decode("ascii").strip() + " " + _comment(host) + "\n"
    with open(pub_path, "w") as f:
        f.write(pub_line)
    if os.name == "posix":
        os.chmod(pub_path, 0o644)

    return priv_path, pub_path


def ensure_keypair(host=None):
    """Return ``(private_path, public_path)``, generating if either is missing.

    Both files must exist for the pair to be considered present — a stray
    ``.pub`` without a private key is treated as missing and forces a
    regeneration.
    """
    host = host or host_slug()
    priv_path = key_path(host)
    pub_path = public_key_path(host)
    if os.path.isfile(priv_path) and os.path.isfile(pub_path):
        return priv_path, pub_path
    return generate_keypair(host)


def read_public_key(host=None):
    pub_path = public_key_path(host)
    with open(pub_path, "r") as f:
        return f.read().strip()


# ============= EOF =============================================
