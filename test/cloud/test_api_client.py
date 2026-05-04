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


if __name__ == "__main__":
    unittest.main()
