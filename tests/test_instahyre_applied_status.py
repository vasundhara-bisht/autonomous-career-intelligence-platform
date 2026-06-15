"""Unit tests for Instahyre applied-status detection (no Playwright)."""

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
    _detail_applied_signals_present,
    _parse_applied_signals_from_html,
)


class InstahyreAppliedSignalTests(unittest.TestCase):
    def test_detect_applied_from_apply_applied_class(self) -> None:
        html = '<div class="apply applied ng-scope"><button disabled>Done</button></div>'
        self.assertTrue(_parse_applied_signals_from_html(html))

    def test_detect_applied_from_application_sent_text(self) -> None:
        html = "<div><button>Application Sent!</button></div>"
        self.assertTrue(_parse_applied_signals_from_html(html))

    def test_detect_applied_from_tooltip_already_applied(self) -> None:
        html = (
            '<button tooltip-text="You have already applied<br/>to this job" '
            'data-original-title="You have already applied to this job">'
            "Application Sent!</button>"
        )
        self.assertTrue(_parse_applied_signals_from_html(html))

    def test_detect_not_applied_open_job(self) -> None:
        html = (
            '<div class="apply"><button class="btn btn-primary">Apply</button></div>'
        )
        self.assertFalse(_parse_applied_signals_from_html(html))

    def test_detail_applied_signals_present_direct(self) -> None:
        self.assertTrue(
            _detail_applied_signals_present(
                has_apply_applied_class=True,
                body_text="",
                tooltip_texts=(),
            )
        )
        self.assertTrue(
            _detail_applied_signals_present(
                body_text="Application Sent! on June 8, 2026",
            )
        )
        self.assertFalse(
            _detail_applied_signals_present(
                body_text="no longer accepting applications",
            )
        )


class InstahyreBuildJobAppliedTests(unittest.TestCase):
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
    @patch("scraper.instahyre._extract_detail_company")
    @patch("scraper.instahyre._extract_detail_title")
    @patch("scraper.instahyre._validate_detail_page")
    @patch("scraper.instahyre._detect_applied_on_detail_page")
    def test_build_job_dict_sets_applied_only(
        self,
        mock_detect,
        mock_validate,
        mock_title,
        mock_company,
        mock_description,
        mock_posted_by,
        mock_posted_date,
    ) -> None:
        mock_detect.return_value = True
        mock_validate.return_value = None
        mock_title.return_value = "Product Manager"
        mock_company.return_value = "Acme"
        mock_description.return_value = "Job description"
        mock_posted_by.return_value = {
            "recruiter_name": "",
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

        self.assertIsNotNone(job)
        assert job is not None
        self.assertTrue(job["applied"])
        self.assertNotIn("pipeline_stage", job)

    @patch("scraper.instahyre._extract_job_posting_posted_date")
    @patch("scraper.instahyre._extract_job_posted_by")
    @patch("scraper.instahyre._extract_description")
    @patch("scraper.instahyre._extract_detail_company")
    @patch("scraper.instahyre._extract_detail_title")
    @patch("scraper.instahyre._validate_detail_page")
    @patch("scraper.instahyre._detect_applied_on_detail_page")
    def test_build_job_dict_not_applied_has_no_stage(
        self,
        mock_detect,
        mock_validate,
        mock_title,
        mock_company,
        mock_description,
        mock_posted_by,
        mock_posted_date,
    ) -> None:
        mock_detect.return_value = False
        mock_validate.return_value = None
        mock_title.return_value = "Product Manager"
        mock_company.return_value = "Acme"
        mock_description.return_value = "Job description"
        mock_posted_by.return_value = {
            "recruiter_name": "",
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

        self.assertIsNotNone(job)
        assert job is not None
        self.assertFalse(job["applied"])
        self.assertNotIn("pipeline_stage", job)


if __name__ == "__main__":
    unittest.main()
