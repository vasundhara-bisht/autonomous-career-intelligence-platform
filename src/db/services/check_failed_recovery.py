"""Reset incident-misclassified check_failed jobs (OHM Phase 6 recovery)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.listing_status import LISTING_STATUS_CHECK_FAILED, LISTING_STATUS_OPEN
from db.models.schema import Job

INCIDENT_MISCLASSIFIED_PREFIXES: tuple[str, ...] = (
    "auth:",
    "dom:",
    "protection:",
)


def is_incident_misclassified_check_failed(reason: object) -> bool:
    """True for provider/auth/dom misclassifications from pre-OHM incident runs."""
    text_value = str(reason or "").strip().lower()
    if not text_value:
        return False
    return any(text_value.startswith(prefix) for prefix in INCIDENT_MISCLASSIFIED_PREFIXES)


def _reason_filter_sql() -> str:
    return " OR ".join(
        f"j.listing_status_reason LIKE '{prefix}%'" for prefix in INCIDENT_MISCLASSIFIED_PREFIXES
    )


def summarize_recovery_candidates(
    session: Session,
    *,
    source: str | None = "linkedin",
) -> dict[str, Any]:
    """Count jobs eligible for incident check_failed recovery."""
    source_clause = "AND j.source = :source" if source else ""
    params: dict[str, Any] = {}
    if source:
        params["source"] = source
    row = session.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN j.listing_check_paused_at IS NOT NULL THEN 1 ELSE 0 END) AS paused
            FROM jobs j
            WHERE j.listing_status = :check_failed
              {source_clause}
              AND ({_reason_filter_sql()})
            """
        ),
        {"check_failed": LISTING_STATUS_CHECK_FAILED, **params},
    ).mappings().one()
    by_reason = session.execute(
        text(
            f"""
            SELECT
              CASE
                WHEN j.listing_status_reason LIKE 'auth:%' THEN 'auth'
                WHEN j.listing_status_reason LIKE 'dom:%' THEN 'dom'
                WHEN j.listing_status_reason LIKE 'protection:%' THEN 'protection'
                ELSE 'other'
              END AS reason_group,
              COUNT(*) AS n
            FROM jobs j
            WHERE j.listing_status = :check_failed
              {source_clause}
              AND ({_reason_filter_sql()})
            GROUP BY reason_group
            ORDER BY n DESC
            """
        ),
        {"check_failed": LISTING_STATUS_CHECK_FAILED, **params},
    ).mappings().all()
    return {
        "source": source,
        "total_candidates": int(row["total"] or 0),
        "paused_candidates": int(row["paused"] or 0),
        "by_reason_group": {str(r["reason_group"]): int(r["n"]) for r in by_reason},
    }


def fetch_recovery_sample(
    session: Session,
    *,
    source: str | None = "linkedin",
    limit: int = 10,
) -> list[dict[str, Any]]:
    source_clause = "AND j.source = :source" if source else ""
    params: dict[str, Any] = {"check_failed": LISTING_STATUS_CHECK_FAILED, "limit": limit}
    if source:
        params["source"] = source
    rows = session.execute(
        text(
            f"""
            SELECT j.id, j.job_key_v2, j.source, j.listing_status_reason
            FROM jobs j
            WHERE j.listing_status = :check_failed
              {source_clause}
              AND ({_reason_filter_sql()})
            ORDER BY j.id ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@dataclass(frozen=True)
class CheckFailedRecoveryResult:
    dry_run: bool
    matched: int
    reset: int
    skipped: int


def reset_incident_check_failed_jobs(
    session: Session,
    *,
    source: str | None = "linkedin",
    dry_run: bool = True,
) -> CheckFailedRecoveryResult:
    """
    Reset incident-misclassified check_failed jobs back to open for recheck.

    Does not touch infrastructure check_failed rows (fetch:/timeout:/etc.).
    """
    query = session.query(Job).filter(Job.listing_status == LISTING_STATUS_CHECK_FAILED)
    if source:
        query = query.filter(Job.source == source)
    jobs = query.all()
    matched = 0
    reset = 0
    skipped = 0
    for job in jobs:
        if not is_incident_misclassified_check_failed(job.listing_status_reason):
            skipped += 1
            continue
        matched += 1
        if dry_run:
            continue
        job.listing_status = LISTING_STATUS_OPEN
        job.listing_status_reason = None
        job.consecutive_check_failures = 0
        job.listing_check_paused_at = None
        reset += 1
    if not dry_run and reset:
        session.flush()
    return CheckFailedRecoveryResult(
        dry_run=dry_run,
        matched=matched,
        reset=reset,
        skipped=skipped,
    )
