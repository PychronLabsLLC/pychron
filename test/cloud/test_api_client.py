"""Unit tests for pychron.cloud.api_client."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from pychron.cloud import api_client


def _resp(status_code=200, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    if json_body is None:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = json_body
    return r


class TestWhoAmI(unittest.TestCase):
    def test_success_parses_payload(self):
        body = {
            "kind": "user_token",
            "scopes": ["workstations:register_ssh_key"],
            "lab": "nmgrl",
        }
        with patch.object(api_client.requests, "get", return_value=_resp(200, body)):
            info = api_client.whoami("https://api.example", "pcy_nmgrl_x")
        self.assertEqual(info.kind, "user_token")
        self.assertEqual(info.lab, "nmgrl")
        self.assertTrue(info.can_register_ssh_key())

    def test_success_strips_trailing_slash(self):
        body = {"kind": "user_token", "scopes": [], "lab": "nmgrl"}
        with patch.object(api_client.requests, "get", return_value=_resp(200, body)) as g:
            api_client.whoami("https://api.example/", "pcy_nmgrl_x")
        called_url = g.call_args[0][0]
        self.assertEqual(called_url, "https://api.example/api/v1/forgejo/whoami")

    def test_401_raises_auth_error(self):
        with patch.object(api_client.requests, "get", return_value=_resp(401, text="nope")):
            with self.assertRaises(api_client.CloudAuthError):
                api_client.whoami("https://api.example", "pcy_nmgrl_x")

    def test_403_raises_api_error_not_auth(self):
        with patch.object(
            api_client.requests, "get", return_value=_resp(403, {"detail": "forbidden"})
        ):
            with self.assertRaises(api_client.CloudAPIError) as cm:
                api_client.whoami("https://api.example", "pcy_nmgrl_x")
            self.assertNotIsInstance(cm.exception, api_client.CloudAuthError)

    def test_transport_error_raises_network_error(self):
        with patch.object(
            api_client.requests,
            "get",
            side_effect=requests.ConnectionError("boom"),
        ):
            with self.assertRaises(api_client.CloudNetworkError):
                api_client.whoami("https://api.example", "pcy_nmgrl_x")

    def test_non_json_body_raises_network_error(self):
        with patch.object(api_client.requests, "get", return_value=_resp(200, None)):
            with self.assertRaises(api_client.CloudNetworkError):
                api_client.whoami("https://api.example", "pcy_nmgrl_x")

    def test_empty_token_raises_auth_error(self):
        with self.assertRaises(api_client.CloudAuthError):
            api_client.whoami("https://api.example", "")

    def test_empty_url_raises_api_error(self):
        with self.assertRaises(api_client.CloudAPIError):
            api_client.whoami("", "pcy_nmgrl_x")

    def test_can_register_ssh_key_false_when_scope_missing(self):
        info = api_client.WhoAmI(kind="user_token", scopes=["other"], lab="nmgrl", raw={})
        self.assertFalse(info.can_register_ssh_key())


_START_BODY = {
    "device_code": "dvc_xyz",
    "user_code": "ABCD-EFGH",
    "verification_url": "https://api.example/device",
    "verification_url_complete": "https://api.example/device?user_code=ABCD-EFGH",
    "expires_at": "2026-05-09T12:00:00Z",
    "interval_seconds": 5,
}


def _poll_body(**overrides):
    body = {
        "api_token": "pcy_NMGRL_xyz",
        "lab": "NMGRL",
        "api_base_url": "https://api.example",
        "default_metadata_repo": None,
        "ssh_host_alias": {
            "alias": "pychron-NMGRL",
            "real_host": "repo.example",
            "port": 222,
            "known_hosts_line": "repo.example ssh-rsa AAAA",
        },
        "ssh_key": {
            "bot_username": "bot-NMGRL-deadbeef",
            "fingerprint": "SHA256:abc",
            "rotated": False,
            "default_metadata_repo": None,
            "ssh_host_alias": {
                "alias": "pychron-NMGRL",
                "real_host": "repo.example",
                "port": 222,
                "known_hosts_line": "repo.example ssh-rsa AAAA",
            },
        },
    }
    body.update(overrides)
    return body


class TestStartDeviceCode(unittest.TestCase):
    URL = "https://api.example"
    PUBKEY = "ssh-ed25519 AAAA test@host"
    HOST = "lab-mac-01"

    def _call(self):
        return api_client.start_device_code(self.URL, self.PUBKEY, self.HOST)

    def test_success_returns_start_result(self):
        with patch.object(api_client.requests, "post", return_value=_resp(201, _START_BODY)):
            r = self._call()
        self.assertEqual(r.device_code, "dvc_xyz")
        self.assertEqual(r.user_code, "ABCD-EFGH")
        self.assertEqual(r.verification_url, "https://api.example/device")
        self.assertEqual(r.interval_seconds, 5)

    def test_post_url_matches_endpoint(self):
        with patch.object(api_client.requests, "post", return_value=_resp(201, _START_BODY)) as p:
            self._call()
        self.assertEqual(
            p.call_args[0][0],
            "https://api.example/api/v1/forgejo/device-codes",
        )

    def test_no_authorization_header(self):
        """Endpoint is unauthenticated. Sending a stale Authorization header
        could leak it on misconfigured proxies; client must omit one."""
        with patch.object(api_client.requests, "post", return_value=_resp(201, _START_BODY)) as p:
            self._call()
        headers = p.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("authorization", {k.lower() for k in headers})

    def test_400_raises_fingerprint_rejected(self):
        with patch.object(api_client.requests, "post", return_value=_resp(400, {"detail": "bad"})):
            with self.assertRaises(api_client.CloudFingerprintRejected):
                self._call()

    def test_500_raises_api_error(self):
        with patch.object(api_client.requests, "post", return_value=_resp(500, {"detail": "boom"})):
            with self.assertRaises(api_client.CloudAPIError):
                self._call()

    def test_transport_error_raises_network_error(self):
        with patch.object(
            api_client.requests,
            "post",
            side_effect=requests.ConnectionError("boom"),
        ):
            with self.assertRaises(api_client.CloudNetworkError):
                self._call()

    def test_non_json_body_raises_network_error(self):
        with patch.object(api_client.requests, "post", return_value=_resp(201, None)):
            with self.assertRaises(api_client.CloudNetworkError):
                self._call()

    def test_empty_args_raise_api_error(self):
        for args in [
            ("", self.PUBKEY, self.HOST),
            (self.URL, "", self.HOST),
            (self.URL, self.PUBKEY, ""),
        ]:
            with self.assertRaises(api_client.CloudAPIError):
                api_client.start_device_code(*args)

    def test_secrets_stripped_from_raw(self):
        """``DeviceCodeStart.raw`` is exposed for debugging. Both the
        device_code (polling secret) and the user_code (admin-facing
        but not meant for logs) must be stripped."""
        with patch.object(api_client.requests, "post", return_value=_resp(201, _START_BODY)):
            r = self._call()
        self.assertNotIn("device_code", r.raw)
        self.assertNotIn("user_code", r.raw)
        self.assertIn("verification_url", r.raw)


class TestPollDeviceCode(unittest.TestCase):
    URL = "https://api.example"
    DEVICE_CODE = "dvc_xyz"

    def _call(self):
        return api_client.poll_device_code(self.URL, self.DEVICE_CODE)

    def test_success_returns_poll_result(self):
        with patch.object(api_client.requests, "post", return_value=_resp(200, _poll_body())):
            r = self._call()
        self.assertEqual(r.api_token, "pcy_NMGRL_xyz")
        self.assertEqual(r.lab, "NMGRL")
        self.assertEqual(r.api_base_url, "https://api.example")
        self.assertEqual(r.ssh_key.bot_username, "bot-NMGRL-deadbeef")
        self.assertEqual(r.ssh_key.alias, "pychron-NMGRL")
        self.assertEqual(r.ssh_key.port, 222)

    def test_post_url_matches_endpoint(self):
        with patch.object(api_client.requests, "post", return_value=_resp(200, _poll_body())) as p:
            self._call()
        self.assertEqual(
            p.call_args[0][0],
            "https://api.example/api/v1/forgejo/device-codes/poll",
        )

    def test_no_authorization_header(self):
        with patch.object(api_client.requests, "post", return_value=_resp(200, _poll_body())) as p:
            self._call()
        headers = p.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_425_raises_pending(self):
        with patch.object(api_client.requests, "post", return_value=_resp(425, {})):
            with self.assertRaises(api_client.CloudDeviceCodePending):
                self._call()

    def test_403_raises_denied(self):
        with patch.object(api_client.requests, "post", return_value=_resp(403, {})):
            with self.assertRaises(api_client.CloudDeviceCodeDenied):
                self._call()

    def test_410_raises_expired(self):
        with patch.object(api_client.requests, "post", return_value=_resp(410, {})):
            with self.assertRaises(api_client.CloudDeviceCodeExpired):
                self._call()

    def test_400_raises_fingerprint_rejected(self):
        with patch.object(api_client.requests, "post", return_value=_resp(400, {})):
            with self.assertRaises(api_client.CloudFingerprintRejected):
                self._call()

    def test_500_raises_api_error(self):
        with patch.object(api_client.requests, "post", return_value=_resp(500, {})):
            with self.assertRaises(api_client.CloudAPIError) as cm:
                self._call()
            # Make sure 5xx isn't accidentally caught as one of the
            # device-code-specific subclasses.
            self.assertNotIsInstance(cm.exception, api_client.CloudDeviceCodePending)
            self.assertNotIsInstance(cm.exception, api_client.CloudDeviceCodeDenied)
            self.assertNotIsInstance(cm.exception, api_client.CloudDeviceCodeExpired)

    def test_transport_error_raises_network_error(self):
        with patch.object(
            api_client.requests, "post", side_effect=requests.ConnectionError("boom")
        ):
            with self.assertRaises(api_client.CloudNetworkError):
                self._call()

    def test_non_json_body_raises_network_error(self):
        with patch.object(api_client.requests, "post", return_value=_resp(200, None)):
            with self.assertRaises(api_client.CloudNetworkError):
                self._call()

    def test_empty_args_raise_api_error(self):
        for args in [("", self.DEVICE_CODE), (self.URL, "")]:
            with self.assertRaises(api_client.CloudAPIError):
                api_client.poll_device_code(*args)

    def test_api_token_stripped_from_raw(self):
        """``DeviceCodePollSuccess.raw`` is exposed for debugging. The
        plaintext bearer token must NOT be in it — only on the dedicated
        `.api_token` attribute that callers treat as a secret."""
        with patch.object(api_client.requests, "post", return_value=_resp(200, _poll_body())):
            r = self._call()
        self.assertEqual(r.api_token, "pcy_NMGRL_xyz")
        self.assertNotIn("api_token", r.raw)

    def test_falls_back_to_caller_base_url_when_server_omits_it(self):
        body = _poll_body()
        body.pop("api_base_url")
        with patch.object(api_client.requests, "post", return_value=_resp(200, body)):
            r = self._call()
        self.assertEqual(r.api_base_url, self.URL)


if __name__ == "__main__":
    unittest.main()
