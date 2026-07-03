"""Tests for applied-status merge in materialize_fully_processed_job."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.main import materialize_fully_processed_job  # noqa: E402


class MaterializeAppliedMergeTests(unittest.TestCase):
    def test_scrape_applied_wins_over_historical_false(self) -> None:
        job = {"applied": True, "title": "PM", "company": "Co"}
        historical = {
            "applied": False,
            "pipeline_stage": "New",
            "ai_score": 8.0,
            "ai_status": "scored",
            "reason": "Strong",
        }
        materialize_fully_processed_job(job, historical)
        self.assertTrue(job["applied"])
        self.assertNotIn("pipeline_stage", job)

    def test_scrape_applied_does_not_override_interview(self) -> None:
        job = {"applied": True, "title": "PM", "company": "Co"}
        historical = {
            "applied": False,
            "pipeline_stage": "Interview",
            "ai_score": 8.0,
            "ai_status": "scored",
        }
        materialize_fully_processed_job(job, historical)
        self.assertFalse(job["applied"])

    def test_scrape_applied_does_not_override_rejected(self) -> None:
        job = {"applied": True, "title": "PM", "company": "Co"}
        historical = {
            "applied": False,
            "rejected": True,
            "pipeline_stage": "Rejected",
            "ai_score": 8.0,
            "ai_status": "scored",
        }
        materialize_fully_processed_job(job, historical)
        self.assertFalse(job["applied"])
        self.assertTrue(job["rejected"])

    def test_scrape_applied_does_not_override_saved(self) -> None:
        job = {"applied": True, "title": "PM", "company": "Co"}
        historical = {
            "applied": False,
            "pipeline_stage": "Saved",
            "ai_score": 8.0,
            "ai_status": "scored",
        }
        materialize_fully_processed_job(job, historical)
        self.assertFalse(job["applied"])

    def test_scrape_not_applied_does_not_downgrade_historical_applied(self) -> None:
        job = {"applied": False, "title": "PM", "company": "Co"}
        historical = {
            "applied": True,
            "pipeline_stage": "Applied",
            "ai_score": 8.0,
            "ai_status": "scored",
        }
        materialize_fully_processed_job(job, historical)
        self.assertTrue(job["applied"])

    def test_sentinel_scrape_preserves_historical_hiring_manager(self) -> None:
        job = {
            "applied": False,
            "title": "PM",
            "company": "Co",
            "hiring_manager": "Not Specified",
        }
        historical = {
            "applied": False,
            "pipeline_stage": "New",
            "ai_score": 8.0,
            "ai_status": "scored",
            "hiring_manager": "Jane Recruiter",
        }
        materialize_fully_processed_job(job, historical)
        self.assertEqual(job["hiring_manager"], "Jane Recruiter")

    def test_valid_scrape_hiring_manager_not_overwritten(self) -> None:
        job = {
            "applied": False,
            "title": "PM",
            "company": "Co",
            "hiring_manager": "New Recruiter",
        }
        historical = {
            "applied": False,
            "pipeline_stage": "New",
            "ai_score": 8.0,
            "ai_status": "scored",
            "hiring_manager": "Jane Recruiter",
        }
        materialize_fully_processed_job(job, historical)
        self.assertEqual(job["hiring_manager"], "New Recruiter")


if __name__ == "__main__":
    unittest.main()
