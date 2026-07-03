"""Tests for listing-status visibility and TD8 age buckets."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from listing_visibility import (  # noqa: E402
    AGE_BUCKET_AGING,
    AGE_BUCKET_FRESH,
    AGE_BUCKET_STALE,
    apply_listing_visibility,
    count_check_failed_jobs,
    derive_age_bucket,
    derive_age_days,
    format_listing_badge_row,
    listing_status_badge,
    normalize_listing_status,
)


class AgeBucketTests(unittest.TestCase):
    def test_derive_age_days_prefers_posted_at_date(self) -> None:
        ref = date(2026, 6, 16)
        days = derive_age_days(
            posted_at_date="2026-06-10",
            first_seen="2026-01-01",
            reference=ref,
        )
        self.assertEqual(days, 6)

    def test_derive_age_days_falls_back_to_first_seen(self) -> None:
        ref = date(2026, 6, 16)
        days = derive_age_days(
            posted_at_date=None,
            first_seen="2026-06-14",
            reference=ref,
        )
        self.assertEqual(days, 2)

    def test_age_bucket_boundaries(self) -> None:
        self.assertEqual(derive_age_bucket(0), AGE_BUCKET_FRESH)
        self.assertEqual(derive_age_bucket(3), AGE_BUCKET_FRESH)
        self.assertEqual(derive_age_bucket(4), AGE_BUCKET_AGING)
        self.assertEqual(derive_age_bucket(13), AGE_BUCKET_AGING)
        self.assertEqual(derive_age_bucket(14), AGE_BUCKET_STALE)


class ListingVisibilityTests(unittest.TestCase):
    def test_removed_hidden(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "JOB_KEY": "a",
                    "pipeline_stage": "New",
                    "listing_status": "removed",
                }
            ]
        )
        out = apply_listing_visibility(df)
        self.assertTrue(out.empty)

    def test_monitor_exempt_only_when_user_managed(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "JOB_KEY": "a",
                    "pipeline_stage": "New",
                    "listing_status": "monitor_exempt",
                },
                {
                    "JOB_KEY": "b",
                    "pipeline_stage": "Applied",
                    "listing_status": "monitor_exempt",
                },
            ]
        )
        out = apply_listing_visibility(df)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["JOB_KEY"], "b")

    def test_closed_visible_for_all_stages(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "JOB_KEY": "a",
                    "pipeline_stage": "New",
                    "listing_status": "closed",
                },
                {
                    "JOB_KEY": "b",
                    "pipeline_stage": "Saved",
                    "listing_status": "closed",
                },
            ]
        )
        out = apply_listing_visibility(df)
        self.assertEqual(len(out), 2)
        self.assertEqual(set(out["JOB_KEY"].tolist()), {"a", "b"})

    def test_check_failed_badge_paused_vs_pending(self) -> None:
        self.assertEqual(
            listing_status_badge(listing_status="check_failed"),
            "Check pending",
        )
        self.assertEqual(
            listing_status_badge(
                listing_status="check_failed",
                listing_check_paused_at="2026-06-01",
            ),
            "Check paused",
        )

    def test_format_listing_badge_row(self) -> None:
        row = pd.Series(
            {
                "listing_status": "open",
                "listing_check_paused_at": None,
                "consecutive_check_failures": 0,
            }
        )
        self.assertEqual(format_listing_badge_row(row), "Open")


class CheckFailedCountTests(unittest.TestCase):
    def test_count_check_failed_jobs_filters_by_source(self) -> None:
        df = pd.DataFrame(
            [
                {"source": "linkedin", "listing_status": "check_failed", "listing_check_paused_at": None},
                {"source": "instahyre", "listing_status": "check_failed", "listing_check_paused_at": None},
                {"source": "instahyre", "listing_status": "check_failed", "listing_check_paused_at": "2026-01-01"},
            ]
        )
        active, paused = count_check_failed_jobs(df, source="instahyre")
        self.assertEqual(active, 1)
        self.assertEqual(paused, 1)


if __name__ == "__main__":
    unittest.main()
