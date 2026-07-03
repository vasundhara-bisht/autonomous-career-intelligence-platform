"""Dashboard data-flow tests for listing-status visibility."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from data_flow import build_dashboard_df  # noqa: E402


def _row(
    *,
    stage: str = "New",
    listing_status: str = "open",
) -> dict:
    return {
        "JOB_KEY": "k1",
        "title": "Engineer",
        "company": "Acme",
        "location": "Remote",
        "source": "linkedin",
        "score": 8,
        "ai_status": "scored",
        "is_ai_scored": True,
        "pipeline_stage": stage,
        "listing_status": listing_status,
        "posted_at_date": "2026-06-10",
        "first_seen": "2026-01-01",
    }


class BuildDashboardDfTests(unittest.TestCase):
    def test_listing_visibility_hides_removed_only(self) -> None:
        df = pd.DataFrame(
            [
                {**_row(stage="New", listing_status="removed"), "JOB_KEY": "removed"},
                {**_row(stage="New", listing_status="open"), "JOB_KEY": "open"},
                {**_row(stage="New", listing_status="closed"), "JOB_KEY": "closed"},
                {**_row(stage="Applied", listing_status="closed"), "JOB_KEY": "applied"},
            ]
        )
        out = build_dashboard_df(df)
        keys = set(out["JOB_KEY"].tolist())
        self.assertNotIn("removed", keys)
        self.assertIn("open", keys)
        self.assertIn("closed", keys)
        self.assertIn("applied", keys)
        self.assertIn("age_bucket", out.columns)
        self.assertIn("age_days_derived", out.columns)


if __name__ == "__main__":
    unittest.main()
