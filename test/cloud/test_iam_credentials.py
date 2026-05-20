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
"""Tests for the device-flow → DVC IAM-credential persistence path."""

from __future__ import absolute_import

import ast
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud.iam_credentials import (
    IamCredentialsError,
    _favorite_name_for_lab,
    _row_set_field,
    apply_iam_credentials_to_prefs,
    build_iam_dvc_csv,
    merge_iam_dvc_favorites,
    write_sa_key_file,
)


def _good_key(client_email="wkstn-x@pychron-prod.iam.gserviceaccount.com"):
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "pychron-prod",
            "private_key_id": "deadbeef",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "client_email": client_email,
            "client_id": "111222333",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def _good_bundle(**overrides):
    base = {
        "instance_connection_name": "pychron-prod:us-central1:lab-db",
        "database_name": "nmgrl",
        "service_account_email": "wkstn-x@pychron-prod.iam.gserviceaccount.com",
        "service_account_key_json": _good_key(),
        "ip_type": "public",
    }
    base.update(overrides)
    return base


class FakePreferences(object):
    def __init__(self, initial=None):
        self._store = dict(initial or {})
        self._flushed = False

    def get(self, key, default=None):
        return self._store.get(key, default)

    def set(self, key, value):
        self._store[key] = value

    def flush(self):
        self._flushed = True


class _IsolatedHomeTestCase(unittest.TestCase):
    """Redirects ``~`` to a tmpdir for tests that touch the SA key file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patcher = patch(
            "pychron.cloud.paths.os.path.expanduser",
            lambda p: p.replace("~", self.tmp),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        def _rmtree():
            import shutil

            shutil.rmtree(self.tmp, ignore_errors=True)

        self.addCleanup(_rmtree)


class WriteSaKeyFileTestCase(_IsolatedHomeTestCase):
    def test_writes_under_pychron_keys_with_lab_slug(self):
        path = write_sa_key_file("nmgrl", _good_key())
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.endswith("cloudsql_nmgrl.json"))
        # File ended up under the redirected ~ → tmp.
        self.assertTrue(path.startswith(self.tmp))
        with open(path) as f:
            self.assertEqual(json.loads(f.read())["type"], "service_account")

    def test_secure_perms_on_posix(self):
        if os.name != "posix":
            self.skipTest("POSIX-only mode bits")
        path = write_sa_key_file("nmgrl", _good_key())
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_re_enrollment_overwrites(self):
        write_sa_key_file("nmgrl", _good_key("first@p.iam.gserviceaccount.com"))
        path = write_sa_key_file("nmgrl", _good_key("second@p.iam.gserviceaccount.com"))
        with open(path) as f:
            self.assertIn("second@p.iam.gserviceaccount.com", f.read())

    def test_unsafe_lab_slug_sanitized(self):
        path = write_sa_key_file("nm grl/!", _good_key())
        # Slashes / spaces stripped — no path-traversal escape.
        self.assertTrue(path.endswith("cloudsql_nmgrl.json"))


class BuildIamDvcCsvTestCase(unittest.TestCase):
    def test_field_order_matches_attributes(self):
        csv = build_iam_dvc_csv(
            _good_bundle(),
            name="cloud-nmgrl",
            sa_key_file_path="/home/lab/.pychron/keys/cloudsql_nmgrl.json",
            organization="nmgrl",
            meta_repo_name="MetaData",
        )
        parts = csv.split(",")
        self.assertEqual(parts[0], "cloud-nmgrl")
        self.assertEqual(parts[1], "postgresql")
        # username + host + password unset for IAM auth — Cloud SQL
        # Connector handles auth via the SA key.
        self.assertEqual(parts[2], "")
        self.assertEqual(parts[3], "")
        self.assertEqual(parts[4], "nmgrl")  # dbname
        self.assertEqual(parts[5], "")
        self.assertEqual(parts[6], "True")  # enabled
        self.assertEqual(parts[7], "True")  # default
        self.assertEqual(parts[14], "cloudsql_iam")  # connection_method
        self.assertEqual(parts[15], "pychron-prod:us-central1:lab-db")
        self.assertEqual(parts[16], "public")
        self.assertEqual(parts[17], "wkstn-x@pychron-prod.iam.gserviceaccount.com")
        self.assertEqual(parts[18], "/home/lab/.pychron/keys/cloudsql_nmgrl.json")


class MergeIamDvcFavoritesTestCase(unittest.TestCase):
    def test_appends_when_no_match(self):
        existing = ["myhand,postgresql,me,h,db,p,True,False,,,,,,,direct,,,,"]
        new_row = (
            "cloud-nmgrl,postgresql,,,nmgrl,,True,True,,,,,5,,cloudsql_iam,"
            "pychron-prod:us-central1:lab-db,public,"
            "wkstn-x@pychron-prod.iam.gserviceaccount.com,"
            "/home/lab/.pychron/keys/cloudsql_nmgrl.json"
        )
        out = merge_iam_dvc_favorites(existing, new_row, "cloud-nmgrl")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1], new_row)

    def test_replaces_matching_row(self):
        existing = [
            "cloud-nmgrl,postgresql,,,nmgrl,,True,True,,,,,5,,cloudsql_iam,"
            "old-instance:r:i,public,old@p.iam.gserviceaccount.com,/old/path"
        ]
        new_row = (
            "cloud-nmgrl,postgresql,,,nmgrl,,True,True,,,,,5,,cloudsql_iam,"
            "new-instance:r:i,public,new@p.iam.gserviceaccount.com,/new/path"
        )
        out = merge_iam_dvc_favorites(existing, new_row, "cloud-nmgrl")
        self.assertEqual(len(out), 1)
        self.assertIn("new-instance", out[0])

    def test_clears_default_flag_on_other_rows(self):
        existing = ["myhand,postgresql,me,h,db,p,True,True,,,,,,,direct,,,,"]
        new_row = (
            "cloud-nmgrl,postgresql,,,nmgrl,,True,True,,,,,5,,cloudsql_iam,"
            "i:r:i,public,sa@p.iam.gserviceaccount.com,/p"
        )
        out = merge_iam_dvc_favorites(existing, new_row, "cloud-nmgrl")
        # Position 7 (default) on the legacy row must flip to False.
        self.assertEqual(out[0].split(",")[7], "False")

    def test_short_row_extended_when_clearing_default(self):
        existing = ["legacy,postgresql,me,h"]  # 4 fields
        new_row = (
            "cloud-x,postgresql,,,db,,True,True,,,,,5,,cloudsql_iam,"
            "i:r:i,public,sa@p.iam.gserviceaccount.com,/p"
        )
        out = merge_iam_dvc_favorites(existing, new_row, "cloud-x")
        legacy_parts = out[0].split(",")
        self.assertGreater(len(legacy_parts), 7)
        self.assertEqual(legacy_parts[7], "False")


class RowSetFieldTestCase(unittest.TestCase):
    def test_extends_short_row(self):
        out = _row_set_field("a,b", 5, "X")
        parts = out.split(",")
        self.assertEqual(len(parts), 6)
        self.assertEqual(parts[5], "X")
        self.assertEqual(parts[0], "a")

    def test_in_range_update(self):
        out = _row_set_field("a,b,c,d", 2, "X")
        self.assertEqual(out, "a,b,X,d")


class FavoriteNameForLabTestCase(unittest.TestCase):
    def test_safe_lab(self):
        self.assertEqual(_favorite_name_for_lab("nmgrl"), "cloud-nmgrl")

    def test_strips_unsafe_chars(self):
        self.assertEqual(_favorite_name_for_lab("nm grl/!"), "cloud-nmgrl")

    def test_empty_lab_falls_back(self):
        self.assertEqual(_favorite_name_for_lab(""), "cloud-default")


class ApplyIamCredentialsToPrefsTestCase(_IsolatedHomeTestCase):
    def test_writes_favorite_and_sa_key(self):
        prefs = FakePreferences()
        name = apply_iam_credentials_to_prefs(
            prefs,
            bundle=_good_bundle(),
            lab_name="nmgrl",
            organization="nmgrl",
            meta_repo_name="MetaData",
        )
        self.assertEqual(name, "cloud-nmgrl")

        # SA key landed on disk.
        sa_path = os.path.join(self.tmp, ".pychron", "keys", "cloudsql_nmgrl.json")
        self.assertTrue(os.path.isfile(sa_path))

        # Favorite wired the key path.
        favs_raw = prefs.get("pychron.dvc.connection.favorites")
        self.assertIsNotNone(favs_raw)
        items = ast.literal_eval(favs_raw)
        self.assertEqual(len(items), 1)
        self.assertIn("cloudsql_iam", items[0])
        self.assertIn(sa_path, items[0])
        self.assertTrue(prefs._flushed)

    def test_replaces_prior_cloud_favorite(self):
        prefs = FakePreferences()
        apply_iam_credentials_to_prefs(
            prefs,
            bundle=_good_bundle(
                instance_connection_name="old:r:i",
                service_account_email="old@p.iam.gserviceaccount.com",
                service_account_key_json=_good_key("old@p.iam.gserviceaccount.com"),
            ),
            lab_name="nmgrl",
        )
        apply_iam_credentials_to_prefs(
            prefs,
            bundle=_good_bundle(
                instance_connection_name="new:r:i",
                service_account_email="new@p.iam.gserviceaccount.com",
                service_account_key_json=_good_key("new@p.iam.gserviceaccount.com"),
            ),
            lab_name="nmgrl",
        )
        items = ast.literal_eval(prefs.get("pychron.dvc.connection.favorites"))
        cloud_items = [r for r in items if r.startswith("cloud-nmgrl,")]
        self.assertEqual(len(cloud_items), 1)
        self.assertIn("new:r:i", cloud_items[0])
        self.assertNotIn("old:r:i", cloud_items[0])

    def test_preserves_user_defined_favorites(self):
        prefs = FakePreferences(
            initial={
                "pychron.dvc.connection.favorites": repr(
                    ["myhand,postgresql,me,otherhost,otherdb,mypw,True,True,,,,,,,direct,,,,"]
                ),
            }
        )
        apply_iam_credentials_to_prefs(prefs, bundle=_good_bundle(), lab_name="nmgrl")
        items = ast.literal_eval(prefs.get("pychron.dvc.connection.favorites"))
        self.assertTrue(any(r.startswith("myhand,") for r in items))
        self.assertTrue(any(r.startswith("cloud-nmgrl,") for r in items))
        legacy_row = [r for r in items if r.startswith("myhand,")][0]
        self.assertEqual(legacy_row.split(",")[7], "False")

    def test_none_bundle_returns_none_without_writing(self):
        prefs = FakePreferences()
        out = apply_iam_credentials_to_prefs(prefs, bundle=None, lab_name="nmgrl")
        self.assertIsNone(out)
        self.assertFalse(prefs._flushed)

    def test_missing_field_raises(self):
        prefs = FakePreferences()
        with self.assertRaises(IamCredentialsError):
            apply_iam_credentials_to_prefs(
                prefs,
                bundle={
                    "instance_connection_name": "x:r:i",
                    "database_name": "nmgrl",
                    "service_account_email": "wkstn-x@p.iam.gserviceaccount.com",
                    # service_account_key_json missing
                    "ip_type": "public",
                },
                lab_name="nmgrl",
            )

    def test_invalid_ip_type_raises(self):
        prefs = FakePreferences()
        with self.assertRaises(IamCredentialsError):
            apply_iam_credentials_to_prefs(
                prefs,
                bundle=_good_bundle(ip_type="carrier_pigeon"),
                lab_name="nmgrl",
            )

    def test_mismatched_key_email_raises(self):
        """Key file's client_email MUST match service_account_email or
        the bundle is a key-swap attempt."""
        prefs = FakePreferences()
        with self.assertRaises(IamCredentialsError):
            apply_iam_credentials_to_prefs(
                prefs,
                bundle=_good_bundle(
                    service_account_email="wkstn-x@p.iam.gserviceaccount.com",
                    service_account_key_json=_good_key("wkstn-y@p.iam.gserviceaccount.com"),
                ),
                lab_name="nmgrl",
            )

    def test_malformed_key_json_raises(self):
        prefs = FakePreferences()
        with self.assertRaises(IamCredentialsError):
            apply_iam_credentials_to_prefs(
                prefs,
                bundle=_good_bundle(service_account_key_json="not-json"),
                lab_name="nmgrl",
            )

    def test_non_service_account_key_raises(self):
        prefs = FakePreferences()
        with self.assertRaises(IamCredentialsError):
            apply_iam_credentials_to_prefs(
                prefs,
                bundle=_good_bundle(
                    service_account_key_json=json.dumps(
                        {
                            "type": "user_account",
                            "client_email": "wkstn-x@p.iam.gserviceaccount.com",
                        }
                    )
                ),
                lab_name="nmgrl",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
