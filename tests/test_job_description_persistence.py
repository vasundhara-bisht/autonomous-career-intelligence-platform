"""Unit tests for job description persistence (scrape-first, fail-soft fetch)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agent.job_description_persistence import (  # noqa: E402
    DescriptionStore,
    MIN_PERSISTABLE_CHARS,
    _merge_fetched_description,
    ensure_description_for_job,
)


def _long_text(prefix: str = "x") -> str:
    return prefix * (MIN_PERSISTABLE_CHARS + 50)


class JobDescriptionPersistenceTests(unittest.TestCase):
    def _job(self, description: str = "", source: str = "instahyre") -> dict:
        return {
            "title": "Product Manager",
            "company": "Acme",
            "link": "https://www.instahyre.com/job-123/",
            "source": source,
            "description": description,
            "JOB_KEY": "legacy-key-1",
            "JOB_KEY_V2": "v2:instahyre:123",
        }

    def test_valid_scrape_description_persisted_without_fetch(self) -> None:
        store = DescriptionStore()
        stats: dict = {}
        job = self._job(description=_long_text("scrape-"))

        with patch("agent.job_description_persistence.fetch_job_description") as mock_fetch:
            ensure_description_for_job(job, store, stats, bucket="brand_new")

        mock_fetch.assert_not_called()
        self.assertEqual(stats.get("scrape_description_usable"), 1)
        self.assertEqual(stats.get("persisted_from_scrape"), 1)
        self.assertEqual(stats.get("fetch_attempted", 0), 0)
        self.assertGreaterEqual(len(job["description"]), MIN_PERSISTABLE_CHARS)
        self.assertIn("v2:instahyre:123", store.by_v2)

    def test_empty_fetch_does_not_overwrite_valid_scrape(self) -> None:
        scrape = _long_text("keep-")
        stats: dict = {}
        merged, from_scrape = _merge_fetched_description(scrape, "", stats)
        self.assertEqual(merged, scrape)
        self.assertTrue(from_scrape)
        self.assertEqual(stats.get("fetch_would_have_overwritten_valid_description"), 1)

    def test_weaker_fetch_does_not_replace_valid_scrape(self) -> None:
        scrape = _long_text("keep-")
        weaker = scrape[: MIN_PERSISTABLE_CHARS + 10]
        stats: dict = {}
        merged, from_scrape = _merge_fetched_description(scrape, weaker, stats)
        self.assertEqual(merged, scrape)
        self.assertTrue(from_scrape)

    def test_stronger_fetch_replaces_when_both_persistable(self) -> None:
        scrape = _long_text("short-")
        stronger = _long_text("longer-")
        stats: dict = {}
        merged, from_scrape = _merge_fetched_description(scrape, stronger, stats)
        self.assertEqual(merged, stronger)
        self.assertFalse(from_scrape)
        self.assertEqual(stats.get("fetch_improved"), 1)

    def test_fetch_path_persists_when_scrape_not_usable(self) -> None:
        store = DescriptionStore()
        stats: dict = {}
        job = self._job(description="too short")
        fetched_text = _long_text("fetched-")

        def _fake_fetch(j: dict) -> dict:
            j["description"] = fetched_text
            return j

        with patch(
            "agent.job_description_persistence.fetch_job_description",
            side_effect=_fake_fetch,
        ):
            ensure_description_for_job(job, store, stats, bucket="brand_new")

        self.assertEqual(stats.get("fetch_attempted"), 1)
        self.assertEqual(stats.get("persisted_from_fetch"), 1)
        self.assertEqual(job["description"], fetched_text)

    def test_empty_fetch_after_short_scrape_does_not_persist(self) -> None:
        store = DescriptionStore()
        stats: dict = {}
        job = self._job(description="short")

        def _fake_fetch(j: dict) -> dict:
            j["description"] = ""
            return j

        with patch(
            "agent.job_description_persistence.fetch_job_description",
            side_effect=_fake_fetch,
        ):
            ensure_description_for_job(job, store, stats, bucket="brand_new")

        self.assertEqual(stats.get("persisted", 0), 0)
        self.assertEqual(len(store.by_v2), 0)


if __name__ == "__main__":
    unittest.main()
