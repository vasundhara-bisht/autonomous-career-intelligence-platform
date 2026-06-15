"""Tests for Job Search Progression workflow HTML presentation."""

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

from funnel import compute_progression_funnel_counts  # noqa: E402
from funnel_workflow import (  # noqa: E402
    JOB_SEARCH_PROGRESSION_TITLE,
    build_workflow_html,
)


def _sample_counts():
    df = pd.DataFrame(
        {
            "pipeline_stage": [
                "New",
                "New",
                "Saved",
                "Applied",
                "Applied",
                "HR Screen",
                "Interview",
                "Final Round",
                "Offer",
                "Rejected",
                "Ghosted",
            ]
        }
    )
    return compute_progression_funnel_counts(df)


class WorkflowHtmlTests(unittest.TestCase):
    def test_includes_all_progression_stages_in_order(self) -> None:
        html_out = build_workflow_html(_sample_counts())
        discovery_idx = html_out.index("Discovery")
        applied_idx = html_out.index("Applied", discovery_idx)
        hr_idx = html_out.index("HR Screen", applied_idx)
        interview_idx = html_out.index("Interview", hr_idx)
        final_idx = html_out.index("Final Round", interview_idx)
        offer_idx = html_out.index("Offer", final_idx)
        self.assertLess(discovery_idx, applied_idx)
        self.assertLess(applied_idx, hr_idx)
        self.assertLess(hr_idx, interview_idx)
        self.assertLess(interview_idx, final_idx)
        self.assertLess(final_idx, offer_idx)

    def test_includes_discovery_breakdown(self) -> None:
        html_out = build_workflow_html(_sample_counts())
        self.assertIn("New: 2", html_out)
        self.assertIn("Saved: 1", html_out)

    def test_includes_outcomes_section(self) -> None:
        html_out = build_workflow_html(_sample_counts())
        self.assertIn("Outcomes", html_out)
        self.assertIn("Rejected", html_out)
        self.assertIn("Ghosted", html_out)
        self.assertIn("outcome-card", html_out)

    def test_horizontal_progression_row(self) -> None:
        html_out = build_workflow_html(_sample_counts())
        self.assertIn("progression-row", html_out)
        self.assertIn('class="arrow"', html_out)
        self.assertIn("→", html_out)
        self.assertNotIn("flex-direction: column", html_out)

    def test_stage_counts_present(self) -> None:
        counts = _sample_counts()
        html_out = build_workflow_html(counts)
        self.assertIn(f'<div class="stage-count">{counts.discovery_total}</div>', html_out)
        applied = int(
            counts.application_df.loc[
                counts.application_df["stage"] == "Applied", "count"
            ].iloc[0]
        )
        self.assertIn(f'<div class="stage-count">{applied}</div>', html_out)

    def test_empty_counts_still_render_cards(self) -> None:
        html_out = build_workflow_html(compute_progression_funnel_counts(pd.DataFrame()))
        self.assertIn("Discovery", html_out)
        self.assertIn("Offer", html_out)
        self.assertIn("Rejected", html_out)

    def test_title_constant_avoids_funnel_word(self) -> None:
        self.assertNotIn("Funnel", JOB_SEARCH_PROGRESSION_TITLE)
        self.assertEqual(JOB_SEARCH_PROGRESSION_TITLE, "Job Search Progression")

    def test_tooltips_avoid_filtered_jobs_wording(self) -> None:
        html_out = build_workflow_html(_sample_counts())
        self.assertNotIn("filtered jobs", html_out.lower())
        self.assertIn("visible jobs", html_out.lower())


class WorkflowRendererWiringTests(unittest.TestCase):
    def test_render_function_importable_from_app(self) -> None:
        from app import _render_job_search_progression

        self.assertTrue(callable(_render_job_search_progression))


if __name__ == "__main__":
    unittest.main()
