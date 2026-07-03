"""Tests for provider monitor snapshot read model."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class MonitorProviderMetricsReadTests(unittest.TestCase):
    def test_load_provider_monitor_snapshots_per_source_counts(self) -> None:
        from db.read.monitor_provider_metrics import load_provider_monitor_snapshots

        dashboard_df = pd.DataFrame(
            [
                {
                    "source": "linkedin",
                    "listing_status": "check_failed",
                    "listing_check_paused_at": None,
                },
                {
                    "source": "linkedin",
                    "listing_status": "check_failed",
                    "listing_check_paused_at": "2026-06-01",
                },
                {
                    "source": "instahyre",
                    "listing_status": "check_failed",
                    "listing_check_paused_at": None,
                },
                {
                    "source": "instahyre",
                    "listing_status": "open",
                    "listing_check_paused_at": None,
                },
            ]
        )
        run_info = {
            "auth_health": "ok",
            "started_at": datetime(2026, 6, 30, 10, 0, 0),
            "completed_at": datetime(2026, 6, 30, 10, 15, 0),
            "provider_summary": (
                "auth_probe_reason=auth:ok,"
                "instahyre_auth_health=ok,"
                "instahyre_auth_probe_reason=auth:ok"
            ),
        }
        session = MagicMock()
        ref = datetime(2026, 6, 30, 2, 43, tzinfo=UTC).replace(tzinfo=None)

        with (
            patch(
                "db.read.monitor_provider_metrics.load_monitor_governance_config",
            ) as mock_config,
            patch(
                "db.read.monitor_provider_metrics.count_provider_checks_today",
                side_effect=[10, 140],
            ),
            patch(
                "db.read.monitor_provider_metrics.budget_day_start",
                return_value=ref,
            ),
            patch(
                "db.read.monitor_provider_metrics.load_provider_state_map",
                return_value={},
            ),
            patch(
                "db.read.monitor_provider_metrics.count_monitor_candidates_by_source",
                side_effect=[42, 17],
            ),
            patch(
                "db.read.monitor_summary.count_provider_checks_in_run_window",
                return_value=2,
            ),
        ):
            mock_config.return_value.linkedin_max_per_day = 150
            mock_config.return_value.instahyre_max_per_day = 500
            snapshots = load_provider_monitor_snapshots(
                session,
                dashboard_df=dashboard_df,
                run_info=run_info,
                reference_at=ref,
            )

        self.assertEqual(snapshots["linkedin"].checks_today, 10)
        self.assertEqual(snapshots["linkedin"].budget_remaining, 140)
        self.assertEqual(snapshots["linkedin"].jobs_needing_attention, 1)
        self.assertEqual(snapshots["linkedin"].jobs_paused, 1)
        self.assertEqual(snapshots["instahyre"].jobs_needing_attention, 1)
        self.assertEqual(snapshots["instahyre"].jobs_paused, 0)
        self.assertEqual(snapshots["instahyre"].login_health, "ok")
        self.assertTrue(snapshots["instahyre"].login_applicable_this_run)
        self.assertEqual(snapshots["linkedin"].eligible_monitor_queue, 42)
        self.assertEqual(snapshots["instahyre"].eligible_monitor_queue, 17)

    def test_instahyre_login_not_applicable_when_no_monitoring_work(self) -> None:
        from db.read.monitor_provider_metrics import load_provider_monitor_snapshots

        dashboard_df = pd.DataFrame()
        run_info = {
            "auth_health": "ok",
            "started_at": datetime(2026, 6, 30, 10, 0, 0),
            "completed_at": datetime(2026, 6, 30, 10, 15, 0),
            "provider_summary": (
                "auth_probe_reason=auth:ok,"
                "instahyre_auth_health=degraded,"
                "instahyre_auth_probe_reason=probe:bot_protection"
            ),
        }
        session = MagicMock()
        ref = datetime(2026, 6, 30, 12, 0, tzinfo=UTC).replace(tzinfo=None)

        with (
            patch(
                "db.read.monitor_provider_metrics.load_monitor_governance_config",
            ) as mock_config,
            patch(
                "db.read.monitor_provider_metrics.count_provider_checks_today",
                side_effect=[150, 0],
            ),
            patch(
                "db.read.monitor_provider_metrics.budget_day_start",
                return_value=ref,
            ),
            patch(
                "db.read.monitor_provider_metrics.load_provider_state_map",
                return_value={},
            ),
            patch(
                "db.read.monitor_provider_metrics.count_monitor_candidates_by_source",
                side_effect=[709, 0],
            ),
            patch(
                "db.read.monitor_summary.count_provider_checks_in_run_window",
                return_value=0,
            ),
        ):
            mock_config.return_value.linkedin_max_per_day = 150
            mock_config.return_value.instahyre_max_per_day = 500
            snapshots = load_provider_monitor_snapshots(
                session,
                dashboard_df=dashboard_df,
                run_info=run_info,
                reference_at=ref,
            )

        self.assertEqual(snapshots["instahyre"].login_health, "degraded")
        self.assertEqual(snapshots["instahyre"].login_reason, "probe:bot_protection")
        self.assertFalse(snapshots["instahyre"].login_applicable_this_run)
        self.assertTrue(snapshots["linkedin"].login_applicable_this_run)


if __name__ == "__main__":
    unittest.main()
