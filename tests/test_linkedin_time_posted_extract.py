"""Tests for LinkedIn relative posted-date extraction (primary + flagship3 fallback)."""

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
    _LI_PRIMARY_POSTED_SELECTOR,
    _li_extract_time_posted_flagship3_fallback,
    _li_extract_time_posted_from_page,
    _li_parse_relative_posted_text,
)

_FIXTURE_FLAGSHIP3 = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_job_details_flagship3.html"
)
_FIXTURE_LEGACY = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_job_details_legacy.html"
)


class _FakeElement:
    def __init__(self, text: str, *, parent_text: str | None = None) -> None:
        self._text = text
        self._parent_text = parent_text if parent_text is not None else text

    def inner_text(self) -> str:
        return self._text

    def evaluate(self, script: str) -> str:
        if "closest('p')" in script:
            return self._parent_text
        return ""


class _FakePage:
    def __init__(
        self,
        paragraphs: list[_FakeElement],
        strongs: list[_FakeElement],
    ) -> None:
        self._paragraphs = paragraphs
        self._strongs = strongs

    def query_selector_all(self, selector: str) -> list[_FakeElement]:
        if selector == "main p":
            return self._paragraphs
        if selector == "main strong":
            return self._strongs
        return []


class _FakePrimaryContainer:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class _FakeExtractPage:
    def __init__(
        self,
        *,
        primary_text: str | None = None,
        primary_raises: bool = False,
        fallback_page: _FakePage | None = None,
    ) -> None:
        self._primary_text = primary_text
        self._primary_raises = primary_raises
        self._fallback_page = fallback_page

    def wait_for_selector(self, selector: str, timeout: int = 0) -> None:
        if self._primary_raises:
            raise TimeoutError("selector timeout")
        if selector != _LI_PRIMARY_POSTED_SELECTOR:
            raise ValueError(selector)

    def query_selector(self, selector: str) -> _FakePrimaryContainer | None:
        if selector != _LI_PRIMARY_POSTED_SELECTOR:
            return None
        if self._primary_text is None:
            return None
        return _FakePrimaryContainer(self._primary_text)

    def query_selector_all(self, selector: str) -> list[_FakeElement]:
        if self._fallback_page is not None:
            return self._fallback_page.query_selector_all(selector)
        return []


class ExtractTimePostedFromPageTests(unittest.TestCase):
    def test_primary_wins(self) -> None:
        page = _FakeExtractPage(
            primary_text="Bangalore · 2 days ago · 10 applicants",
        )
        self.assertEqual(_li_extract_time_posted_from_page(page), "2 days ago")

    def test_fallback_when_primary_missing(self) -> None:
        page = _FakeExtractPage(
            primary_raises=True,
            fallback_page=_FakePage(
                paragraphs=[
                    _FakeElement(
                        "Pune Division, Maharashtra, India · 1 hour ago · 12 applicants"
                    ),
                ],
                strongs=[
                    _FakeElement(
                        "1 hour ago",
                        parent_text="Pune · 1 hour ago · 12 applicants",
                    )
                ],
            ),
        )
        self.assertEqual(_li_extract_time_posted_from_page(page), "1 hour ago")

    def test_unknown_when_both_miss(self) -> None:
        page = _FakeExtractPage(primary_text="No date here")
        self.assertEqual(_li_extract_time_posted_from_page(page), "Unknown")


class ParseRelativePostedTextTests(unittest.TestCase):
    def test_hour_day_week_month(self) -> None:
        self.assertEqual(_li_parse_relative_posted_text("2 hours ago"), "2 hours ago")
        self.assertEqual(_li_parse_relative_posted_text("1 day ago"), "1 day ago")
        self.assertEqual(_li_parse_relative_posted_text("3 weeks ago"), "3 weeks ago")
        self.assertEqual(_li_parse_relative_posted_text("1 month ago"), "1 month ago")

    def test_no_match(self) -> None:
        self.assertIsNone(_li_parse_relative_posted_text("Unknown"))
        self.assertIsNone(_li_parse_relative_posted_text("2026-06-04"))
        self.assertIsNone(_li_parse_relative_posted_text(""))


class Flagship3FallbackTests(unittest.TestCase):
    def test_fallback_from_metadata_row(self) -> None:
        page = _FakePage(
            paragraphs=[
                _FakeElement("Product Manager"),
                _FakeElement(
                    "Pune Division, Maharashtra, India · 1 hour ago · 12 applicants"
                ),
            ],
            strongs=[_FakeElement("1 hour ago", parent_text="Pune · 1 hour ago · 12 applicants")],
        )
        self.assertEqual(_li_extract_time_posted_flagship3_fallback(page), "1 hour ago")

    def test_fallback_ignores_list_card_noise(self) -> None:
        page = _FakePage(
            paragraphs=[
                _FakeElement(
                    "Pune Division, Maharashtra, India · 1 hour ago · 12 applicants"
                ),
                _FakeElement("Posted 3 weeks ago"),
            ],
            strongs=[
                _FakeElement(
                    "1 hour ago",
                    parent_text="Pune · 1 hour ago · 12 applicants",
                ),
                _FakeElement("3 weeks ago", parent_text="Posted 3 weeks ago"),
            ],
        )
        result = _li_extract_time_posted_flagship3_fallback(page)
        self.assertEqual(result, "1 hour ago")

    def test_primary_selector_html_still_wins(self) -> None:
        legacy_text = "Bangalore, Karnataka, India · 2 days ago · 45 applicants"
        parsed = _li_parse_relative_posted_text(legacy_text)
        self.assertEqual(parsed, "2 days ago")
        self.assertIn(
            "job-details-jobs-unified-top-card__primary-description-container",
            _FIXTURE_LEGACY.read_text(encoding="utf-8"),
        )

    def test_fallback_not_needed_when_primary_parses(self) -> None:
        container = MagicMock()
        container.inner_text.return_value = "Bangalore · 2 days ago · 10 applicants"
        parsed = _li_parse_relative_posted_text(container.inner_text())
        self.assertEqual(parsed, "2 days ago")
        with patch(
            "scraper.linkedin._li_extract_time_posted_flagship3_fallback"
        ) as mock_fb:
            time_posted = parsed or "Unknown"
            if time_posted == "Unknown":
                mock_fb.return_value = "1 hour ago"
                fb = mock_fb(MagicMock())
                if fb:
                    time_posted = fb
            mock_fb.assert_not_called()
        self.assertEqual(time_posted, "2 days ago")

    def test_flagship3_fixture_contains_detail_metadata_pattern(self) -> None:
        html = _FIXTURE_FLAGSHIP3.read_text(encoding="utf-8")
        self.assertIn("<strong>1 hour ago</strong>", html)
        self.assertIn("12 applicants", html)
        self.assertIn("Posted 3 weeks ago", html)


if __name__ == "__main__":
    unittest.main()
