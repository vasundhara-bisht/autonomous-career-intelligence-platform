"""Job Listings table helpers (closed-listing read-only UX)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from listing_visibility import LISTING_STATUS_CLOSED, normalize_listing_status

CLOSED_LISTINGS_SECTION_TITLE = "Closed Listings (Read-only History)"

CLOSED_LISTING_READONLY_HELP = (
    "Closed listings are read-only. Pipeline stage, hiring manager, and notes "
    "cannot be edited; rows remain visible for historical reference."
)

CLOSED_ROW_STYLE = "background-color: #f3f4f6; color: #6b7280;"


def closed_listing_mask(editor_df: pd.DataFrame) -> pd.Series:
    if editor_df.empty:
        return pd.Series(dtype=bool)
    if "listing_status" in editor_df.columns:
        return (
            editor_df["listing_status"].map(normalize_listing_status)
            == LISTING_STATUS_CLOSED
        )
    if "Listing" in editor_df.columns:
        listing = editor_df["Listing"].astype(str).str.strip()
        return listing.eq("Closed") | listing.str.startswith("Closed ")
    return pd.Series(False, index=editor_df.index)


def partition_editor_df_by_listing(
    editor_df: pd.DataFrame,
    *,
    listing_visibility_enabled: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if editor_df.empty or not listing_visibility_enabled:
        return editor_df.copy(), editor_df.iloc[0:0].copy()
    closed = closed_listing_mask(editor_df)
    open_df = editor_df.loc[~closed].copy().reset_index(drop=True)
    closed_df = editor_df.loc[closed].copy().reset_index(drop=True)
    if not open_df.empty:
        open_df["#"] = range(1, len(open_df) + 1)
    if not closed_df.empty:
        closed_df["#"] = range(1, len(closed_df) + 1)
    return open_df, closed_df


def closed_listings_readonly_column_config(
    column_config: dict[str, Any],
) -> dict[str, Any]:
    """Return column config with no editable controls (read-only display)."""
    readonly: dict[str, Any] = {}
    for key, value in column_config.items():
        if value is None or key in {"JOB_KEY", "JOB_KEY_V2", "source_key", "listing_status"}:
            readonly[key] = value
            continue
        if key == "Link":
            readonly[key] = st.column_config.LinkColumn("Link", width="medium")
            continue
        if key == "#":
            readonly[key] = st.column_config.NumberColumn("#", width="small", disabled=True)
            continue
        width = "medium"
        if key in {"Title", "Notes"}:
            width = "large"
        elif key in {"Posted", "AI Score", "Source", "Listing", "Age", "#"}:
            width = "small"
        readonly[key] = st.column_config.TextColumn(key, width=width, disabled=True)
    return readonly


def style_closed_listings_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a Styler with muted rows for read-only closed listings."""
    if df.empty:
        return df.style
    return df.style.apply(
        lambda _row: [CLOSED_ROW_STYLE] * len(_row),
        axis=1,
    )


def filter_persisted_job_states(
    updated_states: list[dict],
    editor_df: pd.DataFrame,
    *,
    listing_visibility_enabled: bool,
) -> list[dict]:
    if not listing_visibility_enabled or editor_df.empty:
        return updated_states
    closed = closed_listing_mask(editor_df)
    if not closed.any():
        return updated_states
    closed_keys = {
        str(key).strip() for key in editor_df.loc[closed, "JOB_KEY"].astype(str)
    }
    return [
        state
        for state in updated_states
        if str(state.get("JOB_KEY", "")).strip() not in closed_keys
    ]
