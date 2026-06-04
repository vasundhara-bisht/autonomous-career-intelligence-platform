"""Optional CSV exports from SQLite after write-primary dual-write (D5/D7)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

import paths
from db.bootstrap import ensure_database_ready
from db.models.schema import Job, JobDescription, QueryCooldownState, Recruiter
from db.read.crm import load_active_recruiters_view_df
from db.read.engine import get_read_session
from db.read.export_cohort import load_current_jobs_export_source_df
from db.read.historical import load_historical_jobs_view_df
from db.read.transforms import apply_export_transforms, format_datetime_for_csv_compare


def _format_dt(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return format_datetime_for_csv_compare(value)


def export_historical_jobs_csv(session: Session, *, dest: Path | None = None) -> int:
    from agent.historical_persistence import historical_jobs_schema_columns

    df = load_historical_jobs_view_df(session)
    if df.empty:
        df = pd.DataFrame(columns=historical_jobs_schema_columns())
    else:
        if "pipeline_stage" in df.columns:
            df = df.drop(columns=["pipeline_stage"])
        ordered = historical_jobs_schema_columns()
        for col in ordered:
            if col not in df.columns:
                df[col] = ""
        extra = [c for c in df.columns if c not in ordered]
        df = df.reindex(columns=ordered + extra)
    path = dest or paths.historical_jobs_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(str(path), index=False)
    return len(df)


def export_job_descriptions_csv(session: Session, *, dest: Path | None = None) -> int:
    from agent.job_description_persistence import job_descriptions_schema_columns

    rows = session.execute(
        select(
            Job.job_key,
            JobDescription.job_key_v2,
            JobDescription.description,
            JobDescription.last_updated,
            JobDescription.source,
        ).join(Job, Job.id == JobDescription.job_id)
    ).all()
    records: list[dict[str, str]] = []
    seen_v2: set[str] = set()
    for legacy_key, v2_key, desc, last_updated, source in rows:
        v2 = str(v2_key or "").strip()
        if v2 and v2 in seen_v2:
            continue
        if v2:
            seen_v2.add(v2)
        records.append(
            {
                "JOB_KEY": str(legacy_key or "").strip() or v2,
                "JOB_KEY_V2": v2,
                "description": str(desc or ""),
                "last_updated": _format_dt(last_updated),
                "source": str(source or ""),
            }
        )
    df = pd.DataFrame(records, columns=job_descriptions_schema_columns())
    path = dest or paths.job_descriptions_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(str(path), index=False)
    return len(df)


def export_recruiter_crm_csv(session: Session, *, dest: Path | None = None) -> int:
    from agent.bootstrap_schema import RECRUITER_CRM_SCHEMA_COLUMNS

    df = load_active_recruiters_view_df(session)
    if df.empty:
        df = pd.DataFrame(columns=list(RECRUITER_CRM_SCHEMA_COLUMNS))
    else:
        for col in RECRUITER_CRM_SCHEMA_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df.reindex(columns=list(RECRUITER_CRM_SCHEMA_COLUMNS))
    path = dest or paths.recruiter_crm_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(str(path), index=False)
    return len(df)


def export_jobs_csv(session: Session, *, dest: Path | None = None) -> int:
    from agent.main import _prepare_jobs_export_df

    source = load_current_jobs_export_source_df(session)
    df = _prepare_jobs_export_df(apply_export_transforms(source))
    path = dest or paths.jobs_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        df.to_csv(str(path), index=False)
        return 0
    if "id" not in df.columns:
        df.insert(0, "id", range(1, len(df) + 1))
    df.to_csv(str(path), index=False)
    return len(df)


def export_linkedin_query_state_json(session: Session, *, dest: Path | None = None) -> int:
    rows = session.execute(select(QueryCooldownState)).scalars().all()
    last_run: dict[str, float] = {}
    domain_rotation_index = 0
    for row in rows:
        if row.last_run_at is not None:
            last_run[str(row.query_id)] = float(row.last_run_at)
        if row.domain_rotation_index is not None:
            domain_rotation_index = int(row.domain_rotation_index)
    payload = {
        "last_run_by_query_id": last_run,
        "domain_rotation_index": domain_rotation_index,
    }
    path = dest or paths.linkedin_query_state_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return len(last_run)


def export_csv_memory(
    *,
    output_dir: Path | None = None,
    export_historical: bool = False,
    export_jobs: bool = False,
    export_descriptions: bool = False,
    export_crm: bool = False,
    export_query_state: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Export SQLite product memory to CSV/JSON paths (D7)."""
    counts: dict[str, int] = {}
    if not any(
        (export_historical, export_jobs, export_descriptions, export_crm, export_query_state)
    ):
        return counts

    def _dest(default: Path) -> Path:
        if output_dir is None:
            return default
        return output_dir / default.name

    ensure_database_ready()
    with get_read_session() as session:
        if export_historical:
            target = _dest(paths.historical_jobs_csv())
            counts["historical_jobs"] = 0 if dry_run else export_historical_jobs_csv(
                session, dest=target
            )
            print(f"  historical_jobs -> {target} ({counts['historical_jobs']} rows)")
        if export_jobs:
            target = _dest(paths.jobs_csv())
            counts["jobs"] = 0 if dry_run else export_jobs_csv(session, dest=target)
            print(f"  jobs -> {target} ({counts['jobs']} rows)")
        if export_descriptions:
            target = _dest(paths.job_descriptions_csv())
            counts["job_descriptions"] = (
                0 if dry_run else export_job_descriptions_csv(session, dest=target)
            )
            print(f"  job_descriptions -> {target} ({counts['job_descriptions']} rows)")
        if export_crm:
            target = _dest(paths.recruiter_crm_csv())
            counts["recruiter_crm"] = 0 if dry_run else export_recruiter_crm_csv(
                session, dest=target
            )
            print(f"  recruiter_crm -> {target} ({counts['recruiter_crm']} rows)")
        if export_query_state:
            target = _dest(paths.linkedin_query_state_json())
            counts["query_cooldown_state"] = (
                0 if dry_run else export_linkedin_query_state_json(session, dest=target)
            )
            print(f"  linkedin_query_state -> {target}")
    return counts


def export_write_primary_csvs(
    *,
    export_historical: bool,
    export_descriptions: bool,
    export_crm: bool,
) -> dict[str, int]:
    """Export selected CSV mirrors from SQLite after write-primary dual-write."""
    counts: dict[str, int] = {}
    if not (export_historical or export_descriptions or export_crm):
        return counts

    ensure_database_ready()
    with get_read_session() as session:
        if export_historical:
            counts["historical_jobs"] = export_historical_jobs_csv(session)
            print(
                f"  Exported historical_jobs.csv from DB ({counts['historical_jobs']} rows)"
            )
        if export_descriptions:
            counts["job_descriptions"] = export_job_descriptions_csv(session)
            print(
                f"  Exported job_descriptions.csv from DB ({counts['job_descriptions']} rows)"
            )
        if export_crm:
            counts["recruiter_crm"] = export_recruiter_crm_csv(session)
            print(f"  Exported recruiter_crm.csv from DB ({counts['recruiter_crm']} rows)")
    return counts
