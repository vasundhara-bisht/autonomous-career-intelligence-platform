"""Acquisition Health dashboard section (Scheduler A run metrics + history)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db.read.engine import dashboard_read_enabled
from monitor_display import present_run_status, present_run_trigger
from monitor_ui import format_monitor_duration, format_monitor_timestamp
from ui_help import render_subheader_with_help

_FAILED_SOURCES_NOT_RECORDED = "—"


def acquisition_health_label(status: object) -> str:
    """Map persisted run status to a coarse health label (dashboard-only)."""
    normalized = str(status or "").strip().lower()
    if normalized == "completed":
        return "Healthy"
    if normalized in {"failed", "interrupted"}:
        return "Degraded"
    if normalized:
        return present_run_status(normalized)
    return "—"


def _run_label(row: dict[str, object]) -> str:
    run_id = row.get("run_id")
    if run_id is None:
        return "—"
    return f"Run {run_id}"


def _interested_sync_detail(row: dict[str, object]) -> str:
    sync = row.get("interested_sync")
    if not isinstance(sync, dict):
        return "—"
    jobs = int(sync.get("jobs_discovered") or 0)
    return f"InstaHyre Interested sync — {jobs} jobs"


def build_acquisition_run_history_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "Run",
                "Started",
                "Completed",
                "Duration",
                "Sources",
                "Sub-step",
                "Jobs Discovered",
                "New Jobs",
                "Existing Jobs",
                "Failed Sources",
                "Trigger",
                "Status",
            ]
        )
    records: list[dict[str, object]] = []
    for row in rows:
        sources_list = str(row.get("sources_list") or "").strip()
        records.append(
            {
                "Run": _run_label(row),
                "Started": format_monitor_timestamp(row.get("started_at")),
                "Completed": format_monitor_timestamp(row.get("completed_at")),
                "Duration": format_monitor_duration(
                    started_at=row.get("started_at"),
                    completed_at=row.get("completed_at"),
                ),
                "Sources": sources_list or "—",
                "Sub-step": _interested_sync_detail(row),
                "Jobs Discovered": int(row.get("jobs_discovered") or 0),
                "New Jobs": int(row.get("new_jobs") or 0),
                "Existing Jobs": int(row.get("existing_jobs") or 0),
                "Failed Sources": _FAILED_SOURCES_NOT_RECORDED,
                "Trigger": present_run_trigger(row.get("run_trigger")),
                "Status": present_run_status(row.get("status")),
            }
        )
    return pd.DataFrame(records)


def _load_latest_acquisition_run_info() -> dict[str, object] | None:
    if not dashboard_read_enabled():
        return None
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.acquisition_runs import load_latest_acquisition_run_dashboard_info
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_latest_acquisition_run_dashboard_info(session)
    except Exception:
        return None


def _load_acquisition_run_history() -> list[dict[str, object]]:
    if not dashboard_read_enabled():
        return []
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.acquisition_runs import load_acquisition_run_history
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_acquisition_run_history(session)
    except Exception:
        return []


def render_acquisition_health_section() -> None:
    st.markdown("---")
    render_subheader_with_help(
        "Acquisition Health",
        "Summary metrics and recent acquisition runs.",
        "InstaHyre Interested sync is shown as a sub-step on the parent run (display only).",
    )

    if not dashboard_read_enabled():
        st.info("Acquisition history requires SQLite dashboard reads to be enabled.")

    run_info = _load_latest_acquisition_run_info()
    if run_info is None:
        st.caption("No completed acquisition runs recorded yet.")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Acquisition Health", "—")
        k2.metric("Last Run Status", "—")
        k3.metric("Sources Run", "—")
        k4.metric("Total Jobs Discovered", "—")
        k5, k6, k7, k8 = st.columns(4)
        k5.metric("Total New Jobs", "—")
        k6.metric("Total Existing Jobs", "—")
        k7.metric("Failed Sources", _FAILED_SOURCES_NOT_RECORDED)
        k8.metric("Last Run Duration", "—")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Acquisition Health", acquisition_health_label(run_info.get("status")))
        k2.metric("Last Run Status", present_run_status(run_info.get("status")))
        k3.metric("Sources Run", int(run_info.get("sources_run") or 0))
        k4.metric("Total Jobs Discovered", int(run_info.get("jobs_discovered") or 0))
        k5, k6, k7, k8 = st.columns(4)
        k5.metric("Total New Jobs", int(run_info.get("new_jobs") or 0))
        k6.metric("Total Existing Jobs", int(run_info.get("existing_jobs") or 0))
        k7.metric("Failed Sources", _FAILED_SOURCES_NOT_RECORDED)
        k8.metric(
            "Last Run Duration",
            format_monitor_duration(
                started_at=run_info.get("started_at"),
                completed_at=run_info.get("completed_at"),
            ),
        )

    history_rows = _load_acquisition_run_history()
    history_df = build_acquisition_run_history_df(history_rows)
    if history_df.empty:
        st.caption("No acquisition runs recorded yet.")
    else:
        st.dataframe(history_df, width="stretch", hide_index=True)
