"""Tests for Recruiter Relationship Progression workflow HTML."""

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

from recruiter_funnel import compute_recruiter_progression_counts  # noqa: E402
from recruiter_workflow import (  # noqa: E402
    RECRUITER_RELATIONSHIP_PROGRESSION_TITLE,
    build_recruiter_workflow_html,
)


def _sample_counts():
    df = pd.DataFrame(
        {
            "recruiter_stage": [
                "discovered",
                "discovered",
                "warm",
                "active",
                "responded",
                "ghosted",
                "archived",
            ]
        }
    )
    return compute_recruiter_progression_counts(df)


class RecruiterWorkflowHtmlTests(unittest.TestCase):
    def test_recruiter_workflow_html_stage_order(self) -> None:
        html_out = build_recruiter_workflow_html(_sample_counts())
        discovered_idx = html_out.index("Discovered")
        warm_idx = html_out.index("Warm", discovered_idx)
        active_idx = html_out.index("Active", warm_idx)
        responded_idx = html_out.index("Responded", active_idx)
        self.assertLess(discovered_idx, warm_idx)
        self.assertLess(warm_idx, active_idx)
        self.assertLess(active_idx, responded_idx)
        self.assertIn("Outcomes", html_out)
        self.assertIn("Ghosted", html_out)
        self.assertIn("Archived", html_out)
        self.assertIn("recruiter-relationship-progression", html_out)

    def test_recruiter_workflow_tooltips_use_tracked_recruiters(self) -> None:
        html_out = build_recruiter_workflow_html(_sample_counts())
        self.assertIn("tracked recruiters", html_out.lower())
        self.assertNotIn("visible jobs", html_out.lower())
        self.assertNotIn("currently_active", html_out.lower())

    def test_title_constant(self) -> None:
        self.assertEqual(
            RECRUITER_RELATIONSHIP_PROGRESSION_TITLE,
            "Relationship Progression",
        )

    def test_render_function_importable_from_app(self) -> None:
        from app import _render_recruiter_relationship_progression

        self.assertTrue(callable(_render_recruiter_relationship_progression))


if __name__ == "__main__":
    unittest.main()
