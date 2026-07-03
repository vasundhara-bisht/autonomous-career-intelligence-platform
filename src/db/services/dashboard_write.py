"""Dashboard persistence writes to SQLite (D6)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.pipeline_stages import is_user_managed_pipeline_stage
from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import Job, Recruiter, UserJobState
from db.read.engine import dashboard_write_enabled
from db.services.lifecycle_write import set_monitor_exempt
from db.services.recruiter_enrichment import (
    normalize_hiring_manager,
    sync_recruiter_from_hiring_manager,
)

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
    prior_stage = (
        str(existing.pipeline_stage or "New").strip() if existing is not None else "New"
    )
    new_stage = str(pipeline_stage or "New").strip() or "New"
    payload = {
        "applied": applied,
        "rejected": rejected,
        "interview": interview,
        "offer": offer,
        "notes": str(notes or "").strip() or None,
        "pipeline_stage": new_stage,
        "updated_at": _now_utc_naive(),
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
    else:
        session.add(UserJobState(job_id=job_id, **payload))
    if is_user_managed_pipeline_stage(new_stage) and not is_user_managed_pipeline_stage(
        prior_stage
    ):
        job = session.get(Job, job_id)
        if job is not None:
            set_monitor_exempt(session, job)
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


def mark_job_applied(*, job_key_v2: str = "", job_key: str = "") -> bool:
    """Set a single job to Applied from Recommended Actions (Phase 3A.1)."""
    if not dashboard_write_enabled():
        return False
    ensure_database_ready()
    with get_session() as session:
        assert isinstance(session, Session)
        job_id = _resolve_job_id(session, job_key_v2=job_key_v2, job_key=job_key)
        if job_id is None:
            return False
        existing = session.get(UserJobState, job_id)
        notes = str(existing.notes or "").strip() if existing is not None else ""
        ok = upsert_user_job_state_from_editor(
            session,
            job_key_v2=job_key_v2,
            job_key=job_key,
            applied=True,
            rejected=False,
            interview=False,
            offer=False,
            notes=notes,
            pipeline_stage="Applied",
        )
        if not ok:
            return False
        job = session.get(Job, job_id)
        if job is not None:
            set_monitor_exempt(session, job)
        session.commit()
    _maybe_sync_csv_exports(historical=True, crm=False)
    return True


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


def _prior_hiring_manager_by_job_key(prior_df: pd.DataFrame) -> dict[str, str]:
    """Map JOB_KEY_V2 (or JOB_KEY) to prior Hiring Manager display value."""
    if prior_df.empty:
        return {}
    hm_col = "Hiring Manager" if "Hiring Manager" in prior_df.columns else "hiring_manager"
    if hm_col not in prior_df.columns:
        return {}

    out: dict[str, str] = {}
    for _, row in prior_df.iterrows():
        key = str(row.get("JOB_KEY_V2") or row.get("JOB_KEY") or "").strip()
        if not key:
            continue
        out[key] = normalize_hiring_manager(row.get(hm_col))
    return out


def _row_lookup_key(row: dict[str, Any]) -> str:
    return str(row.get("JOB_KEY_V2") or row.get("JOB_KEY") or "").strip()


def persist_dashboard_job_edits(
    updated_df: pd.DataFrame,
    *,
    prior_df: pd.DataFrame | None = None,
) -> int:
    """Write job editor state and optional Hiring Manager enrichment to SQLite."""
    if not dashboard_write_enabled():
        return 0
    rows = updated_df.to_dict(orient="records")
    if not rows:
        return 0

    prior_hm = _prior_hiring_manager_by_job_key(prior_df) if prior_df is not None else {}

    ensure_database_ready()
    count = 0
    recruiter_touched = False
    with get_session() as session:
        assert isinstance(session, Session)
        for row in rows:
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

            if prior_df is None or "hiring_manager" not in row:
                continue

            lookup = _row_lookup_key(row)
            if not lookup:
                continue

            new_hm = normalize_hiring_manager(row.get("hiring_manager"))
            old_hm = prior_hm.get(lookup)
            if old_hm is None:
                continue
            if new_hm == old_hm:
                continue

            job_id = _resolve_job_id(
                session,
                job_key_v2=str(row.get("JOB_KEY_V2", "") or ""),
                job_key=str(row.get("JOB_KEY", "") or ""),
            )
            if job_id is None:
                continue

            result = sync_recruiter_from_hiring_manager(
                session,
                job_id=job_id,
                hiring_manager=str(row.get("hiring_manager", "") or ""),
                company=str(row.get("company", "") or ""),
                job_source=str(row.get("source", "") or ""),
            )
            if result.outcome != "skipped":
                recruiter_touched = True

        session.commit()

    _maybe_sync_csv_exports(historical=True, crm=recruiter_touched)
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
