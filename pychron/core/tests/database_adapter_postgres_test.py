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
import unittest
from unittest.mock import patch

from pychron.database.core.database_adapter import DatabaseAdapter


class DatabaseAdapterPostgresTestCase(unittest.TestCase):
    """Verify postgres URL construction for the DVC database adapter.

    The connection-preferences Enum stores the dialect as ``"postgres"`` while
    SQLAlchemy's dialect name is ``"postgresql"``. The adapter must accept
    either spelling and emit a SQLAlchemy-compatible URL with the canonical
    ``postgresql+<driver>://`` prefix.
    """

    def _adapter(self, kind):
        a = DatabaseAdapter()
        a.kind = kind
        a.username = "operator"
        a.password = "secret"
        a.host = "db.example"
        a.name = "pychron"
        return a

    def test_enabled_accepts_both_spellings(self):
        for kind in ("postgres", "postgresql"):
            a = self._adapter(kind)
            self.assertTrue(a.enabled, "expected enabled=True for kind={}".format(kind))

    def test_url_uses_postgresql_dialect_for_postgres_alias(self):
        a = self._adapter("postgres")
        with patch.object(DatabaseAdapter, "_import_postgres_driver", return_value="pg8000"):
            url = a.url
        self.assertEqual(url, "postgresql+pg8000://operator:secret@db.example/pychron")

    def test_url_uses_postgresql_dialect_for_postgresql_kind(self):
        a = self._adapter("postgresql")
        with patch.object(DatabaseAdapter, "_import_postgres_driver", return_value="pg8000"):
            url = a.url
        self.assertEqual(url, "postgresql+pg8000://operator:secret@db.example/pychron")

    def test_url_returns_none_when_driver_missing(self):
        a = self._adapter("postgres")
        with patch.object(DatabaseAdapter, "_import_postgres_driver", return_value=None):
            url = a.url
        self.assertIsNone(url)


if __name__ == "__main__":
    unittest.main()


# ============= EOF =============================================
