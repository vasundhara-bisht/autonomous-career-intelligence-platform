#!/usr/bin/env python3
"""CSV ↔ SQLite parity validation.

Modes:
  production (default) — SQLite-first post-acquisition (D8B write-primary)
  source-of-truth      — DB reference vs exported CSV mirrors
  import               — Phase B bootstrap after import_csv_memory.py
  csv-mirror-sync      — Legacy Phase C strict CSV ↔ DB coupling
  post-dual-write      — Lighter key-level check (optional)
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from db.bootstrap import ensure_database_ready
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
from db.read.export_cohort import load_current_jobs_export_source_df
from db.services.parity_checks import (
    check_acquisition_runtime_parity,
    check_cumulative_memory_warnings,
    check_d2_export_metadata_warnings,
    check_historical_key_parity,
    check_historical_v2_uniqueness,
    check_import_bootstrap_parity,
    check_jobs_csv_subset_of_historical,
    check_lifecycle_invariants,
    check_operational_cohort_parity,
    check_orphan_recruiter_links,
    check_production_cumulative_health,
    check_production_db_health,
    check_query_state_parity,
    check_recruiter_parity,
    check_source_of_truth_export_parity,
    merge_sections,
    production_desc_csv_floor_applies,
    read_csv,
    status_dist,
)
from db.write.engine import (
    export_crm_csv_enabled,
    export_descriptions_csv_enabled,
    export_historical_csv_enabled,
    export_jobs_csv_enabled,
    write_primary_enabled,
)


def _print_list(title: str, items: list[str]) -> None:
    print(f"\n{title}")
    if not items:
        print("  (none)")
        return
    for item in items:
        print(f"  - {item}")


def _export_flag_summary() -> str:
    return (
        f"write_primary={int(write_primary_enabled())} "
        f"export_jobs={int(export_jobs_csv_enabled())} "
        f"export_historical={int(export_historical_csv_enabled())} "
        f"export_descriptions={int(export_descriptions_csv_enabled())} "
        f"export_crm={int(export_crm_csv_enabled())}"
    )


def run_import_mode(*, fail_on_error: bool = False) -> int:
    ensure_database_ready()
    historical = read_csv(paths.historical_jobs_csv())
    jobs = read_csv(paths.jobs_csv())
    desc = read_csv(paths.job_descriptions_csv())
    recruiters = read_csv(paths.recruiter_crm_csv())

    with get_session() as session:
        lifecycle = check_lifecycle_invariants(historical)
        import_parity = check_import_bootstrap_parity(session, historical, desc, recruiters)
        report = merge_sections(lifecycle, import_parity)

        db_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
        db_recruiters = session.execute(select(func.count()).select_from(Recruiter)).scalar_one()
        db_status_rows = session.execute(
            select(AiEvaluation.ai_status, func.count()).group_by(AiEvaluation.ai_status)
        ).all()
        db_status = Counter({str(k).lower(): int(v) for k, v in db_status_rows})
        csv_status = status_dist(historical)

        print("SQLite parity report — mode: import (Phase B bootstrap)")
        print(f"  historical_jobs.csv rows:   {len(historical)}")
        print(f"  jobs.csv rows:              {len(jobs)}")
        print(f"  job_descriptions.csv rows:  {len(desc)}")
        print(f"  recruiter_crm.csv rows:     {len(recruiters)}")
        print(f"  DB jobs rows:               {db_jobs}")
        print(f"  DB recruiters rows:         {db_recruiters}")
        print(
            "  ai_status CSV (historical): "
            + ", ".join(f"{k}={csv_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )
        print(
            "  ai_status DB:               "
            + ", ".join(f"{k}={db_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )

        print("\nLIFECYCLE INVARIANTS")
        print(f"  {'PASS' if lifecycle.ok() else 'FAIL'}")
        _print_list("", lifecycle.failures)

        print("\nIMPORT PARITY (strict aggregate + key-level)")
        print(f"  {'PASS' if import_parity.ok() else 'FAIL'}")
        _print_list("", import_parity.failures)

        print(f"\nOVERALL: {'PASS' if report.ok() else 'FAIL'}")
        return 1 if (report.failures and fail_on_error) else 0


def run_production_mode(*, fail_on_error: bool = False) -> int:
    ensure_database_ready()
    historical = read_csv(paths.historical_jobs_csv())
    jobs_csv = read_csv(paths.jobs_csv())
    desc_csv = read_csv(paths.job_descriptions_csv())
    jobs_csv_status = status_dist(jobs_csv)

    with get_session() as session:
        db_counts = {
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
        }
        db_status_rows = session.execute(
            select(AiEvaluation.ai_status, func.count())
            .group_by(AiEvaluation.ai_status)
            .order_by(AiEvaluation.ai_status)
        ).all()
        db_status = Counter({str(k).strip().lower(): int(v) for k, v in db_status_rows})

        db_health = check_production_db_health(
            session,
            jobs_csv,
            require_jobs=db_counts["acquisition_runs"] >= 1,
        )
        operational = merge_sections(
            check_operational_cohort_parity(session, jobs_csv),
            check_acquisition_runtime_parity(session, jobs_csv),
            check_orphan_recruiter_links(session),
        )
        cumulative = check_production_cumulative_health(session, historical)
        query_state = check_query_state_parity(session, strict=False)
        db_export_df = load_current_jobs_export_source_df(session)
        d2_metadata = check_d2_export_metadata_warnings(jobs_csv, db_export_df)

        report = merge_sections(db_health, operational, cumulative)
        report.warnings.extend(query_state.warnings)
        report.warnings.extend(d2_metadata.warnings)

        print("SQLite parity report — mode: production (D8B write-primary)")
        print(f"  {_export_flag_summary()}")
        print(f"  historical_jobs.csv rows:    {len(historical)} (optional export)")
        print(f"  jobs.csv rows:               {len(jobs_csv)}")
        print(f"  job_descriptions.csv rows:   {len(desc_csv)} (optional export)")
        print(f"  DB jobs:                     {db_counts['jobs']}")
        print(f"  DB job_observations:         {db_counts['job_observations']}")
        print(f"  DB ai_evaluations:           {db_counts['ai_evaluations']}")
        print(f"  DB job_descriptions:         {db_counts['job_descriptions']}")
        print(f"  DB recruiters:               {db_counts['recruiters']}")
        print(f"  DB recruiter_job_links:      {db_counts['recruiter_job_links']}")
        print(f"  DB acquisition_runs:         {db_counts['acquisition_runs']}")
        print(
            "  ai_status CSV (jobs.csv):    "
            + ", ".join(
                f"{k}={jobs_csv_status.get(k, 0)}"
                for k in ("scored", "skipped_by_cap", "pending")
            )
        )
        print(
            "  ai_status DB (cumulative):   "
            + ", ".join(f"{k}={db_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )

        print("\nDB HEALTH (strict)")
        print(f"  {'PASS' if db_health.ok() else 'FAIL'}")
        _print_list("", db_health.failures)

        print("\nOPERATIONAL PARITY (strict)")
        print(f"  {'PASS' if operational.ok() else 'FAIL'}")
        _print_list("", operational.failures)

        print("\nCUMULATIVE HEALTH (DB-first)")
        print(f"  {'PASS' if cumulative.ok() else 'FAIL'}")
        _print_list("", cumulative.failures)
        if cumulative.warnings:
            print("  warnings:")
            _print_list("", cumulative.warnings)

        warn_sections = merge_sections(query_state, d2_metadata)
        print("\nNON-FATAL (warnings)")
        print(f"  {'PASS' if not warn_sections.warnings else 'WARN'}")
        _print_list("", warn_sections.warnings)

        print(f"\nOVERALL: {'PASS' if report.ok() else 'FAIL'}")
        _print_list("Failures (strict)", report.failures)
        _print_list("Warnings (non-fatal)", report.warnings)

    return 1 if (report.failures and fail_on_error) else 0


def run_csv_mirror_sync_mode(*, fail_on_error: bool = False) -> int:
    """Legacy Phase C strict CSV ↔ DB parity (former validate_dual_write_parity)."""
    ensure_database_ready()

    historical = read_csv(paths.historical_jobs_csv())
    jobs_csv = read_csv(paths.jobs_csv())
    desc_csv = read_csv(paths.job_descriptions_csv())
    recruiter_csv = read_csv(paths.recruiter_crm_csv())
    csv_status = status_dist(historical)
    jobs_csv_status = status_dist(jobs_csv)

    with get_session() as session:
        db_counts = {
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
        db_status_rows = session.execute(
            select(AiEvaluation.ai_status, func.count())
            .group_by(AiEvaluation.ai_status)
            .order_by(AiEvaluation.ai_status)
        ).all()
        db_status = Counter({str(k).strip().lower(): int(v) for k, v in db_status_rows})

        lifecycle = merge_sections(
            check_lifecycle_invariants(historical),
            check_historical_v2_uniqueness(historical),
            check_jobs_csv_subset_of_historical(jobs_csv, historical),
        )
        operational = merge_sections(
            check_operational_cohort_parity(session, jobs_csv),
            check_historical_key_parity(session, historical),
            check_recruiter_parity(session, len(recruiter_csv.index)),
            check_query_state_parity(session, strict=True),
            check_acquisition_runtime_parity(session, jobs_csv),
            check_orphan_recruiter_links(session),
        )

        floor = merge_sections()
        if db_counts["jobs"] < len(jobs_csv.index):
            floor.failures.append("DB jobs lower than jobs.csv operational cohort")
        if production_desc_csv_floor_applies(desc_csv):
            if db_counts["job_descriptions"] < len(desc_csv.index):
                floor.failures.append(
                    "DB job_descriptions lower than job_descriptions.csv rows"
                )
        if db_counts["job_observations"] < len(jobs_csv.index):
            floor.failures.append(
                "DB job_observations lower than jobs.csv operational cohort"
            )

        cumulative = check_cumulative_memory_warnings(session, historical, jobs_csv)
        report = merge_sections(lifecycle, operational, floor, cumulative)
        db_export_df = load_current_jobs_export_source_df(session)
        d2_metadata = check_d2_export_metadata_warnings(jobs_csv, db_export_df)
        report.warnings.extend(d2_metadata.warnings)

        print("SQLite parity report — mode: csv-mirror-sync (legacy Phase C)")
        print(f"  historical_jobs.csv rows:    {len(historical)}")
        print(f"  jobs.csv rows:               {len(jobs_csv)}")
        print(f"  job_descriptions.csv rows:   {len(desc_csv)}")
        print(f"  recruiter_crm.csv rows:      {len(recruiter_csv)}")
        print(f"  DB jobs:                     {db_counts['jobs']}")
        print(f"  DB job_observations:         {db_counts['job_observations']}")
        print(f"  DB ai_evaluations:           {db_counts['ai_evaluations']}")
        print(f"  DB job_descriptions:         {db_counts['job_descriptions']}")
        print(f"  DB user_job_state:           {db_counts['user_job_state']}")
        print(f"  DB recruiters:               {db_counts['recruiters']}")
        print(f"  DB recruiter_job_links:      {db_counts['recruiter_job_links']}")
        print(f"  DB acquisition_runs:         {db_counts['acquisition_runs']}")
        print(f"  DB acquisition_query_runs:   {db_counts['acquisition_query_runs']}")
        print(f"  DB query_cooldown_state:     {db_counts['query_cooldown_state']}")
        print(
            "  ai_status CSV (historical):  "
            + ", ".join(f"{k}={csv_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )
        print(
            "  ai_status CSV (jobs.csv):    "
            + ", ".join(
                f"{k}={jobs_csv_status.get(k, 0)}"
                for k in ("scored", "skipped_by_cap", "pending")
            )
        )
        print(
            "  ai_status DB (cumulative):   "
            + ", ".join(f"{k}={db_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )

        print("\nLIFECYCLE INVARIANTS")
        print(f"  {'PASS' if lifecycle.ok() else 'FAIL'}")
        _print_list("", lifecycle.failures)

        print("\nOPERATIONAL PARITY (strict)")
        print(f"  {'PASS' if operational.ok() and floor.ok() else 'FAIL'}")
        _print_list("", merge_sections(operational, floor).failures)

        print("\nCUMULATIVE MEMORY HEALTH (warnings only)")
        print(f"  {'PASS' if not cumulative.warnings else 'WARN'}")
        _print_list("", cumulative.warnings)
        if cumulative.failures:
            print("  strict failures from cumulative:")
            _print_list("", cumulative.failures)

        print("\nD2 METADATA PARITY (warn-only)")
        print(f"  {'PASS' if not d2_metadata.warnings else 'WARN'}")
        _print_list("", d2_metadata.warnings)

        print(f"\nOVERALL: {'PASS' if report.ok() else 'FAIL'}")
        _print_list("Failures (strict)", report.failures)
        _print_list("Warnings (non-fatal)", report.warnings)

    return 1 if (report.failures and fail_on_error) else 0


def run_post_dual_write_mode(*, fail_on_error: bool = False) -> int:
    ensure_database_ready()
    historical = read_csv(paths.historical_jobs_csv())
    jobs = read_csv(paths.jobs_csv())
    recruiters = read_csv(paths.recruiter_crm_csv())

    with get_session() as session:
        lifecycle = merge_sections(
            check_lifecycle_invariants(historical),
            check_historical_v2_uniqueness(historical),
            check_jobs_csv_subset_of_historical(jobs, historical),
        )
        operational = merge_sections(
            check_historical_key_parity(session, historical),
            check_recruiter_parity(session, len(recruiters.index)),
            check_query_state_parity(session),
        )
        cumulative = check_cumulative_memory_warnings(session, historical, jobs)
        report = merge_sections(lifecycle, operational, cumulative)

        db_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
        db_status_rows = session.execute(
            select(AiEvaluation.ai_status, func.count()).group_by(AiEvaluation.ai_status)
        ).all()
        db_status = Counter({str(k).lower(): int(v) for k, v in db_status_rows})
        csv_status = status_dist(historical)

        print("SQLite parity report — mode: post-dual-write")
        print(f"  historical_jobs.csv rows:   {len(historical)}")
        print(f"  jobs.csv rows:              {len(jobs)}")
        print(f"  DB jobs rows:               {db_jobs}")
        print(
            "  ai_status CSV (historical): "
            + ", ".join(f"{k}={csv_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )
        print(
            "  ai_status DB (cumulative):  "
            + ", ".join(f"{k}={db_status.get(k, 0)}" for k in ("scored", "skipped_by_cap", "pending"))
        )

        print("\nLIFECYCLE INVARIANTS")
        print(f"  {'PASS' if lifecycle.ok() else 'FAIL'}")
        _print_list("", lifecycle.failures)

        print("\nOPERATIONAL PARITY (key-level historical + recruiters + query state)")
        print(f"  {'PASS' if operational.ok() else 'FAIL'}")
        _print_list("", operational.failures)

        print("\nCUMULATIVE MEMORY HEALTH (warnings only)")
        print(f"  {'PASS' if not cumulative.warnings else 'WARN'}")
        _print_list("", cumulative.warnings)

        print(f"\nOVERALL: {'PASS' if report.ok() else 'FAIL'}")
        _print_list("Failures (strict)", report.failures)
        _print_list("Warnings (non-fatal)", report.warnings)

        return 1 if (report.failures and fail_on_error) else 0


def run_source_of_truth_mode(*, fail_on_error: bool = False) -> int:
    ensure_database_ready()
    historical = read_csv(paths.historical_jobs_csv())
    jobs = read_csv(paths.jobs_csv())
    desc = read_csv(paths.job_descriptions_csv())
    recruiters = read_csv(paths.recruiter_crm_csv())

    with get_session() as session:
        export_parity = check_source_of_truth_export_parity(
            session, historical, jobs, desc, recruiters
        )
        subset = check_jobs_csv_subset_of_historical(jobs, historical)
        report = merge_sections(export_parity, subset)

        db_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
        db_recruiters = session.execute(select(func.count()).select_from(Recruiter)).scalar_one()

        print("SQLite parity report — mode: source-of-truth (DB reference, CSV export compare)")
        print(f"  historical_jobs.csv rows:   {len(historical)}")
        print(f"  jobs.csv rows:              {len(jobs)}")
        print(f"  job_descriptions.csv rows:  {len(desc)}")
        print(f"  recruiter_crm.csv rows:     {len(recruiters)}")
        print(f"  DB jobs rows:               {db_jobs}")
        print(f"  DB recruiters rows:         {db_recruiters}")

        print("\nEXPORT PARITY (strict — DB is reference)")
        print(f"  {'PASS' if export_parity.ok() else 'FAIL'}")
        _print_list("", export_parity.failures)

        if subset.failures:
            print("\nJOBS CSV SUBSET")
            print("  FAIL")
            _print_list("", subset.failures)

        print(f"\nOVERALL: {'PASS' if report.ok() else 'FAIL'}")
        return 1 if (report.failures and fail_on_error) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CSV ↔ SQLite parity.")
    parser.add_argument(
        "--mode",
        choices=(
            "production",
            "import",
            "source-of-truth",
            "csv-mirror-sync",
            "post-dual-write",
        ),
        default="production",
        help=(
            "production: SQLite-first post-acquisition (default); "
            "source-of-truth: after export_csv_memory --all; "
            "import: after import_csv_memory; "
            "csv-mirror-sync: legacy strict CSV mirrors"
        ),
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit 1 when strict checks fail (warnings do not fail).",
    )
    args = parser.parse_args()

    if args.mode == "import":
        return run_import_mode(fail_on_error=args.fail_on_error)
    if args.mode == "source-of-truth":
        return run_source_of_truth_mode(fail_on_error=args.fail_on_error)
    if args.mode == "csv-mirror-sync":
        return run_csv_mirror_sync_mode(fail_on_error=args.fail_on_error)
    if args.mode == "post-dual-write":
        return run_post_dual_write_mode(fail_on_error=args.fail_on_error)
    return run_production_mode(fail_on_error=args.fail_on_error)


if __name__ == "__main__":
    raise SystemExit(main())
