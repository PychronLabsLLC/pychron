"""Unit tests for pychron.cloud.qr."""

import os
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud import qr


class MakeQrPngTestCase(unittest.TestCase):
    URL = "https://api.example/device?user_code=ABCD-EFGH"

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

    def test_writes_png_with_correct_magic(self):
        out = os.path.join(self.tmp, "test_qr.png")
        path = qr.make_qr_png(self.URL, out)
        self.assertEqual(path, out)
        self.assertTrue(os.path.isfile(out))
        with open(out, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_writes_under_pychron_qr_dir(self):
        path = qr.make_qr_for_device_code(self.URL, host_slug="lab-mac-01")
        self.assertTrue(path.endswith("device_lab-mac-01.png"))
        self.assertTrue(os.path.isfile(path))

    def test_overwrites_prior_file_for_same_host(self):
        """A re-enrollment for the same host must overwrite the earlier
        QR rather than accumulating ``device_<host>_2.png`` etc."""
        first = qr.make_qr_for_device_code(self.URL, host_slug="lab-mac-01")
        size_first = os.path.getsize(first)
        # Different URL → different content → confirm overwrite happened.
        second = qr.make_qr_for_device_code(
            "https://api.example/device?user_code=WXYZ-1234",
            host_slug="lab-mac-01",
        )
        self.assertEqual(first, second)
        self.assertNotEqual(os.path.getsize(second), 0)
        # Different content of similar length is plausible — the key
        # guarantee is that exactly one file exists for this slug.
        listing = os.listdir(os.path.dirname(second))
        self.assertEqual(
            [n for n in listing if n.startswith("device_lab-mac-01")],
            ["device_lab-mac-01.png"],
        )

    def test_empty_url_rejected(self):
        with self.assertRaises(ValueError):
            qr.make_qr_png("", os.path.join(self.tmp, "x.png"))
        with self.assertRaises(ValueError):
            qr.make_qr_for_device_code("", host_slug="x")

    def test_default_host_slug(self):
        """Caller may omit host_slug — file is named ``device_default.png``."""
        path = qr.make_qr_for_device_code(self.URL)
        self.assertTrue(path.endswith("device_default.png"))


if __name__ == "__main__":
    unittest.main()
