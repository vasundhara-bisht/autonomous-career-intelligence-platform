#!/usr/bin/env python3
"""TD9 listing lifecycle parity validation — warning-only, always exit 0."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from db.bootstrap import ensure_database_ready  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.services.parity_checks import check_listing_lifecycle_parity  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TD9 listing lifecycle parity checks (warning-only).",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Optional lifecycle_monitor_runs.id for cohort completeness checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit warnings as JSON on stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_database_ready()

    with get_session() as session:
        report = check_listing_lifecycle_parity(session, run_id=args.run_id)

    if args.json:
        print(
            json.dumps(
                {
                    "parity_warnings": report.warning_count,
                    "warnings": report.warnings,
                    "parity_warning_summary": report.summary_text(),
                },
                indent=2,
            )
        )
    else:
        print("=== LIFECYCLE MONITOR PARITY (TD9) ===")
        print(f"parity_warnings={report.warning_count}")
        print(f"parity_warning_summary={report.summary_text()}")
        for warning in report.warnings:
            print(f"  WARNING: {warning}")

    # TD9: never fail Scheduler B wrapper on parity findings.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
