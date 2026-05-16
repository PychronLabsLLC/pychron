# ===============================================================================
# Copyright 2018 ross
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
import os
import sys

# --- Phase 1 M3 diagnostics: install as early as possible, before any Qt
# object construction, so qInstallMessageHandler and the QTimer thread
# guard are in place when the rest of the stack imports.
try:
    # Ensure pychron is importable even when launched outside Pychron.sh
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from pychron.core.helpers.m3_diagnostics import install_early as _m3_install_early
    _m3_install_early()
except Exception as _e:  # pragma: no cover
    sys.stderr.write("m3_diagnostics early install failed: %r\n" % (_e,))


# Seed the OpenSSL trust store BEFORE any module that touches TLS
# (pyface, envisage, requests, aiohttp, google-cloud-sql-connector).
# python.org macOS builds ship a Python whose default ssl context has
# no usable trust roots; without this, the Cloud SQL Connector fails
# its handshake against sqladmin.googleapis.com on first connect.
# `setdefault` preserves an explicit operator override; we only fix
# the case where the var is unset OR points to a non-existent file
# (the common "/etc/ssl/cert.pem" stale value on Mac).
def _ensure_ssl_cert_file():
    try:
        import certifi
    except ImportError:
        return
    ca = certifi.where()
    cur = os.environ.get("SSL_CERT_FILE")
    if not cur or not os.path.isfile(cur):
        os.environ["SSL_CERT_FILE"] = ca
    cur = os.environ.get("REQUESTS_CA_BUNDLE")
    if not cur or not os.path.isfile(cur):
        os.environ["REQUESTS_CA_BUNDLE"] = ca


_ensure_ssl_cert_file()

from helpers import entry_point

appname = os.environ.get("PYCHRON_APPNAME", "pycrunch")
debug = os.environ.get("PYCHRON_DEBUG", False)


entry_point(appname, debug=debug)

# ============= EOF =============================================
