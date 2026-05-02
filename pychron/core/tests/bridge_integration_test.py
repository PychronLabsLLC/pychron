# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
"""Integration tests against a live Pychron Forgejo Bridge.

These tests only run when ``PYCHRON_BRIDGE_INTEGRATION=1`` is set in the
environment, alongside the bridge connection variables below. They are
skipped by default so unit-test runs (CI, local) stay hermetic.

Read-side env (required when integration is enabled):
    PYCHRON_BRIDGE_BASE_URL          Cloud Run URL of the bridge
    PYCHRON_BRIDGE_BEARER_TOKEN      lab-scoped bridge bearer
    PYCHRON_BRIDGE_SA_KEY_PATH       path to the GCP service-account JSON
    PYCHRON_BRIDGE_LAB_NAME          lab name the bearer is scoped to
    PYCHRON_BRIDGE_TEST_REPO         existing repository_identifier in the lab

Write-side env (additional opt-in for ensure_repository):
    PYCHRON_BRIDGE_INTEGRATION_WRITE=1

The write test creates a uniquely-suffixed repository through the bridge.
The bridge currently exposes no delete endpoint, so the artifact persists
in Forgejo until removed manually.
"""

from __future__ import absolute_import

import os
import unittest
import uuid

from pychron.git.hosts._bridge_client import (
    BridgeAuthError,
    BridgeClient,
    BridgeError,
)
from pychron.git.hosts.bridge import BridgeService

_INTEGRATION_FLAG = "PYCHRON_BRIDGE_INTEGRATION"
_WRITE_FLAG = "PYCHRON_BRIDGE_INTEGRATION_WRITE"

_REQUIRED_ENV = (
    "PYCHRON_BRIDGE_BASE_URL",
    "PYCHRON_BRIDGE_BEARER_TOKEN",
    "PYCHRON_BRIDGE_SA_KEY_PATH",
    "PYCHRON_BRIDGE_LAB_NAME",
    "PYCHRON_BRIDGE_TEST_REPO",
)


def _integration_enabled():
    if os.environ.get(_INTEGRATION_FLAG) != "1":
        return False, "{}!=1".format(_INTEGRATION_FLAG)
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        return False, "missing env: {}".format(",".join(missing))
    return True, ""


_ENABLED, _SKIP_REASON = _integration_enabled()


@unittest.skipUnless(_ENABLED, _SKIP_REASON or "bridge integration disabled")
class BridgeClientIntegrationTestCase(unittest.TestCase):
    """Read-side checks against a live bridge."""

    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ["PYCHRON_BRIDGE_BASE_URL"]
        cls.bearer = os.environ["PYCHRON_BRIDGE_BEARER_TOKEN"]
        cls.sa_key = os.environ["PYCHRON_BRIDGE_SA_KEY_PATH"]
        cls.lab = os.environ["PYCHRON_BRIDGE_LAB_NAME"]
        cls.fixture_repo = os.environ["PYCHRON_BRIDGE_TEST_REPO"]
        cls.client = BridgeClient(
            base_url=cls.base_url,
            bearer_token=cls.bearer,
            service_account_key_path=cls.sa_key,
        )

    def test_healthz_returns_true(self):
        self.assertTrue(self.client.healthz())

    def test_lookup_known_repository_returns_payload(self):
        payload = self.client.lookup_repository(self.fixture_repo)
        self.assertIsNotNone(payload)
        self.assertTrue(
            payload.get("clone_url_ssh") or payload.get("clone_url_https"),
            "expected at least one clone URL in payload: {}".format(payload),
        )

    def test_lookup_missing_repository_returns_none(self):
        missing = "pychron_integration_missing_{}".format(uuid.uuid4().hex[:12])
        self.assertIsNone(self.client.lookup_repository(missing))

    def test_list_repositories_for_lab_includes_fixture(self):
        payload = self.client.list_repositories(lab=self.lab, limit=500)
        ids = {r.get("repository_identifier") for r in payload.get("repositories", [])}
        self.assertIn(self.fixture_repo, ids)

    def test_invalid_bearer_raises_auth_error(self):
        bad_client = BridgeClient(
            base_url=self.base_url,
            bearer_token="invalid-token-{}".format(uuid.uuid4().hex),
            service_account_key_path=self.sa_key,
        )
        with self.assertRaises((BridgeAuthError, BridgeError)):
            bad_client.lookup_repository(self.fixture_repo)


@unittest.skipUnless(_ENABLED, _SKIP_REASON or "bridge integration disabled")
class BridgeServiceIntegrationTestCase(unittest.TestCase):
    """Verify the IGitHost wrapper resolves through the live bridge."""

    @classmethod
    def setUpClass(cls):
        cls.fixture_repo = os.environ["PYCHRON_BRIDGE_TEST_REPO"]
        cls.service = BridgeService()
        cls.service.enabled = True
        cls.service.base_url = os.environ["PYCHRON_BRIDGE_BASE_URL"]
        cls.service.bearer_token = os.environ["PYCHRON_BRIDGE_BEARER_TOKEN"]
        cls.service.service_account_key_path = os.environ["PYCHRON_BRIDGE_SA_KEY_PATH"]
        cls.service.lab_name = os.environ["PYCHRON_BRIDGE_LAB_NAME"]

    def test_test_api_succeeds(self):
        self.assertTrue(self.service.test_api())

    def test_remote_exists_for_fixture(self):
        self.assertTrue(self.service.remote_exists(None, self.fixture_repo))

    def test_remote_exists_false_for_missing(self):
        missing = "pychron_integration_missing_{}".format(uuid.uuid4().hex[:12])
        self.assertFalse(self.service.remote_exists(None, missing))

    def test_make_url_returns_ssh_for_fixture(self):
        url = self.service.make_url(self.fixture_repo, organization=None)
        self.assertTrue(url, "expected non-empty SSH URL for fixture repo")

    def test_get_repo_returns_clone_urls(self):
        repo = self.service.get_repo(None, self.fixture_repo)
        self.assertIsNotNone(repo)
        self.assertEqual(repo["name"] or self.fixture_repo, repo["name"])
        self.assertTrue(repo["ssh_url"] or repo["clone_url"])


@unittest.skipUnless(
    _ENABLED and os.environ.get(_WRITE_FLAG) == "1",
    "bridge write integration disabled (set {}=1 to enable)".format(_WRITE_FLAG),
)
class BridgeClientWriteIntegrationTestCase(unittest.TestCase):
    """Create a real repository through the bridge.

    The bridge has no delete endpoint, so the created repo persists in
    Forgejo. The identifier is uuid-suffixed to avoid collisions.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = BridgeClient(
            base_url=os.environ["PYCHRON_BRIDGE_BASE_URL"],
            bearer_token=os.environ["PYCHRON_BRIDGE_BEARER_TOKEN"],
            service_account_key_path=os.environ["PYCHRON_BRIDGE_SA_KEY_PATH"],
        )
        cls.lab = os.environ["PYCHRON_BRIDGE_LAB_NAME"]
        cls.repo_id = "pychron_it_{}".format(uuid.uuid4().hex[:12])

    def test_ensure_repository_then_lookup(self):
        created = self.client.ensure_repository(
            repository_identifier=self.repo_id,
            lab_name=self.lab,
            project="pychron-integration-tests",
            principal_investigator="integration-bot",
            private=True,
        )
        self.assertTrue(created.get("clone_url_ssh"))

        looked_up = self.client.lookup_repository(self.repo_id)
        self.assertIsNotNone(looked_up)
        self.assertEqual(looked_up.get("clone_url_ssh"), created.get("clone_url_ssh"))

    def test_ensure_repository_is_idempotent(self):
        first = self.client.ensure_repository(
            repository_identifier=self.repo_id,
            lab_name=self.lab,
            project="pychron-integration-tests",
            principal_investigator="integration-bot",
            private=True,
        )
        second = self.client.ensure_repository(
            repository_identifier=self.repo_id,
            lab_name=self.lab,
            project="pychron-integration-tests",
            principal_investigator="integration-bot",
            private=True,
        )
        self.assertEqual(first.get("clone_url_ssh"), second.get("clone_url_ssh"))


if __name__ == "__main__":
    unittest.main()


# ============= EOF =============================================
