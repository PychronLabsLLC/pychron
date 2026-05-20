"""End-to-end tests for pychron.cloud.workstation_setup.WorkstationSetup."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud import api_client, workstation_setup


def _registration(alias="pychron-nmgrl"):
    return api_client.SSHKeyRegistration(
        bot_username="lab-nmgrl-bot",
        fingerprint="SHA256:xxx",
        default_metadata_repo="lab-nmgrl/MetaData",
        ssh_host_alias={
            "alias": alias,
            "real_host": "forgejo.example",
            "port": 2222,
            "known_hosts_line": "[forgejo.example]:2222 ssh-ed25519 AAAAC3...",
        },
        raw={
            "bot_username": "lab-nmgrl-bot",
            "fingerprint": "SHA256:xxx",
            "default_metadata_repo": "lab-nmgrl/MetaData",
            "ssh_host_alias": {
                "alias": alias,
                "real_host": "forgejo.example",
                "port": 2222,
                "known_hosts_line": "[forgejo.example]:2222 ssh-ed25519 AAAAC3...",
            },
        },
    )


class WorkstationSetupTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Redirect ~ → tmp so ~/.pychron and ~/.ssh land in scratch space.
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

    def _stub_register(self, **kw):
        return patch.object(workstation_setup, "register_ssh_key", **kw)

    def test_full_run_writes_all_artifacts(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="pcy_nmgrl_xyz",
            lab_name="nmgrl",
            host="testhost",
        )
        with self._stub_register(return_value=_registration()):
            raw = ws.run()

        self.assertEqual(raw["bot_username"], "lab-nmgrl-bot")

        # Keypair on disk.
        priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
        self.assertTrue(os.path.isfile(priv))
        self.assertTrue(os.path.isfile(priv + ".pub"))

        # Registration persisted.
        reg_path = os.path.join(self.tmp, ".pychron", "registration.json")
        self.assertTrue(os.path.isfile(reg_path))
        with open(reg_path) as f:
            self.assertEqual(json.load(f)["bot_username"], "lab-nmgrl-bot")

        # known_hosts has the line.
        kh = os.path.join(self.tmp, ".pychron", "known_hosts")
        with open(kh) as f:
            self.assertIn("forgejo.example", f.read())

        # ~/.ssh/config has the block.
        sshc = os.path.join(self.tmp, ".ssh", "config")
        with open(sshc) as f:
            body = f.read()
        self.assertIn("Host pychron-nmgrl", body)
        self.assertIn("Port 2222", body)
        self.assertIn("IdentityFile ", body)

    def test_run_is_idempotent_on_repeat(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="pcy_nmgrl_xyz",
            lab_name="nmgrl",
            host="testhost",
        )
        with self._stub_register(return_value=_registration()):
            ws.run()
            priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
            with open(priv, "rb") as f:
                priv_first = f.read()
            sshc = os.path.join(self.tmp, ".ssh", "config")
            with open(sshc) as f:
                config_first = f.read()
            ws.run()
            with open(priv, "rb") as f:
                self.assertEqual(priv_first, f.read())
            with open(sshc) as f:
                self.assertEqual(config_first, f.read())

    def test_fingerprint_rejected_rotates_key_and_retries(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="pcy_nmgrl_xyz",
            lab_name="nmgrl",
            host="testhost",
        )
        # First call: write a stale keypair so we can detect rotation.
        from pychron.cloud import ssh_keygen

        priv_path, pub_path = ssh_keygen.generate_keypair("testhost")
        with open(priv_path, "rb") as f:
            stale_priv = f.read()

        with self._stub_register(
            side_effect=[
                api_client.CloudFingerprintRejected("dup"),
                _registration(),
            ]
        ) as stub:
            ws.run()
            self.assertEqual(stub.call_count, 2)

        with open(priv_path, "rb") as f:
            self.assertNotEqual(stale_priv, f.read())

    def test_missing_token_aborts(self):
        ws = workstation_setup.WorkstationSetup(
            api_base_url="https://api.example",
            api_token="",
            lab_name="nmgrl",
            host="testhost",
        )
        with self.assertRaises(workstation_setup.WorkstationSetupError):
            ws.run()

    def test_load_registration_returns_none_when_absent(self):
        self.assertIsNone(workstation_setup.load_registration())


class APIClientRegisterTestCase(unittest.TestCase):
    """Cover register_ssh_key error mapping."""

    def _resp(self, status_code, json_body=None, text=""):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.status_code = status_code
        r.text = text
        if json_body is None:
            r.json.side_effect = ValueError("not json")
        else:
            r.json.return_value = json_body
        return r

    def test_success(self):
        body = {
            "bot_username": "bot",
            "fingerprint": "SHA256:x",
            "default_metadata_repo": "lab/MetaData",
            "ssh_host_alias": {
                "alias": "pychron-nmgrl",
                "real_host": "h",
                "port": 22,
                "known_hosts_line": "h ssh-ed25519 AAAA",
            },
        }
        with patch.object(api_client.requests, "post", return_value=self._resp(201, body)):
            reg = api_client.register_ssh_key(
                "https://api.example", "tok", "ssh-ed25519 AAAA pychron-x"
            )
        self.assertEqual(reg.bot_username, "bot")
        self.assertEqual(reg.alias, "pychron-nmgrl")

    def test_401_maps_to_auth_error(self):
        with patch.object(api_client.requests, "post", return_value=self._resp(401, text="x")):
            with self.assertRaises(api_client.CloudAuthError):
                api_client.register_ssh_key("https://api.example", "tok", "ssh-ed25519 AAAA")

    def test_403_maps_to_permission_error(self):
        with patch.object(api_client.requests, "post", return_value=self._resp(403, text="x")):
            with self.assertRaises(api_client.CloudPermissionError):
                api_client.register_ssh_key("https://api.example", "tok", "ssh-ed25519 AAAA")

    def test_409_maps_to_fingerprint_rejected(self):
        with patch.object(api_client.requests, "post", return_value=self._resp(409, text="dup")):
            with self.assertRaises(api_client.CloudFingerprintRejected):
                api_client.register_ssh_key("https://api.example", "tok", "ssh-ed25519 AAAA")

    def test_422_maps_to_fingerprint_rejected(self):
        with patch.object(
            api_client.requests, "post", return_value=self._resp(422, text="bad key")
        ):
            with self.assertRaises(api_client.CloudFingerprintRejected):
                api_client.register_ssh_key("https://api.example", "tok", "ssh-ed25519 AAAA")

    def test_empty_public_key_raises(self):
        with self.assertRaises(api_client.CloudAPIError):
            api_client.register_ssh_key("https://api.example", "tok", "")


if __name__ == "__main__":
    unittest.main()
