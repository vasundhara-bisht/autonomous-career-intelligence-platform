"""Tests for dashboard date display helpers."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from date_display import (  # noqa: E402
    dashboard_date_input_value,
    format_dashboard_date,
    parse_dashboard_date_input,
)


class FormatDashboardDateTests(unittest.TestCase):
    def test_iso_date_renders_dd_mm_yyyy(self) -> None:
        self.assertEqual(format_dashboard_date("2026-06-11"), "11-06-2026")

    def test_datetime_renders_date_and_time(self) -> None:
        self.assertEqual(
            format_dashboard_date("2026-06-17 10:00:00"),
            "17-06-2026 10:00",
        )

    def test_blank_values(self) -> None:
        self.assertEqual(format_dashboard_date(None), "")
        self.assertEqual(format_dashboard_date("nan"), "")

    def test_date_object(self) -> None:
        self.assertEqual(format_dashboard_date(date(2026, 6, 10)), "10-06-2026")


class ParseDashboardDateInputTests(unittest.TestCase):
    def test_parses_display_format_to_iso(self) -> None:
        self.assertEqual(parse_dashboard_date_input("10-06-2026"), "2026-06-10")

    def test_accepts_legacy_iso_input(self) -> None:
        self.assertEqual(parse_dashboard_date_input("2026-06-10"), "2026-06-10")

    def test_blank_returns_none(self) -> None:
        self.assertIsNone(parse_dashboard_date_input(""))

    def test_dashboard_date_input_value(self) -> None:
        self.assertEqual(
            dashboard_date_input_value(datetime(2026, 6, 10, 15, 30)),
            "10-06-2026",
        )


if __name__ == "__main__":
    unittest.main()
