#!/usr/bin/env python3
"""Remove a single JOB_KEY_V2 orphan from SQLite (CSV remains source of truth)."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import (
    AiEvaluation,
    Job,
    JobDescription,
    JobObservation,
    RecruiterJobLink,
    UserJobState,
)
from db.services.parity_checks import read_csv, v2_keys

DEFAULT_ORPHAN_KEY = "v2:linkedin:4374896750"


@dataclass
class CleanupReport:
    job_key_v2: str
    job_id: int | None = None
    dry_run: bool = False
    rows_removed: dict[str, int] = field(default_factory=dict)

    def total_removed(self) -> int:
        return sum(self.rows_removed.values())


def _key_present_in_csv_memory(job_key_v2: str) -> tuple[bool, str]:
    historical = read_csv(paths.historical_jobs_csv())
    jobs = read_csv(paths.jobs_csv())
    if job_key_v2 in v2_keys(historical):
        return True, "historical_jobs.csv"
    if job_key_v2 in v2_keys(jobs):
        return True, "jobs.csv"
    return False, ""


def cleanup_orphan_job(*, job_key_v2: str, dry_run: bool = False) -> CleanupReport:
    """
    Delete one job and directly related rows by JOB_KEY_V2.

    Refuses to run if the key still exists in historical_jobs.csv or jobs.csv.
    """
    key = job_key_v2.strip()
    if not key:
        raise ValueError("job_key_v2 must be non-empty")

    report = CleanupReport(job_key_v2=key, dry_run=dry_run)
    present, source = _key_present_in_csv_memory(key)
    if present:
        raise RuntimeError(
            f"Refusing cleanup: {key!r} still present in {source} "
            "(remove from CSV first if intentional)."
        )

    ensure_database_ready()

    with get_session() as session:
        job_row = session.execute(
            select(Job.id, Job.title, Job.company, Job.source).where(
                Job.job_key_v2 == key
            )
        ).first()

        if not job_row:
            report.rows_removed = {table: 0 for table in _TABLE_ORDER}
            return report

        job_id = int(job_row[0])
        report.job_id = job_id

        counts: dict[str, int] = {}
        for table_name, model, predicate in _DELETE_STEPS:
            result = session.execute(delete(model).where(predicate(job_id)))
            counts[table_name] = int(result.rowcount or 0)

        job_delete = session.execute(delete(Job).where(Job.id == job_id))
        counts["jobs"] = int(job_delete.rowcount or 0)

        report.rows_removed = counts

        if dry_run:
            session.rollback()
        else:
            session.commit()

    return report


_TABLE_ORDER = (
    "recruiter_job_links",
    "user_job_state",
    "job_observations",
    "ai_evaluations",
    "job_descriptions",
    "jobs",
)

_DELETE_STEPS = [
    ("recruiter_job_links", RecruiterJobLink, lambda jid: RecruiterJobLink.job_id == jid),
    ("user_job_state", UserJobState, lambda jid: UserJobState.job_id == jid),
    ("job_observations", JobObservation, lambda jid: JobObservation.job_id == jid),
    ("ai_evaluations", AiEvaluation, lambda jid: AiEvaluation.job_id == jid),
    ("job_descriptions", JobDescription, lambda jid: JobDescription.job_id == jid),
]


def _print_report(report: CleanupReport) -> None:
    mode = "DRY-RUN" if report.dry_run else "COMMITTED"
    print(f"[{mode}] SQLite orphan cleanup for JOB_KEY_V2={report.job_key_v2!r}")
    if report.job_id is None:
        print("  job not found in SQLite (nothing to remove)")
        return
    print(f"  job_id={report.job_id}")
    print("  rows_removed:")
    for table in _TABLE_ORDER:
        print(f"    {table}: {report.rows_removed.get(table, 0)}")
    print(f"  total_rows_removed: {report.total_removed()}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove a single SQLite job orphan not present in CSV memory."
    )
    parser.add_argument(
        "--job-key-v2",
        default=DEFAULT_ORPHAN_KEY,
        help=f"JOB_KEY_V2 to remove (default: {DEFAULT_ORPHAN_KEY})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without committing.",
    )
    args = parser.parse_args()

    try:
        report = cleanup_orphan_job(job_key_v2=args.job_key_v2, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
