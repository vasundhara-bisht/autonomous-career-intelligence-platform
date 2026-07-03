"""Tests for dashboard_df vs filtered_df data-flow split."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from data_flow import (  # noqa: E402
    SidebarFilterState,
    apply_date_range_filter,
    apply_sidebar_filters,
    build_dashboard_df,
)
from listing_visibility import apply_listing_visibility  # noqa: E402
from funnel import compute_progression_funnel_counts  # noqa: E402
from recommended_actions import compute_recommended_actions  # noqa: E402


def _job_row(
    *,
    stage: str = "New",
    location: str = "Bangalore",
    source: str = "instahyre",
    is_ai_scored: bool = False,
    score: float = 0,
    listing_status: str = "open",
    hiring_manager: str = "Not Specified",
    ai_status: str = "pending",
    first_seen: str = "2026-06-09 12:00:00",
    last_seen: str = "2026-06-17 10:00:00",
    posted_at_date: str | None = "2026-06-09",
    reason: str = "",
) -> dict:
    return {
        "JOB_KEY": f"key-{stage}-{location}",
        "JOB_KEY_V2": f"v2:key-{stage}-{location}",
        "title": "PM",
        "company": "Co",
        "link": "https://example.com/job",
        "location": location,
        "source": source,
        "pipeline_stage": stage,
        "is_ai_scored": is_ai_scored,
        "ai_status": ai_status,
        "score": score,
        "listing_status": listing_status,
        "hiring_manager": hiring_manager,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "posted_at_date": posted_at_date,
        "reason": reason,
        "applied": False,
        "rejected": False,
        "interview": False,
        "offer": False,
        "notes": "",
    }


def _default_filters(**overrides) -> SidebarFilterState:
    base = {
        "date_column": "posted_at_date",
        "date_preset": "All time",
        "custom_start": None,
        "custom_end": None,
        "selected_location": "All",
        "selected_sources": ("instahyre",),
        "selected_statuses": ("New", "Saved", "Applied"),
        "min_score": 0,
        "recruiter_only": False,
    }
    base.update(overrides)
    return SidebarFilterState(**base)


class DashboardDfTests(unittest.TestCase):
    def test_dashboard_df_applies_listing_visibility_only(self) -> None:
        raw = pd.DataFrame(
            [
                _job_row(stage="New", listing_status="removed"),
                _job_row(stage="Applied", listing_status="closed"),
            ]
        )
        dashboard_df = build_dashboard_df(raw)
        self.assertEqual(len(dashboard_df), 1)
        self.assertEqual(str(dashboard_df.iloc[0]["pipeline_stage"]), "Applied")

    def test_header_total_jobs_matches_dashboard_df(self) -> None:
        raw = pd.DataFrame(
            [
                _job_row(stage="New", listing_status="open"),
                _job_row(stage="New", listing_status="removed"),
                _job_row(stage="Applied", listing_status="closed"),
            ]
        )
        dashboard_df = build_dashboard_df(raw)
        self.assertEqual(len(dashboard_df), 2)


class SidebarFilterIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboard_df = pd.DataFrame(
            [
                _job_row(stage="New", location="Bangalore", is_ai_scored=True, score=8),
                _job_row(stage="New", location="Remote", is_ai_scored=True, score=3),
                _job_row(stage="Applied", location="Bangalore"),
                _job_row(stage="Rejected", location="Bangalore"),
            ]
        )

    def test_sidebar_filters_reduce_row_count(self) -> None:
        filters = _default_filters(
            selected_location="Bangalore",
            selected_statuses=("New", "Saved", "Applied", "Rejected", "Ghosted"),
        )
        filtered_df = apply_sidebar_filters(self.dashboard_df, filters)
        self.assertLess(len(filtered_df), len(self.dashboard_df))
        self.assertEqual(len(filtered_df), 3)

    def test_progression_counts_stable_under_sidebar_filters(self) -> None:
        before = compute_progression_funnel_counts(self.dashboard_df)
        filters = _default_filters(
            selected_location="Remote",
            selected_statuses=("New",),
            min_score=7,
        )
        filtered_df = apply_sidebar_filters(self.dashboard_df, filters)
        after_dashboard = compute_progression_funnel_counts(self.dashboard_df)
        self.assertEqual(before.discovery_total, after_dashboard.discovery_total)
        self.assertEqual(
            int(before.application_df.loc[
                before.application_df["stage"] == "Applied", "count"
            ].iloc[0]),
            int(after_dashboard.application_df.loc[
                after_dashboard.application_df["stage"] == "Applied", "count"
            ].iloc[0]),
        )
        self.assertEqual(len(filtered_df), 0)

    def test_filtered_df_differs_when_status_subset(self) -> None:
        filters = _default_filters(selected_statuses=("Applied",))
        filtered_df = apply_sidebar_filters(self.dashboard_df, filters)
        self.assertEqual(len(filtered_df), 1)
        self.assertEqual(len(self.dashboard_df), 4)

    def test_min_score_affects_filtered_not_dashboard(self) -> None:
        filters = _default_filters(min_score=7)
        filtered_df = apply_sidebar_filters(self.dashboard_df, filters)
        self.assertEqual(len(filtered_df), 2)
        self.assertEqual(len(self.dashboard_df), 4)
        self.assertEqual(len(apply_listing_visibility(self.dashboard_df)), 4)

    def test_recommended_actions_stable_under_sidebar_filters(self) -> None:
        cohort = pd.DataFrame(
            [
                _job_row(
                    stage="New",
                    is_ai_scored=True,
                    ai_status="scored",
                    score=9,
                    reason="Fit",
                    first_seen="2026-06-09 12:00:00",
                ),
                _job_row(
                    stage="New",
                    location="Remote",
                    is_ai_scored=True,
                    ai_status="scored",
                    score=9,
                    reason="Fit",
                    first_seen="2026-05-20 12:00:00",
                ),
            ]
        )
        ref = date(2026, 6, 10)
        before = compute_recommended_actions(cohort, reference_date=ref)
        filters = _default_filters(
            selected_location="Remote",
            selected_statuses=("New",),
            min_score=7,
        )
        apply_sidebar_filters(cohort, filters)
        after = compute_recommended_actions(cohort, reference_date=ref)
        self.assertEqual(before.high_confidence_total, after.high_confidence_total)
        self.assertEqual(before.apply_today_total, after.apply_today_total)
        self.assertEqual(before.apply_this_week_total, after.apply_this_week_total)
        self.assertEqual(before.needs_review_total, after.needs_review_total)


class PostedAtDateFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.null_job = _job_row(
            stage="New",
            location="NullPosted",
            is_ai_scored=True,
            score=8,
            ai_status="scored",
            posted_at_date=None,
            last_seen="2026-06-17 10:00:00",
        )
        self.dated_job = _job_row(
            stage="New",
            location="DatedPosted",
            is_ai_scored=True,
            score=8,
            ai_status="scored",
            posted_at_date="2026-06-09",
            last_seen="2026-06-17 10:00:00",
        )
        self.cohort = pd.DataFrame([self.null_job, self.dated_job])

    def test_null_posted_at_date_visible_in_default_dashboard_view(self) -> None:
        dashboard_df = build_dashboard_df(self.cohort)
        self.assertEqual(len(dashboard_df), 2)

        filters = _default_filters(date_column="posted_at_date", date_preset="All time")
        filtered_df = apply_sidebar_filters(dashboard_df, filters)
        self.assertEqual(len(filtered_df), len(dashboard_df))
        self.assertIn(
            "v2:key-New-NullPosted",
            set(filtered_df["JOB_KEY_V2"].astype(str)),
        )

    def test_build_dashboard_df_does_not_use_last_seen_as_posted_at_date(self) -> None:
        dashboard_df = build_dashboard_df(self.cohort)
        null_row = dashboard_df[
            dashboard_df["JOB_KEY_V2"] == "v2:key-New-NullPosted"
        ].iloc[0]
        self.assertTrue(pd.isna(null_row["posted_at_date"]))

    def test_all_time_includes_null_posted_at_date(self) -> None:
        out = apply_date_range_filter(
            self.cohort,
            date_column="posted_at_date",
            preset="All time",
            custom_start=None,
            custom_end=None,
        )
        self.assertEqual(len(out), 2)

    def test_last_7_days_excludes_null_posted_at_date(self) -> None:
        out = apply_date_range_filter(
            self.cohort,
            date_column="posted_at_date",
            preset="Last 7 days",
            custom_start=None,
            custom_end=None,
        )
        self.assertEqual(len(out), 0)

    def test_last_30_days_excludes_null_posted_at_date(self) -> None:
        out = apply_date_range_filter(
            self.cohort,
            date_column="posted_at_date",
            preset="Last 30 days",
            custom_start=None,
            custom_end=None,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out.iloc[0]["JOB_KEY_V2"]), "v2:key-New-DatedPosted")
        self.assertNotIn(
            "v2:key-New-NullPosted",
            set(out["JOB_KEY_V2"].astype(str)),
        )

    def test_custom_range_excludes_null_posted_at_date(self) -> None:
        out = apply_date_range_filter(
            self.cohort,
            date_column="posted_at_date",
            preset="Custom",
            custom_start=date(2026, 6, 1),
            custom_end=date(2026, 6, 30),
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out.iloc[0]["JOB_KEY_V2"]), "v2:key-New-DatedPosted")

    def test_custom_range_missing_dates_includes_null_posted_at_date(self) -> None:
        out = apply_date_range_filter(
            self.cohort,
            date_column="posted_at_date",
            preset="Custom",
            custom_start=None,
            custom_end=None,
        )
        self.assertEqual(len(out), 2)

    def test_dashboard_count_invariant_under_default_filters(self) -> None:
        dashboard_df = build_dashboard_df(self.cohort)
        kpi_count = len(dashboard_df)
        filtered_df = apply_sidebar_filters(
            dashboard_df,
            _default_filters(date_column="posted_at_date", date_preset="All time"),
        )
        self.assertEqual(len(filtered_df), kpi_count)


class EditorPostedColumnTests(unittest.TestCase):
    def test_posted_column_from_posted_at_date_not_last_seen(self) -> None:
        from app import _build_editor_df

        raw = pd.DataFrame(
            [
                _job_row(
                    stage="New",
                    is_ai_scored=True,
                    score=8,
                    ai_status="scored",
                    posted_at_date="2026-06-11",
                    last_seen="2026-06-17 10:00:00",
                )
            ]
        )
        dashboard_df = build_dashboard_df(raw)
        editor_df = _build_editor_df(dashboard_df, raw)
        self.assertEqual(editor_df.iloc[0]["Posted"], "11-06-2026")

    def test_null_posted_at_date_renders_blank(self) -> None:
        from app import _build_editor_df

        raw = pd.DataFrame(
            [
                _job_row(
                    stage="New",
                    is_ai_scored=True,
                    score=8,
                    ai_status="scored",
                    posted_at_date=None,
                    last_seen="2026-06-17 10:00:00",
                )
            ]
        )
        dashboard_df = build_dashboard_df(raw)
        editor_df = _build_editor_df(dashboard_df, raw)
        self.assertEqual(editor_df.iloc[0]["Posted"], "")


if __name__ == "__main__":
    unittest.main()
