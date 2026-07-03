"""Tests for LinkedIn post URL validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach.linkedin_post_url import (  # noqa: E402
    LinkedInPostUrlError,
    is_linkedin_post_url,
    validate_linkedin_post_url,
)


class LinkedInPostUrlTests(unittest.TestCase):
    def test_accepts_posts_url(self) -> None:
        url = validate_linkedin_post_url(
            "https://www.linkedin.com/posts/jane-founder_hiring-pm-activity-123"
        )
        self.assertTrue(url.startswith("https://www.linkedin.com/posts/"))

    def test_accepts_feed_update_urn(self) -> None:
        url = validate_linkedin_post_url(
            "https://linkedin.com/feed/update/urn:li:activity:7123456789012345678"
        )
        self.assertIn("/feed/update/urn:li:activity:", url)

    def test_accepts_schemeless_linkedin_host(self) -> None:
        self.assertTrue(
            is_linkedin_post_url(
                "linkedin.com/posts/acme-inc_hiring-activity-999"
            )
        )

    def test_rejects_non_linkedin_host(self) -> None:
        with self.assertRaises(LinkedInPostUrlError):
            validate_linkedin_post_url("https://twitter.com/user/status/1")

    def test_rejects_linkedin_profile(self) -> None:
        with self.assertRaises(LinkedInPostUrlError):
            validate_linkedin_post_url("https://www.linkedin.com/in/jane-founder")

    def test_rejects_blog_and_whatsapp(self) -> None:
        self.assertFalse(is_linkedin_post_url("https://example.com/blog/hiring"))
        self.assertFalse(is_linkedin_post_url("https://chat.whatsapp.com/invite"))


if __name__ == "__main__":
    unittest.main()
