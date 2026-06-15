"""Tests for dashboard stage-aware visibility helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app import (  # noqa: E402
    USER_MANAGED_PIPELINE_STAGES,
    _apply_activity_visibility,
    _apply_discovery_score_filter,
    _is_user_managed_stage,
)


def _row(
    *,
    stage: str = "New",
    is_ai_scored: bool = False,
    score: float = 0,
    currently_active: bool = True,
) -> dict:
    return {
        "JOB_KEY": "k1",
        "pipeline_stage": stage,
        "is_ai_scored": is_ai_scored,
        "score": score,
        "currently_active": currently_active,
    }


class UserManagedStageTests(unittest.TestCase):
    def test_all_user_managed_stages_recognized(self) -> None:
        for stage in USER_MANAGED_PIPELINE_STAGES:
            self.assertTrue(_is_user_managed_stage(stage))

    def test_discovery_stages_not_user_managed(self) -> None:
        self.assertFalse(_is_user_managed_stage("New"))
        self.assertFalse(_is_user_managed_stage("Saved"))


class ActivityVisibilityTests(unittest.TestCase):
    def test_inactive_applied_passes(self) -> None:
        df = pd.DataFrame([_row(stage="Applied", currently_active=False)])
        out = _apply_activity_visibility(df)
        self.assertEqual(len(out), 1)

    def test_inactive_new_fails(self) -> None:
        df = pd.DataFrame([_row(stage="New", currently_active=False)])
        out = _apply_activity_visibility(df)
        self.assertEqual(len(out), 0)

    def test_active_new_passes(self) -> None:
        df = pd.DataFrame([_row(stage="New", currently_active=True)])
        out = _apply_activity_visibility(df)
        self.assertEqual(len(out), 1)


class DiscoveryScoreFilterTests(unittest.TestCase):
    def test_unscored_applied_passes(self) -> None:
        df = pd.DataFrame([_row(stage="Applied", is_ai_scored=False, score=0)])
        out = _apply_discovery_score_filter(df, min_score=0)
        self.assertEqual(len(out), 1)

    def test_unscored_new_fails(self) -> None:
        df = pd.DataFrame([_row(stage="New", is_ai_scored=False, score=0)])
        out = _apply_discovery_score_filter(df, min_score=0)
        self.assertEqual(len(out), 0)

    def test_scored_new_below_min_fails(self) -> None:
        df = pd.DataFrame([_row(stage="New", is_ai_scored=True, score=3)])
        out = _apply_discovery_score_filter(df, min_score=5)
        self.assertEqual(len(out), 0)

    def test_user_managed_low_score_passes(self) -> None:
        df = pd.DataFrame([_row(stage="Applied", is_ai_scored=True, score=3)])
        out = _apply_discovery_score_filter(df, min_score=5)
        self.assertEqual(len(out), 1)

    def test_scored_new_at_min_passes(self) -> None:
        df = pd.DataFrame([_row(stage="New", is_ai_scored=True, score=7)])
        out = _apply_discovery_score_filter(df, min_score=7)
        self.assertEqual(len(out), 1)

    def test_all_user_managed_stages_bypass_score_when_unscored(self) -> None:
        for stage in USER_MANAGED_PIPELINE_STAGES:
            df = pd.DataFrame([_row(stage=stage, is_ai_scored=False, score=0)])
            out = _apply_discovery_score_filter(df, min_score=0)
            self.assertEqual(len(out), 1, stage)


if __name__ == "__main__":
    unittest.main()
