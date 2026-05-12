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
