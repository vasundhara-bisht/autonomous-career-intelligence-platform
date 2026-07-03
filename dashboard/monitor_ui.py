"""Operational Monitor Health dashboard section (Scheduler B run metrics + history)."""

from __future__ import annotations

import html
import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from db.listing_status import monitor_pause_threshold
from db.read.engine import dashboard_read_enabled
from db.read.monitor_summary import deferral_counts, parse_provider_summary
from monitor_display import (
    BannerResult,
    badge_tone_for_monitor_health,
    classify_status_banner,
    format_budget_usage,
    present_auth_health,
    present_latest_monitor_overview,
    present_overall_login_health,
    present_provider_login_health,
    present_run_status,
    present_run_trigger,
    present_systemic_alert,
    render_status_badge,
    summarize_run_skip_issues,
)
from ui_help import (
    inject_dashboard_help_css,
    render_metric_label_with_help,
    render_subheader_with_help,
    render_subsection_heading,
)

_MONITOR_HEALTH_CSS = """
<style>
.mon-compact-metric {
    padding: 0.1rem 0 0.35rem;
}
.mon-compact-metric-label {
    font-size: 0.78rem;
    line-height: 1.25;
    color: rgba(49, 51, 63, 0.68);
    margin-bottom: 0.15rem;
}
.mon-compact-metric-value {
    font-size: 1.05rem;
    line-height: 1.35;
    font-weight: 650;
    color: rgb(49, 51, 63);
    word-break: break-word;
}
</style>
"""

OP_LIFECYCLE_POLL_WAKE = "op_lifecycle_poll_wake"
OP_LIFECYCLE_POLL_WAKE_UNTIL = "op_lifecycle_poll_wake_until"
OP_ACQUISITION_POLL_WAKE = "op_acquisition_poll_wake"
OP_ACQUISITION_POLL_WAKE_UNTIL = "op_acquisition_poll_wake_until"
_MONITOR_FRAGMENT_HAD_RUNNING_KEY = "op_monitor_fragment_had_running"
_POLL_WAKE_SEC = 120.0
_METRIC_PLACEHOLDER = "—"


def _is_running_row(row: dict[str, object]) -> bool:
    return str(row.get("status") or "").strip().lower() == "running"


def mark_lifecycle_poll_wake() -> None:
    """Start a short wake window so history polls until a running row appears."""
    st.session_state[OP_LIFECYCLE_POLL_WAKE] = True
    st.session_state[OP_LIFECYCLE_POLL_WAKE_UNTIL] = time.monotonic() + _POLL_WAKE_SEC


def mark_acquisition_poll_wake() -> None:
    """Start a short wake window until acquisition lock indicates execution."""
    st.session_state[OP_ACQUISITION_POLL_WAKE] = True
    st.session_state[OP_ACQUISITION_POLL_WAKE_UNTIL] = time.monotonic() + _POLL_WAKE_SEC


def _clear_lifecycle_poll_wake() -> None:
    st.session_state.pop(OP_LIFECYCLE_POLL_WAKE, None)
    st.session_state.pop(OP_LIFECYCLE_POLL_WAKE_UNTIL, None)


def lifecycle_poll_wake_active() -> bool:
    if not st.session_state.get(OP_LIFECYCLE_POLL_WAKE):
        return False
    until = st.session_state.get(OP_LIFECYCLE_POLL_WAKE_UNTIL)
    if until is None or time.monotonic() > float(until):
        _clear_lifecycle_poll_wake()
        return False
    return True


def _clear_acquisition_poll_wake() -> None:
    st.session_state.pop(OP_ACQUISITION_POLL_WAKE, None)
    st.session_state.pop(OP_ACQUISITION_POLL_WAKE_UNTIL, None)


def acquisition_poll_wake_active() -> bool:
    if not st.session_state.get(OP_ACQUISITION_POLL_WAKE):
        return False
    until = st.session_state.get(OP_ACQUISITION_POLL_WAKE_UNTIL)
    if until is None or time.monotonic() > float(until):
        _clear_acquisition_poll_wake()
        return False
    return True


def _lifecycle_poll_wake_active() -> bool:
    return lifecycle_poll_wake_active()


def monitor_db_running() -> bool:
    if not dashboard_read_enabled():
        return False
    try:
        from sqlalchemy import text

        from db.bootstrap import ensure_database_ready
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            row = session.execute(
                text(
                    "SELECT 1 FROM lifecycle_monitor_runs WHERE status = 'running' LIMIT 1"
                )
            ).first()
            return row is not None
    except Exception:
        return False


def _sync_lifecycle_poll_wake() -> None:
    if monitor_db_running():
        _clear_lifecycle_poll_wake()
    else:
        lifecycle_poll_wake_active()


def _should_poll_monitor_health() -> bool:
    return monitor_db_running() or lifecycle_poll_wake_active()


def _inject_monitor_health_css() -> None:
    inject_dashboard_help_css()
    st.markdown(_MONITOR_HEALTH_CSS, unsafe_allow_html=True)


def _utc_naive_to_local(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.tzinfo is None:
        utc_ts = ts.tz_localize("UTC")
    else:
        utc_ts = ts.tz_convert("UTC")
    local_ts = utc_ts.tz_convert(datetime.now().astimezone().tzinfo)
    return local_ts.tz_localize(None)


def format_monitor_timestamp(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return "—"
    return _utc_naive_to_local(ts).strftime("%d %b %Y · %I:%M %p")


def format_monitor_duration(
    *,
    duration_sec: object = None,
    started_at: object = None,
    completed_at: object = None,
) -> str:
    """Format run duration from persisted duration_sec or started/completed timestamps."""
    secs: float | None = None
    if duration_sec is not None:
        try:
            parsed = float(duration_sec)
            if parsed > 0:
                secs = parsed
        except (TypeError, ValueError):
            secs = None
    if secs is None:
        start = pd.to_datetime(started_at, errors="coerce")
        end = pd.to_datetime(completed_at, errors="coerce")
        if pd.notna(start) and pd.notna(end):
            delta = (end - start).total_seconds()
            if delta > 0:
                secs = delta
    if secs is None:
        return "—"
    total = int(round(secs))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def build_monitor_run_history_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "Run",
                "Started",
                "Completed",
                "Duration",
                "Login status",
                "Cohort",
                "Checked",
                "Open",
                "Closed",
                "Removed",
                "Need attention",
                "Failure rate",
                "Trigger",
                "Status",
            ]
        )
    records: list[dict[str, object]] = []
    for row in rows:
        run_id = row.get("run_id")
        if _is_running_row(row):
            records.append(
                {
                    "Run": f"Run {run_id}" if run_id is not None else "—",
                    "Started": format_monitor_timestamp(row.get("started_at")),
                    "Completed": _METRIC_PLACEHOLDER,
                    "Duration": _METRIC_PLACEHOLDER,
                    "Login status": _METRIC_PLACEHOLDER,
                    "Cohort": _METRIC_PLACEHOLDER,
                    "Checked": _METRIC_PLACEHOLDER,
                    "Open": _METRIC_PLACEHOLDER,
                    "Closed": _METRIC_PLACEHOLDER,
                    "Removed": _METRIC_PLACEHOLDER,
                    "Need attention": _METRIC_PLACEHOLDER,
                    "Failure rate": _METRIC_PLACEHOLDER,
                    "Trigger": present_run_trigger(row.get("run_trigger")),
                    "Status": present_run_status(row.get("status")),
                }
            )
            continue
        rate = row.get("check_failed_rate")
        rate_label = f"{float(rate):.0%}" if rate is not None else "—"
        records.append(
            {
                "Run": f"Run {run_id}" if run_id is not None else "—",
                "Started": format_monitor_timestamp(row.get("started_at")),
                "Completed": format_monitor_timestamp(row.get("completed_at")),
                "Duration": format_monitor_duration(
                    duration_sec=row.get("duration_sec"),
                    started_at=row.get("started_at"),
                    completed_at=row.get("completed_at"),
                ),
                "Login status": present_auth_health(row.get("auth_health")),
                "Cohort": int(row.get("cohort_size") or 0),
                "Checked": int(row.get("checked_count") or 0),
                "Open": int(row.get("open_count") or 0),
                "Closed": int(row.get("closed_count") or 0),
                "Removed": int(row.get("removed_count") or 0),
                "Need attention": int(row.get("check_failed_count") or 0),
                "Failure rate": rate_label,
                "Trigger": present_run_trigger(row.get("run_trigger")),
                "Status": present_run_status(row.get("status")),
            }
        )
    return pd.DataFrame(records)


def _load_latest_monitor_run_info() -> dict[str, object] | None:
    if not dashboard_read_enabled():
        return None
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.engine import get_dashboard_read_session
        from db.read.monitor_runs import load_latest_monitor_run_info

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_latest_monitor_run_info(session)
    except Exception:
        return None


def _load_monitor_run_history() -> list[dict[str, object]]:
    if not dashboard_read_enabled():
        return []
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.engine import get_dashboard_read_session
        from db.read.monitor_runs import load_monitor_run_history

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_monitor_run_history(session)
    except Exception:
        return []


def _load_provider_snapshots(
    dashboard_df: pd.DataFrame,
    run_info: dict[str, object] | None,
) -> dict[str, object]:
    if not dashboard_read_enabled():
        return {}
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.engine import get_dashboard_read_session
        from db.read.monitor_provider_metrics import load_provider_monitor_snapshots

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_provider_monitor_snapshots(
                session,
                dashboard_df=dashboard_df,
                run_info=run_info,
            )
    except Exception:
        return {}


def _render_compact_metric(
    container: st.delta_generator.DeltaGenerator,
    label: str,
    value: object,
    *,
    html_value: bool = False,
) -> None:
    value_html = str(value) if html_value else html.escape(str(value))
    container.markdown(
        '<div class="mon-compact-metric">'
        f'<div class="mon-compact-metric-label">{html.escape(label)}</div>'
        f'<div class="mon-compact-metric-value">{value_html}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _render_badge_metric(
    container: st.delta_generator.DeltaGenerator,
    label: str,
    badge_label: str,
    tone: str,
) -> None:
    badge_html = render_status_badge(badge_label, tone)
    _render_compact_metric(container, label, badge_html, html_value=True)


def _render_status_banner(banner: BannerResult) -> None:
    css_class = {
        "green": "mon-banner-green",
        "orange": "mon-banner-orange",
        "red": "mon-banner-red",
    }.get(banner.level, "mon-banner-green")
    details_html = ""
    if banner.details:
        detail_lines = "<br>".join(html.escape(line) for line in banner.details)
        details_html = f'<div class="mon-banner-details">{detail_lines}</div>'
    st.markdown(
        f'<div class="mon-status-banner {css_class}">'
        f"{html.escape(banner.message)}"
        f"{details_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def _jobs_needing_attention_help() -> tuple[str, ...]:
    return (
        "Jobs with listing status check_failed that are still being retried by the monitor (not paused).",
    )


def _paused_jobs_help() -> tuple[str, ...]:
    threshold = monitor_pause_threshold()
    return (
        f"After {threshold} consecutive check failures, the monitor pauses the job and removes it "
        "from the daily cohort so repeatedly failing listings do not consume budget.",
        "Paused jobs remain visible in the dashboard; they resume when login recovers (LinkedIn) "
        "or after the underlying issue is fixed.",
    )


def _eligible_monitor_queue_help() -> tuple[str, ...]:
    return (
        "Jobs in the discovery pipeline that meet monitor tier rules and are waiting "
        "for a listing check.",
        "Count is before today's per-provider budget cap.",
        "Useful when running multiple manual monitor passes in one day.",
    )


def _render_provider_card(
    *,
    title: str,
    snapshot: object,
    deferral_lines: list[str],
) -> None:
    from db.read.monitor_provider_metrics import ProviderMonitorSnapshot

    if not isinstance(snapshot, ProviderMonitorSnapshot):
        st.caption("Metrics unavailable.")
        return

    login_label, _login_tone = present_provider_login_health(snapshot)
    checked = format_budget_usage(snapshot.checks_today, snapshot.budget_cap_per_day)

    metrics_html = "".join(
        [
            render_metric_label_with_help("Login", login_label),
            render_metric_label_with_help("Checked Today", checked),
            render_metric_label_with_help(
                "Budget Remaining Today",
                str(snapshot.budget_remaining),
            ),
            render_metric_label_with_help(
                "Eligible Monitor Queue",
                str(snapshot.eligible_monitor_queue),
                *_eligible_monitor_queue_help(),
            ),
            render_metric_label_with_help(
                "Jobs Needing Attention",
                str(snapshot.jobs_needing_attention),
                *_jobs_needing_attention_help(),
            ),
            render_metric_label_with_help(
                "Paused Jobs",
                str(snapshot.jobs_paused),
                *_paused_jobs_help(),
            ),
        ]
    )
    st.markdown(
        f'<p class="mon-provider-card-title">{html.escape(title)}</p>{metrics_html}',
        unsafe_allow_html=True,
    )
    for line in deferral_lines:
        st.caption(line)


def _render_monitor_health_body(dashboard_df: pd.DataFrame) -> None:
    run_info = _load_latest_monitor_run_info()
    provider_snapshots = _load_provider_snapshots(dashboard_df, run_info)

    protection_backoff: dict[str, bool] = {}
    if provider_snapshots:
        from db.read.monitor_provider_metrics import provider_protection_backoff_active

        for source, snap in provider_snapshots.items():
            protection_backoff[source] = provider_protection_backoff_active(snap)

    banner = classify_status_banner(
        run_info,
        provider_snapshots,
        protection_backoff_by_source=protection_backoff,
    )

    if run_info is None:
        k1, k2, k3, k4 = st.columns(4)
        _render_badge_metric(k1, "Overall Monitor Status", "—", "neutral")
        _render_badge_metric(k2, "Overall Login Status", "—", "neutral")
        _render_compact_metric(k3, "Overall Failure Rate", "—")
        _render_compact_metric(k4, "Alerts", "—")
    else:
        monitor_label = present_latest_monitor_overview(run_info)
        monitor_tone = badge_tone_for_monitor_health(run_info)
        login_label, login_tone = present_overall_login_health(provider_snapshots)
        rate = run_info.get("check_failed_rate")
        rate_label = f"{float(rate):.0%}" if rate is not None else "—"

        k1, k2, k3, k4 = st.columns(4)
        _render_badge_metric(k1, "Overall Monitor Status", monitor_label, monitor_tone)
        _render_badge_metric(k2, "Overall Login Status", login_label, login_tone)
        _render_compact_metric(k3, "Overall Failure Rate", rate_label)
        _render_compact_metric(
            k4,
            "Alerts",
            present_systemic_alert(run_info.get("systemic_alert")),
        )

    _render_status_banner(banner)

    render_subsection_heading("Provider Health")

    deferrals = deferral_counts((run_info or {}).get("provider_summary"))
    p1, p2 = st.columns(2)
    with p1:
        with st.container(border=True):
            _render_provider_card(
                title="LinkedIn",
                snapshot=provider_snapshots.get("linkedin"),
                deferral_lines=summarize_run_skip_issues(deferrals, source="linkedin"),
            )
    with p2:
        with st.container(border=True):
            _render_provider_card(
                title="InstaHyre",
                snapshot=provider_snapshots.get("instahyre"),
                deferral_lines=summarize_run_skip_issues(deferrals, source="instahyre"),
            )

    history_rows = _load_monitor_run_history()
    history_df = build_monitor_run_history_df(history_rows)
    if history_df.empty:
        st.caption("No monitor runs recorded yet.")
    else:
        st.dataframe(history_df, width="stretch", hide_index=True)


@st.fragment(run_every=timedelta(seconds=30))
def _render_monitor_health_live(dashboard_df: pd.DataFrame) -> None:
    had_running = bool(st.session_state.get(_MONITOR_FRAGMENT_HAD_RUNNING_KEY))
    _sync_lifecycle_poll_wake()
    running = monitor_db_running()
    if had_running and not running:
        st.session_state.pop(_MONITOR_FRAGMENT_HAD_RUNNING_KEY, None)
        st.rerun(scope="app")
    st.session_state[_MONITOR_FRAGMENT_HAD_RUNNING_KEY] = running
    _render_monitor_health_body(dashboard_df)


def render_operational_monitor_health_section(dashboard_df: pd.DataFrame) -> None:
    st.markdown("---")
    render_subheader_with_help(
        "Operational Monitor Health",
        "How the daily listing monitor is performing.",
        "Counts and failure rate reflect the latest completed run.",
    )

    _inject_monitor_health_css()

    if not dashboard_read_enabled():
        st.info("Monitor run history requires SQLite dashboard reads to be enabled.")

    _sync_lifecycle_poll_wake()
    if _should_poll_monitor_health():
        _render_monitor_health_live(dashboard_df)
        return
    st.session_state.pop(_MONITOR_FRAGMENT_HAD_RUNNING_KEY, None)
    _render_monitor_health_body(dashboard_df)
