"""Unit tests for Top Applicant / qualification landing navigation helpers."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from scraper.linkedin import (  # noqa: E402
    _li_build_qualification_url_no_job_id,
    _li_qualification_page_ready,
)
from scraper.linkedin_query_orchestrator import (  # noqa: E402
    load_query_catalog,
    resolve_query_url,
)

_EXPECTED_ENTRY_URL = "https://www.linkedin.com/jobs/"


class BuildQualificationUrlTests(unittest.TestCase):
    def test_omits_job_id_params(self) -> None:
        url = _li_build_qualification_url_no_job_id(
            "Product Manager",
            geo_id="90009633",
        )
        self.assertIn("showHowYouFit=HOW_YOU_FIT", url)
        self.assertIn("origin=QUALIFICATION_LANDING", url)
        self.assertIn("keywords=Product+Manager", url)
        self.assertIn("geoId=90009633", url)
        self.assertNotIn("currentJobId", url)
        self.assertNotIn("originToLandingJobPostings", url)

    def test_default_keywords_when_empty(self) -> None:
        url = _li_build_qualification_url_no_job_id("", "")
        self.assertIn("keywords=Product+Manager", url)
        self.assertNotIn("geoId=", url)


class QualificationPageReadyTests(unittest.TestCase):
    def test_ready_when_visible_qualification_card(self) -> None:
        class _Loc:
            def __init__(self, count: int, visible: bool) -> None:
                self._count = count
                self._visible = visible

            def count(self) -> int:
                return self._count

            @property
            def first(self):
                return self

            def is_visible(self) -> bool:
                return self._visible

        class _Page:
            url = "https://www.linkedin.com/jobs/search-results/?showHowYouFit=HOW_YOU_FIT"

            def locator(self, _sel: str):
                return self

            def filter(self, **_kwargs):
                return _Loc(count=2, visible=True)

        self.assertTrue(_li_qualification_page_ready(_Page()))

    def test_not_ready_when_no_cards(self) -> None:
        class _Loc:
            def count(self) -> int:
                return 0

            @property
            def first(self):
                return self

            def is_visible(self) -> bool:
                return False

        class _Page:
            url = "https://www.linkedin.com/jobs/"

            def locator(self, _sel: str):
                return self

            def filter(self, **_kwargs):
                return _Loc()

        self.assertFalse(_li_qualification_page_ready(_Page()))


class ResolveQueryUrlNavigationTests(unittest.TestCase):
    def test_navigation_config_returns_entry_url(self) -> None:
        q = {
            "id": "top_applicants_anchor",
            "url_mode": "qualification_landing",
            "navigation": {
                "entry_url": _EXPECTED_ENTRY_URL,
                "keywords": "Product Manager",
                "geo_id": "90009633",
            },
            "landing_url": "",
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LINKEDIN_QUALIFICATION_LANDING_URL", None)
            url = resolve_query_url(q, {})
        self.assertEqual(url, _EXPECTED_ENTRY_URL)

    def test_catalog_anchor_uses_entry_url(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LINKEDIN_QUALIFICATION_LANDING_URL", None)
            _cfg, catalog = load_query_catalog()
            anchor = next(q for q in catalog if q.id == "top_applicants_anchor")
        self.assertEqual(anchor.url, _EXPECTED_ENTRY_URL)
        self.assertIsNotNone(anchor.navigation)
        self.assertEqual(anchor.navigation.get("keywords"), "Product Manager")


if __name__ == "__main__":
    unittest.main()
