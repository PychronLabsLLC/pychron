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
"""Tests for the device-flow → DVC connection-prefs persistence path."""

from __future__ import absolute_import

import unittest

from pychron.cloud.dvc_credentials import (
    DatabaseUrlParseError,
    _favorite_name_for_lab,
    _row_set_field,
    apply_db_credentials_to_prefs,
    build_dvc_connection_csv,
    merge_dvc_connection_favorites,
    parse_database_url,
)


class FakePreferences(object):
    """Minimal apptools.preferences-like adapter for unit tests."""

    def __init__(self, initial=None):
        self._store = dict(initial or {})
        self._flushed = False

    def get(self, key, default=None):
        return self._store.get(key, default)

    def set(self, key, value):
        self._store[key] = value

    def flush(self):
        self._flushed = True


class ParseDatabaseUrlTestCase(unittest.TestCase):
    def test_basic_url_round_trip(self):
        out = parse_database_url("postgresql://wkstn_x:secret@10.0.1.5:5432/nmgrl")
        self.assertEqual(out["host"], "10.0.1.5")
        self.assertEqual(out["port"], 5432)
        self.assertEqual(out["username"], "wkstn_x")
        self.assertEqual(out["password"], "secret")
        self.assertEqual(out["dbname"], "nmgrl")

    def test_postgres_alias_scheme_accepted(self):
        out = parse_database_url("postgres://user:pw@h/db")
        self.assertEqual(out["dbname"], "db")

    def test_no_port_defaults_to_none(self):
        out = parse_database_url("postgresql://user:pw@h/db")
        self.assertIsNone(out["port"])

    def test_percent_encoded_password_decoded(self):
        out = parse_database_url("postgresql://user:p%40ss@h:5432/db")
        self.assertEqual(out["password"], "p@ss")

    def test_empty_url_raises(self):
        with self.assertRaises(DatabaseUrlParseError):
            parse_database_url("")

    def test_non_postgres_scheme_raises(self):
        with self.assertRaises(DatabaseUrlParseError):
            parse_database_url("mysql://u:p@h/db")

    def test_missing_host_raises(self):
        with self.assertRaises(DatabaseUrlParseError):
            parse_database_url("postgresql:///db")

    def test_missing_dbname_raises(self):
        with self.assertRaises(DatabaseUrlParseError):
            parse_database_url("postgresql://u:p@h/")


class BuildDvcConnectionCsvTestCase(unittest.TestCase):
    def test_csv_field_order_matches_attributes(self):
        parsed = parse_database_url("postgresql://wkstn_x:secret@10.0.1.5:5432/nmgrl")
        csv = build_dvc_connection_csv(
            parsed,
            name="cloud-nmgrl",
            organization="nmgrl",
            meta_repo_name="MetaData",
        )
        parts = csv.split(",")
        self.assertEqual(parts[0], "cloud-nmgrl")
        self.assertEqual(parts[1], "postgresql")
        self.assertEqual(parts[2], "wkstn_x")
        self.assertEqual(parts[3], "10.0.1.5:5432")  # host:port
        self.assertEqual(parts[4], "nmgrl")
        self.assertEqual(parts[5], "secret")
        self.assertEqual(parts[6], "True")  # enabled
        self.assertEqual(parts[7], "True")  # default
        self.assertEqual(parts[9], "nmgrl")  # organization
        self.assertEqual(parts[10], "MetaData")  # meta_repo_name

    def test_port_appended_to_host(self):
        """Caveman finding: port was lost. Host field MUST carry
        host:port so non-default-port Cloud SQL connections work."""
        parsed = parse_database_url("postgresql://u:p@db.lab.example.com:6543/nmgrl")
        csv = build_dvc_connection_csv(parsed, name="cloud-nmgrl")
        self.assertIn("db.lab.example.com:6543", csv)

    def test_no_port_omits_colon(self):
        parsed = parse_database_url("postgresql://u:p@db.lab/nmgrl")
        csv = build_dvc_connection_csv(parsed, name="cloud-nmgrl")
        parts = csv.split(",")
        self.assertEqual(parts[3], "db.lab")
        self.assertNotIn(":", parts[3])

    def test_password_with_comma_rejected(self):
        """A literal comma in the password would corrupt the CSV
        positional encoding. Caller must catch + abort rather than
        write a poison favorite."""
        parsed = parse_database_url("postgresql://u:p@h/db")
        parsed["password"] = "a,b"
        with self.assertRaises(DatabaseUrlParseError):
            build_dvc_connection_csv(parsed, name="cloud-x")


class MergeFavoritesTestCase(unittest.TestCase):
    def test_appends_when_no_match(self):
        existing = ["myhand,postgresql,me,h,db,p,True,False,,"]
        new_row = "cloud-nmgrl,postgresql,wkstn,h,db,p,True,True,,"
        out = merge_dvc_connection_favorites(existing, new_row, "cloud-nmgrl")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1], new_row)

    def test_replaces_matching_row(self):
        existing = [
            "myhand,postgresql,me,h,db,p,True,False,,",
            "cloud-nmgrl,postgresql,old,h,db,old,True,True,,",
        ]
        new_row = "cloud-nmgrl,postgresql,new,h,db,new,True,True,,"
        out = merge_dvc_connection_favorites(existing, new_row, "cloud-nmgrl")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1], new_row)

    def test_clears_default_flag_on_other_rows(self):
        """Adding a new default=True favorite must demote any other
        row that previously held the default flag — only one default
        at a time."""
        existing = [
            "myhand,postgresql,me,h,db,p,True,True,,",
        ]
        new_row = "cloud-nmgrl,postgresql,wkstn,h,db,p,True,True,,"
        out = merge_dvc_connection_favorites(existing, new_row, "cloud-nmgrl")
        self.assertIn("True,False", out[0])  # default field flipped
        self.assertIn("cloud-nmgrl", out[1])

    def test_short_row_extended_when_clearing_default(self):
        """Caveman finding: _row_set_field used to silently no-op
        when idx >= len(parts), leaving stale default=True flags on
        legacy short-format rows."""
        existing = ["legacy,postgresql,me,h"]  # 4 fields only
        new_row = "cloud-x,postgresql,wkstn,h,db,p,True,True,,"
        out = merge_dvc_connection_favorites(existing, new_row, "cloud-x")
        # The old short row was extended so position 7 now holds the
        # new default=False marker rather than being missing.
        legacy_parts = out[0].split(",")
        self.assertGreater(len(legacy_parts), 7)
        self.assertEqual(legacy_parts[7], "False")

    def test_no_default_change_when_new_row_isnt_default(self):
        """Edge case: if the new row isn't default, leave existing
        default flags alone."""
        existing = ["myhand,postgresql,me,h,db,p,True,True,,"]
        new_row = "cloud-x,postgresql,wkstn,h,db,p,True,False,,"
        out = merge_dvc_connection_favorites(existing, new_row, "cloud-x")
        self.assertIn("True,True", out[0])  # original default preserved


class RowSetFieldTestCase(unittest.TestCase):
    def test_extends_short_row(self):
        """Regression: `_row_set_field` used to drop updates whose
        index exceeded the row length."""
        out = _row_set_field("a,b", 5, "X")
        parts = out.split(",")
        self.assertEqual(len(parts), 6)
        self.assertEqual(parts[5], "X")
        # In-range positions preserved.
        self.assertEqual(parts[0], "a")
        self.assertEqual(parts[1], "b")

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

    def test_none_lab_falls_back(self):
        self.assertEqual(_favorite_name_for_lab(None), "cloud-default")


class ApplyDbCredentialsToPrefsTestCase(unittest.TestCase):
    def test_writes_favorite_into_empty_prefs(self):
        prefs = FakePreferences()
        name = apply_db_credentials_to_prefs(
            prefs,
            database_url="postgresql://wkstn_x:secret@10.0.1.5:5432/nmgrl",
            lab_name="nmgrl",
            organization="nmgrl",
            meta_repo_name="MetaData",
        )
        self.assertEqual(name, "cloud-nmgrl")
        favs = prefs.get("pychron.dvc.connection.favorites")
        self.assertIsNotNone(favs)
        # Round-trip through repr — that's what _join_favorites uses.
        import ast

        items = ast.literal_eval(favs)
        self.assertEqual(len(items), 1)
        self.assertIn("cloud-nmgrl", items[0])
        self.assertIn("10.0.1.5:5432", items[0])
        self.assertIn("secret", items[0])
        self.assertTrue(prefs._flushed)

    def test_replaces_prior_cloud_favorite(self):
        """Re-enrolling the same lab must REPLACE the prior cloud-*
        favorite, not stack them."""
        prefs = FakePreferences()
        apply_db_credentials_to_prefs(
            prefs,
            database_url="postgresql://wkstn_old:old@h:5432/nmgrl",
            lab_name="nmgrl",
        )
        apply_db_credentials_to_prefs(
            prefs,
            database_url="postgresql://wkstn_new:new@h:5432/nmgrl",
            lab_name="nmgrl",
        )
        import ast

        items = ast.literal_eval(prefs.get("pychron.dvc.connection.favorites"))
        cloud_items = [r for r in items if r.startswith("cloud-nmgrl,")]
        self.assertEqual(len(cloud_items), 1)
        self.assertIn("new", cloud_items[0])
        self.assertNotIn("old", cloud_items[0])

    def test_preserves_user_defined_favorites(self):
        legacy = "myhand,postgresql,me,otherhost,otherdb,mypw,True,True,,"
        prefs = FakePreferences(
            initial={
                "pychron.dvc.connection.favorites": repr([legacy]),
            }
        )
        apply_db_credentials_to_prefs(
            prefs,
            database_url="postgresql://wkstn_x:secret@10.0.1.5:5432/nmgrl",
            lab_name="nmgrl",
        )
        import ast

        items = ast.literal_eval(prefs.get("pychron.dvc.connection.favorites"))
        # legacy row preserved (not deleted)
        self.assertTrue(any(r.startswith("myhand,") for r in items))
        # new row appended
        self.assertTrue(any(r.startswith("cloud-nmgrl,") for r in items))
        # legacy default flag flipped to False (only one default)
        legacy_row = [r for r in items if r.startswith("myhand,")][0]
        self.assertEqual(legacy_row.split(",")[7], "False")

    def test_none_url_returns_none_without_writing(self):
        prefs = FakePreferences()
        out = apply_db_credentials_to_prefs(prefs, database_url=None, lab_name="nmgrl")
        self.assertIsNone(out)
        self.assertFalse(prefs._flushed)
        self.assertIsNone(prefs.get("pychron.dvc.connection.favorites"))

    def test_malformed_url_raises(self):
        prefs = FakePreferences()
        with self.assertRaises(DatabaseUrlParseError):
            apply_db_credentials_to_prefs(
                prefs,
                database_url="not-a-url",
                lab_name="nmgrl",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
