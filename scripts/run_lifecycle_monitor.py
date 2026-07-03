#!/usr/bin/env python3
"""Scheduler B lifecycle monitor CLI (T1C)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from db.bootstrap import ensure_database_ready  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.services.lifecycle_monitor import (  # noqa: E402
    debug_enabled,
    default_apply_limit,
    run_lifecycle_monitor,
)
from monitor.classifiers.linkedin_diagnostics import linkedin_classifier_debug_enabled  # noqa: E402


def _configure_logging() -> None:
    level = logging.INFO if (debug_enabled() or linkedin_classifier_debug_enabled()) else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scheduler B lifecycle monitor — dry-run cohort preview by default.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Classify cohort jobs with Playwright and persist listing_status updates.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum cohort jobs to process (e.g. 10, 50, 100).",
    )
    parser.add_argument(
        "--job-key-v2",
        dest="job_key_v2",
        default=None,
        help="Restrict to a single job_key_v2.",
    )
    parser.add_argument(
        "--source",
        choices=["linkedin", "instahyre"],
        default=None,
        help="Restrict cohort to a single source.",
    )
    parser.add_argument(
        "--cohort-file",
        dest="cohort_file",
        default=None,
        help="Newline-delimited job_key_v2 list for targeted validation cohorts.",
    )
    parser.add_argument(
        "--skip-parity",
        action="store_true",
        help="Skip TD9 post-apply parity checks (apply mode only).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = build_parser().parse_args(argv)

    ensure_database_ready()

    limit = args.limit
    if limit is None and args.apply:
        limit = default_apply_limit()

    try:
        run_lifecycle_monitor(
            get_session,
            apply=args.apply,
            limit=limit,
            job_key_v2=args.job_key_v2,
            source=args.source,
            cohort_file=args.cohort_file,
            run_parity_checks=args.apply and not args.skip_parity,
        )
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
