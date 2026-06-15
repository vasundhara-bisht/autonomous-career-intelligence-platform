"""Job Progression Funnel helpers (dashboard-only, snapshot semantics)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import altair as alt
import pandas as pd

FUNNEL_SECTIONS: dict[str, tuple[str, ...]] = {
    "Discovery": ("New", "Saved"),
    "Application": ("Applied", "HR Screen", "Interview", "Final Round", "Offer"),
    "Outcomes": ("Rejected", "Ghosted"),
}

DISCOVERY_STAGES = FUNNEL_SECTIONS["Discovery"]
APPLICATION_STAGES = FUNNEL_SECTIONS["Application"]
OUTCOME_STAGES = FUNNEL_SECTIONS["Outcomes"]


@dataclass(frozen=True)
class ProgressionFunnelCounts:
    total_filtered: int
    discovery_total: int
    new_count: int
    saved_count: int
    application_df: pd.DataFrame
    outcomes_df: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_filtered": self.total_filtered,
            "discovery_total": self.discovery_total,
            "new_count": self.new_count,
            "saved_count": self.saved_count,
            "application_df": self.application_df,
            "outcomes_df": self.outcomes_df,
        }


def _normalize_stage_value(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "New"
    text = str(value).strip()
    if text.lower() in ("", "nan", "none"):
        return "New"
    return text


def _stage_column(df: pd.DataFrame) -> pd.Series:
    if "pipeline_stage" in df.columns:
        return df["pipeline_stage"].map(_normalize_stage_value)
    if "Status" in df.columns:
        return df["Status"].map(_normalize_stage_value)
    return pd.Series(["New"] * len(df), index=df.index)


def _section_frame(
    *,
    section: str,
    stages: tuple[str, ...],
    stage_counts: dict[str, int],
    total_filtered: int,
) -> pd.DataFrame:
    rows = []
    for stage in stages:
        count = int(stage_counts.get(stage, 0))
        pct = round((count / total_filtered) * 100, 1) if total_filtered else 0.0
        rows.append(
            {
                "section": section,
                "stage": stage,
                "count": count,
                "pct_of_filtered": pct,
            }
        )
    return pd.DataFrame(rows)


def compute_progression_funnel_counts(df: pd.DataFrame) -> ProgressionFunnelCounts:
    """Count jobs by current pipeline_stage within funnel sections."""
    if df.empty:
        empty = _section_frame(
            section="Application",
            stages=APPLICATION_STAGES,
            stage_counts={},
            total_filtered=0,
        )
        empty_out = _section_frame(
            section="Outcomes",
            stages=OUTCOME_STAGES,
            stage_counts={},
            total_filtered=0,
        )
        return ProgressionFunnelCounts(
            total_filtered=0,
            discovery_total=0,
            new_count=0,
            saved_count=0,
            application_df=empty,
            outcomes_df=empty_out,
        )

    stages = _stage_column(df)
    total_filtered = len(df)
    counts = stages.value_counts().to_dict()
    stage_counts = {str(k): int(v) for k, v in counts.items()}

    new_count = int(stage_counts.get("New", 0))
    saved_count = int(stage_counts.get("Saved", 0))
    discovery_total = new_count + saved_count

    application_df = _section_frame(
        section="Application",
        stages=APPLICATION_STAGES,
        stage_counts=stage_counts,
        total_filtered=total_filtered,
    )
    outcomes_df = _section_frame(
        section="Outcomes",
        stages=OUTCOME_STAGES,
        stage_counts=stage_counts,
        total_filtered=total_filtered,
    )

    return ProgressionFunnelCounts(
        total_filtered=total_filtered,
        discovery_total=discovery_total,
        new_count=new_count,
        saved_count=saved_count,
        application_df=application_df,
        outcomes_df=outcomes_df,
    )


def build_progression_funnel_chart(
    section_df: pd.DataFrame,
    *,
    stage_order: list[str],
    title: str | None = None,
) -> alt.Chart:
    """Horizontal bar chart for one funnel section."""
    chart = (
        alt.Chart(section_df)
        .mark_bar()
        .encode(
            x=alt.X("count:Q", title="Jobs"),
            y=alt.Y("stage:N", sort=stage_order, title=None),
            color=alt.Color("section:N", legend=None),
            tooltip=[
                alt.Tooltip("section:N", title="Section"),
                alt.Tooltip("stage:N", title="Stage"),
                alt.Tooltip("count:Q", title="Jobs"),
                alt.Tooltip("pct_of_filtered:Q", title="% of filtered", format=".1f"),
            ],
        )
        .properties(height=max(120, 36 * len(stage_order)))
    )
    if title:
        chart = chart.properties(title=title)
    return chart
