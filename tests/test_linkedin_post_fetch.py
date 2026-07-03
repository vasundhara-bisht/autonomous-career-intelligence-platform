"""Tests for LinkedIn post HTML extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach.linkedin_post_fetch import (  # noqa: E402
    HiringSignalContext,
    LinkedInPostFetchError,
    PostSnapshot,
    _enrich_profile_on_page,
    fetch_hiring_signal_context,
    parse_post_snapshot_from_html,
)
from outreach.linkedin_profile_fetch import ProfileSnapshot  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "linkedin_post_sample.html"
_SAMPLE_URL = "https://www.linkedin.com/posts/jane-founder_hiring-pm-activity-123"


class LinkedInPostFetchTests(unittest.TestCase):
    def test_parse_fixture_extracts_post_and_author(self) -> None:
        html = _FIXTURE.read_text(encoding="utf-8")
        snapshot = parse_post_snapshot_from_html(html, url=_SAMPLE_URL)
        self.assertEqual(snapshot.url, _SAMPLE_URL)
        self.assertIn("Senior Product Manager", snapshot.body_text)
        self.assertEqual(snapshot.author_name, "Jane Founder")
        self.assertEqual(snapshot.author_profile_url, "https://www.linkedin.com/in/jane-founder")

    def test_parse_empty_html_raises(self) -> None:
        with self.assertRaises(LinkedInPostFetchError):
            parse_post_snapshot_from_html("<html><body></body></html>", url=_SAMPLE_URL)

    def test_parse_login_wall_raises(self) -> None:
        html = "<html><body>Join LinkedIn Sign in to continue</body></html>"
        with self.assertRaises(LinkedInPostFetchError):
            parse_post_snapshot_from_html(html, url=_SAMPLE_URL)

    def test_fetch_hiring_signal_context_enriches_profile(self) -> None:
        post = PostSnapshot(
            url=_SAMPLE_URL,
            body_text="Hiring PM. Contact hr@acme.com",
            author_name="Jane Founder",
            author_profile_url="https://www.linkedin.com/in/jane-founder",
            fetched_at="2026-06-10T12:00:00+00:00",
        )
        profile = ProfileSnapshot(
            profile_url="https://www.linkedin.com/in/jane-founder",
            person_name="Jane Founder",
            headline="CEO",
            company="Acme Fintech",
            fetched_at="2026-06-10T12:00:00+00:00",
        )
        page = MagicMock()
        playwright = MagicMock()
        browser = MagicMock()
        context = MagicMock()
        playwright.chromium.launch.return_value = browser
        browser.new_context.return_value = context
        context.new_page.return_value = page

        with (
            patch(
                "outreach.linkedin_post_url.validate_linkedin_post_url",
                return_value=_SAMPLE_URL,
            ),
            patch(
                "outreach.linkedin_post_fetch._auth_path_or_raise",
                return_value=Path("auth.json"),
            ),
            patch(
                "outreach.linkedin_post_fetch.extract_post_snapshot_from_page",
                return_value=post,
            ),
            patch(
                "outreach.linkedin_post_fetch._enrich_profile_on_page",
                return_value=(profile, None),
            ),
            patch("playwright.sync_api.sync_playwright") as mock_pw,
        ):
            mock_pw.return_value.__enter__.return_value = playwright
            result = fetch_hiring_signal_context(_SAMPLE_URL)

        self.assertEqual(result.post.author_name, "Jane Founder")
        self.assertIsNotNone(result.profile)
        self.assertEqual(result.detected_emails, ["hr@acme.com"])

    def test_enrich_profile_on_page_invalid_url_skips(self) -> None:
        profile, warning = _enrich_profile_on_page(
            MagicMock(),
            profile_url="https://www.linkedin.com/posts/not-a-profile",
            timeout_ms=1000,
        )
        self.assertIsNone(profile)
        self.assertIsNone(warning)


if __name__ == "__main__":
    unittest.main()
