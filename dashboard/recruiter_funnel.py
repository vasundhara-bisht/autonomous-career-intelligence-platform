"""Recruiter relationship progression counts (dashboard-only, snapshot semantics)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from recruiter_stages import (
    ENGAGEMENT_STAGES,
    OUTCOME_STAGES,
    normalize_recruiter_stage,
)


@dataclass(frozen=True)
class RecruiterProgressionCounts:
    total: int
    stage_counts: dict[str, int]
    engagement_df: pd.DataFrame
    outcomes_df: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "stage_counts": dict(self.stage_counts),
            "engagement_df": self.engagement_df,
            "outcomes_df": self.outcomes_df,
        }


def _stage_column(df: pd.DataFrame) -> pd.Series:
    if "recruiter_stage" in df.columns:
        return df["recruiter_stage"].map(normalize_recruiter_stage)
    if "Status" in df.columns:
        return df["Status"].map(normalize_recruiter_stage)
    return pd.Series(["discovered"] * len(df), index=df.index)


def _section_frame(
    *,
    section: str,
    stages: tuple[str, ...],
    stage_counts: dict[str, int],
    total: int,
) -> pd.DataFrame:
    rows = []
    for stage in stages:
        count = int(stage_counts.get(stage, 0))
        pct = round((count / total) * 100, 1) if total else 0.0
        rows.append(
            {
                "section": section,
                "stage": stage,
                "count": count,
                "pct_of_total": pct,
            }
        )
    return pd.DataFrame(rows)


def compute_recruiter_progression_counts(df: pd.DataFrame) -> RecruiterProgressionCounts:
    """Count recruiters by current recruiter_stage (CRM workflow snapshot)."""
    if df.empty:
        empty_engagement = _section_frame(
            section="Engagement",
            stages=ENGAGEMENT_STAGES,
            stage_counts={},
            total=0,
        )
        empty_outcomes = _section_frame(
            section="Outcomes",
            stages=OUTCOME_STAGES,
            stage_counts={},
            total=0,
        )
        return RecruiterProgressionCounts(
            total=0,
            stage_counts={},
            engagement_df=empty_engagement,
            outcomes_df=empty_outcomes,
        )

    stages = _stage_column(df)
    total = len(df)
    raw_counts = stages.value_counts().to_dict()
    stage_counts = {str(k): int(v) for k, v in raw_counts.items()}

    engagement_df = _section_frame(
        section="Engagement",
        stages=ENGAGEMENT_STAGES,
        stage_counts=stage_counts,
        total=total,
    )
    outcomes_df = _section_frame(
        section="Outcomes",
        stages=OUTCOME_STAGES,
        stage_counts=stage_counts,
        total=total,
    )

    return RecruiterProgressionCounts(
        total=total,
        stage_counts=stage_counts,
        engagement_df=engagement_df,
        outcomes_df=outcomes_df,
    )
