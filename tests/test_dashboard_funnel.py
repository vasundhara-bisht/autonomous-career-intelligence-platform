"""Tests for Job Progression Funnel dashboard helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from funnel import (  # noqa: E402
    APPLICATION_STAGES,
    DISCOVERY_STAGES,
    OUTCOME_STAGES,
    build_progression_funnel_chart,
    compute_progression_funnel_counts,
)


def _jobs(stages: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"pipeline_stage": stages})


class ProgressionFunnelCountTests(unittest.TestCase):
    def test_empty_dataframe(self) -> None:
        result = compute_progression_funnel_counts(pd.DataFrame())
        self.assertEqual(result.total_filtered, 0)
        self.assertEqual(result.discovery_total, 0)
        self.assertEqual(result.new_count, 0)
        self.assertEqual(result.saved_count, 0)
        self.assertEqual(len(result.application_df), len(APPLICATION_STAGES))
        self.assertEqual(len(result.outcomes_df), len(OUTCOME_STAGES))
        self.assertTrue((result.application_df["count"] == 0).all())

    def test_discovery_combined_equals_new_plus_saved(self) -> None:
        df = _jobs(["New", "New", "Saved", "Applied"])
        result = compute_progression_funnel_counts(df)
        self.assertEqual(result.new_count, 2)
        self.assertEqual(result.saved_count, 1)
        self.assertEqual(result.discovery_total, 3)

    def test_application_section_counts(self) -> None:
        df = _jobs(
            [
                "Applied",
                "Applied",
                "HR Screen",
                "Interview",
                "Final Round",
                "Offer",
            ]
        )
        result = compute_progression_funnel_counts(df)
        app = result.application_df.set_index("stage")["count"]
        self.assertEqual(int(app["Applied"]), 2)
        self.assertEqual(int(app["HR Screen"]), 1)
        self.assertEqual(int(app["Interview"]), 1)
        self.assertEqual(int(app["Final Round"]), 1)
        self.assertEqual(int(app["Offer"]), 1)

    def test_outcomes_section_counts(self) -> None:
        df = _jobs(["Rejected", "Rejected", "Ghosted"])
        result = compute_progression_funnel_counts(df)
        out = result.outcomes_df.set_index("stage")["count"]
        self.assertEqual(int(out["Rejected"]), 2)
        self.assertEqual(int(out["Ghosted"]), 1)

    def test_application_stage_order_preserved(self) -> None:
        df = _jobs(["Offer", "Applied"])
        result = compute_progression_funnel_counts(df)
        self.assertEqual(
            result.application_df["stage"].tolist(),
            list(APPLICATION_STAGES),
        )

    def test_pct_of_filtered(self) -> None:
        df = _jobs(["New", "Applied", "Applied", "Applied"])
        result = compute_progression_funnel_counts(df)
        applied_row = result.application_df.loc[
            result.application_df["stage"] == "Applied"
        ].iloc[0]
        self.assertEqual(int(applied_row["count"]), 3)
        self.assertEqual(float(applied_row["pct_of_filtered"]), 75.0)

    def test_status_column_fallback(self) -> None:
        df = pd.DataFrame({"Status": ["Saved", "Ghosted"]})
        result = compute_progression_funnel_counts(df)
        self.assertEqual(result.saved_count, 1)
        ghosted = result.outcomes_df.loc[
            result.outcomes_df["stage"] == "Ghosted"
        ].iloc[0]
        self.assertEqual(int(ghosted["count"]), 1)

    def test_missing_stage_normalized_to_new_via_pipeline_stage(self) -> None:
        df = pd.DataFrame({"pipeline_stage": [None, ""]})
        result = compute_progression_funnel_counts(df)
        self.assertEqual(result.new_count, 2)
        self.assertEqual(result.discovery_total, 2)

    def test_stages_only_in_funnel_sections(self) -> None:
        df = _jobs(["New", "Interview", "Ghosted"])
        result = compute_progression_funnel_counts(df)
        self.assertEqual(result.total_filtered, 3)
        self.assertEqual(int(result.application_df["count"].sum()), 1)
        self.assertEqual(int(result.outcomes_df["count"].sum()), 1)
        self.assertEqual(result.discovery_total, 1)


class ProgressionFunnelChartTests(unittest.TestCase):
    def test_build_chart_returns_altair_chart(self) -> None:
        df = _jobs(["Applied"])
        counts = compute_progression_funnel_counts(df)
        chart = build_progression_funnel_chart(
            counts.application_df,
            stage_order=list(APPLICATION_STAGES),
        )
        self.assertIsNotNone(chart.to_dict())


class FunnelRendererWiringTests(unittest.TestCase):
    def test_render_function_importable_from_app(self) -> None:
        from app import _render_job_search_progression

        self.assertTrue(callable(_render_job_search_progression))


class FunnelConfigTests(unittest.TestCase):
    def test_all_discovery_stages_in_config(self) -> None:
        self.assertEqual(DISCOVERY_STAGES, ("New", "Saved"))

    def test_outcomes_exclude_offer(self) -> None:
        self.assertNotIn("Offer", OUTCOME_STAGES)
        self.assertIn("Rejected", OUTCOME_STAGES)
        self.assertIn("Ghosted", OUTCOME_STAGES)


if __name__ == "__main__":
    unittest.main()
