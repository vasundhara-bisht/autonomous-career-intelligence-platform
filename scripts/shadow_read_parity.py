#!/usr/bin/env python3
"""D0 shadow parity: compare CSV product memory vs SQLite read views."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from db.bootstrap import ensure_database_ready
from db.read.export_cohort import (
    load_current_jobs_view_df,
    load_export_cohort_keys,
    load_latest_run_info,
)
from db.read.historical import load_historical_jobs_view_df
from db.read.shadow import ShadowReport, compare_historical_csv_to_view, compare_jobs_csv_to_view
from db.read.views import assert_read_views_present
from db.services.parity_checks import read_csv


def _print_report(report: ShadowReport) -> None:
    print(f"\n{report.name}: {'PASS' if report.ok() else 'FAIL'}")
    for key, value in sorted(report.stats.items()):
        print(f"  {key}: {value}")
    if report.failures:
        print("  failures:")
        for item in report.failures:
            print(f"    - {item}")
    if report.warnings:
        print("  warnings:")
        for item in report.warnings:
            print(f"    - {item}")


def run_shadow(*, fail_on_error: bool = False) -> int:
    if not os.environ.get("SQLITE_ENABLED", "").strip():
        print(
            "Note: SQLITE_ENABLED is not set; enabling for this shadow run only "
            "(no pipeline behavior change)."
        )
        os.environ["SQLITE_ENABLED"] = "1"

    ensure_database_ready()
    from db.read.engine import get_read_session

    jobs_csv = read_csv(paths.jobs_csv())
    historical_csv = read_csv(paths.historical_jobs_csv())

    with get_read_session() as session:
        assert_read_views_present(session)
        run_info = load_latest_run_info(session)
        cohort_keys = load_export_cohort_keys(session)
        current_view = load_current_jobs_view_df(session, apply_transforms=True)
        historical_view = load_historical_jobs_view_df(session)

    print("SQLite shadow read parity (D0)")
    if run_info:
        print(
            f"  latest_acquisition_run: id={run_info.get('run_id')} "
            f"notes={run_info.get('notes')!r}"
        )
    else:
        print("  latest_acquisition_run: (none)")

    print(f"  export_cohort_keys: {len(cohort_keys)}")
    print(f"  jobs.csv rows: {len(jobs_csv)}")
    print(f"  current_jobs_view rows (transformed): {len(current_view)}")
    print(f"  historical_jobs.csv rows: {len(historical_csv)}")
    print(f"  historical_jobs_view rows: {len(historical_view)}")

    if len(jobs_csv) and not cohort_keys:
        print(
            "\nWARN: jobs.csv has rows but export cohort is empty. "
            "Run main.py with SQLITE_DUAL_WRITE=1 before export shadow compare."
        )

    jobs_report = compare_jobs_csv_to_view(jobs_csv, current_view, cohort_keys=cohort_keys)
    hist_report = compare_historical_csv_to_view(historical_csv, historical_view)

    _print_report(jobs_report)
    _print_report(hist_report)

    overall_ok = jobs_report.ok() and hist_report.ok()
    print(f"\nOVERALL: {'PASS' if overall_ok else 'FAIL'}")
    if fail_on_error and not overall_ok:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="D0 CSV vs SQLite read-view shadow parity.")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit 1 when strict shadow checks fail (warnings do not fail).",
    )
    args = parser.parse_args()
    return run_shadow(fail_on_error=args.fail_on_error)


if __name__ == "__main__":
    raise SystemExit(main())
