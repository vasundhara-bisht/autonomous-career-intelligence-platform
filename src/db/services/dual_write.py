"""Phase C dual-write service (SQLite source of truth when flags on; default D8B)."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

import paths
from db.bootstrap import ensure_database_ready
from db.config import sqlite_flag
from db.engine import get_session
from db.models.schema import (
    AcquisitionQueryRun,
    AcquisitionRun,
    AiEvaluation,
    Job,
    JobDescription,
    JobObservation,
    QueryCooldownState,
    Recruiter,
    RecruiterJobLink,
    UserJobState,
)


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_ts(value: Any) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _dual_write_enabled() -> bool:
    return sqlite_flag("SQLITE_ENABLED") and sqlite_flag("SQLITE_DUAL_WRITE")


def _fail_on_error_enabled() -> bool:
    raw = os.environ.get("SQLITE_FAIL_ON_ERROR", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class DualWriteContext:
    run_started_at: datetime
    run_completed_at: datetime
    run_status: str = "completed"
    run_notes: str | None = None


def _upsert_jobs(session: Session, jobs: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    payloads: dict[str, dict[str, Any]] = {}
    for row in jobs:
        v2 = _as_text(row.get("JOB_KEY_V2"))
        if not v2:
            continue
        payloads[v2] = {
            "job_key_v2": v2,
            "job_key": _as_text(row.get("JOB_KEY")) or v2,
            "identity_source": _as_text(row.get("identity_source")),
            "title": _as_text(row.get("title")) or "",
            "company": _as_text(row.get("company")) or "",
            "location": _as_text(row.get("location")),
            "source": _as_text(row.get("source")),
            "link": _as_text(row.get("link")),
            "hiring_manager": _as_text(row.get("hiring_manager")),
            "time_posted": _as_text(row.get("time_posted")),
            "posted_at_date": _as_text(row.get("posted_at_date")),
            "age_days": _as_int(row.get("age_days")),
            "updated_at": _now_utc_naive(),
        }
    if payloads:
        stmt = sqlite_insert(Job).values(list(payloads.values()))
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Job.job_key_v2],
                set_={
                    "job_key": stmt.excluded.job_key,
                    "identity_source": stmt.excluded.identity_source,
                    "title": stmt.excluded.title,
                    "company": stmt.excluded.company,
                    "location": stmt.excluded.location,
                    "source": stmt.excluded.source,
                    "link": stmt.excluded.link,
                    "hiring_manager": stmt.excluded.hiring_manager,
                    "time_posted": stmt.excluded.time_posted,
                    "posted_at_date": stmt.excluded.posted_at_date,
                    "age_days": stmt.excluded.age_days,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )
    mapping = dict(session.execute(select(Job.job_key_v2, Job.id)).all())
    return mapping, len(payloads)


def _upsert_acquisition_runs(session: Session, ctx: DualWriteContext) -> int:
    row = AcquisitionRun(
        started_at=ctx.run_started_at,
        completed_at=ctx.run_completed_at,
        status=ctx.run_status,
        notes=ctx.run_notes,
    )
    session.add(row)
    session.flush()
    return row.id


def _query_run_key(row: dict[str, Any]) -> tuple[str, str] | None:
    source = _as_text(row.get("source"))
    if source == "linkedin":
        qid = _as_text(row.get("linkedin_query_id"))
        return ("linkedin", qid) if qid else None
    if source == "instahyre":
        qid = _as_text(row.get("instahyre_query_id")) or _as_text(row.get("instahyre_feed_id"))
        return ("instahyre", qid) if qid else None
    return None


def _metadata_run_ts(row: dict[str, Any], *, source: str) -> str | None:
    if source == "linkedin":
        return _as_text(row.get("linkedin_run_ts"))
    if source == "instahyre":
        return _as_text(row.get("instahyre_run_ts"))
    return None


def _upsert_acquisition_query_runs(
    session: Session,
    *,
    run_id: int,
    jobs: list[dict[str, Any]],
    run_started_at: datetime,
    run_completed_at: datetime,
) -> tuple[int, dict[tuple[str, str], int]]:
    by_query: dict[tuple[str, str], dict[str, Any]] = {}
    for row in jobs:
        key = _query_run_key(row)
        if not key:
            continue
        source, qid = key
        if source == "linkedin":
            qlabel = _as_text(row.get("linkedin_query_label"))
            qrole = _as_text(row.get("linkedin_query_role"))
            qgroup = _as_text(row.get("linkedin_query_group"))
            fprofile = _as_text(row.get("linkedin_filter_profile"))
            ts = _parse_ts(row.get("linkedin_run_ts"))
            run_ts = _metadata_run_ts(row, source="linkedin")
        else:
            qlabel = _as_text(row.get("instahyre_query_label")) or _as_text(
                row.get("instahyre_feed_label")
            )
            qrole = "feed"
            qgroup = None
            fprofile = None
            ts = _parse_ts(row.get("instahyre_run_ts"))
            run_ts = _metadata_run_ts(row, source="instahyre")

        bucket = by_query.setdefault(
            key,
            {
                "query_label": qlabel,
                "query_role": qrole,
                "query_group": qgroup,
                "filter_profile": fprofile,
                "run_ts": run_ts,
                "started_at": ts or run_started_at,
                "completed_at": ts or run_completed_at,
                "jobs_collected": 0,
            },
        )
        bucket["jobs_collected"] += 1
        if qgroup and not bucket.get("query_group"):
            bucket["query_group"] = qgroup
        if fprofile and not bucket.get("filter_profile"):
            bucket["filter_profile"] = fprofile
        if run_ts and not bucket.get("run_ts"):
            bucket["run_ts"] = run_ts
        if ts:
            bucket["started_at"] = min(bucket["started_at"], ts)
            bucket["completed_at"] = max(bucket["completed_at"], ts)

    id_by_key: dict[tuple[str, str], int] = {}
    for (source, qid), bucket in by_query.items():
        row = AcquisitionQueryRun(
            run_id=run_id,
            query_id=qid,
            query_label=bucket["query_label"],
            query_role=bucket["query_role"],
            query_group=bucket.get("query_group"),
            filter_profile=bucket.get("filter_profile"),
            run_ts=bucket.get("run_ts"),
            source=source,
            started_at=bucket["started_at"],
            completed_at=bucket["completed_at"],
            jobs_collected=bucket["jobs_collected"],
        )
        session.add(row)
        session.flush()
        id_by_key[(source, qid)] = row.id
    return len(by_query), id_by_key


def _upsert_job_observations(
    session: Session,
    *,
    run_id: int,
    jobs: list[dict[str, Any]],
    job_id_by_v2: dict[str, int],
    query_run_id_by_key: dict[tuple[str, str], int] | None = None,
) -> int:
    query_run_id_by_key = query_run_id_by_key or {}
    count = 0
    for row in jobs:
        v2 = _as_text(row.get("JOB_KEY_V2"))
        job_id = job_id_by_v2.get(v2 or "")
        if not job_id:
            continue
        qkey = _query_run_key(row)
        query_run_id = query_run_id_by_key.get(qkey) if qkey else None
        existing = session.execute(
            select(JobObservation).where(
                JobObservation.run_id == run_id, JobObservation.job_id == job_id
            )
        ).scalar_one_or_none()
        payload = {
            "source": _as_text(row.get("source")),
            "observed_at": _now_utc_naive(),
            "currently_active": _as_bool(row.get("currently_active"), default=True),
            "times_seen": _as_int(row.get("times_seen")) or 1,
            "query_run_id": query_run_id,
        }
        if existing:
            session.query(JobObservation).filter(JobObservation.id == existing.id).update(payload)
        else:
            session.add(
                JobObservation(
                    job_id=job_id,
                    run_id=run_id,
                    **payload,
                )
            )
        count += 1
    return count


def _upsert_ai_evaluations(
    session: Session,
    *,
    run_id: int,
    jobs: list[dict[str, Any]],
    job_id_by_v2: dict[str, int],
) -> tuple[int, Counter]:
    existing = {
        job_id: row_id
        for job_id, row_id in session.execute(select(AiEvaluation.job_id, AiEvaluation.id)).all()
    }
    count = 0
    status_dist: Counter = Counter()
    for row in jobs:
        v2 = _as_text(row.get("JOB_KEY_V2"))
        job_id = job_id_by_v2.get(v2 or "")
        if not job_id:
            continue
        status = (_as_text(row.get("ai_status")) or "pending").lower()
        payload = {
            "job_id": job_id,
            "run_id": run_id,
            "ai_status": status,
            "ai_score": _as_float(row.get("ai_score") if row.get("ai_score") is not None else row.get("score")),
            "reason": _as_text(row.get("reason")),
            "model": "runtime_dual_write",
            "evaluated_at": _now_utc_naive(),
        }
        existing_id = existing.get(job_id)
        if existing_id:
            session.query(AiEvaluation).filter(AiEvaluation.id == existing_id).update(payload)
        else:
            session.add(AiEvaluation(**payload))
        status_dist[status] += 1
        count += 1
    return count, status_dist


def _upsert_job_descriptions(
    session: Session,
    *,
    jobs: list[dict[str, Any]],
    job_id_by_v2: dict[str, int],
) -> int:
    existing = {
        job_id: row_id
        for job_id, row_id in session.execute(select(JobDescription.job_id, JobDescription.id)).all()
    }
    count = 0
    for row in jobs:
        v2 = _as_text(row.get("JOB_KEY_V2"))
        description = _as_text(row.get("description"))
        job_id = job_id_by_v2.get(v2 or "")
        if not job_id or not description:
            continue
        payload = {
            "job_id": job_id,
            "job_key_v2": v2,
            "description": description,
            "source": _as_text(row.get("source")),
            "last_updated": _now_utc_naive(),
        }
        existing_id = existing.get(job_id)
        if existing_id:
            session.query(JobDescription).filter(JobDescription.id == existing_id).update(payload)
        else:
            session.add(JobDescription(**payload))
        count += 1
    return count


def _upsert_user_job_state(
    session: Session,
    *,
    jobs: list[dict[str, Any]],
    job_id_by_v2: dict[str, int],
) -> int:
    existing_job_ids = set(session.execute(select(UserJobState.job_id)).scalars().all())
    count = 0
    for row in jobs:
        v2 = _as_text(row.get("JOB_KEY_V2"))
        job_id = job_id_by_v2.get(v2 or "")
        if not job_id:
            continue
        payload = {
            "applied": _as_bool(row.get("applied"), default=False),
            "rejected": _as_bool(row.get("rejected"), default=False),
            "interview": _as_bool(row.get("interview"), default=False),
            "offer": _as_bool(row.get("offer"), default=False),
            "pipeline_stage": _as_text(row.get("pipeline_stage")),
            "notes": _as_text(row.get("notes")),
            "updated_at": _now_utc_naive(),
        }
        if job_id in existing_job_ids:
            session.query(UserJobState).filter(UserJobState.job_id == job_id).update(payload)
        else:
            session.add(UserJobState(job_id=job_id, **payload))
        count += 1
    return count


def _upsert_recruiters_and_links(
    session: Session,
    *,
    jobs: list[dict[str, Any]],
    job_id_by_v2: dict[str, int],
) -> tuple[int, int]:
    recruiter_payloads: dict[str, dict[str, Any]] = {}
    for row in jobs:
        name = _as_text(row.get("recruiter_name")) or _as_text(row.get("hiring_manager"))
        if not name or name.lower() in {"unknown", "not specified", "nan"}:
            continue
        key = name.lower()
        recruiter_payloads[key] = {
            "recruiter_key": key,
            "recruiter_name": name,
            "current_company": _as_text(row.get("company")),
            "source": _as_text(row.get("source")),
            "recruiter_title": _as_text(row.get("recruiter_title")),
            "recruiter_company": _as_text(row.get("recruiter_company")),
            "first_seen": _now_utc_naive(),
            "last_seen": _now_utc_naive(),
            "jobs_connected": 1,
            "recruiter_stage": "discovered",
            "outreach_sent": False,
            "recruiter_replied": False,
            "notes": "",
            "last_outreach_date": None,
            "last_response_date": None,
            "touchpoint_count": 0,
            "last_interaction_note": None,
            "currently_active": True,
        }
    if recruiter_payloads:
        stmt = sqlite_insert(Recruiter).values(list(recruiter_payloads.values()))
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Recruiter.recruiter_key],
                set_={
                    "recruiter_name": stmt.excluded.recruiter_name,
                    "current_company": stmt.excluded.current_company,
                    "source": stmt.excluded.source,
                    "recruiter_title": stmt.excluded.recruiter_title,
                    "recruiter_company": stmt.excluded.recruiter_company,
                    "last_seen": stmt.excluded.last_seen,
                    "currently_active": stmt.excluded.currently_active,
                },
            )
        )
    recruiter_map = dict(session.execute(select(Recruiter.recruiter_key, Recruiter.id)).all())
    existing_links = set(
        session.execute(select(RecruiterJobLink.recruiter_id, RecruiterJobLink.job_id)).all()
    )
    links_added = 0
    for row in jobs:
        name = _as_text(row.get("recruiter_name")) or _as_text(row.get("hiring_manager"))
        v2 = _as_text(row.get("JOB_KEY_V2"))
        if not name or not v2:
            continue
        recruiter_id = recruiter_map.get(name.lower())
        job_id = job_id_by_v2.get(v2)
        if not recruiter_id or not job_id:
            continue
        pair = (recruiter_id, job_id)
        if pair in existing_links:
            continue
        session.add(
            RecruiterJobLink(
                recruiter_id=recruiter_id,
                job_id=job_id,
                linked_at=_now_utc_naive(),
            )
        )
        existing_links.add(pair)
        links_added += 1
    return len(recruiter_payloads), links_added


def _upsert_query_cooldown_state(session: Session) -> int:
    state_path: Path = paths.linkedin_query_state_json()
    if not state_path.is_file():
        return 0
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
    domain_rotation_index = _as_int(state.get("domain_rotation_index"))
    last_run = state.get("last_run_by_query_id") or {}
    count = 0
    for query_id, last_run_at in last_run.items():
        stmt = sqlite_insert(QueryCooldownState).values(
            query_id=str(query_id),
            last_run_at=_as_float(last_run_at),
            domain_rotation_index=domain_rotation_index,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[QueryCooldownState.query_id],
                set_={
                    "last_run_at": stmt.excluded.last_run_at,
                    "domain_rotation_index": stmt.excluded.domain_rotation_index,
                },
            )
        )
        count += 1
    return count


def _count_rows(session: Session) -> dict[str, int]:
    return {
        "jobs": session.execute(select(func.count()).select_from(Job)).scalar_one(),
        "job_observations": session.execute(
            select(func.count()).select_from(JobObservation)
        ).scalar_one(),
        "ai_evaluations": session.execute(
            select(func.count()).select_from(AiEvaluation)
        ).scalar_one(),
        "job_descriptions": session.execute(
            select(func.count()).select_from(JobDescription)
        ).scalar_one(),
        "recruiters": session.execute(select(func.count()).select_from(Recruiter)).scalar_one(),
        "recruiter_job_links": session.execute(
            select(func.count()).select_from(RecruiterJobLink)
        ).scalar_one(),
        "acquisition_runs": session.execute(
            select(func.count()).select_from(AcquisitionRun)
        ).scalar_one(),
        "acquisition_query_runs": session.execute(
            select(func.count()).select_from(AcquisitionQueryRun)
        ).scalar_one(),
        "query_cooldown_state": session.execute(
            select(func.count()).select_from(QueryCooldownState)
        ).scalar_one(),
        "user_job_state": session.execute(
            select(func.count()).select_from(UserJobState)
        ).scalar_one(),
    }


def dual_write_runtime_snapshot(
    *,
    jobs: list[dict[str, Any]],
    persistence_cohort_count: int,
    csv_counts: dict[str, int] | None = None,
    run_started_at: datetime | None = None,
    run_notes: str | None = None,
) -> dict[str, Any]:
    """
    Write runtime persistence cohort into SQLite tables.

    SQLite is authoritative when dual-write flags are on (D8B default).
    Errors are logged unless SQLITE_FAIL_ON_ERROR is enabled.
    """
    report: dict[str, Any] = {
        "enabled": _dual_write_enabled(),
        "success": False,
        "error": "",
        "csv_counts": csv_counts or {},
        "db_write_counts": {},
        "db_table_counts": {},
        "ai_status_db_write_dist": {},
        "persistence_cohort_count": persistence_cohort_count,
    }
    if not _dual_write_enabled():
        return report

    run_ctx = DualWriteContext(
        run_started_at=run_started_at or _now_utc_naive(),
        run_completed_at=_now_utc_naive(),
        run_status="completed",
        run_notes=run_notes,
    )
    try:
        ensure_database_ready()
        with get_session() as session:
            assert isinstance(session, Session)
            run_id = _upsert_acquisition_runs(session, run_ctx)
            job_id_by_v2, jobs_upserted = _upsert_jobs(session, jobs)
            query_run_count, query_run_id_by_key = _upsert_acquisition_query_runs(
                session,
                run_id=run_id,
                jobs=jobs,
                run_started_at=run_ctx.run_started_at,
                run_completed_at=run_ctx.run_completed_at,
            )
            observations = _upsert_job_observations(
                session,
                run_id=run_id,
                jobs=jobs,
                job_id_by_v2=job_id_by_v2,
                query_run_id_by_key=query_run_id_by_key,
            )
            ai_evals, ai_dist = _upsert_ai_evaluations(
                session, run_id=run_id, jobs=jobs, job_id_by_v2=job_id_by_v2
            )
            descriptions = _upsert_job_descriptions(
                session, jobs=jobs, job_id_by_v2=job_id_by_v2
            )
            recruiters, recruiter_links = _upsert_recruiters_and_links(
                session, jobs=jobs, job_id_by_v2=job_id_by_v2
            )
            query_state = _upsert_query_cooldown_state(session)
            user_state = _upsert_user_job_state(
                session, jobs=jobs, job_id_by_v2=job_id_by_v2
            )
            session.commit()

            report["db_write_counts"] = {
                "jobs": jobs_upserted,
                "job_observations": observations,
                "ai_evaluations": ai_evals,
                "job_descriptions": descriptions,
                "recruiters": recruiters,
                "recruiter_job_links": recruiter_links,
                "acquisition_runs": 1,
                "acquisition_query_runs": query_run_count,
                "query_cooldown_state": query_state,
                "user_job_state": user_state,
            }
            report["db_table_counts"] = _count_rows(session)
            report["ai_status_db_write_dist"] = dict(ai_dist)
            report["run_id"] = run_id
            report["success"] = True
            return report
    except Exception as exc:
        report["error"] = repr(exc)
        if _fail_on_error_enabled():
            raise
        return report

