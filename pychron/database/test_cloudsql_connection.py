import os
import types
import tempfile
import unittest
from unittest.mock import patch

from pychron.database.core.database_adapter import DatabaseAdapter
from pychron.dvc.tasks.dvc_preferences import DVCConnectionItem


class CloudSQLDVCConnectionItemTestCase(unittest.TestCase):
    def test_legacy_favorite_loads(self):
        fav = (
            "local,mysql,user,localhost,pychrondvc,pwd,True,True,,Org," "Meta,OrgMeta,7,/tmp/repos"
        )

        item = DVCConnectionItem(attrs=fav)

        self.assertEqual(item.connection_method, "direct")
        self.assertEqual(item.kind, "mysql")
        self.assertEqual(item.timeout, 7)
        self.assertEqual(item.repository_root, "/tmp/repos")

    def test_cloudsql_favorite_round_trip(self):
        item = DVCConnectionItem()
        item.trait_set(
            name="cloudsql",
            kind="postgresql",
            dbname="pychrondvc",
            enabled=True,
            default=True,
            organization="Org",
            meta_repo_name="Meta",
            meta_repo_dir="OrgMeta",
            timeout=10,
            repository_root="/tmp/repos",
            connection_method="cloudsql_iam",
            cloudsql_instance_connection_name="project:region:instance",
            cloudsql_ip_type="private",
            cloudsql_service_account_email="pychron@project.iam.gserviceaccount.com",
            cloudsql_service_account_key_path="/tmp/key.json",
        )

        loaded = DVCConnectionItem(attrs=item.to_string())

        self.assertEqual(loaded.connection_method, "cloudsql_iam")
        self.assertEqual(loaded.cloudsql_instance_connection_name, "project:region:instance")
        self.assertEqual(loaded.cloudsql_ip_type, "private")
        self.assertEqual(
            loaded.cloudsql_service_account_email,
            "pychron@project.iam.gserviceaccount.com",
        )
        self.assertEqual(loaded.cloudsql_service_account_key_path, "/tmp/key.json")

    def test_legacy_postgres_kind_normalizes(self):
        fav = "pg,postgres,user,localhost,pychrondvc,pwd,True,False,,Org,Meta,OrgMeta"

        item = DVCConnectionItem(attrs=fav)

        self.assertEqual(item.kind, "postgresql")


class CloudSQLDatabaseAdapterTestCase(unittest.TestCase):
    def test_mysql_service_account_user(self):
        db = DatabaseAdapter(
            kind="mysql",
            cloudsql_service_account_email="pychron@project.iam.gserviceaccount.com",
        )

        self.assertEqual(db._get_cloudsql_iam_user(), "pychron")

    def test_postgresql_service_account_user(self):
        db = DatabaseAdapter(
            kind="postgresql",
            cloudsql_service_account_email="pychron@project.iam.gserviceaccount.com",
        )

        self.assertEqual(db._get_cloudsql_iam_user(), "pychron@project.iam")

    def test_cloudsql_engine_uses_creator(self):
        class Connector:
            def __init__(self):
                self.calls = []

            def connect(self, *args, **kw):
                self.calls.append((args, kw))
                return object()

        connector = Connector()
        engines = []

        def create_engine(url, **kw):
            engines.append((url, kw))
            return "engine"

        db = DatabaseAdapter(
            kind="mysql",
            name="pychrondvc",
            connection_method="cloudsql_iam",
            cloudsql_instance_connection_name="project:region:instance",
            cloudsql_ip_type="private",
            cloudsql_service_account_email="pychron@project.iam.gserviceaccount.com",
        )

        with patch.object(db, "_make_cloudsql_connector", return_value=connector):
            with patch.object(db, "_get_cloudsql_driver", return_value="pymysql"):
                with patch(
                    "pychron.database.core.database_adapter.create_engine",
                    side_effect=create_engine,
                ):
                    engine = db._create_cloudsql_engine("mysql+pymysql://", 600)

        self.assertEqual(engine, "engine")
        self.assertEqual(engines[0][0], "mysql+pymysql://")
        creator = engines[0][1]["creator"]
        creator()

        args, kw = connector.calls[0]
        self.assertEqual(args, ("project:region:instance", "pymysql"))
        self.assertEqual(kw["user"], "pychron")
        self.assertEqual(kw["db"], "pychrondvc")
        self.assertEqual(kw["ip_type"], "private")
        self.assertTrue(kw["enable_iam_auth"])

    def test_service_account_key_credentials_are_scoped(self):
        class Credentials:
            requires_scopes = True

            @classmethod
            def from_service_account_file(cls, path):
                credential = cls()
                credential.path = path
                return credential

            def with_scopes(self, scopes):
                self.scopes = scopes
                return self

        with tempfile.NamedTemporaryFile() as rfile:
            db = DatabaseAdapter(cloudsql_service_account_key_path=rfile.name)
            google = types.ModuleType("google")
            oauth2 = types.ModuleType("google.oauth2")
            service_account = types.ModuleType("google.oauth2.service_account")
            service_account.Credentials = Credentials
            oauth2.service_account = service_account
            google.oauth2 = oauth2
            with patch.dict(
                "sys.modules",
                {
                    "google": google,
                    "google.oauth2": oauth2,
                    "google.oauth2.service_account": service_account,
                },
            ):
                credentials = db._get_cloudsql_credentials()

        self.assertEqual(credentials.path, os.path.abspath(rfile.name))
        self.assertEqual(credentials.scopes, ["https://www.googleapis.com/auth/cloud-platform"])


if __name__ == "__main__":
    unittest.main()
