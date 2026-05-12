"""Tests for pychron.cloud.api_client.list_repositories (P4)."""

import unittest
from unittest.mock import MagicMock, patch

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


class ListRepositoriesTestCase(unittest.TestCase):
    def test_success_with_envelope(self):
        body = {
            "repositories": [
                {
                    "repository_identifier": "X_001",
                    "ssh_url": "git@h:lab/X.git",
                    "https_url": "https://h/lab/X.git",
                    "default_branch": "main",
                    "description": "first",
                },
                {
                    "repository_identifier": "Y_002",
                    "ssh_url": "git@h:lab/Y.git",
                    "https_url": "https://h/lab/Y.git",
                },
            ]
        }
        with patch.object(api_client.requests, "get", return_value=_resp(200, body)):
            repos = api_client.list_repositories("https://api.example", "tok", "nmgrl")
        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[0].repository_identifier, "X_001")
        self.assertEqual(repos[0].description, "first")
        self.assertEqual(repos[1].default_branch, "main")  # default fill-in

    def test_success_with_bare_list(self):
        body = [{"repository_identifier": "X_001", "ssh_url": "git@h:l/X.git"}]
        with patch.object(api_client.requests, "get", return_value=_resp(200, body)):
            repos = api_client.list_repositories("https://api.example", "tok", "nmgrl")
        self.assertEqual(len(repos), 1)

    def test_404_returns_empty_list(self):
        with patch.object(api_client.requests, "get", return_value=_resp(404)):
            repos = api_client.list_repositories("https://api.example", "tok", "nmgrl")
        self.assertEqual(repos, [])

    def test_401_raises_auth_error(self):
        with patch.object(api_client.requests, "get", return_value=_resp(401)):
            with self.assertRaises(api_client.CloudAuthError):
                api_client.list_repositories("https://api.example", "tok", "nmgrl")

    def test_403_raises_permission_error(self):
        with patch.object(api_client.requests, "get", return_value=_resp(403)):
            with self.assertRaises(api_client.CloudPermissionError):
                api_client.list_repositories("https://api.example", "tok", "nmgrl")

    def test_5xx_raises_api_error(self):
        with patch.object(api_client.requests, "get", return_value=_resp(503, text="x")):
            with self.assertRaises(api_client.CloudAPIError):
                api_client.list_repositories("https://api.example", "tok", "nmgrl")

    def test_non_list_payload_raises(self):
        body = {"repositories": "not a list"}
        with patch.object(api_client.requests, "get", return_value=_resp(200, body)):
            with self.assertRaises(api_client.CloudNetworkError):
                api_client.list_repositories("https://api.example", "tok", "nmgrl")

    def test_empty_lab_name_raises(self):
        with self.assertRaises(api_client.CloudAPIError):
            api_client.list_repositories("https://api.example", "tok", "")

    def test_url_includes_lab_path(self):
        with patch.object(
            api_client.requests, "get", return_value=_resp(200, {"repositories": []})
        ) as g:
            api_client.list_repositories("https://api.example", "tok", "nmgrl")
        called = g.call_args[0][0]
        self.assertEqual(called, "https://api.example/api/v1/forgejo/labs/nmgrl/repositories")


if __name__ == "__main__":
    unittest.main()
