#!/usr/bin/env python3
"""Phase B CSV -> SQLite importer (idempotent, rerunnable, non-destructive)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import (
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


@dataclass
class ImportStats:
    jobs_upserted: int = 0
    descriptions_upserted: int = 0
    evaluations_upserted: int = 0
    recruiter_upserted: int = 0
    recruiter_links_upserted: int = 0
    user_state_upserted: int = 0
    query_state_upserted: int = 0
    observations_upserted: int = 0
    run_id: int | None = None


def _boolish(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    if path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _load_frames() -> dict[str, pd.DataFrame]:
    job_state = _read_csv(paths.job_state_csv())
    if not job_state.empty:
        print(
            "WARN: job_state.csv is deprecated (D7); "
            "pipeline_stage and flags live in historical_jobs.csv / user_job_state. "
            "Rows are merged on import but job_state.csv is no longer reset by default."
        )
    return {
        "historical": _read_csv(paths.historical_jobs_csv()),
        "jobs": _read_csv(paths.jobs_csv()),
        "descriptions": _read_csv(paths.job_descriptions_csv()),
        "recruiters": _read_csv(paths.recruiter_crm_csv()),
        "job_state": job_state,
    }


def _bootstrap_run(session: Session) -> int:
    marker = "phase_b_csv_import_bootstrap"
    run = session.execute(
        select(AcquisitionRun).where(AcquisitionRun.notes == marker)
    ).scalar_one_or_none()
    if run:
        run.completed_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "completed"
        session.flush()
        return run.id
    run = AcquisitionRun(
        started_at=datetime.now(UTC).replace(tzinfo=None),
        completed_at=datetime.now(UTC).replace(tzinfo=None),
        status="completed",
        notes=marker,
    )
    session.add(run)
    session.flush()
    return run.id


def _jobs_payload_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    job_key_v2 = _text(row.get("JOB_KEY_V2"))
    if not job_key_v2:
        return None
    return {
        "job_key_v2": job_key_v2,
        "job_key": _text(row.get("JOB_KEY")) or job_key_v2,
        "identity_source": _text(row.get("identity_source")),
        "title": _text(row.get("title")) or "",
        "company": _text(row.get("company")) or "",
        "location": _text(row.get("location")),
        "source": _text(row.get("source")),
        "link": _text(row.get("link")),
        "hiring_manager": _text(row.get("hiring_manager")),
        "time_posted": _text(row.get("time_posted")),
        "posted_at_date": _text(row.get("posted_at_date")),
        "age_days": _int_or_none(row.get("age_days")),
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
    }


def _upsert_jobs(session: Session, frames: dict[str, pd.DataFrame], stats: ImportStats) -> dict[str, int]:
    seen: dict[str, dict[str, Any]] = {}
    for frame_name in ("historical", "jobs"):
        frame = frames[frame_name]
        if frame.empty:
            continue
        for row in frame.to_dict(orient="records"):
            payload = _jobs_payload_from_row(row)
            if payload:
                seen[payload["job_key_v2"]] = payload
    if not seen:
        return {}

    stmt = sqlite_insert(Job).values(list(seen.values()))
    update_cols = {
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
    }
    session.execute(
        stmt.on_conflict_do_update(index_elements=[Job.job_key_v2], set_=update_cols)
    )
    stats.jobs_upserted = len(seen)

    mapping = dict(
        session.execute(select(Job.job_key_v2, Job.id)).all()
    )
    return mapping


def _upsert_descriptions(
    session: Session, descriptions: pd.DataFrame, job_id_by_key: dict[str, int], stats: ImportStats
) -> None:
    if descriptions.empty:
        return
    existing = {
        row[0]: row[1]
        for row in session.execute(select(JobDescription.job_id, JobDescription.id)).all()
    }
    for row in descriptions.to_dict(orient="records"):
        key = _text(row.get("JOB_KEY_V2"))
        job_id = job_id_by_key.get(key or "")
        if not job_id:
            continue
        payload = {
            "job_id": job_id,
            "job_key_v2": key,
            "description": _text(row.get("description")) or "",
            "source": _text(row.get("source")),
            "last_updated": _parse_dt(row.get("last_updated"))
            or datetime.now(UTC).replace(tzinfo=None),
        }
        existing_id = existing.get(job_id)
        if existing_id:
            session.query(JobDescription).filter(JobDescription.id == existing_id).update(payload)
        else:
            session.add(JobDescription(**payload))
        stats.descriptions_upserted += 1


def _upsert_ai_evaluations(
    session: Session,
    historical: pd.DataFrame,
    job_id_by_key: dict[str, int],
    run_id: int,
    stats: ImportStats,
) -> None:
    if historical.empty:
        return
    existing = {
        row[0]: row[1]
        for row in session.execute(select(AiEvaluation.job_id, AiEvaluation.id)).all()
    }
    for row in historical.to_dict(orient="records"):
        key = _text(row.get("JOB_KEY_V2"))
        job_id = job_id_by_key.get(key or "")
        if not job_id:
            continue
        status = (_text(row.get("ai_status")) or "pending").lower()
        payload = {
            "job_id": job_id,
            "run_id": run_id,
            "ai_status": status,
            "ai_score": _float_or_none(row.get("ai_score")),
            "reason": _text(row.get("reason")),
            "model": "csv_import",
            "evaluated_at": _parse_dt(row.get("last_seen"))
            or datetime.now(UTC).replace(tzinfo=None),
        }
        existing_id = existing.get(job_id)
        if existing_id:
            session.query(AiEvaluation).filter(AiEvaluation.id == existing_id).update(payload)
        else:
            session.add(AiEvaluation(**payload))
        stats.evaluations_upserted += 1


def _upsert_user_state(
    session: Session,
    historical: pd.DataFrame,
    job_state: pd.DataFrame,
    job_id_by_key: dict[str, int],
    stats: ImportStats,
) -> None:
    state_by_key: dict[str, dict[str, Any]] = {}
    for row in historical.to_dict(orient="records"):
        key = _text(row.get("JOB_KEY_V2"))
        if not key:
            continue
        state_by_key[key] = {
            "applied": _boolish(row.get("applied")),
            "rejected": _boolish(row.get("rejected")),
            "interview": _boolish(row.get("interview")),
            "offer": _boolish(row.get("offer")),
            "pipeline_stage": _text(row.get("pipeline_stage")),
            "notes": _text(row.get("notes")),
            "updated_at": _parse_dt(row.get("last_seen"))
            or datetime.now(UTC).replace(tzinfo=None),
        }
    if not job_state.empty:
        by_key_v2 = {
            row[0]: row[1]
            for row in session.execute(select(Job.job_key, Job.job_key_v2)).all()
        }
        for row in job_state.to_dict(orient="records"):
            old_key = _text(row.get("JOB_KEY"))
            key_v2 = by_key_v2.get(old_key or "")
            if not key_v2:
                continue
            current = state_by_key.setdefault(
                key_v2,
                {
                    "applied": False,
                    "rejected": False,
                    "interview": False,
                    "offer": False,
                    "pipeline_stage": None,
                    "notes": None,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                },
            )
            current["applied"] = _boolish(row.get("APPLIED")) or current["applied"]
            current["rejected"] = _boolish(row.get("REJECTED")) or current["rejected"]

    existing = {
        row[0]: True for row in session.execute(select(UserJobState.job_id)).all()
    }
    for key_v2, payload in state_by_key.items():
        job_id = job_id_by_key.get(key_v2)
        if not job_id:
            continue
        row_payload = {"job_id": job_id, **payload}
        if existing.get(job_id):
            session.query(UserJobState).filter(UserJobState.job_id == job_id).update(payload)
        else:
            session.add(UserJobState(**row_payload))
        stats.user_state_upserted += 1


def _upsert_recruiters(session: Session, recruiters: pd.DataFrame, stats: ImportStats) -> dict[str, int]:
    if recruiters.empty:
        return {}
    payloads: list[dict[str, Any]] = []
    for row in recruiters.to_dict(orient="records"):
        key = _text(row.get("RECRUITER_KEY"))
        if not key:
            continue
        payloads.append(
            {
                "recruiter_key": key,
                "recruiter_name": _text(row.get("recruiter_name")) or key,
                "current_company": _text(row.get("current_company")),
                "source": _text(row.get("source")),
                "recruiter_title": _text(row.get("recruiter_title")),
                "recruiter_company": _text(row.get("recruiter_company")),
                "first_seen": _parse_dt(row.get("first_seen")),
                "last_seen": _parse_dt(row.get("last_seen")),
                "jobs_connected": _int_or_none(row.get("jobs_connected")) or 0,
                "recruiter_stage": _text(row.get("recruiter_stage")),
                "outreach_sent": _boolish(row.get("outreach_sent")),
                "recruiter_replied": _boolish(row.get("recruiter_replied")),
                "notes": _text(row.get("notes")),
                "last_outreach_date": _text(row.get("last_outreach_date")),
                "last_response_date": _text(row.get("last_response_date")),
                "touchpoint_count": _int_or_none(row.get("touchpoint_count")) or 0,
                "last_interaction_note": _text(row.get("last_interaction_note")),
                "currently_active": _boolish(row.get("currently_active")),
            }
        )
    if not payloads:
        return {}

    stmt = sqlite_insert(Recruiter).values(payloads)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Recruiter.recruiter_key],
            set_={
                "recruiter_name": stmt.excluded.recruiter_name,
                "current_company": stmt.excluded.current_company,
                "source": stmt.excluded.source,
                "recruiter_title": stmt.excluded.recruiter_title,
                "recruiter_company": stmt.excluded.recruiter_company,
                "first_seen": stmt.excluded.first_seen,
                "last_seen": stmt.excluded.last_seen,
                "jobs_connected": stmt.excluded.jobs_connected,
                "recruiter_stage": stmt.excluded.recruiter_stage,
                "outreach_sent": stmt.excluded.outreach_sent,
                "recruiter_replied": stmt.excluded.recruiter_replied,
                "notes": stmt.excluded.notes,
                "last_outreach_date": stmt.excluded.last_outreach_date,
                "last_response_date": stmt.excluded.last_response_date,
                "touchpoint_count": stmt.excluded.touchpoint_count,
                "last_interaction_note": stmt.excluded.last_interaction_note,
                "currently_active": stmt.excluded.currently_active,
            },
        )
    )
    stats.recruiter_upserted = len(payloads)
    return dict(session.execute(select(Recruiter.recruiter_key, Recruiter.id)).all())


def _upsert_recruiter_links(
    session: Session,
    jobs_df: pd.DataFrame,
    recruiters: dict[str, int],
    job_id_by_key: dict[str, int],
    stats: ImportStats,
) -> None:
    if jobs_df.empty:
        return
    links: set[tuple[int, int]] = set()
    for row in jobs_df.to_dict(orient="records"):
        recruiter_key = _text(row.get("recruiter_name"))
        key = _text(row.get("JOB_KEY_V2"))
        if not recruiter_key or not key:
            continue
        recruiter_id = recruiters.get(recruiter_key.lower())
        if recruiter_id is None:
            recruiter_id = recruiters.get(recruiter_key)
        job_id = job_id_by_key.get(key)
        if recruiter_id and job_id:
            links.add((recruiter_id, job_id))
    if not links:
        return
    existing = set(session.execute(select(RecruiterJobLink.recruiter_id, RecruiterJobLink.job_id)).all())
    for recruiter_id, job_id in links:
        if (recruiter_id, job_id) in existing:
            continue
        session.add(
            RecruiterJobLink(
                recruiter_id=recruiter_id,
                job_id=job_id,
                linked_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        stats.recruiter_links_upserted += 1


def _upsert_query_state(session: Session, stats: ImportStats) -> None:
    state_path = paths.linkedin_query_state_json()
    if not state_path.is_file():
        return
    with open(state_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    domain_rotation_index = _int_or_none(payload.get("domain_rotation_index"))
    query_state = payload.get("last_run_by_query_id", {}) or {}
    for query_id, last_run_at in query_state.items():
        stmt = sqlite_insert(QueryCooldownState).values(
            query_id=str(query_id),
            last_run_at=_float_or_none(last_run_at),
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
        stats.query_state_upserted += 1


def _upsert_observations(
    session: Session,
    historical: pd.DataFrame,
    job_id_by_key: dict[str, int],
    run_id: int,
    stats: ImportStats,
) -> None:
    if historical.empty:
        return
    existing = {
        row[0]: row[1]
        for row in session.execute(
            select(JobObservation.job_id, JobObservation.id).where(JobObservation.run_id == run_id)
        ).all()
    }
    for row in historical.to_dict(orient="records"):
        key = _text(row.get("JOB_KEY_V2"))
        job_id = job_id_by_key.get(key or "")
        if not job_id:
            continue
        payload = {
            "job_id": job_id,
            "run_id": run_id,
            "query_run_id": None,
            "source": _text(row.get("source")),
            "observed_at": _parse_dt(row.get("last_seen"))
            or datetime.now(UTC).replace(tzinfo=None),
            "times_seen": _int_or_none(row.get("times_seen")) or 1,
        }
        existing_id = existing.get(job_id)
        if existing_id:
            session.query(JobObservation).filter(JobObservation.id == existing_id).update(payload)
        else:
            session.add(JobObservation(**payload))
        stats.observations_upserted += 1


def _normalize_recruiter_key_map(recruiters: dict[str, int]) -> dict[str, int]:
    out = dict(recruiters)
    for key, value in list(recruiters.items()):
        out[str(key).lower()] = value
    return out


def run_import(*, dry_run: bool = False) -> ImportStats:
    ensure_database_ready()
    stats = ImportStats()
    frames = _load_frames()
    with get_session() as session:
        assert isinstance(session, Session)
        run_id = _bootstrap_run(session)
        stats.run_id = run_id

        job_id_by_key = _upsert_jobs(session, frames, stats)
        _upsert_descriptions(session, frames["descriptions"], job_id_by_key, stats)
        _upsert_ai_evaluations(session, frames["historical"], job_id_by_key, run_id, stats)
        _upsert_user_state(session, frames["historical"], frames["job_state"], job_id_by_key, stats)
        recruiter_map = _upsert_recruiters(session, frames["recruiters"], stats)
        recruiter_map = _normalize_recruiter_key_map(recruiter_map)
        _upsert_recruiter_links(session, frames["jobs"], recruiter_map, job_id_by_key, stats)
        _upsert_query_state(session, stats)
        _upsert_observations(session, frames["historical"], job_id_by_key, run_id, stats)

        if dry_run:
            session.rollback()
        else:
            session.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import CSV product memory files into SQLite MVP tables."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute/preview import actions without committing DB changes.",
    )
    args = parser.parse_args()

    stats = run_import(dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "COMMITTED"
    print(f"[{mode}] Phase B CSV import summary")
    print(f"  run_id: {stats.run_id}")
    print(f"  jobs_upserted: {stats.jobs_upserted}")
    print(f"  descriptions_upserted: {stats.descriptions_upserted}")
    print(f"  evaluations_upserted: {stats.evaluations_upserted}")
    print(f"  user_state_upserted: {stats.user_state_upserted}")
    print(f"  recruiter_upserted: {stats.recruiter_upserted}")
    print(f"  recruiter_links_upserted: {stats.recruiter_links_upserted}")
    print(f"  query_state_upserted: {stats.query_state_upserted}")
    print(f"  observations_upserted: {stats.observations_upserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
