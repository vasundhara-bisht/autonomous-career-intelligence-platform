"""AI Refresh Health dashboard section (Refresh AI Evaluations run metrics + history)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db.read.engine import dashboard_read_enabled
from monitor_display import present_run_status
from monitor_ui import format_monitor_duration, format_monitor_timestamp
from ui_help import render_subheader_with_help

from db.read.ai_refresh_cohort import AI_REFRESH_PRESETS


def ai_refresh_health_label(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "completed":
        return "Healthy"
    if normalized in {"failed", "interrupted"}:
        return "Degraded"
    if normalized:
        return present_run_status(normalized)
    return "—"


def _preset_label(preset: object) -> str:
    key = str(preset or "").strip().lower()
    return AI_REFRESH_PRESETS.get(key, key or "—")


def _run_label(row: dict[str, object]) -> str:
    run_id = row.get("run_id")
    if run_id is None:
        return "—"
    return f"Run {run_id}"


def build_ai_refresh_run_history_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "Run",
                "Preset",
                "Started",
                "Completed",
                "Duration",
                "Cohort",
                "Eligible",
                "Scored",
                "Persist Skipped",
                "No Description",
                "Status",
            ]
        )
    records: list[dict[str, object]] = []
    for row in rows:
        records.append(
            {
                "Run": _run_label(row),
                "Preset": _preset_label(row.get("preset")),
                "Started": format_monitor_timestamp(row.get("started_at")),
                "Completed": format_monitor_timestamp(row.get("completed_at")),
                "Duration": format_monitor_duration(
                    started_at=row.get("started_at"),
                    completed_at=row.get("completed_at"),
                ),
                "Cohort": int(row.get("cohort_size") or 0),
                "Eligible": int(row.get("eligible_count") or 0),
                "Scored": int(row.get("scored_count") or 0),
                "Persist Skipped": int(row.get("persist_skipped_count") or 0),
                "No Description": int(row.get("skipped_no_description") or 0),
                "Status": present_run_status(row.get("status")),
            }
        )
    return pd.DataFrame(records)


def _load_latest_ai_refresh_run_info() -> dict[str, object] | None:
    if not dashboard_read_enabled():
        return None
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.ai_refresh_runs import load_latest_ai_refresh_run_info
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_latest_ai_refresh_run_info(session)
    except Exception:
        return None


def _load_ai_refresh_run_history() -> list[dict[str, object]]:
    if not dashboard_read_enabled():
        return []
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.ai_refresh_runs import load_ai_refresh_run_history
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_ai_refresh_run_history(session)
    except Exception:
        return []


def render_ai_refresh_health_section() -> None:
    st.markdown("---")
    render_subheader_with_help(
        "AI Refresh Health",
        "Summary metrics and recent Refresh AI Evaluations runs.",
        "Re-scores existing jobs from SQLite descriptions using the current candidate profile. "
        "Does not re-run acquisition or re-fetch descriptions.",
    )

    if not dashboard_read_enabled():
        st.info("AI refresh history requires SQLite dashboard reads to be enabled.")

    run_info = _load_latest_ai_refresh_run_info()
    k1, k2 = st.columns(2)
    if run_info is None:
        k1.metric("AI Refresh Health", "—")
        k2.metric("Last Preset", "—")
        k3, k4, k5, k6, k7 = st.columns(5)
        k3.metric("Jobs Scored", "—")
        k4.metric("Last Run Duration", "—")
        k5.metric("Last Run Cohort", "—")
        k6.metric("Last Run Eligible", "—")
        k7.metric("Batch Failures", "—")
    else:
        k1.metric("AI Refresh Health", ai_refresh_health_label(run_info.get("status")))
        k2.metric("Last Preset", _preset_label(run_info.get("preset")))
        k3, k4, k5, k6, k7 = st.columns(5)
        k3.metric("Jobs Scored", int(run_info.get("scored_count") or 0))
        k4.metric(
            "Last Run Duration",
            format_monitor_duration(
                started_at=run_info.get("started_at"),
                completed_at=run_info.get("completed_at"),
            ),
        )
        k5.metric("Last Run Cohort", int(run_info.get("cohort_size") or 0))
        k6.metric("Last Run Eligible", int(run_info.get("eligible_count") or 0))
        k7.metric("Batch Failures", int(run_info.get("batch_failures") or 0))

    history_rows = _load_ai_refresh_run_history()
    history_df = build_ai_refresh_run_history_df(history_rows)
    if history_df.empty:
        st.caption("No AI refresh runs recorded yet.")
    else:
        st.dataframe(history_df, width="stretch", hide_index=True)
