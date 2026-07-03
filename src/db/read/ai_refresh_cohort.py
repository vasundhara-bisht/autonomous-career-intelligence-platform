"""Cohort selection for Refresh AI Evaluations operator control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from agent.job_description_persistence import (
    DescriptionStore,
    _is_persistable_description,
    try_hydrate_from_store,
)
from agent.pipeline_stages import (
    DISCOVERY_PIPELINE_STAGES,
    is_discovery_pipeline_stage,
    is_user_managed_pipeline_stage,
)
from db.read.description_store import populate_description_store_from_session
from db.read.historical import load_historical_jobs_view_df

AI_REFRESH_PRESET_BACKLOG = "backlog"
AI_REFRESH_PRESET_DISCOVERY = "discovery"

AI_REFRESH_PRESETS: dict[str, str] = {
    AI_REFRESH_PRESET_BACKLOG: "Refresh Scoring Backlog",
    AI_REFRESH_PRESET_DISCOVERY: "Refresh Evaluations",
}


@dataclass(frozen=True)
class CohortPreview:
    preset: str
    cohort_size: int
    eligible_with_description: int
    estimated_batches: int
    batch_size: int


def _normalize_listing_status(value: object) -> str:
    return str(value or "open").strip().lower() or "open"


def _historical_job_needs_ai_fallback(h_row: dict[str, Any]) -> bool:
    ai_status = str(h_row.get("ai_status", "") or "").strip().lower()
    reason = str(h_row.get("reason", "")).strip()

    if ai_status == "not_required":
        return False

    if ai_status == "scored":
        return not reason

    try:
        ai_score = float(h_row.get("ai_score", 0))
    except (TypeError, ValueError):
        ai_score = 0

    return ai_score <= 0 or not reason


def _is_backlog_status(h_row: dict[str, Any]) -> bool:
    ai_status = str(h_row.get("ai_status", "") or "").strip().lower()
    if ai_status in ("pending", "skipped_by_cap"):
        return True
    if ai_status == "scored":
        return _historical_job_needs_ai_fallback(h_row)
    return _historical_job_needs_ai_fallback(h_row)


def _is_discovery_open(row: dict[str, Any]) -> bool:
    return _normalize_listing_status(row.get("listing_status")) == "open"


def _status_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    ai_status = str(row.get("ai_status", "") or "").strip().lower()
    priority = {"skipped_by_cap": 0, "pending": 1, "scored": 2}.get(ai_status, 3)
    first_seen = str(row.get("first_seen", "") or "")
    return priority, first_seen


def _row_to_job_dict(row: dict[str, Any], store: DescriptionStore) -> dict[str, Any]:
    job = {
        "JOB_KEY": str(row.get("JOB_KEY", "") or "").strip(),
        "JOB_KEY_V2": str(row.get("JOB_KEY_V2", "") or "").strip(),
        "title": str(row.get("title", "") or "").strip(),
        "company": str(row.get("company", "") or "").strip(),
        "location": str(row.get("location", "") or "").strip(),
        "link": str(row.get("link", "") or "").strip(),
        "source": str(row.get("source", "") or "").strip(),
        "time_posted": str(row.get("time_posted", "") or row.get("posted_at_date", "") or "").strip(),
        "ai_status": str(row.get("ai_status", "") or "").strip().lower(),
        "ai_score": row.get("ai_score"),
        "reason": str(row.get("reason", "") or "").strip(),
    }
    stats: dict[str, int] = {}
    try_hydrate_from_store(job, store, stats, bucket="ai_refresh")
    return job


def _has_persistable_description(job: dict[str, Any], store: DescriptionStore) -> bool:
    if _is_persistable_description(job.get("description", "")):
        return True
    rec, _via = store.resolve(job)
    return bool(rec and _is_persistable_description(rec.get("description", "")))


def _matches_preset_row(row: dict[str, Any], preset: str) -> bool:
    stage = str(row.get("pipeline_stage", "") or "New").strip()
    if is_user_managed_pipeline_stage(stage):
        return False
    ai_status = str(row.get("ai_status", "") or "").strip().lower()
    if ai_status == "not_required":
        return False
    v2 = str(row.get("JOB_KEY_V2", "") or "").strip()
    if not v2:
        return False

    preset_key = str(preset or AI_REFRESH_PRESET_BACKLOG).strip().lower()
    if preset_key == AI_REFRESH_PRESET_DISCOVERY:
        if stage != "New":
            return False
        if not _is_discovery_open(row):
            return False
        return ai_status in ("pending", "skipped_by_cap", "scored")

    if not is_discovery_pipeline_stage(stage):
        return False
    return _is_backlog_status(row)


def select_ai_refresh_cohort_rows(
    df: pd.DataFrame,
    preset: str,
) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, series in df.iterrows():
        row = series.to_dict()
        if _matches_preset_row(row, preset):
            rows.append(row)
    rows.sort(key=_status_sort_key)
    return rows


def load_ai_refresh_cohort(
    session: Session,
    preset: str,
    *,
    require_description: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Load job dicts ready for scoring.

    Returns (eligible_jobs, skipped_no_description_count).
    """
    preset_key = str(preset or AI_REFRESH_PRESET_BACKLOG).strip().lower()
    if require_description is None:
        require_description = preset_key == AI_REFRESH_PRESET_DISCOVERY

    df = load_historical_jobs_view_df(session)
    cohort_rows = select_ai_refresh_cohort_rows(df, preset_key)

    store = DescriptionStore()
    populate_description_store_from_session(session, store)

    eligible: list[dict[str, Any]] = []
    skipped_no_description = 0
    for row in cohort_rows:
        job = _row_to_job_dict(row, store)
        if not _has_persistable_description(job, store):
            skipped_no_description += 1
            if require_description:
                continue
            continue
        eligible.append(job)

    return eligible, skipped_no_description


def preview_ai_refresh_cohort(session: Session, preset: str) -> CohortPreview:
    from agent.ai_runtime_config import resolve_batch_size
    import math

    preset_key = str(preset or AI_REFRESH_PRESET_BACKLOG).strip().lower()
    df = load_historical_jobs_view_df(session)
    cohort_rows = select_ai_refresh_cohort_rows(df, preset_key)
    cohort_size = len(cohort_rows)

    store = DescriptionStore()
    populate_description_store_from_session(session, store)

    eligible = 0
    for row in cohort_rows:
        job = _row_to_job_dict(row, store)
        if _has_persistable_description(job, store):
            eligible += 1

    batch_size = resolve_batch_size()
    batches = math.ceil(eligible / batch_size) if eligible > 0 else 0

    return CohortPreview(
        preset=preset_key,
        cohort_size=cohort_size,
        eligible_with_description=eligible,
        estimated_batches=batches,
        batch_size=batch_size,
    )
