"""Tests for the git publishing helpers (no repository required)."""

from __future__ import annotations

import unittest

from oslabs_scraper.publish import _authenticated_url, _scrub, default_message


class AuthenticatedUrlTests(unittest.TestCase):
    def test_token_is_injected(self) -> None:
        url = _authenticated_url("https://github.com/LiinChun/os-experiment.git", "ghp_example")
        self.assertEqual(
            url, "https://x-access-token:ghp_example@github.com/LiinChun/os-experiment.git"
        )

    def test_without_token_the_url_is_untouched(self) -> None:
        original = "https://github.com/LiinChun/os-experiment.git"
        self.assertEqual(_authenticated_url(original, ""), original)

    def test_existing_userinfo_is_replaced(self) -> None:
        url = _authenticated_url("https://old:secret@github.com/o/r.git", "new")
        self.assertIn("x-access-token:new@github.com", url)
        self.assertNotIn("secret", url)

    def test_non_http_remotes_are_untouched(self) -> None:
        ssh = "git@github.com:LiinChun/os-experiment.git"
        self.assertEqual(_authenticated_url(ssh, "ghp_example"), ssh)


class ScrubTests(unittest.TestCase):
    def test_token_is_redacted(self) -> None:
        self.assertEqual(
            _scrub("failed with token=ghp_secret", "ghp_secret"),
            "failed with token=***",
        )

    def test_no_token_is_a_no_op(self) -> None:
        self.assertEqual(_scrub("plain", ""), "plain")


class MessageTests(unittest.TestCase):
    def test_default_message_mentions_scrape(self) -> None:
        self.assertIn("scrape", default_message())


if __name__ == "__main__":
    unittest.main()
