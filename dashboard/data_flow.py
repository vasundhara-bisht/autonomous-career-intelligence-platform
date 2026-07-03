"""Dashboard data-flow: system visibility cohort vs sidebar-filtered table cohort."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from agent.pipeline_stages import is_user_managed_pipeline_stage
from listing_visibility import (
    apply_age_bucket_columns,
    apply_listing_visibility,
)
from loaders import apply_historical_display_columns


def is_user_managed_stage(stage: object) -> bool:
    return is_user_managed_pipeline_stage(stage)


def apply_discovery_score_filter(df: pd.DataFrame, min_score: int) -> pd.DataFrame:
    """Discovery stages require AI score; user-managed stages do not."""
    if df.empty:
        return df
    out = df.copy()
    if "pipeline_stage" not in out.columns:
        out["pipeline_stage"] = "New"
    out["pipeline_stage"] = out["pipeline_stage"].fillna("New").astype(str).str.strip()
    managed = out["pipeline_stage"].map(is_user_managed_stage)
    if "is_ai_scored" not in out.columns:
        return out.loc[managed].copy()
    scored = out["is_ai_scored"].fillna(False).astype(bool)
    if "score" not in out.columns:
        return out.loc[managed | scored].copy()
    score_ok = pd.to_numeric(out["score"], errors="coerce").fillna(0) >= min_score
    return out.loc[managed | (scored & score_ok)].copy()


def _ensure_merge_key_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "JOB_KEY" not in out.columns:
        out["JOB_KEY"] = ""
    if "JOB_KEY_V2" not in out.columns:
        out["JOB_KEY_V2"] = ""
    leg = out["JOB_KEY"].fillna("").astype(str).str.strip()
    v2 = out["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    out["__merge_key"] = v2.where(v2 != "", leg)
    return out


def _merge_pipeline_stage(display_base: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    hist = _ensure_merge_key_columns(historical)
    stage_cols = ["__merge_key", "pipeline_stage"]
    if "pipeline_stage" not in hist.columns:
        hist["pipeline_stage"] = "New"

    out = _ensure_merge_key_columns(display_base)
    out = out.merge(hist[stage_cols], on="__merge_key", how="left")
    out["pipeline_stage"] = out["pipeline_stage"].fillna("New")
    return out.drop(columns=["__merge_key"], errors="ignore")


def _parse_dashboard_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def apply_date_range_filter(
    df: pd.DataFrame,
    *,
    date_column: str,
    preset: str,
    custom_start: date | None,
    custom_end: date | None,
) -> pd.DataFrame:
    if preset == "All time" or date_column not in df.columns:
        return df

    parsed = _parse_dashboard_datetime(df[date_column])
    today = pd.Timestamp.now().normalize()

    if preset == "Last 7 days":
        start = today - pd.Timedelta(days=7)
        end = today + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif preset == "Last 30 days":
        start = today - pd.Timedelta(days=30)
        end = today + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif preset == "Custom":
        if not custom_start or not custom_end:
            return df
        start = pd.Timestamp(custom_start).normalize()
        end = pd.Timestamp(custom_end).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    else:
        return df

    mask = parsed.notna() & (parsed >= start) & (parsed <= end)
    return df.loc[mask].copy()


def build_dashboard_df(historical_state_df: pd.DataFrame) -> pd.DataFrame:
    """Display prep + listing-status visibility (system rules only; no sidebar filters)."""
    display_df = apply_historical_display_columns(historical_state_df.copy())

    if "pipeline_stage" not in display_df.columns:
        display_df = _merge_pipeline_stage(display_df, historical_state_df)
    else:
        display_df["pipeline_stage"] = (
            display_df["pipeline_stage"].fillna("New").astype(str).str.strip()
        )

    display_df = apply_age_bucket_columns(display_df)
    return apply_listing_visibility(display_df)


@dataclass(frozen=True)
class SidebarFilterState:
    date_column: str
    date_preset: str
    custom_start: date | None
    custom_end: date | None
    selected_location: str
    selected_sources: tuple[str, ...]
    selected_statuses: tuple[str, ...]
    min_score: int
    recruiter_only: bool


def apply_sidebar_filters(df: pd.DataFrame, filters: SidebarFilterState) -> pd.DataFrame:
    """Apply sidebar filters for table/list views only."""
    out = apply_date_range_filter(
        df,
        date_column=filters.date_column,
        preset=filters.date_preset,
        custom_start=filters.custom_start,
        custom_end=filters.custom_end,
    )

    if filters.selected_location != "All":
        out = out[out["location"] == filters.selected_location]

    if filters.selected_sources:
        out = out[out["source"].isin(filters.selected_sources)]

    if filters.selected_statuses:
        out = out[out["pipeline_stage"].isin(filters.selected_statuses)]

    out = apply_discovery_score_filter(out, filters.min_score)

    if filters.recruiter_only:
        out = out[out["hiring_manager"] != "Not Specified"]

    return out


def sort_for_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sort_cols = [c for c in ("is_ai_scored", "score", "JOB_KEY") if c in df.columns]
    if not sort_cols:
        return df
    ascending = [False, False, True][: len(sort_cols)]
    return df.sort_values(by=sort_cols, ascending=ascending)
