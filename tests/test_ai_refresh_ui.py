"""Tests for AI Refresh Health dashboard section."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from ai_refresh_ui import build_ai_refresh_run_history_df  # noqa: E402


class AiRefreshUiTests(unittest.TestCase):
    def test_history_df_columns(self) -> None:
        df = build_ai_refresh_run_history_df(
            [
                {
                    "run_id": 3,
                    "preset": "discovery",
                    "started_at": "2026-06-10 09:00:00",
                    "completed_at": "2026-06-10 09:05:00",
                    "status": "completed",
                    "cohort_size": 12,
                    "eligible_count": 10,
                    "scored_count": 8,
                    "persist_skipped_count": 0,
                    "skipped_by_cap_count": 2,
                    "skipped_no_description": 2,
                }
            ]
        )
        self.assertEqual(list(df.columns), [
            "Run",
            "Preset",
            "Started",
            "Completed",
            "Duration",
            "Cohort",
            "Eligible",
            "Scored",
            "Persist Skipped",
            "No Description",
            "Status",
        ])
        self.assertEqual(df.iloc[0]["Run"], "Run 3")
        self.assertEqual(df.iloc[0]["Preset"], "Refresh Evaluations")
        self.assertEqual(int(df.iloc[0]["Scored"]), 8)

    def test_app_wires_ai_refresh_health(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        self.assertIn("render_ai_refresh_health_section", source)
        acquisition_idx = source.index("render_acquisition_health_section()")
        refresh_idx = source.index("render_ai_refresh_health_section()")
        monitor_idx = source.index("render_operational_monitor_health_section(")
        controls_idx = source.index("render_operational_controls_section()")
        self.assertLess(controls_idx, acquisition_idx)
        self.assertLess(acquisition_idx, monitor_idx)
        self.assertLess(monitor_idx, refresh_idx)


if __name__ == "__main__":
    unittest.main()
