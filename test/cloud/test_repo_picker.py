"""Tests for pychron.cloud.repo_picker."""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud import api_client, repo_picker


def _git(cwd, *args):
    subprocess.check_call(
        ["git", *args],
        cwd=cwd,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@x",
        },
    )


class RepoPickerTestCase(unittest.TestCase):
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

    def _make_upstream(self):
        upstream = os.path.join(self.tmp, "upstream.git")
        os.makedirs(upstream)
        subprocess.check_call(["git", "init", "--bare", "-b", "main", upstream])
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        subprocess.check_call(["git", "init", "-b", "main", seed])
        with open(os.path.join(seed, "README"), "w") as f:
            f.write("hi\n")
        _git(seed, "add", "README")
        _git(seed, "commit", "-m", "init")
        _git(seed, "remote", "add", "origin", upstream)
        _git(seed, "push", "origin", "main")
        return upstream

    def test_load_last_repo_returns_empty_when_absent(self):
        self.assertEqual(repo_picker.load_last_repo(), "")

    def test_save_and_load_last_repo_round_trip(self):
        os.makedirs(os.path.join(self.tmp, ".pychron"), exist_ok=True)
        repo_picker.save_last_repo("X_001")
        self.assertEqual(repo_picker.load_last_repo(), "X_001")

    def test_alias_falls_back_to_registration_when_unset(self):
        # Pre-stage a registration.json with an alias.
        os.makedirs(os.path.join(self.tmp, ".pychron"), exist_ok=True)
        reg_path = os.path.join(self.tmp, ".pychron", "registration.json")
        with open(reg_path, "w") as f:
            json.dump({"ssh_host_alias": {"alias": "pychron-nmgrl"}}, f)
        picker = repo_picker.RepoPicker(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
        )
        self.assertEqual(picker.alias, "pychron-nmgrl")

    def test_fetch_calls_list_repositories(self):
        picker = repo_picker.RepoPicker(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            alias="pychron-nmgrl",
        )
        repos = [api_client.Repository("X_001", "git@h:lab/X.git", "", "main", "")]
        with patch.object(repo_picker, "list_repositories", return_value=repos) as lr:
            self.assertEqual(picker.fetch(), repos)
            lr.assert_called_once_with("https://api.example", "tok", "nmgrl")

    def test_open_clones_and_persists_last_repo(self):
        upstream = self._make_upstream()
        picker = repo_picker.RepoPicker(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            alias="",  # alias rewriter no-ops on empty alias
        )
        repo = api_client.Repository("X_001", upstream, "", "main", "")
        path = picker.open(repo)
        self.assertTrue(os.path.isfile(os.path.join(path, "README")))
        self.assertEqual(repo_picker.load_last_repo(), "X_001")

    def test_open_accepts_dict_payload(self):
        upstream = self._make_upstream()
        picker = repo_picker.RepoPicker(
            api_base_url="https://api.example",
            api_token="tok",
            lab_name="nmgrl",
            alias="",
        )
        path = picker.open(
            {
                "repository_identifier": "X_001",
                "ssh_url": upstream,
                "default_branch": "main",
            }
        )
        self.assertTrue(os.path.isfile(os.path.join(path, "README")))


if __name__ == "__main__":
    unittest.main()
