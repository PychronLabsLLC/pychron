"""Unit tests for pychron.cloud.keyring_store."""

import unittest
from unittest.mock import patch

from keyring.errors import KeyringError, PasswordDeleteError

from pychron.cloud import keyring_store


class TestKeyringStore(unittest.TestCase):
    def test_get_token_returns_stored(self):
        with patch.object(keyring_store.keyring, "get_password", return_value="pcy_lab_xyz") as gp:
            self.assertEqual(keyring_store.get_token("nmgrl"), "pcy_lab_xyz")
            gp.assert_called_once_with("pychron.cloud", "nmgrl")

    def test_get_token_empty_lab_uses_default_account(self):
        with patch.object(keyring_store.keyring, "get_password", return_value=None) as gp:
            self.assertEqual(keyring_store.get_token(""), "")
            gp.assert_called_once_with("pychron.cloud", "default")

    def test_get_token_keyring_error_returns_empty(self):
        with patch.object(keyring_store.keyring, "get_password", side_effect=KeyringError("nope")):
            self.assertEqual(keyring_store.get_token("nmgrl"), "")

    def test_set_token_writes(self):
        with patch.object(keyring_store.keyring, "set_password") as sp:
            self.assertTrue(keyring_store.set_token("nmgrl", "pcy_lab_xyz"))
            sp.assert_called_once_with("pychron.cloud", "nmgrl", "pcy_lab_xyz")

    def test_set_token_empty_is_noop(self):
        with patch.object(keyring_store.keyring, "set_password") as sp:
            self.assertFalse(keyring_store.set_token("nmgrl", ""))
            sp.assert_not_called()

    def test_set_token_keyring_error_returns_false(self):
        with patch.object(keyring_store.keyring, "set_password", side_effect=KeyringError("nope")):
            self.assertFalse(keyring_store.set_token("nmgrl", "pcy_lab_xyz"))

    def test_delete_token_idempotent_on_missing(self):
        with patch.object(
            keyring_store.keyring,
            "delete_password",
            side_effect=PasswordDeleteError("not found"),
        ):
            # No exception, returns False because nothing deleted.
            self.assertFalse(keyring_store.delete_token("nmgrl"))

    def test_delete_token_success(self):
        with patch.object(keyring_store.keyring, "delete_password") as dp:
            self.assertTrue(keyring_store.delete_token("nmgrl"))
            dp.assert_called_once_with("pychron.cloud", "nmgrl")


if __name__ == "__main__":
    unittest.main()
