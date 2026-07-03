"""Provider-scoped monitor metrics for dashboard Operational Monitor Health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy.orm import Session

from db.read.monitor_runs import load_latest_monitor_run_info
from db.read.monitor_summary import (
    instahyre_monitoring_work_performed_in_run,
    parse_provider_summary,
)
from db.read.provider_state import load_provider_state_map
from db.services.monitor_governance import (
    budget_day_start,
    count_provider_checks_today,
    load_monitor_governance_config,
)
from db.services.lifecycle_cohort import count_monitor_candidates_by_source

MONITORED_PROVIDER_SOURCES: tuple[str, ...] = ("linkedin", "instahyre")

_LISTING_STATUS_CHECK_FAILED = "check_failed"


def _normalize_listing_status(value: object) -> str:
    return str(value or "open").strip().lower() or "open"


def _count_check_failed_for_source(
    dashboard_df: pd.DataFrame,
    source: str,
) -> tuple[int, int]:
    if dashboard_df.empty or "listing_status" not in dashboard_df.columns:
        return 0, 0
    if "source" not in dashboard_df.columns:
        return 0, 0
    src = (source or "").strip().lower()
    working = dashboard_df[
        dashboard_df["source"].astype(str).str.strip().str.lower() == src
    ]
    if working.empty:
        return 0, 0
    statuses = working["listing_status"].map(_normalize_listing_status)
    failed = statuses == _LISTING_STATUS_CHECK_FAILED
    if "listing_check_paused_at" not in working.columns:
        return int(failed.sum()), 0
    paused = working["listing_check_paused_at"].notna() & (
        working["listing_check_paused_at"].astype(str).str.strip() != ""
    )
    paused_failed = failed & paused
    active_failed = failed & ~paused_failed
    return int(active_failed.sum()), int(paused_failed.sum())


@dataclass(frozen=True)
class ProviderMonitorSnapshot:
    source: str
    login_health: str
    login_reason: str | None
    login_applicable_this_run: bool
    checks_today: int
    budget_cap_per_day: int
    budget_remaining: int
    jobs_needing_attention: int
    jobs_paused: int
    eligible_monitor_queue: int
    provider_state: dict[str, object] | None


def _login_health_for_source(
    source: str,
    *,
    run_info: dict[str, object] | None,
    summary: dict[str, str],
) -> tuple[str, str | None]:
    src = source.strip().lower()
    if src == "linkedin":
        health = str((run_info or {}).get("auth_health") or "").strip().lower()
        reason = summary.get("auth_probe_reason")
        if health in ("ok", "degraded"):
            return health, reason
        return "unknown", reason
    health = str(summary.get("instahyre_auth_health") or "").strip().lower()
    reason = summary.get("instahyre_auth_probe_reason")
    if health in ("ok", "degraded"):
        return health, reason
    return "unknown", reason


def load_provider_monitor_snapshots(
    session: Session,
    *,
    dashboard_df: pd.DataFrame,
    run_info: dict[str, object] | None = None,
    reference_at: datetime | None = None,
) -> dict[str, ProviderMonitorSnapshot]:
    """Build per-provider monitor snapshots for dashboard provider cards."""
    now = reference_at or datetime.now(UTC).replace(tzinfo=None)
    latest_run = run_info if run_info is not None else load_latest_monitor_run_info(session)
    summary = parse_provider_summary((latest_run or {}).get("provider_summary"))
    provider_states = load_provider_state_map(session)
    config = load_monitor_governance_config()
    day_start = budget_day_start(now)

    caps = {
        "linkedin": config.linkedin_max_per_day,
        "instahyre": config.instahyre_max_per_day,
    }

    snapshots: dict[str, ProviderMonitorSnapshot] = {}
    instahyre_work_performed = instahyre_monitoring_work_performed_in_run(
        latest_run,
        summary,
        session=session,
    )
    for source in MONITORED_PROVIDER_SOURCES:
        checks_today = count_provider_checks_today(session, source, day_start=day_start)
        cap = caps[source]
        active_failed, paused_failed = _count_check_failed_for_source(dashboard_df, source)
        login_health, login_reason = _login_health_for_source(
            source,
            run_info=latest_run,
            summary=summary,
        )
        login_applicable = (
            instahyre_work_performed if source == "instahyre" else True
        )
        queue_size = count_monitor_candidates_by_source(session, source, reference_at=now)
        snapshots[source] = ProviderMonitorSnapshot(
            source=source,
            login_health=login_health,
            login_reason=login_reason,
            login_applicable_this_run=login_applicable,
            checks_today=checks_today,
            budget_cap_per_day=cap,
            budget_remaining=max(0, cap - checks_today),
            jobs_needing_attention=active_failed,
            jobs_paused=paused_failed,
            eligible_monitor_queue=queue_size,
            provider_state=provider_states.get(source),
        )
    return snapshots


def provider_protection_backoff_active(
    snapshot: ProviderMonitorSnapshot,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True when provider protection backoff is still active."""
    state = snapshot.provider_state
    if not state:
        return False
    health = str(state.get("health") or "").strip().lower()
    if health != "protection":
        return False
    ref = now or datetime.now(UTC).replace(tzinfo=None)
    backoff_until = state.get("backoff_until")
    if backoff_until is None:
        return False
    if isinstance(backoff_until, datetime):
        return backoff_until > ref
    parsed = pd.to_datetime(backoff_until, errors="coerce")
    if pd.isna(parsed):
        return False
    if hasattr(parsed, "to_pydatetime"):
        parsed = parsed.to_pydatetime()
    if getattr(parsed, "tzinfo", None) is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed > ref
