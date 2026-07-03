"""Unit tests for Instahyre Interested sync lightweight detail enrichment."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scraper.instahyre import (  # noqa: E402
    OpportunityCard,
    _build_job_from_card,
    _enrich_interested_sync_stub,
    _extract_instahyre_detail_metadata,
    _parse_instahyre_opportunity_tags,
    sync_instahyre_interested,
)


class ParseOpportunityTagsTests(unittest.TestCase):
    def test_parses_employment_workplace_experience(self) -> None:
        meta = _parse_instahyre_opportunity_tags(
            ["Full-time", "Remote", "5+ years", "Product"]
        )
        self.assertEqual(meta["employment_type"], "full-time")
        self.assertEqual(meta["workplace_type"], "remote")
        self.assertIn("5", meta["experience_level"])

    def test_empty_tags_return_empty_fields(self) -> None:
        meta = _parse_instahyre_opportunity_tags([])
        self.assertEqual(meta["employment_type"], "")
        self.assertEqual(meta["workplace_type"], "")
        self.assertEqual(meta["experience_level"], "")


class EnrichInterestedStubTests(unittest.TestCase):
    def _card(self) -> OpportunityCard:
        return OpportunityCard(
            job_id="424242",
            opportunity_url_path="/candidate/opportunities/job-424242/",
            canonical_url="https://www.instahyre.com/candidate/opportunities/job-424242/",
            title="List Title",
            company="List Co",
            location="Bangalore",
            card_text="",
            tags=["Full-time", "Hybrid"],
        )

    def _base_stub(self) -> dict:
        return {
            "title": "List Title",
            "company": "List Co",
            "location": "Bangalore",
            "applied": True,
            "JOB_KEY_V2": "v2:instahyre:424242",
        }

    def test_detail_overrides_list_fields(self) -> None:
        stub = self._base_stub()
        tag_meta = _parse_instahyre_opportunity_tags(self._card().tags)
        enriched = _enrich_interested_sync_stub(
            stub,
            self._card(),
            detail_meta={
                "title": "Detail Title",
                "company": "Detail Co",
                "location": "Mumbai",
                "hiring_manager": "Jane Recruiter",
                "posted_at_date": "2026-06-01",
                "age_days": 15,
            },
            tag_meta=tag_meta,
        )
        self.assertTrue(enriched["applied"])
        self.assertEqual(enriched["title"], "Detail Title")
        self.assertEqual(enriched["company"], "Detail Co")
        self.assertEqual(enriched["location"], "Mumbai")
        self.assertEqual(enriched["hiring_manager"], "Jane Recruiter")
        self.assertEqual(enriched["posted_at_date"], "2026-06-01")
        self.assertEqual(enriched["employment_type"], "full-time")
        self.assertEqual(enriched["workplace_type"], "hybrid")

    def test_preserves_applied_when_detail_empty(self) -> None:
        stub = self._base_stub()
        enriched = _enrich_interested_sync_stub(
            stub,
            self._card(),
            detail_meta={},
            tag_meta=_parse_instahyre_opportunity_tags([]),
        )
        self.assertTrue(enriched["applied"])
        self.assertEqual(enriched["title"], "List Title")


class ExtractDetailMetadataTests(unittest.TestCase):
    def _card(self) -> OpportunityCard:
        return OpportunityCard(
            job_id="12345",
            opportunity_url_path="/candidate/opportunities/job-12345/",
            canonical_url="https://www.instahyre.com/candidate/opportunities/job-12345/",
            title="PM",
            company="Acme",
            location="Bangalore",
            card_text="",
        )

    @patch("scraper.instahyre._extract_job_posting_posted_date")
    @patch("scraper.instahyre._extract_job_posted_by")
    @patch("scraper.instahyre._extract_job_posting_ld_fields")
    @patch("scraper.instahyre._extract_detail_company")
    @patch("scraper.instahyre._extract_detail_title")
    @patch("scraper.instahyre._validate_detail_page")
    def test_returns_metadata_without_description(
        self,
        mock_validate,
        mock_title,
        mock_company,
        mock_ld,
        mock_posted_by,
        mock_posted_date,
    ) -> None:
        mock_validate.return_value = None
        mock_title.return_value = "Product Manager"
        mock_company.return_value = "Acme Corp"
        mock_ld.return_value = {"datePosted": "", "jobLocation": "Bengaluru, India"}
        mock_posted_by.return_value = {"recruiter_name": "Jane Doe"}
        mock_posted_date.return_value = {
            "posted_at_raw": "2026-06-01",
            "posted_at_source": "schema.org_job_posting",
            "posted_at_date": "2026-06-01",
            "age_days": 15,
        }
        page = MagicMock()

        meta = _extract_instahyre_detail_metadata(page, self._card())

        self.assertEqual(meta["title"], "Product Manager")
        self.assertEqual(meta["hiring_manager"], "Jane Doe")
        self.assertEqual(meta["location"], "Bengaluru, India")
        self.assertNotIn("description", meta)

    @patch("scraper.instahyre._validate_detail_page")
    def test_returns_empty_on_validation_reject(self, mock_validate) -> None:
        mock_validate.return_value = "detail_contains_no_longer_accepting"
        page = MagicMock()
        self.assertEqual(_extract_instahyre_detail_metadata(page, self._card()), {})


class InterestedSyncEnrichmentFlowTests(unittest.TestCase):
    @patch("scraper.instahyre._interested_detail_enrich_enabled", return_value=True)
    @patch("scraper.instahyre._extract_instahyre_detail_metadata")
    @patch("scraper.instahyre._open_card_detail", return_value=True)
    @patch("scraper.instahyre._collect_feed_opportunity_cards")
    @patch("scraper.instahyre._assert_candidate_session")
    @patch("scraper.instahyre._ensure_interested_filter_selected")
    @patch("scraper.instahyre._new_authenticated_context")
    @patch("scraper.instahyre.sync_playwright")
    def test_sync_enriches_stub_from_detail(
        self,
        mock_playwright,
        mock_new_context,
        _mock_filter,
        _mock_assert,
        mock_collect,
        mock_open,
        mock_extract,
        _mock_enrich_flag,
    ) -> None:
        card = OpportunityCard(
            job_id="777",
            opportunity_url_path="/candidate/opportunities/job-777/",
            canonical_url="https://www.instahyre.com/candidate/opportunities/job-777/",
            title="PM",
            company="Co",
            location="India",
            card_text="",
            tags=["Remote"],
        )
        mock_collect.return_value = ([card], {"harvest_mode": "angular_aligned"})
        mock_extract.return_value = {
            "hiring_manager": "Recruiter One",
            "posted_at_date": "2026-06-10",
            "age_days": 6,
        }
        mock_new_context.return_value  # silence lint
        mock_playwright.return_value.__enter__.return_value

        stubs, stats = sync_instahyre_interested()

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0]["hiring_manager"], "Recruiter One")
        self.assertEqual(stubs[0]["workplace_type"], "remote")
        self.assertTrue(stubs[0]["applied"])
        self.assertEqual(stats["detail_enriched"], 1)
        mock_open.assert_called_once()

    @patch("scraper.instahyre._interested_detail_enrich_enabled", return_value=True)
    @patch("scraper.instahyre._open_card_detail", return_value=False)
    @patch("scraper.instahyre._collect_feed_opportunity_cards")
    @patch("scraper.instahyre._assert_candidate_session")
    @patch("scraper.instahyre._ensure_interested_filter_selected")
    @patch("scraper.instahyre._new_authenticated_context")
    @patch("scraper.instahyre.sync_playwright")
    def test_detail_open_failure_keeps_list_stub(
        self,
        mock_playwright,
        mock_new_context,
        _mock_filter,
        _mock_assert,
        mock_collect,
        _mock_open,
        _mock_enrich_flag,
    ) -> None:
        card = OpportunityCard(
            job_id="888",
            opportunity_url_path="/candidate/opportunities/job-888/",
            canonical_url="https://www.instahyre.com/candidate/opportunities/job-888/",
            title="PM",
            company="Co",
            location="India",
            card_text="",
        )
        mock_collect.return_value = ([card], {})
        mock_playwright.return_value.__enter__.return_value
        mock_new_context.return_value

        stubs, stats = sync_instahyre_interested()

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0]["JOB_KEY_V2"], "v2:instahyre:888")
        self.assertTrue(stubs[0]["applied"])
        self.assertEqual(stats["detail_open_failed"], 1)


class BuildJobFromCardRegressionTests(unittest.TestCase):
    def _card(self) -> OpportunityCard:
        return OpportunityCard(
            job_id="12345",
            opportunity_url_path="/candidate/opportunities/job-12345/",
            canonical_url="https://www.instahyre.com/candidate/opportunities/job-12345/",
            title="Product Manager",
            company="Acme",
            location="Bangalore",
            card_text="",
        )

    @patch("scraper.instahyre._extract_job_posting_posted_date")
    @patch("scraper.instahyre._extract_job_posted_by")
    @patch("scraper.instahyre._extract_description")
    @patch("scraper.instahyre._extract_instahyre_detail_metadata")
    @patch("scraper.instahyre._validate_detail_page")
    @patch("scraper.instahyre._detect_applied_on_detail_page")
    def test_still_includes_description_and_applied(
        self,
        mock_detect,
        mock_validate,
        mock_metadata,
        mock_description,
        mock_posted_by,
        mock_posted_date,
    ) -> None:
        mock_detect.return_value = True
        mock_validate.return_value = None
        mock_metadata.return_value = {
            "title": "Product Manager",
            "company": "Acme",
            "location": "Bangalore",
        }
        mock_description.return_value = "Long job description"
        mock_posted_by.return_value = {
            "recruiter_name": "Jane",
            "recruiter_title": "",
            "recruiter_company": "",
            "recruiter_profile": "",
        }
        mock_posted_date.return_value = {
            "posted_at_raw": None,
            "posted_at_source": None,
            "posted_at_date": None,
            "age_days": None,
        }
        page = MagicMock()
        page.url = "https://www.instahyre.com/candidate/opportunities/job-12345/"

        job = _build_job_from_card(page, self._card())

        assert job is not None
        self.assertEqual(job["description"], "Long job description")
        self.assertTrue(job["applied"])


if __name__ == "__main__":
    unittest.main()
