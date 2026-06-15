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

    def test_jobs_csv_mtime_path_uses_local_timestamp_unchanged(self) -> None:
        from app import _format_refresh_label

        local_ts = pd.Timestamp("2026-06-07 21:50:48")
        self.assertEqual(
            _format_refresh_label(local_ts),
            "07 Jun 2026 · 09:50 PM",
        )
