"""Tests for pychron.cloud.ssh_keygen."""

import os
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud import ssh_keygen


class SSHKeygenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(self._rmtree, self.tmp)
        # Redirect ~/.pychron under our tmp dir.
        self._patcher = patch(
            "pychron.cloud.paths.os.path.expanduser",
            lambda p: p.replace("~", self.tmp),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _rmtree(self, path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def test_generate_creates_both_files_with_secure_perms(self):
        priv, pub = ssh_keygen.generate_keypair("testhost")
        self.assertTrue(os.path.isfile(priv))
        self.assertTrue(os.path.isfile(pub))
        if os.name == "posix":
            mode = os.stat(priv).st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_public_key_format_is_openssh_ed25519(self):
        _, pub = ssh_keygen.generate_keypair("testhost")
        with open(pub) as f:
            line = f.read().strip()
        self.assertTrue(line.startswith("ssh-ed25519 "))
        # Comment field appended.
        self.assertTrue(line.endswith("pychron-testhost"))

    def test_ensure_keypair_is_idempotent(self):
        priv, pub = ssh_keygen.ensure_keypair("testhost")
        with open(priv, "rb") as f:
            priv_bytes_first = f.read()
        # Second call must not regenerate.
        priv2, pub2 = ssh_keygen.ensure_keypair("testhost")
        self.assertEqual(priv, priv2)
        with open(priv, "rb") as f:
            priv_bytes_second = f.read()
        self.assertEqual(priv_bytes_first, priv_bytes_second)

    def test_ensure_keypair_regenerates_when_pub_missing(self):
        priv, pub = ssh_keygen.ensure_keypair("testhost")
        with open(priv, "rb") as f:
            first = f.read()
        os.remove(pub)
        ssh_keygen.ensure_keypair("testhost")
        with open(priv, "rb") as f:
            second = f.read()
        # Private key was regenerated since the pair was incomplete.
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
