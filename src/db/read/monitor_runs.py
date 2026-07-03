"""Lifecycle monitor run reads for dashboard (TD8 / Operational Monitor Health)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.listing_status import (
    MONITOR_RUN_STATUS_COMPLETED,
    MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED,
)

_MONITOR_RUN_HISTORY_COLUMNS = """
    id AS run_id,
    started_at,
    completed_at,
    status,
    run_trigger,
    cohort_size,
    checked_count,
    open_count,
    closed_count,
    removed_count,
    check_failed_count,
    check_failed_rate,
    duration_sec,
    monitor_health,
    systemic_alert,
    auth_health,
    parity_warning_summary,
    provider_summary
"""


_MONITOR_TERMINAL_STATUSES = (
    MONITOR_RUN_STATUS_COMPLETED,
    MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED,
)


def load_latest_monitor_run_info(session: Session) -> dict[str, object] | None:
    row = session.execute(
        text(
            """
            SELECT
                id AS run_id,
                started_at,
                completed_at,
                status,
                run_trigger,
                cohort_size,
                checked_count,
                open_count,
                closed_count,
                removed_count,
                check_failed_count,
                check_failed_rate,
                monitor_health,
                systemic_alert,
                auth_health,
                parity_warning_summary,
                provider_summary
            FROM lifecycle_monitor_runs
            WHERE status IN (:completed_status, :skipped_budget_status)
              AND completed_at IS NOT NULL
            ORDER BY completed_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "completed_status": MONITOR_RUN_STATUS_COMPLETED,
            "skipped_budget_status": MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED,
        },
    ).mappings().first()
    return dict(row) if row else None


def load_latest_productive_monitor_run_info(session: Session) -> dict[str, object] | None:
    """Most recent run that actually checked at least one job."""
    row = session.execute(
        text(
            """
            SELECT
                id AS run_id,
                started_at,
                completed_at,
                status,
                cohort_size,
                checked_count,
                open_count,
                closed_count,
                removed_count,
                check_failed_count,
                check_failed_rate,
                monitor_health,
                systemic_alert,
                auth_health,
                parity_warning_summary,
                provider_summary
            FROM lifecycle_monitor_runs
            WHERE completed_at IS NOT NULL
              AND checked_count > 0
            ORDER BY completed_at DESC, id DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    return dict(row) if row else None


def load_monitor_run_history(session: Session, *, limit: int = 100) -> list[dict[str, object]]:
    """All monitor runs for dashboard history table (most recent first)."""
    rows = session.execute(
        text(
            f"""
            SELECT
                {_MONITOR_RUN_HISTORY_COLUMNS}
            FROM lifecycle_monitor_runs
            ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
            LIMIT :limit
            """
        ),
        {"limit": int(limit)},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_recruiter_visible_jobs_connected(session: Session) -> dict[str, int]:
    """Count recruiter job links excluding removed listings (TD5 §5E)."""
    rows = session.execute(
        text(
            """
            SELECT
                r.recruiter_key AS recruiter_key,
                COUNT(DISTINCT l.job_id) AS jobs_connected
            FROM recruiter_job_links l
            JOIN recruiters r ON r.id = l.recruiter_id
            JOIN jobs j ON j.id = l.job_id
            WHERE COALESCE(j.listing_status, 'open') != 'removed'
            GROUP BY r.recruiter_key
            """
        )
    ).mappings().all()
    return {
        str(row["recruiter_key"]): int(row["jobs_connected"] or 0)
        for row in rows
        if row.get("recruiter_key")
    }
