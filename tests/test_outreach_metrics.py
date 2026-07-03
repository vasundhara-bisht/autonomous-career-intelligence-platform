"""Tests for outreach KPI metrics."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach_metrics import compute_outreach_metrics  # noqa: E402


class OutreachMetricsTests(unittest.TestCase):
    def test_empty_dataframe(self) -> None:
        metrics = compute_outreach_metrics(pd.DataFrame(), reference_date=date(2026, 6, 10))
        self.assertEqual(metrics.total, 0)
        self.assertEqual(metrics.active, 0)

    def test_active_and_followups(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "status": "sent",
                    "follow_up_date": "2026-06-10",
                },
                {
                    "status": "closed",
                    "follow_up_date": "2026-06-10",
                },
                {
                    "status": "replied",
                    "follow_up_date": "2026-06-08",
                },
            ]
        )
        metrics = compute_outreach_metrics(df, reference_date=date(2026, 6, 10))
        self.assertEqual(metrics.total, 3)
        self.assertEqual(metrics.active, 2)
        self.assertEqual(metrics.follow_ups_due_today, 1)
        self.assertEqual(metrics.overdue_follow_ups, 1)


if __name__ == "__main__":
    unittest.main()
