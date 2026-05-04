"""Tests for pychron.cloud.ssh_config."""

import os
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud import ssh_config


class KnownHostsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patcher = patch(
            "pychron.cloud.paths.os.path.expanduser",
            lambda p: p.replace("~", self.tmp),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self._rmtree, self.tmp)

    def _rmtree(self, path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def test_appends_when_absent(self):
        from pychron.cloud.paths import known_hosts_path

        line = "[forgejo.example]:2222 ssh-ed25519 AAAAC3..."
        self.assertTrue(ssh_config.append_known_hosts_line(line))
        self.assertIn(line, self._read(known_hosts_path()))

    def test_idempotent_when_already_present(self):
        line = "[forgejo.example]:2222 ssh-ed25519 AAAAC3..."
        self.assertTrue(ssh_config.append_known_hosts_line(line))
        # Second call returns False (no rewrite).
        self.assertFalse(ssh_config.append_known_hosts_line(line))


class SSHConfigBlockTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config")
        self.addCleanup(self._rmtree, self.tmp)

    def _rmtree(self, path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def _read(self):
        with open(self.path) as f:
            return f.read()

    def _common_kw(self, alias="pychron-nmgrl"):
        return dict(
            alias=alias,
            real_host="forgejo.example",
            port=2222,
            identity_file="/home/u/.pychron/keys/pychron_x",
            known_hosts_file="/home/u/.pychron/known_hosts",
            path=self.path,
        )

    def test_inserts_block_into_empty_file(self):
        self.assertTrue(ssh_config.upsert_ssh_config_block(**self._common_kw()))
        body = self._read()
        self.assertIn("# BEGIN pychron-cloud:pychron-nmgrl", body)
        self.assertIn("Host pychron-nmgrl", body)
        self.assertIn("# END pychron-cloud:pychron-nmgrl", body)
        self.assertIn("HostName forgejo.example", body)
        self.assertIn("Port 2222", body)
        self.assertIn("IdentitiesOnly yes", body)

    def test_idempotent_on_repeat(self):
        ssh_config.upsert_ssh_config_block(**self._common_kw())
        first = self._read()
        # Second call must not rewrite — returns False.
        self.assertFalse(ssh_config.upsert_ssh_config_block(**self._common_kw()))
        self.assertEqual(first, self._read())

    def test_replaces_block_on_drift(self):
        ssh_config.upsert_ssh_config_block(**self._common_kw())
        kw = self._common_kw()
        kw["port"] = 22  # drift
        self.assertTrue(ssh_config.upsert_ssh_config_block(**kw))
        body = self._read()
        self.assertIn("Port 22", body)
        self.assertNotIn("Port 2222", body)
        # No duplicate BEGIN markers.
        self.assertEqual(body.count("# BEGIN pychron-cloud:pychron-nmgrl"), 1)

    def test_preserves_unrelated_content(self):
        with open(self.path, "w") as f:
            f.write("Host other\n    HostName other.example\n")
        ssh_config.upsert_ssh_config_block(**self._common_kw())
        body = self._read()
        self.assertIn("Host other", body)
        self.assertIn("HostName other.example", body)
        self.assertIn("Host pychron-nmgrl", body)

    def test_remove_block(self):
        ssh_config.upsert_ssh_config_block(**self._common_kw())
        self.assertTrue(ssh_config.remove_ssh_config_block("pychron-nmgrl", path=self.path))
        body = self._read()
        self.assertNotIn("pychron-cloud", body)
        self.assertNotIn("Host pychron-nmgrl", body)

    def test_remove_block_missing_returns_false(self):
        with open(self.path, "w") as f:
            f.write("Host other\n")
        self.assertFalse(ssh_config.remove_ssh_config_block("pychron-nmgrl", path=self.path))


if __name__ == "__main__":
    unittest.main()
