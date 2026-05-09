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
"""QR-code generation for the device-code enrollment flow.

The device-code grant returns a ``verification_url_complete`` —
the verification URL with the ``user_code`` already encoded as a
query parameter. Encoding that string as a QR lets the admin scan
the workstation's screen with a phone instead of typing the URL +
short code by hand.

Backed by ``segno`` (pure Python, ~24KB, no PIL dependency for PNG
output). The output path is a regular file the caller is responsible
for cleaning up.
"""

from __future__ import absolute_import

import os

import segno

from pychron.cloud.paths import pychron_dir


def qr_dir():
    """Return ``~/.pychron/qr/``, creating it 0700 if missing."""
    path = os.path.join(pychron_dir(), "qr")
    if not os.path.isdir(path):
        os.makedirs(path, mode=0o700)
    elif os.name == "posix":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def make_qr_png(url, out_path, scale=8, border=2):
    """Encode ``url`` as a QR code and write it to ``out_path`` as PNG.

    Uses error-correction level M (15% recoverable) which is plenty
    for a screen-to-camera scan of an https URL of typical length.
    ``scale`` is the pixel-per-module size; ``border`` is the
    quiet-zone width in modules. Defaults render to roughly
    ~330×330 px for a 33-module symbol — readable from arm's length.
    """
    if not url:
        raise ValueError("url is empty")
    qr = segno.make(url, error="m")
    qr.save(out_path, kind="png", scale=scale, border=border)
    if os.name == "posix":
        try:
            os.chmod(out_path, 0o600)
        except OSError:
            pass
    return out_path


def make_qr_for_device_code(verification_url_complete, host_slug=""):
    """Convenience wrapper: emit ``~/.pychron/qr/device_<host>.png``.

    Returns the absolute path to the generated PNG. Overwrites any
    prior file at the same path so a fresh enrollment does not pick
    up a stale QR from an earlier attempt.
    """
    if not verification_url_complete:
        raise ValueError("verification_url_complete is empty")
    name = "device_{}.png".format(host_slug or "default")
    out_path = os.path.join(qr_dir(), name)
    return make_qr_png(verification_url_complete, out_path)


# ============= EOF =============================================
