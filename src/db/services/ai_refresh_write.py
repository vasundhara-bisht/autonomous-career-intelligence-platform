"""AI refresh run persistence (append evaluations, no acquisition side effects)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import paths
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.bootstrap import ensure_database_ready
from db.listing_status import (
    MONITOR_RUN_STATUS_COMPLETED,
    MONITOR_RUN_STATUS_FAILED,
    MONITOR_RUN_STATUS_RUNNING,
)
from db.models.schema import AiEvaluation, AiRefreshRun, Job
from db.read.engine import get_session


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


def _resolved_score(row: dict[str, Any]) -> float | None:
    """
    Prefer orchestrator `score` over historical `ai_score`.

    Stale or NaN `ai_score` values must not block persistence when `score` is set.
    """
    scored = _as_float(row.get("score"))
    if scored is not None:
        return scored
    return _as_float(row.get("ai_score"))


@dataclass(frozen=True)
class PersistRefreshResult:
    scoring_candidates: int
    persisted: int
    skipped: int

    @property
    def persist_complete(self) -> bool:
        return self.skipped == 0


def open_ai_refresh_run(preset: str) -> int:
    """Create a running ai_refresh_runs row; returns run id."""
    ensure_database_ready()
    preset_key = str(preset or "backlog").strip().lower()
    with get_session() as session:
        assert isinstance(session, Session)
        run = AiRefreshRun(
            started_at=_now_utc_naive(),
            status=MONITOR_RUN_STATUS_RUNNING,
            preset=preset_key,
            profile_path=str(paths.ai_candidate_profile_path()),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return int(run.id)


def finalize_ai_refresh_run(
    run_id: int,
    *,
    status: str,
    cohort_size: int = 0,
    eligible_count: int = 0,
    scored_count: int = 0,
    persist_skipped_count: int = 0,
    skipped_no_description: int = 0,
    skipped_by_cap_count: int = 0,
    batch_failures: int = 0,
    duration_sec: float | None = None,
    error_summary: str | None = None,
) -> None:
    ensure_database_ready()
    with get_session() as session:
        assert isinstance(session, Session)
        run = session.get(AiRefreshRun, int(run_id))
        if run is None:
            return
        run.completed_at = _now_utc_naive()
        run.status = status
        run.cohort_size = int(cohort_size)
        run.eligible_count = int(eligible_count)
        run.scored_count = int(scored_count)
        run.persist_skipped_count = int(persist_skipped_count)
        run.skipped_no_description = int(skipped_no_description)
        run.skipped_by_cap_count = int(skipped_by_cap_count)
        run.batch_failures = int(batch_failures)
        run.duration_sec = duration_sec
        run.error_summary = error_summary
        session.commit()


def insert_scored_evaluations(
    session: Session,
    *,
    ai_refresh_run_id: int,
    jobs: list[dict[str, Any]],
) -> PersistRefreshResult:
    """
    Append new ai_evaluations rows for successfully scored jobs.

    Skips jobs without scored status or not_required guard on existing eval.
    """
    scoring_candidates = 0
    persisted = 0
    skipped = 0
    evaluated_at = _now_utc_naive()
    for row in jobs:
        if str(row.get("ai_status") or "").strip().lower() != "scored":
            continue
        scoring_candidates += 1
        v2 = str(row.get("JOB_KEY_V2") or "").strip()
        if not v2:
            skipped += 1
            continue
        job_id = session.execute(
            select(Job.id).where(Job.job_key_v2 == v2)
        ).scalar_one_or_none()
        if job_id is None:
            skipped += 1
            continue
        existing_status = session.execute(
            select(AiEvaluation.ai_status)
            .where(AiEvaluation.job_id == job_id)
            .order_by(AiEvaluation.evaluated_at.desc(), AiEvaluation.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if str(existing_status or "").strip().lower() == "not_required":
            skipped += 1
            continue
        score = _resolved_score(row)
        reason = str(row.get("reason") or "").strip()
        if score is None or not reason:
            skipped += 1
            continue
        session.add(
            AiEvaluation(
                job_id=int(job_id),
                run_id=None,
                ai_refresh_run_id=int(ai_refresh_run_id),
                ai_status="scored",
                ai_score=score,
                reason=reason,
                model="ai_refresh",
                evaluated_at=evaluated_at,
            )
        )
        persisted += 1
    return PersistRefreshResult(
        scoring_candidates=scoring_candidates,
        persisted=persisted,
        skipped=skipped,
    )


def persist_ai_refresh_scored_jobs(
    ai_refresh_run_id: int,
    jobs: list[dict[str, Any]],
) -> PersistRefreshResult:
    """Commit append-only evaluations for scored jobs."""
    ensure_database_ready()
    with get_session() as session:
        assert isinstance(session, Session)
        result = insert_scored_evaluations(
            session,
            ai_refresh_run_id=ai_refresh_run_id,
            jobs=jobs,
        )
        session.commit()
        return result


__all__ = [
    "MONITOR_RUN_STATUS_COMPLETED",
    "MONITOR_RUN_STATUS_FAILED",
    "MONITOR_RUN_STATUS_RUNNING",
    "PersistRefreshResult",
    "finalize_ai_refresh_run",
    "insert_scored_evaluations",
    "open_ai_refresh_run",
    "persist_ai_refresh_scored_jobs",
]
