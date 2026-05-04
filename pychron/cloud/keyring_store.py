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
"""OS keyring-backed storage for the Pychron Cloud (pychronAPI) token.

The pychronAPI bearer token is treated as a secret. It is stored in the
host OS keyring (Keychain / Credential Manager / Secret Service) keyed by
lab name so a workstation can be re-onboarded to a different lab without
clobbering the prior credential atomically — re-onboarding is a separate
destructive flow that calls :func:`delete_token` explicitly.
"""

from __future__ import absolute_import

import logging

import keyring
from keyring.errors import KeyringError

logger = logging.getLogger(__name__)

SERVICE_NAME = "pychron.cloud"
DEFAULT_ACCOUNT = "default"


def _account(lab_name):
    lab_name = (lab_name or "").strip()
    return lab_name or DEFAULT_ACCOUNT


def get_token(lab_name):
    """Return the stored token for ``lab_name`` or empty string."""
    try:
        return keyring.get_password(SERVICE_NAME, _account(lab_name)) or ""
    except KeyringError as exc:
        logger.warning("keyring get_password failed: %s", exc)
        return ""


def set_token(lab_name, token):
    """Store ``token`` for ``lab_name``. Empty token is a no-op (use delete)."""
    if not token:
        return False
    try:
        keyring.set_password(SERVICE_NAME, _account(lab_name), token)
        return True
    except KeyringError as exc:
        logger.warning("keyring set_password failed: %s", exc)
        return False


def delete_token(lab_name):
    """Remove the token for ``lab_name``. Idempotent."""
    try:
        keyring.delete_password(SERVICE_NAME, _account(lab_name))
        return True
    except KeyringError:
        return False


# ============= EOF =============================================
