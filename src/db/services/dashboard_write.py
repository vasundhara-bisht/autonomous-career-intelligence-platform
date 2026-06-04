"""Dashboard persistence writes to SQLite (D6)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import Job, Recruiter, UserJobState
from db.read.engine import dashboard_write_enabled

_log = logging.getLogger(__name__)


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("", "nan", "none"):
        return default
    return text in ("1", "true", "yes", "on")


def _resolve_job_id(session: Session, *, job_key_v2: str, job_key: str) -> int | None:
    v2 = str(job_key_v2 or "").strip()
    if v2:
        job_id = session.execute(
            select(Job.id).where(Job.job_key_v2 == v2)
        ).scalar_one_or_none()
        if job_id is not None:
            return int(job_id)
    leg = str(job_key or "").strip()
    if leg:
        job_id = session.execute(
            select(Job.id).where(Job.job_key == leg)
        ).scalar_one_or_none()
        if job_id is not None:
            return int(job_id)
    return None


def upsert_user_job_state_from_editor(
    session: Session,
    *,
    job_key_v2: str = "",
    job_key: str = "",
    applied: bool = False,
    rejected: bool = False,
    interview: bool = False,
    offer: bool = False,
    notes: str = "",
    pipeline_stage: str = "New",
) -> bool:
    job_id = _resolve_job_id(session, job_key_v2=job_key_v2, job_key=job_key)
    if job_id is None:
        return False
    existing = session.get(UserJobState, job_id)
    payload = {
        "applied": applied,
        "rejected": rejected,
        "interview": interview,
        "offer": offer,
        "notes": str(notes or "").strip() or None,
        "pipeline_stage": str(pipeline_stage or "New").strip() or "New",
        "updated_at": _now_utc_naive(),
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
    else:
        session.add(UserJobState(job_id=job_id, **payload))
    return True


def upsert_user_job_state_batch(updates: list[dict[str, Any]]) -> int:
    """Persist job editor rows; keys: JOB_KEY_V2/JOB_KEY + state fields."""
    if not updates:
        return 0
    ensure_database_ready()
    count = 0
    with get_session() as session:
        assert isinstance(session, Session)
        for row in updates:
            if upsert_user_job_state_from_editor(
                session,
                job_key_v2=str(row.get("JOB_KEY_V2", "") or ""),
                job_key=str(row.get("JOB_KEY", "") or ""),
                applied=_as_bool(row.get("applied")),
                rejected=_as_bool(row.get("rejected")),
                interview=_as_bool(row.get("interview")),
                offer=_as_bool(row.get("offer")),
                notes=str(row.get("notes", "") or ""),
                pipeline_stage=str(row.get("pipeline_stage", "New") or "New"),
            ):
                count += 1
        session.commit()
    return count


def update_recruiter_from_editor(
    session: Session,
    *,
    recruiter_key: str,
    recruiter_stage: str,
) -> bool:
    key = str(recruiter_key or "").strip()
    if not key:
        return False
    recruiter = session.execute(
        select(Recruiter).where(Recruiter.recruiter_key == key)
    ).scalar_one_or_none()
    if recruiter is None:
        return False
    recruiter.recruiter_stage = str(recruiter_stage or "discovered").strip() or "discovered"
    return True


def update_recruiter_stages(edits: list[tuple[str, str]]) -> int:
    if not edits:
        return 0
    ensure_database_ready()
    count = 0
    with get_session() as session:
        assert isinstance(session, Session)
        for recruiter_key, stage in edits:
            if update_recruiter_from_editor(
                session,
                recruiter_key=recruiter_key,
                recruiter_stage=stage,
            ):
                count += 1
        session.commit()
    return count


def _maybe_sync_csv_exports(*, historical: bool, crm: bool) -> None:
    try:
        from db.write.csv_export import export_write_primary_csvs
        from db.write.engine import (
            export_crm_csv_enabled,
            export_historical_csv_enabled,
            write_primary_enabled,
        )

        if not write_primary_enabled():
            return
        export_write_primary_csvs(
            export_historical=historical and export_historical_csv_enabled(),
            export_descriptions=False,
            export_crm=crm and export_crm_csv_enabled(),
        )
    except Exception:
        _log.exception("Post-dashboard CSV export sync failed")


def persist_dashboard_job_edits(updated_df: pd.DataFrame) -> int:
    """Write job pipeline editor state to user_job_state when flag enabled."""
    if not dashboard_write_enabled():
        return 0
    rows = updated_df.to_dict(orient="records")
    count = upsert_user_job_state_batch(rows)
    _maybe_sync_csv_exports(historical=True, crm=False)
    return count


def persist_dashboard_crm_edits(
    recruiter_keys: list[str],
    recruiter_stages: list[str],
) -> int:
    if not dashboard_write_enabled():
        return 0
    edits = list(zip(recruiter_keys, recruiter_stages, strict=True))
    count = update_recruiter_stages(edits)
    _maybe_sync_csv_exports(historical=False, crm=True)
    return count
