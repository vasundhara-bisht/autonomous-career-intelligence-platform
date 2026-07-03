"""Recommended Actions listing-status gating tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from recommended_actions import compute_recommended_actions  # noqa: E402


def _eligible_row(*, listing_status: str = "open") -> dict:
    return {
        "JOB_KEY": "k1",
        "JOB_KEY_V2": "v2-1",
        "title": "Engineer",
        "company": "Acme",
        "source": "linkedin",
        "link": "https://example.com/job",
        "pipeline_stage": "New",
        "score": 9,
        "ai_status": "scored",
        "is_ai_scored": True,
        "reason": "Strong match",
        "listing_status": listing_status,
        "first_seen": "2026-06-14",
        "posted_at_date": "2026-06-14",
        "age_days_derived": 2,
    }


class RecommendedActionsListingTests(unittest.TestCase):
    def test_excludes_non_open_listings(self) -> None:
        df = pd.DataFrame(
            [
                _eligible_row(listing_status="open"),
                _eligible_row(listing_status="closed"),
                _eligible_row(listing_status="check_failed"),
            ]
        )
        result = compute_recommended_actions(df)
        entity_keys = {a.entity_key for a in result.high_confidence}
        self.assertEqual(entity_keys, {"v2-1"})


if __name__ == "__main__":
    unittest.main()
