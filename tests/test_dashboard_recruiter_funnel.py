"""Tests for recruiter relationship progression counts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from recruiter_funnel import compute_recruiter_progression_counts  # noqa: E402
from recruiter_stages import ALL_RECRUITER_STAGES, CRM_STATUS_OPTIONS  # noqa: E402


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "recruiter_stage": [
                "discovered",
                "discovered",
                "warm",
                "active",
                "responded",
                "ghosted",
                "archived",
                "",
                None,
            ]
        }
    )


class RecruiterFunnelTests(unittest.TestCase):
    def test_compute_recruiter_progression_counts(self) -> None:
        counts = compute_recruiter_progression_counts(_sample_df())
        self.assertEqual(counts.total, 9)
        self.assertEqual(counts.stage_counts.get("discovered"), 4)
        self.assertEqual(counts.stage_counts.get("warm"), 1)
        self.assertEqual(counts.stage_counts.get("active"), 1)
        self.assertEqual(counts.stage_counts.get("responded"), 1)
        self.assertEqual(counts.stage_counts.get("ghosted"), 1)
        self.assertEqual(counts.stage_counts.get("archived"), 1)

    def test_unknown_recruiter_stage_buckets_to_discovered(self) -> None:
        df = pd.DataFrame({"recruiter_stage": ["mystery", "discovered"]})
        counts = compute_recruiter_progression_counts(df)
        self.assertEqual(counts.stage_counts.get("discovered"), 2)
        self.assertNotIn("mystery", counts.stage_counts)

    def test_empty_cohort(self) -> None:
        counts = compute_recruiter_progression_counts(pd.DataFrame())
        self.assertEqual(counts.total, 0)
        self.assertEqual(counts.stage_counts, {})

    def test_crm_status_options_match_stages_module(self) -> None:
        self.assertEqual(CRM_STATUS_OPTIONS, list(ALL_RECRUITER_STAGES))


if __name__ == "__main__":
    unittest.main()
