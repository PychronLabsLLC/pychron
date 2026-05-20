"""Tests for WorkstationSetup.from_device_code end-to-end flow."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pychron.cloud import api_client, workstation_setup


_START_BODY = {
    "device_code": "dvc_xyz",
    "user_code": "ABCD-EFGH",
    "verification_url": "https://api.example/device",
    "verification_url_complete": "https://api.example/device?user_code=ABCD-EFGH",
    "expires_at": "2026-05-09T12:00:00Z",
    "interval_seconds": 1,
}


def _poll_body():
    return {
        "api_token": "pcy_NMGRL_xyz",
        "lab": "NMGRL",
        "api_base_url": "https://api.example",
        "default_metadata_repo": None,
        "ssh_host_alias": {
            "alias": "pychron-NMGRL",
            "real_host": "repo.example",
            "port": 2222,
            "known_hosts_line": "[repo.example]:2222 ssh-ed25519 AAAA",
        },
        "ssh_key": {
            "bot_username": "bot-NMGRL-deadbeef",
            "fingerprint": "SHA256:abc",
            "rotated": False,
            "default_metadata_repo": None,
            "ssh_host_alias": {
                "alias": "pychron-NMGRL",
                "real_host": "repo.example",
                "port": 2222,
                "known_hosts_line": "[repo.example]:2222 ssh-ed25519 AAAA",
            },
        },
    }


def _resp(status_code, body):
    r = MagicMock()
    r.status_code = status_code
    r.text = str(body)
    if body is None:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = body
    return r


class FromDeviceCodeTestCase(unittest.TestCase):
    URL = "https://api.example"

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

    def test_happy_path_pending_then_success(self):
        seen_codes = []

        def on_user_code(uc, vu, vu_complete, exp):
            seen_codes.append((uc, vu, vu_complete, exp))

        with (
            patch.object(api_client.requests, "post") as post,
            patch.object(workstation_setup, "keyring_set_token", return_value=True) as kr,
        ):
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(425, {}),  # pending
                _resp(200, _poll_body()),
            ]
            sleeps = []
            setup = workstation_setup.WorkstationSetup.from_device_code(
                self.URL,
                on_user_code=on_user_code,
                sleep=lambda s: sleeps.append(s),
                host="testhost",
            )

        # Callback fired exactly once with the user_code + URL.
        self.assertEqual(len(seen_codes), 1)
        self.assertEqual(seen_codes[0][0], "ABCD-EFGH")
        self.assertEqual(seen_codes[0][1], "https://api.example/device")

        # One sleep between pending and success (interval_seconds=1).
        self.assertEqual(sleeps, [1])

        # Returned setup populated.
        self.assertEqual(setup.api_token, "pcy_NMGRL_xyz")
        self.assertEqual(setup.lab_name, "NMGRL")
        self.assertEqual(setup.api_base_url, "https://api.example")

        # Keypair, registration.json, known_hosts, and ~/.ssh/config all written.
        priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
        self.assertTrue(os.path.isfile(priv))
        self.assertTrue(os.path.isfile(priv + ".pub"))

        reg_path = os.path.join(self.tmp, ".pychron", "registration.json")
        self.assertTrue(os.path.isfile(reg_path))
        with open(reg_path) as f:
            self.assertEqual(json.load(f)["bot_username"], "bot-NMGRL-deadbeef")

        kh = os.path.join(self.tmp, ".pychron", "known_hosts")
        with open(kh) as f:
            self.assertIn("[repo.example]:2222", f.read())

        ssh_cfg = os.path.join(self.tmp, ".ssh", "config")
        with open(ssh_cfg) as f:
            self.assertIn("Host pychron-NMGRL", f.read())

        # Keyring write happened with the right (lab, token).
        kr.assert_called_once_with("NMGRL", "pcy_NMGRL_xyz")

        # Polling endpoints hit. Start was the first call, polls came after.
        self.assertEqual(
            post.call_args_list[0][0][0],
            "https://api.example/api/v1/forgejo/device-codes",
        )
        self.assertEqual(
            post.call_args_list[1][0][0],
            "https://api.example/api/v1/forgejo/device-codes/poll",
        )
        # No Authorization header on either unauthenticated call.
        for call in post.call_args_list:
            self.assertNotIn("Authorization", call.kwargs["headers"])

    def test_denied_propagates_no_artifacts_persisted(self):
        with patch.object(api_client.requests, "post") as post:
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(403, {}),  # admin denied
            ]
            with self.assertRaises(api_client.CloudDeviceCodeDenied):
                workstation_setup.WorkstationSetup.from_device_code(
                    self.URL,
                    on_user_code=lambda *a: None,
                    sleep=lambda s: None,
                    host="testhost",
                )
        # Keypair was generated (start_device_code happened) but no
        # registration / SSH config persisted because we never reached
        # the success branch.
        priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
        self.assertTrue(os.path.isfile(priv))
        reg_path = os.path.join(self.tmp, ".pychron", "registration.json")
        self.assertFalse(os.path.isfile(reg_path))

    def test_expired_propagates(self):
        with patch.object(api_client.requests, "post") as post:
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(425, {}),
                _resp(410, {}),
            ]
            with self.assertRaises(api_client.CloudDeviceCodeExpired):
                workstation_setup.WorkstationSetup.from_device_code(
                    self.URL,
                    on_user_code=lambda *a: None,
                    sleep=lambda s: None,
                    host="testhost",
                )

    def test_should_cancel_raises_DeviceEnrollmentCancelled(self):
        ticks = {"n": 0}

        def cancel():
            ticks["n"] += 1
            return ticks["n"] >= 2  # cancel on second tick

        with patch.object(api_client.requests, "post") as post:
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(425, {}),  # pending → loop sleeps then re-checks cancel
            ]
            with self.assertRaises(workstation_setup.DeviceEnrollmentCancelled):
                workstation_setup.WorkstationSetup.from_device_code(
                    self.URL,
                    on_user_code=lambda *a: None,
                    should_cancel=cancel,
                    sleep=lambda s: None,
                    host="testhost",
                )

    def test_keyring_failure_raises_typed_error_token_not_in_str(self):
        """Single-use polling secret was already consumed; if the keyring
        write fails silently the technician would lose the credential.
        Surface as ``KeyringWriteFailedError`` whose ``__str__`` does
        NOT contain the token (so it can be safely logged) but whose
        ``.api_token`` / ``.lab_name`` attributes carry the plaintext
        for the UI to display.
        """
        with (
            patch.object(api_client.requests, "post") as post,
            patch.object(workstation_setup, "keyring_set_token", return_value=False),
        ):
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(200, _poll_body()),
            ]
            with self.assertRaises(workstation_setup.KeyringWriteFailedError) as cm:
                workstation_setup.WorkstationSetup.from_device_code(
                    self.URL,
                    on_user_code=lambda *a: None,
                    sleep=lambda s: None,
                    host="testhost",
                )
        # Token NOT leaked through str(exc) — protects log files.
        self.assertNotIn("pcy_NMGRL_xyz", str(cm.exception))
        # But available on attributes for the UI.
        self.assertEqual(cm.exception.api_token, "pcy_NMGRL_xyz")
        self.assertEqual(cm.exception.lab_name, "NMGRL")
        # Still a WorkstationSetupError subclass for any callers
        # catching the broader type.
        self.assertIsInstance(cm.exception, workstation_setup.WorkstationSetupError)

    def test_transient_502_during_poll_is_retried(self):
        """A 502 (Forgejo upstream blip during mint) leaves the
        device-code row approved + unconsumed on the server, so the
        workstation should retry instead of giving up. After a few
        retries the next poll succeeds and the enrollment completes
        normally."""
        with (
            patch.object(api_client.requests, "post") as post,
            patch.object(workstation_setup, "keyring_set_token", return_value=True),
        ):
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(425, {}),
                _resp(502, {"detail": "forgejo upstream error: ..."}),
                _resp(502, {"detail": "forgejo upstream error: ..."}),
                _resp(200, _poll_body()),
            ]
            sleeps = []
            setup = workstation_setup.WorkstationSetup.from_device_code(
                self.URL,
                on_user_code=lambda *a: None,
                sleep=lambda s: sleeps.append(s),
                host="testhost",
            )
        # Three sleeps: pending, 502, 502 — final 200 commits.
        self.assertEqual(sleeps, [1, 1, 1])
        self.assertEqual(setup.api_token, "pcy_NMGRL_xyz")

    def test_persistent_5xx_eventually_propagates(self):
        """If the upstream stays broken past the retry budget, the
        ``CloudAPIError`` must propagate so the UI can surface
        ``Enrollment failed`` rather than spinning forever."""
        # Build a side_effect long enough to trip the budget: 1 start
        # + (RETRY_LIMIT + 2) consecutive 502s.
        budget = workstation_setup._POLL_TRANSIENT_RETRY_LIMIT
        responses = [_resp(201, _START_BODY)] + [
            _resp(502, {"detail": "forgejo upstream error"}) for _ in range(budget + 2)
        ]
        with (
            patch.object(api_client.requests, "post") as post,
            patch.object(workstation_setup, "keyring_set_token", return_value=True),
        ):
            post.side_effect = responses
            with self.assertRaises(api_client.CloudAPIError):
                workstation_setup.WorkstationSetup.from_device_code(
                    self.URL,
                    on_user_code=lambda *a: None,
                    sleep=lambda s: None,
                    host="testhost",
                )

    def test_empty_api_base_url_aborts_before_any_io(self):
        with patch.object(api_client.requests, "post") as post:
            with self.assertRaises(workstation_setup.WorkstationSetupError):
                workstation_setup.WorkstationSetup.from_device_code(
                    "",
                    on_user_code=lambda *a: None,
                    sleep=lambda s: None,
                    host="testhost",
                )
        post.assert_not_called()
        priv = os.path.join(self.tmp, ".pychron", "keys", "pychron_testhost")
        self.assertFalse(os.path.isfile(priv))


if __name__ == "__main__":
    unittest.main()


class FromDeviceCodeIamCredentialsTestCase(unittest.TestCase):
    """The poll-success body now optionally carries a ``database_iam``
    bundle minted off-cluster by the admin tool. The orchestrator must
    surface it onto the returned ``WorkstationSetup`` so the prefs
    pane can persist the SA key + cloudsql_* favorite — without
    leaking the bundle into ``DeviceCodePollSuccess.raw`` (which is
    exposed for debug logs)."""

    URL = "https://api.example"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patcher = patch(
            "pychron.cloud.paths.os.path.expanduser",
            lambda p: p.replace("~", self.tmp),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        def _rmtree():
            import shutil

            shutil.rmtree(self.tmp, ignore_errors=True)

        self.addCleanup(_rmtree)

    def _iam_bundle(self):
        return {
            "instance_connection_name": "pychron-prod:us-central1:lab-db",
            "database_name": "nmgrl",
            "service_account_email": ("wkstn-x@pychron-prod.iam.gserviceaccount.com"),
            "service_account_key_json": json.dumps(
                {
                    "type": "service_account",
                    "client_email": ("wkstn-x@pychron-prod.iam.gserviceaccount.com"),
                    "private_key": (
                        "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"
                    ),
                }
            ),
            "ip_type": "public",
        }

    def _poll_body_with_iam(self):
        body = _poll_body()
        body["database_iam"] = self._iam_bundle()
        return body

    def test_iam_bundle_propagates_to_setup(self):
        with (
            patch.object(api_client.requests, "post") as post,
            patch.object(workstation_setup, "keyring_set_token", return_value=True),
        ):
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(200, self._poll_body_with_iam()),
            ]
            setup = workstation_setup.WorkstationSetup.from_device_code(
                self.URL,
                on_user_code=lambda *a: None,
                sleep=lambda s: None,
                host="testhost",
            )
        self.assertIsNotNone(setup.database_iam)
        self.assertEqual(
            setup.database_iam["instance_connection_name"],
            "pychron-prod:us-central1:lab-db",
        )
        self.assertEqual(
            setup.database_iam["service_account_email"],
            "wkstn-x@pychron-prod.iam.gserviceaccount.com",
        )

    def test_no_iam_bundle_leaves_setup_attr_none(self):
        with (
            patch.object(api_client.requests, "post") as post,
            patch.object(workstation_setup, "keyring_set_token", return_value=True),
        ):
            post.side_effect = [
                _resp(201, _START_BODY),
                _resp(200, _poll_body()),  # no database_iam
            ]
            setup = workstation_setup.WorkstationSetup.from_device_code(
                self.URL,
                on_user_code=lambda *a: None,
                sleep=lambda s: None,
                host="testhost",
            )
        self.assertIsNone(setup.database_iam)

    def test_database_iam_stripped_from_raw_debug_field(self):
        """The SA private key embedded in ``database_iam`` must not
        survive into the ``raw`` dict that callers may log for
        debugging — same defensive treatment we give ``api_token``."""
        with patch.object(api_client.requests, "post") as post:
            post.side_effect = [_resp(200, self._poll_body_with_iam())]
            success = api_client.poll_device_code(self.URL, "dvc_xyz")
        self.assertNotIn("database_iam", success.raw)
        self.assertNotIn("api_token", success.raw)
        # But the typed attribute carries the bundle for the orchestrator.
        self.assertEqual(
            success.database_iam["service_account_email"],
            "wkstn-x@pychron-prod.iam.gserviceaccount.com",
        )
