"""Shared CSV ↔ SQLite parity checks (operational, cumulative, lifecycle)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import paths
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
)


def read_csv(path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def status_dist(frame: pd.DataFrame, col: str = "ai_status") -> Counter[str]:
    counter: Counter[str] = Counter()
    if frame.empty or col not in frame.columns:
        return counter
    for raw in frame[col].tolist():
        counter[str(raw).strip().lower() or "pending"] += 1
    return counter


def v2_keys(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "JOB_KEY_V2" not in frame.columns:
        return set()
    return {
        str(v).strip()
        for v in frame["JOB_KEY_V2"].tolist()
        if str(v).strip()
    }


def load_query_state_csv() -> tuple[dict[str, float], int | None]:
    if not paths.linkedin_query_state_json().is_file():
        return {}, None
    with open(paths.linkedin_query_state_json(), encoding="utf-8") as handle:
        payload = json.load(handle)
    raw_map = payload.get("last_run_by_query_id", {}) or {}
    csv_map = {str(k): float(v) for k, v in raw_map.items()}
    rotation = payload.get("domain_rotation_index")
    return csv_map, int(rotation) if rotation is not None else None


@dataclass
class ParitySections:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.failures


def check_historical_v2_uniqueness(historical: pd.DataFrame) -> ParitySections:
    """Strict: non-empty JOB_KEY_V2 values must be unique in historical_jobs.csv."""
    out = ParitySections()
    if historical.empty or "JOB_KEY_V2" not in historical.columns:
        return out

    key_counts = Counter(
        str(v).strip()
        for v in historical["JOB_KEY_V2"].tolist()
        if str(v).strip()
    )
    dupes = sorted(k for k, count in key_counts.items() if count > 1)
    if dupes:
        preview = ", ".join(dupes[:8])
        suffix = "..." if len(dupes) > 8 else ""
        out.failures.append(
            f"duplicate JOB_KEY_V2 in historical_jobs.csv ({len(dupes)}): {preview}{suffix}"
        )
    return out


def check_jobs_csv_subset_of_historical(
    jobs_csv: pd.DataFrame, historical: pd.DataFrame
) -> ParitySections:
    """Strict: every operational jobs.csv JOB_KEY_V2 must exist in historical_jobs.csv."""
    out = ParitySections()
    jobs_keys = v2_keys(jobs_csv)
    if not jobs_keys:
        return out

    hist_keys = v2_keys(historical)
    jobs_only = sorted(jobs_keys - hist_keys)
    if jobs_only:
        preview = ", ".join(jobs_only[:8])
        suffix = "..." if len(jobs_only) > 8 else ""
        out.failures.append(
            f"jobs.csv JOB_KEY_V2 not in historical_jobs.csv ({len(jobs_only)}): "
            f"{preview}{suffix}"
        )
    return out


def check_lifecycle_invariants(historical: pd.DataFrame) -> ParitySections:
    out = ParitySections()
    csv_status = status_dist(historical)
    csv_hist_rows = len(historical.index)
    csv_scored = csv_status.get("scored", 0)

    if csv_hist_rows < csv_scored:
        out.failures.append("persistence cohort < scored cohort in CSV")

    scored_without_score = 0
    if not historical.empty and "ai_status" in historical.columns and "ai_score" in historical.columns:
        subset = historical[historical["ai_status"].astype(str).str.lower() == "scored"]
        for value in subset["ai_score"].tolist():
            txt = str(value).strip()
            if not txt:
                scored_without_score += 1
            else:
                try:
                    float(txt)
                except ValueError:
                    scored_without_score += 1
    if scored_without_score > 0:
        out.failures.append(
            f"scored rows with blank/non-numeric ai_score in historical ({scored_without_score})"
        )
    return out


def check_query_state_parity(session: Session, *, strict: bool = True) -> ParitySections:
    out = ParitySections()
    csv_map, csv_rotation = load_query_state_csv()
    if not csv_map and csv_rotation is None:
        return out

    db_rows = session.execute(
        select(
            QueryCooldownState.query_id,
            QueryCooldownState.last_run_at,
            QueryCooldownState.domain_rotation_index,
        )
    ).all()
    db_map = {row[0]: row[1] for row in db_rows}
    db_domain_values = {row[2] for row in db_rows if row[2] is not None}

    def _record(message: str) -> None:
        if strict:
            out.failures.append(message)
        else:
            out.warnings.append(message)

    if set(csv_map.keys()) != set(db_map.keys()):
        _record("query_cooldown_state query_id set differs from CSV JSON")
    else:
        for query_id, csv_last in csv_map.items():
            db_last = db_map.get(query_id)
            if db_last is None:
                _record(f"query_state missing DB last_run_at for {query_id}")
                continue
            if abs(float(db_last) - float(csv_last)) > 0.001:
                _record(f"query_state last_run_at mismatch for {query_id}")

    if csv_rotation is not None and db_domain_values:
        if len(db_domain_values) != 1 or int(next(iter(db_domain_values))) != int(csv_rotation):
            _record("query_cooldown_state domain_rotation_index mismatch")
    return out


def check_recruiter_parity(session: Session, recruiter_csv_rows: int) -> ParitySections:
    out = ParitySections()
    db_recruiters = session.execute(select(func.count()).select_from(Recruiter)).scalar_one()
    if db_recruiters != recruiter_csv_rows:
        out.failures.append(
            f"DB recruiters ({db_recruiters}) != recruiter_crm.csv ({recruiter_csv_rows})"
        )
    return out


def check_orphan_recruiter_links(session: Session) -> ParitySections:
    out = ParitySections()
    orphans = session.execute(
        select(func.count())
        .select_from(RecruiterJobLink)
        .outerjoin(Recruiter, Recruiter.id == RecruiterJobLink.recruiter_id)
        .outerjoin(Job, Job.id == RecruiterJobLink.job_id)
        .where(Recruiter.id.is_(None) | Job.id.is_(None))
    ).scalar_one()
    if orphans > 0:
        out.failures.append(f"orphan recruiter_job_links detected ({orphans})")
    return out


def _evaluation_for_v2(session: Session, key_v2: str) -> tuple[str, float | None, str | None] | None:
    row = session.execute(
        select(AiEvaluation.ai_status, AiEvaluation.ai_score, AiEvaluation.model)
        .join(Job, Job.id == AiEvaluation.job_id)
        .where(Job.job_key_v2 == key_v2)
    ).first()
    if not row:
        return None
    return str(row[0]).strip().lower(), row[1], row[2]


def check_operational_cohort_parity(session: Session, jobs_csv: pd.DataFrame) -> ParitySections:
    """Strict per-key parity for jobs.csv operational export cohort."""
    out = ParitySections()
    if jobs_csv.empty or "JOB_KEY_V2" not in jobs_csv.columns:
        if len(jobs_csv.index) > 0:
            out.failures.append("jobs.csv missing JOB_KEY_V2 column")
        return out

    missing_job = 0
    missing_eval = 0
    status_mismatch = 0

    for _, row in jobs_csv.iterrows():
        key = str(row.get("JOB_KEY_V2", "")).strip()
        if not key:
            out.failures.append("jobs.csv row with empty JOB_KEY_V2")
            continue

        job_exists = session.execute(
            select(Job.id).where(Job.job_key_v2 == key)
        ).scalar_one_or_none()
        if job_exists is None:
            missing_job += 1
            continue

        eval_row = _evaluation_for_v2(session, key)
        if eval_row is None:
            missing_eval += 1
            continue

        csv_status = str(row.get("ai_status", "")).strip().lower() or "pending"
        db_status = eval_row[0]
        if csv_status != db_status:
            status_mismatch += 1

    if missing_job:
        out.failures.append(f"jobs.csv keys missing in DB jobs ({missing_job})")
    if missing_eval:
        out.failures.append(f"jobs.csv keys missing DB ai_evaluations ({missing_eval})")
    if status_mismatch:
        out.failures.append(f"jobs.csv ai_status mismatches vs DB ({status_mismatch})")
    return out


def check_historical_key_parity(session: Session, historical: pd.DataFrame) -> ParitySections:
    """Strict: every historical JOB_KEY_V2 must exist in DB with matching ai_status."""
    out = ParitySections()
    if historical.empty or "JOB_KEY_V2" not in historical.columns:
        return out

    missing_eval = 0
    status_mismatch = 0
    for _, row in historical.iterrows():
        key = str(row.get("JOB_KEY_V2", "")).strip()
        if not key:
            continue
        eval_row = _evaluation_for_v2(session, key)
        if eval_row is None:
            missing_eval += 1
            continue
        csv_status = str(row.get("ai_status", "")).strip().lower() or "pending"
        if csv_status != eval_row[0]:
            status_mismatch += 1

    if missing_eval:
        out.failures.append(f"historical keys missing DB ai_evaluations ({missing_eval})")
    if status_mismatch:
        out.failures.append(f"historical ai_status mismatches vs DB ({status_mismatch})")
    return out


def check_acquisition_runtime_parity(
    session: Session,
    jobs_csv: pd.DataFrame,
    *,
    require_query_runs: bool = True,
) -> ParitySections:
    out = ParitySections()
    run_count = session.execute(select(func.count()).select_from(AcquisitionRun)).scalar_one()
    if run_count < 1:
        out.failures.append("no acquisition_runs rows in SQLite")

    query_run_count = session.execute(
        select(func.count()).select_from(AcquisitionQueryRun)
    ).scalar_one()

    has_query_metadata = False
    if not jobs_csv.empty:
        for col in ("linkedin_query_id", "instahyre_query_id", "instahyre_feed_id"):
            if col in jobs_csv.columns:
                if jobs_csv[col].fillna("").astype(str).str.strip().ne("").any():
                    has_query_metadata = True
                    break

    if require_query_runs and has_query_metadata and query_run_count < 1:
        out.failures.append(
            "jobs.csv has query metadata but acquisition_query_runs is empty"
        )
    return out


def check_cumulative_memory_warnings(
    session: Session,
    historical: pd.DataFrame,
    jobs_csv: pd.DataFrame,
    *,
    max_extra_keys_listed: int = 8,
) -> ParitySections:
    out = ParitySections()
    hist_keys = v2_keys(historical)
    jobs_keys = v2_keys(jobs_csv)

    db_job_keys = {
        row[0]
        for row in session.execute(select(Job.job_key_v2)).all()
        if row[0]
    }
    extra_in_db = sorted(db_job_keys - hist_keys)
    missing_in_db = sorted(hist_keys - db_job_keys)

    if missing_in_db:
        out.failures.append(f"historical JOB_KEY_V2 missing in DB jobs ({len(missing_in_db)})")

    if len(db_job_keys) > len(hist_keys):
        out.warnings.append(
            f"DB jobs ({len(db_job_keys)}) > historical_jobs.csv ({len(hist_keys)}); "
            f"+{len(extra_in_db)} cumulative extra keys"
        )
    if extra_in_db:
        preview = ", ".join(extra_in_db[:max_extra_keys_listed])
        suffix = "..." if len(extra_in_db) > max_extra_keys_listed else ""
        out.warnings.append(f"extra DB JOB_KEY_V2 not in historical: {preview}{suffix}")

    csv_status = status_dist(historical)
    db_status_rows = session.execute(
        select(AiEvaluation.ai_status, func.count())
        .group_by(AiEvaluation.ai_status)
    ).all()
    db_status = Counter({str(k).lower(): int(v) for k, v in db_status_rows})

    for status in ("scored", "skipped_by_cap", "pending"):
        csv_n = csv_status.get(status, 0)
        db_n = db_status.get(status, 0)
        if db_n > csv_n:
            out.warnings.append(
                f"DB ai_status {status} ({db_n}) > historical CSV ({csv_n}); "
                "cumulative memory superset"
            )
        elif db_n < csv_n and status == "scored":
            out.failures.append(f"DB ai_status scored ({db_n}) < historical CSV ({csv_n})")

    if extra_in_db:
        import_extras = session.execute(
            select(func.count())
            .select_from(AiEvaluation)
            .join(Job, Job.id == AiEvaluation.job_id)
            .where(AiEvaluation.model == "csv_import", Job.job_key_v2.in_(extra_in_db))
        ).scalar_one()
        if import_extras:
            out.warnings.append(
                f"retained csv_import evaluations among extra DB keys ({import_extras})"
            )

    return out


def check_import_bootstrap_parity(
    session: Session,
    historical: pd.DataFrame,
    desc_csv: pd.DataFrame,
    recruiter_csv: pd.DataFrame,
) -> ParitySections:
    """Stricter Phase B import semantics (aggregate parity)."""
    out = ParitySections()
    hist_rows = len(historical.index)
    db_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
    db_desc = session.execute(select(func.count()).select_from(JobDescription)).scalar_one()
    db_recruiters = session.execute(select(func.count()).select_from(Recruiter)).scalar_one()

    if db_jobs < hist_rows:
        out.failures.append("DB jobs count lower than historical_jobs.csv rows")
    if db_desc < len(desc_csv.index):
        out.failures.append("DB job_descriptions lower than job_descriptions.csv rows")

    out.extend(check_recruiter_parity(session, len(recruiter_csv.index)))
    out.extend(check_query_state_parity(session))
    out.extend(check_historical_key_parity(session, historical))

    csv_status = status_dist(historical)
    db_status_rows = session.execute(
        select(AiEvaluation.ai_status, func.count()).group_by(AiEvaluation.ai_status)
    ).all()
    db_status = Counter({str(k).lower(): int(v) for k, v in db_status_rows})
    for status in ("scored", "skipped_by_cap", "pending"):
        if db_status.get(status, 0) != csv_status.get(status, 0):
            out.failures.append(f"ai_status aggregate mismatch for {status} (import mode)")

    return out


def check_source_of_truth_export_parity(
    session: Session,
    historical: pd.DataFrame,
    jobs_csv: pd.DataFrame,
    desc_csv: pd.DataFrame,
    recruiter_csv: pd.DataFrame,
) -> ParitySections:
    """
    DB is reference; on-disk CSV exports must match SQLite (D7 validator inversion).
    """
    out = ParitySections()
    out.extend(check_import_bootstrap_parity(session, historical, desc_csv, recruiter_csv))
    out.extend(check_operational_cohort_parity(session, jobs_csv))
    out.extend(check_orphan_recruiter_links(session))

    hist_keys = v2_keys(historical)
    db_job_keys = {
        row[0]
        for row in session.execute(select(Job.job_key_v2)).all()
        if row[0]
    }
    csv_only = sorted(hist_keys - db_job_keys)
    db_only = sorted(db_job_keys - hist_keys)
    if csv_only:
        preview = ", ".join(csv_only[:8])
        suffix = "..." if len(csv_only) > 8 else ""
        out.failures.append(
            f"CSV export has JOB_KEY_V2 not in DB ({len(csv_only)}): {preview}{suffix}"
        )
    if db_only:
        preview = ", ".join(db_only[:8])
        suffix = "..." if len(db_only) > 8 else ""
        out.failures.append(
            f"DB jobs missing from historical_jobs.csv export ({len(db_only)}): "
            f"{preview}{suffix}"
        )

    db_desc = session.execute(select(func.count()).select_from(JobDescription)).scalar_one()
    if db_desc != len(desc_csv.index):
        out.failures.append(
            f"DB job_descriptions ({db_desc}) != job_descriptions.csv ({len(desc_csv.index)})"
        )

    return out


D2_METADATA_WARN_COLUMNS = (
    "linkedin_query_id",
    "linkedin_query_group",
    "linkedin_query_label",
    "linkedin_filter_profile",
    "linkedin_query_role",
    "linkedin_run_ts",
    "instahyre_feed_id",
    "instahyre_query_id",
    "instahyre_query_label",
    "instahyre_run_ts",
)


def check_d2_export_metadata_warnings(
    jobs_csv: pd.DataFrame,
    db_export_df: pd.DataFrame | None,
) -> ParitySections:
    """Warn-only: jobs.csv metadata column coverage vs current_jobs_view export source."""
    out = ParitySections()
    if jobs_csv.empty or db_export_df is None or db_export_df.empty:
        return out
    for col in D2_METADATA_WARN_COLUMNS:
        if col not in jobs_csv.columns:
            continue
        csv_filled = int(jobs_csv[col].fillna("").astype(str).str.strip().ne("").sum())
        if csv_filled == 0:
            continue
        db_filled = (
            int(db_export_df[col].fillna("").astype(str).str.strip().ne("").sum())
            if col in db_export_df.columns
            else 0
        )
        if db_filled < csv_filled:
            out.warnings.append(
                f"D2 metadata WARN {col}: jobs.csv={csv_filled} current_jobs_view={db_filled}"
            )
    return out


def check_production_db_health(
    session: Session,
    jobs_csv: pd.DataFrame,
    *,
    require_jobs: bool = True,
) -> ParitySections:
    """SQLite-first row-count and cohort coverage checks after acquisition."""
    out = ParitySections()
    db_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
    db_evals = session.execute(select(func.count()).select_from(AiEvaluation)).scalar_one()
    db_observations = session.execute(
        select(func.count()).select_from(JobObservation)
    ).scalar_one()
    cohort_rows = len(jobs_csv.index)

    if require_jobs and db_jobs < 1:
        out.failures.append("no jobs rows in SQLite after acquisition")
    if db_jobs > 0 and db_evals < db_jobs:
        out.failures.append(
            f"DB ai_evaluations ({db_evals}) lower than DB jobs ({db_jobs})"
        )
    if cohort_rows > 0 and db_observations < cohort_rows:
        out.failures.append(
            f"DB job_observations ({db_observations}) lower than jobs.csv cohort ({cohort_rows})"
        )
    if cohort_rows > 0 and db_jobs < cohort_rows:
        out.failures.append(
            f"DB jobs ({db_jobs}) lower than jobs.csv operational cohort ({cohort_rows})"
        )
    return out


def check_production_cumulative_health(
    session: Session,
    historical: pd.DataFrame,
) -> ParitySections:
    """
    DB-first cumulative health for production mode.

    Strict in-DB checks always apply. Historical CSV key cross-check is strict only when
    SQLITE_EXPORT_HISTORICAL_CSV=1; otherwise stale optional-export rows are warnings.
    """
    from db.write.engine import export_historical_csv_enabled

    out = ParitySections()
    hist_keys = v2_keys(historical)
    db_job_keys = {
        row[0]
        for row in session.execute(select(Job.job_key_v2)).all()
        if row[0]
    }
    if hist_keys:
        missing_in_db = sorted(hist_keys - db_job_keys)
        if missing_in_db:
            preview = ", ".join(missing_in_db[:8])
            suffix = "..." if len(missing_in_db) > 8 else ""
            msg = (
                f"historical JOB_KEY_V2 in CSV not in DB jobs ({len(missing_in_db)}): "
                f"{preview}{suffix}"
            )
            if export_historical_csv_enabled():
                out.failures.append(msg)
            else:
                out.warnings.append(
                    f"{msg} (optional historical_jobs.csv artifact; "
                    "SQLITE_EXPORT_HISTORICAL_CSV=0; SQLite authoritative)"
                )

    jobs_without_eval = session.execute(
        select(func.count())
        .select_from(Job)
        .outerjoin(AiEvaluation, AiEvaluation.job_id == Job.id)
        .where(AiEvaluation.id.is_(None))
    ).scalar_one()
    if jobs_without_eval > 0:
        out.warnings.append(f"jobs in DB without ai_evaluation ({jobs_without_eval})")

    db_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
    db_desc = session.execute(select(func.count()).select_from(JobDescription)).scalar_one()
    if db_desc < db_jobs:
        out.warnings.append(
            f"DB job_descriptions ({db_desc}) lower than DB jobs ({db_jobs}); "
            "description enrichment gap"
        )

    db_status_rows = session.execute(
        select(AiEvaluation.ai_status, func.count()).group_by(AiEvaluation.ai_status)
    ).all()
    db_status = Counter({str(k).strip().lower(): int(v) for k, v in db_status_rows})
    db_scored_jobs = session.execute(
        select(func.count())
        .select_from(Job)
        .join(AiEvaluation, AiEvaluation.job_id == Job.id)
        .where(AiEvaluation.ai_status == "scored")
    ).scalar_one()
    if db_status.get("scored", 0) < db_scored_jobs:
        out.failures.append(
            f"DB ai_status scored aggregate ({db_status.get('scored', 0)}) "
            f"lower than scored job rows ({db_scored_jobs})"
        )

    return out


def production_desc_csv_floor_applies(desc_csv: pd.DataFrame) -> bool:
    """Skip description CSV floor when mirror is empty under write-primary."""
    from db.write.engine import export_descriptions_csv_enabled, write_primary_enabled

    if len(desc_csv.index) > 0:
        return True
    if write_primary_enabled() and not export_descriptions_csv_enabled():
        return False
    return False


def merge_sections(*sections: ParitySections) -> ParitySections:
    merged = ParitySections()
    for section in sections:
        merged.failures.extend(section.failures)
        merged.warnings.extend(section.warnings)
    return merged


def _extend(section: ParitySections, other: ParitySections) -> ParitySections:
    section.failures.extend(other.failures)
    section.warnings.extend(other.warnings)
    return section


ParitySections.extend = _extend  # type: ignore[method-assign]
