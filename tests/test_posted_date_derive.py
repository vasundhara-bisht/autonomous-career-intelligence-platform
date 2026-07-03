"""Tests for posted_at_date derivation from time_posted."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.posted_date_derive import (  # noqa: E402
    derive_posted_at_date,
    parse_time_posted_to_date,
)

_ANCHOR = date(2026, 6, 17)


class ParseTimePostedToDateTests(unittest.TestCase):
    def test_hours_ago_same_day(self) -> None:
        self.assertEqual(parse_time_posted_to_date("21 hours ago", _ANCHOR), _ANCHOR)

    def test_minutes_ago_same_day(self) -> None:
        for text in ("1 minute ago", "21 minutes ago", "59 minutes ago"):
            with self.subTest(text=text):
                self.assertEqual(parse_time_posted_to_date(text, _ANCHOR), _ANCHOR)

    def test_days_ago(self) -> None:
        self.assertEqual(
            parse_time_posted_to_date("2 days ago", _ANCHOR),
            date(2026, 6, 15),
        )

    def test_weeks_ago(self) -> None:
        self.assertEqual(
            parse_time_posted_to_date("1 week ago", _ANCHOR),
            date(2026, 6, 10),
        )

    def test_months_ago(self) -> None:
        self.assertEqual(
            parse_time_posted_to_date("1 month ago", _ANCHOR),
            date(2026, 5, 18),
        )

    def test_years_ago(self) -> None:
        self.assertEqual(
            parse_time_posted_to_date("2 years ago", _ANCHOR),
            date(2024, 6, 17),
        )

    def test_compact_days(self) -> None:
        self.assertEqual(parse_time_posted_to_date("14d", _ANCHOR), date(2026, 6, 3))

    def test_just_now(self) -> None:
        self.assertEqual(parse_time_posted_to_date("just now", _ANCHOR), _ANCHOR)

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(parse_time_posted_to_date("Unknown", _ANCHOR))
        self.assertIsNone(parse_time_posted_to_date("", _ANCHOR))
        self.assertIsNone(parse_time_posted_to_date("N/A", _ANCHOR))

    def test_iso_in_time_posted(self) -> None:
        self.assertEqual(
            parse_time_posted_to_date("2026-04-28", _ANCHOR),
            date(2026, 4, 28),
        )


class DerivePostedAtDateTests(unittest.TestCase):
    def test_derives_from_time_posted(self) -> None:
        job = {"time_posted": "1 day ago", "company": "Acme"}
        out = derive_posted_at_date(job, _ANCHOR)
        self.assertEqual(out["posted_at_date"], "2026-06-16")
        self.assertEqual(out["age_days"], 1)

    def test_derives_from_minutes_ago(self) -> None:
        job = {"time_posted": "21 minutes ago", "company": "Origin"}
        out = derive_posted_at_date(job, _ANCHOR)
        self.assertEqual(out["posted_at_date"], "2026-06-17")
        self.assertEqual(out["age_days"], 0)

    def test_does_not_overwrite_existing(self) -> None:
        job = {
            "time_posted": "1 day ago",
            "posted_at_date": "2026-04-28",
            "age_days": 50,
        }
        out = derive_posted_at_date(job, _ANCHOR)
        self.assertEqual(out["posted_at_date"], "2026-04-28")
        self.assertEqual(out["age_days"], 50)

    def test_unconvertible_leaves_unchanged(self) -> None:
        job = {"time_posted": "Unknown"}
        out = derive_posted_at_date(job, _ANCHOR)
        self.assertNotIn("posted_at_date", out)


if __name__ == "__main__":
    unittest.main()
