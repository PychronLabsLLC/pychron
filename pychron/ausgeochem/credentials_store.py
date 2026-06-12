# ===============================================================================
# Copyright 2024 Pychron Developers
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

"""Cross-platform encrypted credential storage for EarthBank profiles.

Layered backend selection:

1. ``keyring`` against an OS-native vault when one is available:
   - macOS Keychain
   - Windows Credential Locker
   - Linux Secret Service (gnome-keyring / KWallet) — when running under a
     desktop session.

2. ``cryptography.fernet`` symmetric-encrypted file on disk when no usable
   OS keyring is found (headless Linux, CI, etc.). The encryption key is
   stored in a sibling file with ``0600`` permissions.

3. Process-local dict as last resort if ``cryptography`` is unavailable;
   passwords disappear when the process exits. A warning is logged so
   the user knows credentials are not being persisted.

Profile metadata (name, base_url, username) lives in pychron preferences as
JSON. Only the password ever touches this module.
"""


import json
import logging
import os
import stat
import sys

KEYRING_SERVICE = "pychron.earthbank"

_logger = logging.getLogger(__name__)
_fallback_store = {}

# -- backend probes ----------------------------------------------------------

_keyring = None
_keyring_errors = None
try:
    import keyring as _keyring
    import keyring.errors as _keyring_errors
except ImportError:
    _logger.warning("'keyring' not installed; falling back to encrypted file")


def _have_os_keyring():
    """Return True if a *real* OS keyring backend is loaded.

    keyring picks a `null` or `fail` backend on systems without a vault
    (typically headless Linux). Those don't actually persist anything, so we
    detect and bypass them in favor of the encrypted file fallback.
    """
    if _keyring is None:
        return False
    try:
        backend = _keyring.get_keyring()
    except Exception:
        return False
    name = type(backend).__module__.lower()
    if "null" in name or "fail" in name or "chainer" in name:
        # chainer wraps multiple — accept if at least one child is real
        children = getattr(backend, "backends", None) or []
        for c in children:
            cname = type(c).__module__.lower()
            if "null" not in cname and "fail" not in cname:
                return True
        return False
    return True


_fernet = None
_have_crypto = False
try:
    from cryptography.fernet import Fernet, InvalidToken

    _have_crypto = True
except ImportError:
    Fernet = None
    InvalidToken = Exception
    _logger.warning("'cryptography' not installed; cannot encrypt credentials at rest")


def _store_dir():
    """Return the directory where the encrypted vault + key live.

    Prefers pychron's own ``paths.appdata_dir`` (the canonical hidden
    per-install location, ``<pychron_root>/.appdata``) so credentials sit
    alongside other pychron app data on every platform. Falls back to an
    OS-appropriate user app-data dir if pychron paths haven't been
    initialized yet (e.g. during a unit test).
    """

    try:
        from pychron.paths import paths

        appdata = getattr(paths, "appdata_dir", None)
        if appdata:
            os.makedirs(appdata, exist_ok=True)
            return appdata
    except Exception:
        pass

    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, "pychron", ".appdata")
    os.makedirs(path, exist_ok=True)
    return path


def _key_path():
    return os.path.join(_store_dir(), "earthbank.key")


def _vault_path():
    return os.path.join(_store_dir(), "earthbank_credentials.enc")


def _load_or_create_key():
    if not _have_crypto:
        return None
    path = _key_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(path, "wb") as f:
        f.write(key)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def _get_fernet():
    global _fernet
    if _fernet is not None or not _have_crypto:
        return _fernet
    key = _load_or_create_key()
    if key:
        _fernet = Fernet(key)
    return _fernet


def _load_vault():
    f = _get_fernet()
    if f is None:
        return {}
    path = _vault_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
        if not blob:
            return {}
        return json.loads(f.decrypt(blob).decode("utf-8"))
    except (OSError, ValueError, InvalidToken) as exc:
        _logger.warning("EarthBank vault unreadable (%s); starting empty", exc)
        return {}


def _save_vault(vault):
    f = _get_fernet()
    if f is None:
        return False
    path = _vault_path()
    blob = f.encrypt(json.dumps(vault).encode("utf-8"))
    with open(path, "wb") as fh:
        fh.write(blob)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return True


# -- public API --------------------------------------------------------------


def backend_name():
    """Return a short label naming the active backend; used for diagnostics."""

    if _have_os_keyring():
        try:
            return "keyring:{}".format(type(_keyring.get_keyring()).__module__)
        except Exception:
            return "keyring"
    if _have_crypto:
        return "file:fernet"
    return "memory"


def _account_key(profile_name, username):
    return "{}:{}".format(profile_name or "", username or "")


def set_password(profile_name, username, password):
    """Store ``password`` against (profile_name, username). Empty password
    removes the entry."""

    key = _account_key(profile_name, username)
    if password is None or password == "":
        return delete_password(profile_name, username)

    if _have_os_keyring():
        try:
            _keyring.set_password(KEYRING_SERVICE, key, password)
            _fallback_store.pop(key, None)
            return True
        except _keyring_errors.KeyringError as exc:
            _logger.warning("OS keyring set failed: %s; using encrypted file", exc)

    if _have_crypto:
        vault = _load_vault()
        vault[key] = password
        if _save_vault(vault):
            _fallback_store.pop(key, None)
            return True

    # Last resort: in-process dict; not persisted, not safe across runs.
    _logger.warning(
        "EarthBank password for %s held in-memory only — install 'keyring' "
        "or 'cryptography' to persist securely",
        key,
    )
    _fallback_store[key] = password
    return True


def get_password(profile_name, username):
    """Return the stored password or ``None``."""

    key = _account_key(profile_name, username)

    if _have_os_keyring():
        try:
            val = _keyring.get_password(KEYRING_SERVICE, key)
            if val is not None:
                return val
        except _keyring_errors.KeyringError as exc:
            _logger.warning("OS keyring get failed: %s", exc)

    if _have_crypto:
        vault = _load_vault()
        if key in vault:
            return vault[key]

    return _fallback_store.get(key)


def delete_password(profile_name, username):
    key = _account_key(profile_name, username)

    if _have_os_keyring():
        try:
            _keyring.delete_password(KEYRING_SERVICE, key)
        except _keyring_errors.PasswordDeleteError:
            pass
        except _keyring_errors.KeyringError as exc:
            _logger.warning("OS keyring delete failed: %s", exc)

    if _have_crypto:
        vault = _load_vault()
        if key in vault:
            vault.pop(key, None)
            _save_vault(vault)

    _fallback_store.pop(key, None)
    return True


# ============= EOF =============================================
