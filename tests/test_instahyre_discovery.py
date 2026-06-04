"""Unit tests for Instahyre Feed 1 discovery settings (no Playwright)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scraper.instahyre import (  # noqa: E402
    _DEFAULT_MAX_JOBS_PER_FEED,
    _FEED_ID_MATCHING_PERSONALIZED,
    _FEED_ID_PM_CURATED_SEARCH,
    _FEED_PM_SEARCH_URL,
    _PAGINATED_FEED_IDS,
    _max_jobs_per_feed,
    _normalize_opportunity_href,
    _opportunity_card_from_dom,
    VisibleDomCard,
    discovery_settings_for_feed,
    is_valid_candidate_session_url,
    uses_dom_first_harvest,
)


class InstahyreDiscoverySettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_matching_feed_defaults_to_pagination(self) -> None:
        for key in (
            "INSTAHYRE_SCROLL_MAX_CYCLES",
            "INSTAHYRE_STABLE_ROUNDS",
            "INSTAHYRE_LIST_WAIT_MS",
            "INSTAHYRE_POST_SCROLL_WAIT_MS",
            "INSTAHYRE_MATCHING_SCROLL_FALLBACK",
            "INSTAHYRE_MAX_PAGES",
        ):
            os.environ.pop(key, None)

        settings = discovery_settings_for_feed(_FEED_ID_MATCHING_PERSONALIZED)
        self.assertTrue(settings.deep_discovery)
        self.assertEqual(settings.traversal_mode, "pagination")
        self.assertEqual(settings.max_pages, 5)
        self.assertAlmostEqual(settings.page_min_new_ratio, 0.15)

    def test_matching_scroll_fallback_env(self) -> None:
        os.environ["INSTAHYRE_MATCHING_SCROLL_FALLBACK"] = "1"
        settings = discovery_settings_for_feed(_FEED_ID_MATCHING_PERSONALIZED)
        self.assertEqual(settings.traversal_mode, "scroll")
        self.assertGreaterEqual(settings.scroll_max_cycles, 12)
        self.assertGreater(settings.stable_rounds, 3)

    def test_max_pages_env_override(self) -> None:
        os.environ["INSTAHYRE_MAX_PAGES"] = "8"
        settings = discovery_settings_for_feed(_FEED_ID_MATCHING_PERSONALIZED)
        self.assertEqual(settings.max_pages, 8)

    def test_max_jobs_per_feed_defaults_high(self) -> None:
        os.environ.pop("INSTAHYRE_MAX_JOBS_PER_FEED", None)
        self.assertGreaterEqual(_max_jobs_per_feed(), _DEFAULT_MAX_JOBS_PER_FEED)

    def test_max_jobs_per_feed_env_override(self) -> None:
        os.environ["INSTAHYRE_MAX_JOBS_PER_FEED"] = "60"
        self.assertEqual(_max_jobs_per_feed(), 60)

    def test_pm_feed_uses_dom_first_harvest(self) -> None:
        self.assertTrue(uses_dom_first_harvest(_FEED_ID_PM_CURATED_SEARCH))
        self.assertFalse(uses_dom_first_harvest(_FEED_ID_MATCHING_PERSONALIZED))

    def test_opportunity_card_from_dom_job_link(self) -> None:
        dom = VisibleDomCard(
            index=0,
            title="Product Manager",
            company="Acme",
            location="Bangalore",
            card_text="Acme - Product Manager\nBangalore",
            tags=[],
        )
        card = _opportunity_card_from_dom(dom, "/job-424242/some-slug/")
        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card.job_id, "424242")
        self.assertIn("/job-424242", card.canonical_url)

    def test_normalize_opportunity_href_absolute(self) -> None:
        path = _normalize_opportunity_href(
            "https://www.instahyre.com/job-12345/example/"
        )
        self.assertTrue(path.startswith("/job-12345"))

    def test_pm_feed_uses_pagination_path(self) -> None:
        for key in (
            "INSTAHYRE_SCROLL_MAX_CYCLES",
            "INSTAHYRE_STABLE_ROUNDS",
            "INSTAHYRE_LIST_WAIT_MS",
            "INSTAHYRE_POST_SCROLL_WAIT_MS",
            "INSTAHYRE_MAX_PAGES",
        ):
            os.environ.pop(key, None)

        self.assertIn(_FEED_ID_PM_CURATED_SEARCH, _PAGINATED_FEED_IDS)
        settings = discovery_settings_for_feed(_FEED_ID_PM_CURATED_SEARCH)
        self.assertTrue(settings.deep_discovery)
        self.assertEqual(settings.traversal_mode, "pagination")
        self.assertEqual(settings.max_pages, 5)

    def test_candidate_session_accepts_search_jobs(self) -> None:
        self.assertTrue(
            is_valid_candidate_session_url(
                "https://www.instahyre.com/search-jobs?search=true&offset=20"
            )
        )

    def test_candidate_session_accepts_opportunities(self) -> None:
        self.assertTrue(
            is_valid_candidate_session_url(
                "https://www.instahyre.com/candidate/opportunities/?matching=true"
            )
        )

    def test_candidate_session_rejects_login(self) -> None:
        self.assertFalse(
            is_valid_candidate_session_url("https://www.instahyre.com/login")
        )

    def test_candidate_session_rejects_employer(self) -> None:
        self.assertFalse(
            is_valid_candidate_session_url(
                "https://www.instahyre.com/employer/dashboard"
            )
        )

    def test_pm_search_url_constant_matches_catalog(self) -> None:
        import json

        from paths import instahyre_feeds_json

        with open(instahyre_feeds_json(), encoding="utf-8") as f:
            cfg = json.load(f)
        feed2 = next(f for f in cfg["feeds"] if f["id"] == _FEED_ID_PM_CURATED_SEARCH)
        self.assertEqual(feed2["url"], _FEED_PM_SEARCH_URL)
        self.assertIn("/search-jobs", feed2["url"])

    def test_shared_env_overrides_apply_to_matching(self) -> None:
        os.environ["INSTAHYRE_SCROLL_MAX_CYCLES"] = "25"
        os.environ["INSTAHYRE_POST_SCROLL_WAIT_MS"] = "3000"
        settings = discovery_settings_for_feed(_FEED_ID_MATCHING_PERSONALIZED)
        self.assertEqual(settings.scroll_max_cycles, 25)
        self.assertEqual(settings.post_scroll_wait_ms, 3000)


if __name__ == "__main__":
    unittest.main()
