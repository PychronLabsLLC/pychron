"""Unit tests for pychron.cloud.tasks.preferences.CloudPreferences.

Covers:

- API token round-trips through the OS keyring helpers (never to .cfg).
- Switching ``lab_name`` reloads the matching keyring slot.
- The "Test Connection" button surfaces 401, scope, and lab-mismatch
  states.
"""

import unittest
from unittest.mock import patch

from apptools.preferences.api import Preferences, set_default_preferences

from pychron.cloud import api_client
from pychron.cloud.tasks.preferences import CloudPreferences


class _FakeKeyring(object):
    """In-memory replacement for :mod:`keyring` so tests do not touch the
    real OS credential store.
    """

    def __init__(self):
        self._store = {}

    def get_password(self, service, account):
        return self._store.get((service, account))

    def set_password(self, service, account, password):
        self._store[(service, account)] = password

    def delete_password(self, service, account):
        try:
            del self._store[(service, account)]
        except KeyError:
            from keyring.errors import PasswordDeleteError

            raise PasswordDeleteError("not found")


class CloudPreferencesTestCase(unittest.TestCase):
    def setUp(self):
        set_default_preferences(Preferences())
        self.fake = _FakeKeyring()
        self._patcher = patch("pychron.cloud.keyring_store.keyring", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _build(self, **kw):
        return CloudPreferences(**kw)

    # -- token persistence --------------------------------------------

    def test_api_token_is_not_a_preference_trait(self):
        helper = self._build()
        self.assertFalse(helper._is_preference_trait("api_token"))

    def test_api_token_writes_to_keyring(self):
        helper = self._build(lab_name="nmgrl")
        helper.api_token = "pcy_nmgrl_xyz"
        self.assertEqual(self.fake._store.get(("pychron.cloud", "nmgrl")), "pcy_nmgrl_xyz")

    def test_api_token_without_lab_name_is_not_stored(self):
        helper = self._build()
        helper.api_token = "pcy_unknown_xyz"
        self.assertEqual(self.fake._store, {})
        self.assertEqual(helper._remote_status, "Set lab_name first")

    def test_api_token_clear_deletes_keyring_entry(self):
        helper = self._build(lab_name="nmgrl")
        helper.api_token = "pcy_nmgrl_xyz"
        helper.api_token = ""
        self.assertNotIn(("pychron.cloud", "nmgrl"), self.fake._store)

    def test_initialize_loads_token_from_keyring(self):
        # Pre-populate the fake keyring under the lab account.
        self.fake._store[("pychron.cloud", "nmgrl")] = "pcy_nmgrl_existing"
        helper = self._build(lab_name="nmgrl")
        self.assertEqual(helper.api_token, "pcy_nmgrl_existing")

    def test_lab_name_change_reloads_token_for_new_lab(self):
        self.fake._store[("pychron.cloud", "nmgrl")] = "tok_nmgrl"
        self.fake._store[("pychron.cloud", "ucla")] = "tok_ucla"
        helper = self._build(lab_name="nmgrl")
        self.assertEqual(helper.api_token, "tok_nmgrl")
        helper.lab_name = "ucla"
        self.assertEqual(helper.api_token, "tok_ucla")

    # -- test_connection button ---------------------------------------

    def _stub_whoami(self, **kw):
        return patch.object(
            __import__("pychron.cloud.tasks.preferences", fromlist=["whoami"]),
            "whoami",
            **kw,
        )

    def test_test_connection_no_url(self):
        helper = self._build(lab_name="nmgrl")
        helper.api_token = "pcy_nmgrl_xyz"
        helper._test_connection_fired()
        self.assertEqual(helper._remote_status, "No URL")

    def test_test_connection_no_token(self):
        helper = self._build(lab_name="nmgrl", api_base_url="https://api.example")
        helper._test_connection_fired()
        self.assertEqual(helper._remote_status, "No token")

    def test_test_connection_401(self):
        helper = self._build(lab_name="nmgrl", api_base_url="https://api.example")
        helper.api_token = "pcy_nmgrl_xyz"
        with self._stub_whoami(side_effect=api_client.CloudAuthError("401")):
            helper._test_connection_fired()
        self.assertEqual(helper._remote_status, "401 Unauthorized")

    def test_test_connection_unreachable(self):
        helper = self._build(lab_name="nmgrl", api_base_url="https://api.example")
        helper.api_token = "pcy_nmgrl_xyz"
        with self._stub_whoami(side_effect=api_client.CloudNetworkError("dns")):
            helper._test_connection_fired()
        self.assertEqual(helper._remote_status, "Unreachable")

    def test_test_connection_lab_mismatch(self):
        helper = self._build(lab_name="nmgrl", api_base_url="https://api.example")
        helper.api_token = "pcy_nmgrl_xyz"
        info = api_client.WhoAmI(
            kind="user_token",
            scopes=["workstations:register_ssh_key"],
            lab="ucla",
            raw={},
        )
        with self._stub_whoami(return_value=info):
            helper._test_connection_fired()
        self.assertEqual(helper._remote_status, "Lab mismatch (ucla)")

    def test_test_connection_missing_scope(self):
        helper = self._build(lab_name="nmgrl", api_base_url="https://api.example")
        helper.api_token = "pcy_nmgrl_xyz"
        info = api_client.WhoAmI(
            kind="user_token",
            scopes=["other:scope"],
            lab="nmgrl",
            raw={},
        )
        with self._stub_whoami(return_value=info):
            helper._test_connection_fired()
        self.assertIn("Missing scope", helper._remote_status)
        self.assertIn("other:scope", helper._remote_status)

    def test_test_connection_ok(self):
        helper = self._build(lab_name="nmgrl", api_base_url="https://api.example")
        helper.api_token = "pcy_nmgrl_xyz"
        info = api_client.WhoAmI(
            kind="user_token",
            scopes=["workstations:register_ssh_key"],
            lab="nmgrl",
            raw={},
        )
        with self._stub_whoami(return_value=info):
            helper._test_connection_fired()
        self.assertTrue(helper._remote_status.startswith("OK"))


if __name__ == "__main__":
    unittest.main()
