"""Tests for Top Applicant / qualification landing card scrape behaviour."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from scraper.linkedin import (  # noqa: E402
    _LinkedInTraversalMetrics,
    _li_scrape_qualification_landing_cards_into,
)

_CARD_TEXT = (
    "Senior Product Manager\n"
    "Acme Corp\n"
    "Bangalore, Karnataka, India\n"
    "2 days ago"
)


class _FakeCard:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text

    def click(self, **_kwargs) -> None:
        return None


class _FakeCardLocator:
    def __init__(self, cards: list[_FakeCard]) -> None:
        self._cards = cards

    def count(self) -> int:
        return len(self._cards)

    def nth(self, idx: int) -> _FakeCard:
        return self._cards[idx]


class QualificationScrapeHmTests(unittest.TestCase):
    def test_extracts_hiring_manager_after_card_click(self) -> None:
        page = MagicMock()
        page.url = (
            "https://www.linkedin.com/jobs/search-results/"
            "?currentJobId=12345&showHowYouFit=HOW_YOU_FIT"
        )
        page.title.return_value = "Senior Product Manager | Acme Corp | LinkedIn"

        jobs: list = []
        processed: set[str] = set()
        seen: set[str] = set()
        metrics = _LinkedInTraversalMetrics()

        with (
            patch(
                "scraper.linkedin._li_job_card_locator",
                return_value=_FakeCardLocator([_FakeCard(_CARD_TEXT)]),
            ),
            patch(
                "scraper.linkedin._li_url_current_job_id",
                return_value="12345",
            ),
            patch(
                "scraper.linkedin._li_extract_hiring_manager_from_page",
                return_value="Jane Recruiter",
            ) as mock_hm,
            patch("scraper.linkedin._li_humanized_pause"),
            patch(
                "scraper.linkedin._li_extract_time_posted_from_page",
                return_value="2 days ago",
            ),
        ):
            _li_scrape_qualification_landing_cards_into(
                page,
                jobs,
                processed,
                seen,
                "test_pass",
                metrics=metrics,
            )

        mock_hm.assert_called_once_with(page)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["hiring_manager"], "Jane Recruiter")
        self.assertEqual(jobs[0]["time_posted"], "2 days ago")
        self.assertIn("12345", jobs[0]["link"])


if __name__ == "__main__":
    unittest.main()
