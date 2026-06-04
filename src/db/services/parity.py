"""Helpers for runtime CSV/SQLite dual-write parity summaries."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

import paths


def _read_csv(path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def csv_runtime_counts() -> dict[str, int]:
    historical = _read_csv(paths.historical_jobs_csv())
    jobs = _read_csv(paths.jobs_csv())
    descriptions = _read_csv(paths.job_descriptions_csv())
    recruiters = _read_csv(paths.recruiter_crm_csv())
    job_state = _read_csv(paths.job_state_csv())
    return {
        "historical_jobs": len(historical),
        "jobs_csv": len(jobs),
        "job_descriptions": len(descriptions),
        "recruiter_crm": len(recruiters),
        "job_state": len(job_state),
    }


def csv_ai_status_dist() -> dict[str, int]:
    historical = _read_csv(paths.historical_jobs_csv())
    if historical.empty or "ai_status" not in historical.columns:
        return {"scored": 0, "skipped_by_cap": 0, "pending": 0}
    dist: Counter[str] = Counter()
    for value in historical["ai_status"].tolist():
        status = str(value).strip().lower() or "pending"
        dist[status] += 1
    return {
        "scored": dist.get("scored", 0),
        "skipped_by_cap": dist.get("skipped_by_cap", 0),
        "pending": dist.get("pending", 0),
    }


def log_dual_write_summary(report: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("🗄️ SQLITE DUAL-WRITE SUMMARY (Phase C)")
    print("=" * 60)
    print(f"enabled={int(bool(report.get('enabled')))}")
    print(f"success={int(bool(report.get('success')))}")
    if report.get("run_id") is not None:
        print(f"acquisition_run_id={report.get('run_id')}")
    if report.get("error"):
        print(f"error={report.get('error')}")

    csv_counts = report.get("csv_counts") or {}
    if csv_counts:
        print("\nCSV counts:")
        for k, v in csv_counts.items():
            print(f"  {k}: {v}")

    write_counts = report.get("db_write_counts") or {}
    if write_counts:
        print("\nSQLite write counts:")
        for k, v in write_counts.items():
            print(f"  {k}: {v}")

    table_counts = report.get("db_table_counts") or {}
    if table_counts:
        print("\nSQLite table counts:")
        for k, v in table_counts.items():
            print(f"  {k}: {v}")

    ai_dist = report.get("ai_status_db_write_dist") or {}
    if ai_dist:
        print(
            "\nai_status (DB write dist): "
            + ", ".join(
                f"{k}={ai_dist.get(k, 0)}"
                for k in ("scored", "skipped_by_cap", "pending")
            )
        )

    cohort = report.get("persistence_cohort_count")
    if cohort is not None:
        print(f"persistence_cohort_count: {cohort}")
    print("=" * 60)

