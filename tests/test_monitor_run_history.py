"""Tests for monitor run history reads and dashboard table builders."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from db.read.monitor_runs import load_monitor_run_history  # noqa: E402
from monitor_ui import (  # noqa: E402
    build_monitor_run_history_df,
    format_monitor_duration,
    format_monitor_timestamp,
)


class MonitorRunHistoryReadTests(unittest.TestCase):
    def test_load_monitor_run_history_orders_most_recent_first(self) -> None:
        session = MagicMock()
        session.execute.return_value.mappings.return_value.all.return_value = [
            {"run_id": 15, "status": "completed"},
            {"run_id": 14, "status": "completed"},
        ]
        rows = load_monitor_run_history(session, limit=25)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["run_id"], 15)
        sql = str(session.execute.call_args[0][0])
        self.assertIn("ORDER BY COALESCE(completed_at, started_at) DESC", sql)
        self.assertIn("run_trigger", sql)
        self.assertEqual(session.execute.call_args[0][1], {"limit": 25})


class MonitorRunHistoryTableTests(unittest.TestCase):
    def test_build_history_df_labels_runs_and_columns(self) -> None:
        df = build_monitor_run_history_df(
            [
                {
                    "run_id": 15,
                    "started_at": datetime(2026, 6, 23, 4, 30, 38),
                    "completed_at": datetime(2026, 6, 23, 6, 44, 12),
                    "duration_sec": 8024.0,
                    "status": "completed",
                    "cohort_size": 984,
                    "checked_count": 984,
                    "open_count": 900,
                    "closed_count": 50,
                    "removed_count": 20,
                    "check_failed_count": 14,
                    "check_failed_rate": 0.014,
                    "auth_health": "ok",
                }
            ]
        )
        self.assertEqual(df.iloc[0]["Run"], "Run 15")
        self.assertEqual(df.iloc[0]["Login status"], "Connected")
        self.assertEqual(df.iloc[0]["Cohort"], 984)
        self.assertEqual(df.iloc[0]["Need attention"], 14)
        self.assertEqual(df.iloc[0]["Failure rate"], "1%")
        self.assertEqual(df.iloc[0]["Status"], "Completed")
        self.assertIn("Trigger", df.columns)
        self.assertEqual(df.iloc[0]["Trigger"], "—")

    def test_build_history_df_shows_run_trigger(self) -> None:
        df = build_monitor_run_history_df(
            [
                {
                    "run_id": 16,
                    "started_at": datetime(2026, 6, 23, 4, 30, 38),
                    "completed_at": datetime(2026, 6, 23, 6, 44, 12),
                    "duration_sec": 8024.0,
                    "status": "completed",
                    "run_trigger": "scheduled",
                    "cohort_size": 10,
                    "checked_count": 10,
                    "open_count": 8,
                    "closed_count": 1,
                    "removed_count": 1,
                    "check_failed_count": 0,
                    "check_failed_rate": 0.0,
                    "auth_health": "ok",
                }
            ]
        )
        self.assertEqual(df.iloc[0]["Trigger"], "Scheduled")

    def test_build_history_df_running_row_uses_placeholders(self) -> None:
        df = build_monitor_run_history_df(
            [
                {
                    "run_id": 17,
                    "started_at": datetime(2026, 6, 23, 5, 0, 0),
                    "completed_at": None,
                    "status": "running",
                    "run_trigger": "manual",
                    "cohort_size": 0,
                    "checked_count": 0,
                    "auth_health": "ok",
                }
            ]
        )
        self.assertEqual(df.iloc[0]["Status"], "Running")
        self.assertEqual(df.iloc[0]["Trigger"], "Manual")
        self.assertEqual(df.iloc[0]["Completed"], "—")
        self.assertEqual(df.iloc[0]["Duration"], "—")
        self.assertEqual(df.iloc[0]["Login status"], "—")
        self.assertEqual(df.iloc[0]["Cohort"], "—")
        self.assertEqual(df.iloc[0]["Checked"], "—")

    def test_format_duration_prefers_persisted_duration_sec(self) -> None:
        label = format_monitor_duration(
            duration_sec=3661.0,
            started_at=datetime(2026, 6, 23, 1, 0, 0),
            completed_at=datetime(2026, 6, 23, 1, 5, 0),
        )
        self.assertEqual(label, "1h 1m")

    def test_format_duration_falls_back_to_timestamps(self) -> None:
        label = format_monitor_duration(
            duration_sec=None,
            started_at=datetime(2026, 6, 23, 1, 0, 0),
            completed_at=datetime(2026, 6, 23, 1, 2, 30),
        )
        self.assertEqual(label, "2m 30s")

    def test_format_timestamp_returns_dash_when_missing(self) -> None:
        self.assertEqual(format_monitor_timestamp(None), "—")


if __name__ == "__main__":
    unittest.main()
