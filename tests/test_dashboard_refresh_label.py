"""Tests for dashboard Last acquisition refresh timezone display."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class AcquisitionRefreshLabelTests(unittest.TestCase):
    def test_utc_naive_completed_at_converts_to_local_for_display(self) -> None:
        from app import _acquisition_completed_at_to_local, _format_refresh_label

        utc_completed = pd.Timestamp("2026-06-07 16:20:47.781217")
        ist = ZoneInfo("Asia/Kolkata")

        with patch("app.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 6, 7, 22, 0, tzinfo=ist)
            local_ts = _acquisition_completed_at_to_local(utc_completed)

        label = _format_refresh_label(local_ts)
        self.assertEqual(label, "07 Jun 2026 · 09:50 PM")

    def test_refresh_labels_row_markup_and_layout(self) -> None:
        ui_source = (_REPO_ROOT / "dashboard" / "ui_help.py").read_text(encoding="utf-8")
        app_source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        self.assertIn("dash-refresh-labels", ui_source)
        self.assertIn("flex-wrap: wrap", ui_source)
        self.assertIn("render_refresh_labels_row(_last_refresh_label", app_source)

    def test_jobs_csv_mtime_path_uses_local_timestamp_unchanged(self) -> None:
        from app import _format_refresh_label

        local_ts = pd.Timestamp("2026-06-07 21:50:48")
        self.assertEqual(
            _format_refresh_label(local_ts),
            "07 Jun 2026 · 09:50 PM",
        )

    def test_monitoring_refresh_label_from_lifecycle_run(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app import load_last_monitoring_refresh_label

        class _FakeSession:
            def __enter__(self):
                return object()

            def __exit__(self, *args):
                return False

        load_last_monitoring_refresh_label.clear()
        ist = ZoneInfo("Asia/Kolkata")
        with patch("db.read.engine.get_dashboard_read_session", return_value=_FakeSession()):
            with patch(
                "db.read.monitor_runs.load_latest_productive_monitor_run_info",
                return_value={"completed_at": "2026-06-07 16:20:47.781217"},
            ):
                with patch("db.bootstrap.ensure_database_ready"):
                    with patch("app.datetime") as mock_datetime:
                        mock_datetime.now.return_value = datetime(
                            2026, 6, 7, 22, 0, tzinfo=ist
                        )
                        label = load_last_monitoring_refresh_label(True, 1.0)
        self.assertEqual(label, "07 Jun 2026 · 09:50 PM")

    def test_monitoring_refresh_unknown_without_sqlite(self) -> None:
        from app import load_last_monitoring_refresh_label

        self.assertEqual(load_last_monitoring_refresh_label(False, 0.0), "Unknown")
