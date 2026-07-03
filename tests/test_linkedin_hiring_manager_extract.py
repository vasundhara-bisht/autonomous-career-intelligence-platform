"""Tests for LinkedIn hiring-manager extraction (primary + flagship3 fallback)."""

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
    _LI_NOT_SPECIFIED_HM,
    _LI_PRIMARY_HM_SELECTOR,
    _li_extract_hiring_manager_flagship3_fallback,
    _li_extract_hiring_manager_from_page,
    _li_is_valid_hiring_manager,
    _li_normalize_hiring_manager,
)

_FIXTURE_FLAGSHIP3_POSTER = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_job_details_flagship3_poster.html"
)
_FIXTURE_LEGACY_HM = (
    Path(__file__).resolve().parent / "fixtures" / "linkedin_job_details_legacy_hm.html"
)


class _FakeHmElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text

    def evaluate(self, script: str) -> str:
        if "Meet the hiring team" in self._text or "Job poster" in self._text:
            return "Deblina Hait"
        return ""


class _FakeHmPage:
    def __init__(
        self,
        *,
        primary: _FakeHmElement | None = None,
        paragraphs: list[_FakeHmElement] | None = None,
    ) -> None:
        self._primary = primary
        self._paragraphs = paragraphs or []
        self.mouse = MagicMock()

    def query_selector(self, selector: str) -> _FakeHmElement | None:
        if selector == _LI_PRIMARY_HM_SELECTOR:
            return self._primary
        return None

    def query_selector_all(self, selector: str) -> list[_FakeHmElement]:
        if selector == "main p":
            return self._paragraphs
        return []

    def wait_for_timeout(self, _ms: int) -> None:
        return None


class HiringManagerHelperTests(unittest.TestCase):
    def test_valid_and_normalize(self) -> None:
        self.assertTrue(_li_is_valid_hiring_manager("Deblina Hait"))
        self.assertFalse(_li_is_valid_hiring_manager("Not Specified"))
        self.assertEqual(_li_normalize_hiring_manager("  Jane Doe  "), "Jane Doe")
        self.assertEqual(
            _li_normalize_hiring_manager("Recruiter at Acme"),
            "",
        )

    def test_flagship3_fixture_contains_poster_markers(self) -> None:
        html = _FIXTURE_FLAGSHIP3_POSTER.read_text(encoding="utf-8")
        self.assertIn("Meet the hiring team", html)
        self.assertIn("Deblina Hait", html)
        self.assertIn("Job poster", html)

    def test_legacy_fixture_contains_primary_selector(self) -> None:
        html = _FIXTURE_LEGACY_HM.read_text(encoding="utf-8")
        self.assertIn("jobs-poster__name", html)
        self.assertIn("Jane Recruiter", html)


class ExtractHiringManagerFromPageTests(unittest.TestCase):
    def test_primary_wins(self) -> None:
        page = _FakeHmPage(primary=_FakeHmElement("Jane Recruiter"))
        with patch(
            "scraper.linkedin._li_extract_hiring_manager_flagship3_fallback"
        ) as mock_fb:
            result = _li_extract_hiring_manager_from_page(page)
            mock_fb.assert_not_called()
        self.assertEqual(result, "Jane Recruiter")

    def test_fallback_when_primary_missing(self) -> None:
        page = _FakeHmPage(
            paragraphs=[_FakeHmElement("Meet the hiring team")],
        )
        self.assertEqual(_li_extract_hiring_manager_from_page(page), "Deblina Hait")

    def test_returns_not_specified_when_both_miss(self) -> None:
        page = _FakeHmPage()
        self.assertEqual(
            _li_extract_hiring_manager_from_page(page),
            _LI_NOT_SPECIFIED_HM,
        )

    def test_primary_not_overwritten_by_fallback(self) -> None:
        page = _FakeHmPage(primary=_FakeHmElement("Primary Person"))
        with patch(
            "scraper.linkedin._li_extract_hiring_manager_flagship3_fallback",
            return_value="Fallback Person",
        ) as mock_fb:
            result = _li_extract_hiring_manager_from_page(page)
            mock_fb.assert_not_called()
        self.assertEqual(result, "Primary Person")


class Flagship3FallbackTests(unittest.TestCase):
    def test_fallback_extracts_name_from_poster_section(self) -> None:
        page = _FakeHmPage(
            paragraphs=[
                _FakeHmElement("Meet the hiring team"),
                _FakeHmElement("Job poster"),
            ]
        )
        self.assertEqual(
            _li_extract_hiring_manager_flagship3_fallback(page),
            "Deblina Hait",
        )

    def test_fallback_ignores_unrelated_paragraphs(self) -> None:
        page = _FakeHmPage(paragraphs=[_FakeHmElement("About the job")])
        self.assertIsNone(_li_extract_hiring_manager_flagship3_fallback(page))


if __name__ == "__main__":
    unittest.main()
