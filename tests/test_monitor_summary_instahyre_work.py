"""Tests for InstaHyre monitoring-work detection from run data."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class MonitorSummaryInstahyreWorkTests(unittest.TestCase):
    def test_from_summary_backfill(self) -> None:
        from db.read.monitor_summary import instahyre_monitoring_work_performed_from_summary

        self.assertTrue(
            instahyre_monitoring_work_performed_from_summary(
                {"instahyre_backfill_count": "2"},
            )
        )

    def test_from_summary_skipped_limit(self) -> None:
        from db.read.monitor_summary import instahyre_monitoring_work_performed_from_summary

        self.assertTrue(
            instahyre_monitoring_work_performed_from_summary(
                {"instahyre_skipped_limit": "5"},
            )
        )

    def test_from_summary_reconciliation(self) -> None:
        from db.read.monitor_summary import instahyre_monitoring_work_performed_from_summary

        self.assertTrue(
            instahyre_monitoring_work_performed_from_summary(
                {"instahyre_auth_probe_reason": "auth:ok_monitor_reconciliation"},
            )
        )

    def test_from_summary_probe_only_is_false(self) -> None:
        from db.read.monitor_summary import instahyre_monitoring_work_performed_from_summary

        self.assertFalse(
            instahyre_monitoring_work_performed_from_summary(
                {
                    "instahyre_auth_health": "degraded",
                    "instahyre_auth_probe_reason": "probe:bot_protection",
                }
            )
        )

    def test_in_run_uses_run_window_when_summary_silent(self) -> None:
        from db.read.monitor_summary import instahyre_monitoring_work_performed_in_run

        run_info = {
            "started_at": datetime(2026, 6, 30, 10, 0, 0),
            "completed_at": datetime(2026, 6, 30, 10, 15, 0),
        }
        session = MagicMock()
        with patch(
            "db.read.monitor_summary.count_provider_checks_in_run_window",
            return_value=3,
        ) as mock_count:
            result = instahyre_monitoring_work_performed_in_run(
                run_info,
                {},
                session=session,
            )
        self.assertTrue(result)
        mock_count.assert_called_once()

    def test_in_run_false_when_no_summary_signals_and_zero_window_checks(self) -> None:
        from db.read.monitor_summary import instahyre_monitoring_work_performed_in_run

        run_info = {
            "started_at": datetime(2026, 6, 30, 10, 0, 0),
            "completed_at": datetime(2026, 6, 30, 10, 15, 0),
        }
        session = MagicMock()
        with patch(
            "db.read.monitor_summary.count_provider_checks_in_run_window",
            return_value=0,
        ):
            result = instahyre_monitoring_work_performed_in_run(
                run_info,
                {
                    "instahyre_auth_health": "degraded",
                    "instahyre_auth_probe_reason": "probe:bot_protection",
                },
                session=session,
            )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
