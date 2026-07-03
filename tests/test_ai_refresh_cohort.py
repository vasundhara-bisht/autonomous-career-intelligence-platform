"""Tests for AI refresh cohort selection."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from db.read.ai_refresh_cohort import (  # noqa: E402
    AI_REFRESH_PRESET_BACKLOG,
    AI_REFRESH_PRESET_DISCOVERY,
    _matches_preset_row,
    select_ai_refresh_cohort_rows,
)


def _row(**kwargs: object) -> dict:
    base = {
        "JOB_KEY": "k1",
        "JOB_KEY_V2": "v2:test:co:1",
        "title": "PM",
        "company": "Co",
        "pipeline_stage": "New",
        "listing_status": "open",
        "ai_status": "pending",
        "ai_score": None,
        "reason": "",
        "currently_active": True,
        "first_seen": "2026-06-01",
    }
    base.update(kwargs)
    return base


class AiRefreshCohortTests(unittest.TestCase):
    def test_backlog_includes_pending_and_skipped(self) -> None:
        df = pd.DataFrame(
            [
                _row(ai_status="pending"),
                _row(JOB_KEY_V2="v2:cap", ai_status="skipped_by_cap"),
                _row(JOB_KEY_V2="v2:scored", ai_status="scored", ai_score=8.0, reason="ok"),
            ]
        )
        rows = select_ai_refresh_cohort_rows(df, AI_REFRESH_PRESET_BACKLOG)
        keys = {r["JOB_KEY_V2"] for r in rows}
        self.assertIn("v2:test:co:1", keys)
        self.assertIn("v2:cap", keys)
        self.assertNotIn("v2:scored", keys)

    def test_backlog_includes_incomplete_scored(self) -> None:
        df = pd.DataFrame([_row(ai_status="scored", ai_score=0.0, reason="")])
        rows = select_ai_refresh_cohort_rows(df, AI_REFRESH_PRESET_BACKLOG)
        self.assertEqual(len(rows), 1)

    def test_discovery_includes_scored_open_new(self) -> None:
        df = pd.DataFrame(
            [
                _row(ai_status="scored", ai_score=9.0, reason="Strong fit."),
                _row(JOB_KEY_V2="v2:saved", pipeline_stage="Saved", ai_status="pending"),
                _row(JOB_KEY_V2="v2:closed", listing_status="closed", ai_status="pending"),
            ]
        )
        rows = select_ai_refresh_cohort_rows(df, AI_REFRESH_PRESET_DISCOVERY)
        keys = {r["JOB_KEY_V2"] for r in rows}
        self.assertIn("v2:test:co:1", keys)
        self.assertNotIn("v2:saved", keys)
        self.assertNotIn("v2:closed", keys)

    def test_excludes_not_required_and_user_managed(self) -> None:
        df = pd.DataFrame(
            [
                _row(ai_status="not_required"),
                _row(JOB_KEY_V2="v2:applied", pipeline_stage="Applied", ai_status="pending"),
            ]
        )
        rows = select_ai_refresh_cohort_rows(df, AI_REFRESH_PRESET_BACKLOG)
        self.assertEqual(rows, [])

    def test_matches_preset_row_discovery_requires_new(self) -> None:
        self.assertTrue(
            _matches_preset_row(
                _row(ai_status="scored", ai_score=8.0, reason="ok"),
                AI_REFRESH_PRESET_DISCOVERY,
            )
        )
        self.assertFalse(
            _matches_preset_row(
                _row(pipeline_stage="Saved", ai_status="pending"),
                AI_REFRESH_PRESET_DISCOVERY,
            )
        )


if __name__ == "__main__":
    unittest.main()
