"""Tests for pychron.cloud.url_rewrite."""

import unittest

from pychron.cloud.url_rewrite import rewrite_to_alias


class RewriteToAliasTestCase(unittest.TestCase):
    def test_scp_form_rewritten(self):
        self.assertEqual(
            rewrite_to_alias("git@forgejo.example:nmgrl/X_001.git", "pychron-nmgrl"),
            "pychron-nmgrl:nmgrl/X_001.git",
        )

    def test_scp_form_no_user(self):
        self.assertEqual(
            rewrite_to_alias("forgejo.example:nmgrl/X_001.git", "pychron-nmgrl"),
            "pychron-nmgrl:nmgrl/X_001.git",
        )

    def test_ssh_uri_with_port(self):
        self.assertEqual(
            rewrite_to_alias("ssh://git@forgejo.example:2222/nmgrl/X_001.git", "pychron-nmgrl"),
            "pychron-nmgrl:nmgrl/X_001.git",
        )

    def test_ssh_uri_no_port(self):
        self.assertEqual(
            rewrite_to_alias("ssh://git@forgejo.example/nmgrl/X.git", "pychron-nmgrl"),
            "pychron-nmgrl:nmgrl/X.git",
        )

    def test_already_alias_form_passes_through(self):
        self.assertEqual(
            rewrite_to_alias("pychron-nmgrl:nmgrl/X.git", "pychron-nmgrl"),
            "pychron-nmgrl:nmgrl/X.git",
        )

    def test_https_unchanged(self):
        self.assertEqual(
            rewrite_to_alias("https://forgejo.example/nmgrl/X.git", "pychron-nmgrl"),
            "https://forgejo.example/nmgrl/X.git",
        )

    def test_empty_url_unchanged(self):
        self.assertEqual(rewrite_to_alias("", "pychron-nmgrl"), "")

    def test_empty_alias_passes_through(self):
        self.assertEqual(
            rewrite_to_alias("git@forgejo.example:nmgrl/X.git", ""),
            "git@forgejo.example:nmgrl/X.git",
        )


if __name__ == "__main__":
    unittest.main()
