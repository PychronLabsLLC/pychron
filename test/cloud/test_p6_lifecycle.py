"""Tests for P6: revoke / reonboard / switch_lab + prefs-pane wiring."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from apptools.preferences.api import Preferences, set_default_preferences

from pychron.cloud import api_client, workstation_setup
from pychron.cloud.tasks.preferences import CloudPreferences


def _resp(status_code, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    if json_body is None:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = json_body
    return r


def _registration():
    return api_client.SSHKeyRegistration(
        bot_username="bot",
        fingerprint="SHA256:x",
        default_metadata_repo="lab/MetaData",
        ssh_host_alias={
            "alias": "pychron-nmgrl",
            "real_host": "forgejo.example",
            "port": 2222,
            "known_hosts_line": "[forgejo.example]:2222 ssh-ed25519 AAAA",
        },
        raw={
            "bot_username": "bot",
            "fingerprint": "SHA256:x",
            "default_metadata_repo": "lab/MetaData",
            "ssh_host_alias": {
                "alias": "pychron-nmgrl",
                "real_host": "forgejo.example",
                "port": 2222,
                "known_hosts_line": "[forgejo.example]:2222 ssh-ed25519 AAAA",
            },
        },
    )


class _BaseFSTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(self._rmtree, self.tmp)
        self._patcher = patch(
            "pychron.cloud.paths.os.path.expanduser",
            lambda p: p.replace("~", self.tmp),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _rmtree(self, path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def _stub_register(self, **kw):
        return patch.object(workstation_setup, "register_ssh_key", **kw)


# -- api_client.revoke_workstation_token ----------------------------------


class RevokeTokenAPITestCase(unittest.TestCase):
    def test_204_returns_true(self):
        with patch.object(api_client.requests, "delete", return_value=_resp(204)):
            self.assertTrue(api_client.revoke_workstation_token("https://api.example", "tok"))

    def test_200_returns_true(self):
        with patch.object(api_client.requests, "delete", return_value=_resp(200, {"ok": True})):
            self.assertTrue(api_client.revoke_workstation_token("https://api.example", "tok"))

    def test_401_treated_as_already_revoked(self):
        with patch.object(api_client.requests, "delete", return_value=_resp(401)):
            self.assertTrue(api_client.revoke_workstation_token("https://api.example", "tok"))

    def test_404_treated_as_already_revoked(self):
        with patch.object(api_client.requests, "delete", return_value=_resp(404)):
            self.assertTrue(api_client.revoke_workstation_token("https://api.example", "tok"))

    def test_500_raises(self):
        with patch.object(api_client.requests, "delete", return_value=_resp(500, text="boom")):
            with self.assertRaises(api_client.CloudAPIError):
                api_client.revoke_workstation_token("https://api.example", "tok")

    def test_transport_error_raises_network_error(self):
        import requests

        with patch.object(
            api_client.requests,
            "delete",
            side_effect=requests.ConnectionError("dns"),
        ):
            with self.assertRaises(api_client.CloudNetworkError):
                api_client.revoke_workstation_token("https://api.example", "tok")

    def test_empty_token_returns_true_without_call(self):
        with patch.object(api_client.requests, "delete") as d:
            self.assertTrue(api_client.revoke_workstation_token("https://api.example", ""))
            d.assert_not_called()


# -- WorkstationSetup.reonboard / revoke_and_wipe / wipe_local_state ------


class ReonboardTestCase(_BaseFSTestCase):
    def test_reonboard_rotates_key(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            host="testhost",
        )
        with self._stub_register(return_value=_registration()):
            ws.run()
        priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
        with open(priv, "rb") as f:
            first = f.read()

        with self._stub_register(return_value=_registration()):
            ws.reonboard()

        with open(priv, "rb") as f:
            self.assertNotEqual(first, f.read())

    def test_reonboard_replaces_alias_block_when_alias_changes(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            host="testhost",
        )
        with self._stub_register(return_value=_registration()):
            ws.run()

        # New registration uses a different alias.
        new_reg = api_client.SSHKeyRegistration(
            bot_username="bot2",
            fingerprint="SHA256:y",
            default_metadata_repo="lab/MetaData",
            ssh_host_alias={
                "alias": "pychron-newlab",
                "real_host": "forgejo.example",
                "port": 2222,
                "known_hosts_line": "[forgejo.example]:2222 ssh-ed25519 BBBB",
            },
            raw={
                "ssh_host_alias": {
                    "alias": "pychron-newlab",
                    "real_host": "forgejo.example",
                    "port": 2222,
                    "known_hosts_line": "[forgejo.example]:2222 ssh-ed25519 BBBB",
                }
            },
        )
        with self._stub_register(return_value=new_reg):
            ws.reonboard()

        sshc = os.path.join(self.tmp, ".ssh", "config")
        with open(sshc) as f:
            body = f.read()
        self.assertIn("Host pychron-newlab", body)
        self.assertNotIn("Host pychron-nmgrl", body)


class RevokeAndWipeTestCase(_BaseFSTestCase):
    def _onboard(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            host="testhost",
        )
        with self._stub_register(return_value=_registration()):
            ws.run()
        return ws

    def _assert_wiped(self):
        priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
        kh = os.path.join(self.tmp, ".pychron", "known_hosts")
        reg = os.path.join(self.tmp, ".pychron", "registration.json")
        sshc = os.path.join(self.tmp, ".ssh", "config")
        self.assertFalse(os.path.isfile(priv))
        self.assertFalse(os.path.isfile(kh))
        self.assertFalse(os.path.isfile(reg))
        if os.path.isfile(sshc):
            with open(sshc) as f:
                self.assertNotIn("pychron-nmgrl", f.read())

    def test_revoke_and_wipe_wipes_local_state_on_success(self):
        ws = self._onboard()
        with patch.object(workstation_setup, "revoke_workstation_token", return_value=True):
            ws.revoke_and_wipe()
        self._assert_wiped()

    def test_revoke_and_wipe_wipes_local_state_even_when_server_fails(self):
        ws = self._onboard()
        with patch.object(
            workstation_setup,
            "revoke_workstation_token",
            side_effect=api_client.CloudNetworkError("boom"),
        ):
            with self.assertRaises(api_client.CloudNetworkError):
                ws.revoke_and_wipe()
        # Local state still wiped.
        self._assert_wiped()


class SwitchLabTestCase(_BaseFSTestCase):
    def test_switch_lab_wipes_projects_dir_too(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            host="testhost",
        )
        with self._stub_register(return_value=_registration()):
            ws.run()
        # Plant a fake project clone.
        proj = os.path.join(self.tmp, "Pychron", "projects", "X_001")
        os.makedirs(proj)
        with open(os.path.join(proj, "marker"), "w") as f:
            f.write("x")

        workstation_setup.switch_lab(host="testhost")

        self.assertFalse(os.path.isdir(proj))
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, "Pychron", "projects")))


# -- prefs pane button wiring --------------------------------------------


class _FakeKeyring(object):
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


class PrefsPaneButtonsTestCase(_BaseFSTestCase):
    def setUp(self):
        super().setUp()
        set_default_preferences(Preferences())
        self.fake_kr = _FakeKeyring()
        self._kp = patch("pychron.cloud.keyring_store.keyring", self.fake_kr)
        self._kp.start()
        self.addCleanup(self._kp.stop)

    def _build(self):
        h = CloudPreferences(
            api_base_url="https://api.example",
            lab_name="nmgrl",
        )
        h.api_token = "tok"
        return h

    def test_reonboard_button_uses_workstation_setup(self):
        h = self._build()
        ws = MagicMock()
        with patch.object(h, "_build_setup", return_value=ws):
            h._reonboard_button_fired()
        ws.reonboard.assert_called_once()
        self.assertEqual(h._remote_status, "Re-onboarded")

    def test_reonboard_button_surfaces_401(self):
        h = self._build()
        ws = MagicMock()
        ws.reonboard.side_effect = api_client.CloudAuthError("nope")
        with patch.object(h, "_build_setup", return_value=ws):
            h._reonboard_button_fired()
        self.assertIn("401", h._remote_status)

    def test_reonboard_button_requires_inputs(self):
        h = CloudPreferences()
        h._reonboard_button_fired()
        self.assertEqual(h._remote_status, "Need URL, token, and lab")

    def test_revoke_button_aborts_when_user_declines(self):
        h = self._build()
        ws = MagicMock()
        with (
            patch(
                "pychron.cloud.tasks.preferences.confirmation_dialog",
                return_value=False,
            ),
            patch.object(h, "_build_setup", return_value=ws),
        ):
            h._revoke_button_fired()
        ws.revoke_and_wipe.assert_not_called()

    def test_revoke_button_clears_keyring_and_token(self):
        h = self._build()
        # Token already in fake keyring via _api_token_changed.
        self.assertEqual(self.fake_kr._store.get(("pychron.cloud", "nmgrl")), "tok")
        ws = MagicMock()
        with (
            patch(
                "pychron.cloud.tasks.preferences.confirmation_dialog",
                return_value=True,
            ),
            patch.object(h, "_build_setup", return_value=ws),
        ):
            h._revoke_button_fired()
        ws.revoke_and_wipe.assert_called_once()
        self.assertNotIn(("pychron.cloud", "nmgrl"), self.fake_kr._store)
        self.assertEqual(h.api_token, "")

    def test_switch_lab_button_aborts_when_user_declines(self):
        h = self._build()
        with (
            patch(
                "pychron.cloud.tasks.preferences.confirmation_dialog",
                return_value=False,
            ),
            patch("pychron.cloud.tasks.preferences.wipe_for_switch_lab") as wipe,
        ):
            h._switch_lab_button_fired()
        wipe.assert_not_called()

    def test_switch_lab_button_wipes_local_state_and_clears_prefs(self):
        h = self._build()
        with (
            patch(
                "pychron.cloud.tasks.preferences.confirmation_dialog",
                return_value=True,
            ),
            patch("pychron.cloud.tasks.preferences.wipe_for_switch_lab") as wipe,
        ):
            h._switch_lab_button_fired()
        wipe.assert_called_once()
        self.assertEqual(h.api_token, "")
        self.assertEqual(h.lab_name, "")
        self.assertEqual(h.api_base_url, "")
        self.assertNotIn(("pychron.cloud", "nmgrl"), self.fake_kr._store)


if __name__ == "__main__":
    unittest.main()
