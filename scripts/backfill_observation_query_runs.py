#!/usr/bin/env python3
"""Best-effort D3 backfill: link job_observations.query_run_id for a completed run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import AcquisitionQueryRun, Job, JobObservation
from db.services.dual_write import _query_run_key


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def run_backfill(*, dry_run: bool, run_id: int | None) -> int:
    ensure_database_ready()
    jobs_csv = paths.jobs_csv()
    if not jobs_csv.is_file():
        print("jobs.csv not found; nothing to backfill")
        return 1

    df = pd.read_csv(jobs_csv, dtype=str, keep_default_na=False)
    if df.empty or "JOB_KEY_V2" not in df.columns:
        print("jobs.csv empty or missing JOB_KEY_V2")
        return 1

    with get_session() as session:
        if run_id is None:
            from db.read.export_cohort import load_latest_run_info

            run_info = load_latest_run_info(session)
            if not run_info:
                print("no completed acquisition run in DB")
                return 1
            run_id = int(run_info["run_id"])

        query_runs = session.execute(
            select(AcquisitionQueryRun).where(AcquisitionQueryRun.run_id == run_id)
        ).scalars().all()
        id_by_key: dict[tuple[str, str], int] = {}
        for row in query_runs:
            source = _text(row.source)
            qid = _text(row.query_id)
            if source and qid:
                id_by_key[(source, qid)] = row.id

        updated = 0
        skipped = 0
        for _, csv_row in df.iterrows():
            v2 = _text(csv_row.get("JOB_KEY_V2"))
            if not v2:
                continue
            job_id = session.execute(
                select(Job.id).where(Job.job_key_v2 == v2)
            ).scalar_one_or_none()
            if job_id is None:
                skipped += 1
                continue
            obs = session.execute(
                select(JobObservation).where(
                    JobObservation.run_id == run_id, JobObservation.job_id == job_id
                )
            ).scalar_one_or_none()
            if obs is None:
                skipped += 1
                continue
            key = _query_run_key(csv_row.to_dict())
            query_run_id = id_by_key.get(key) if key else None
            if query_run_id is None:
                skipped += 1
                continue
            if obs.query_run_id == query_run_id:
                continue
            updated += 1
            if not dry_run:
                obs.query_run_id = query_run_id

        if not dry_run and updated:
            session.commit()

        print(f"run_id={run_id} updated={updated} skipped={skipped} dry_run={dry_run}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill job_observations.query_run_id")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--run-id", type=int, default=None, help="Acquisition run id")
    args = parser.parse_args()
    return run_backfill(dry_run=args.dry_run, run_id=args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
