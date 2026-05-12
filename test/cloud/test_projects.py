"""Tests for pychron.cloud.projects (clone-or-pull)."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pychron.cloud import projects


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


class ProjectsTestCase(unittest.TestCase):
    """Use a real local bare repo as the "remote" so git's transport
    layer is exercised end-to-end. The alias rewriter is bypassed by
    passing an empty alias.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(self._rmtree, self.tmp)

        # Build an upstream bare repo with one commit on the configured
        # default branch ("main") so clone has something to checkout.
        self.upstream = os.path.join(self.tmp, "upstream.git")
        os.makedirs(self.upstream)
        subprocess.check_call(["git", "init", "--bare", "-b", "main", self.upstream])

        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        subprocess.check_call(["git", "init", "-b", "main", seed])
        with open(os.path.join(seed, "README"), "w") as f:
            f.write("hi\n")
        _git(seed, "add", "README")
        _git(seed, "commit", "-m", "init")
        _git(seed, "remote", "add", "origin", self.upstream)
        _git(seed, "push", "origin", "main")

        # Redirect ~ → tmp so projects/<repo> lands in scratch.
        self._patcher = patch(
            "pychron.cloud.paths.os.path.expanduser",
            lambda p: p.replace("~", self.tmp),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _rmtree(self, path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def test_clone_creates_local_repo(self):
        path = projects.clone_or_pull("X_001", self.upstream, alias="", branch="main")
        expected = os.path.join(self.tmp, "Pychron", "projects", "X_001")
        self.assertEqual(path, expected)
        self.assertTrue(os.path.isfile(os.path.join(expected, "README")))

    def test_pull_after_clone_is_idempotent(self):
        projects.clone_or_pull("X_001", self.upstream, alias="", branch="main")
        # Second call should pull (no error) and leave path intact.
        path = projects.clone_or_pull("X_001", self.upstream, alias="", branch="main")
        self.assertTrue(os.path.isfile(os.path.join(path, "README")))

    def test_mismatched_origin_aborts(self):
        projects.clone_or_pull("X_001", self.upstream, alias="", branch="main")
        # Build a second unrelated bare repo and try to "open" X_001
        # against it — must refuse.
        other = os.path.join(self.tmp, "other.git")
        os.makedirs(other)
        subprocess.check_call(["git", "init", "--bare", "-b", "main", other])
        with self.assertRaises(projects.ProjectCloneError):
            projects.clone_or_pull("X_001", other, alias="", branch="main")

    def test_existing_non_repo_path_aborts(self):
        dest = os.path.join(self.tmp, "Pychron", "projects", "X_001")
        os.makedirs(dest)
        # Empty dir — not a git repo.
        with self.assertRaises(projects.ProjectCloneError):
            projects.clone_or_pull("X_001", self.upstream, alias="", branch="main")

    def test_list_local_projects_only_lists_clones(self):
        projects.clone_or_pull("X_001", self.upstream, alias="", branch="main")
        # Drop a stray non-repo dir.
        os.makedirs(os.path.join(self.tmp, "Pychron", "projects", "not_a_repo"), exist_ok=True)
        self.assertEqual(projects.list_local_projects(), ["X_001"])

    def test_empty_repo_name_raises(self):
        with self.assertRaises(projects.ProjectCloneError):
            projects.clone_or_pull("", self.upstream, alias="")

    def test_empty_ssh_url_raises(self):
        with self.assertRaises(projects.ProjectCloneError):
            projects.clone_or_pull("X_001", "", alias="")


if __name__ == "__main__":
    unittest.main()
