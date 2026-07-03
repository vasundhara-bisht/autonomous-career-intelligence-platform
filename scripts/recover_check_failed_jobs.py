#!/usr/bin/env python3
"""Reset incident-misclassified check_failed jobs (OHM Phase 6).

Dry-run by default. Only resets provider/auth/dom misclassifications (auth:/dom:/protection:).
Infrastructure check_failed rows (fetch:/timeout:/etc.) are preserved.
"""

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
from db.services.check_failed_recovery import (  # noqa: E402
    fetch_recovery_sample,
    reset_incident_check_failed_jobs,
    summarize_recovery_candidates,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset incident-misclassified LinkedIn check_failed jobs to open (dry-run default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist resets (default is dry-run preview only).",
    )
    parser.add_argument(
        "--source",
        choices=["linkedin", "instahyre"],
        default="linkedin",
        help="Job source filter (default: linkedin).",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Number of sample rows to print in dry-run output.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_database_ready()
    dry_run = not args.apply

    with get_session() as session:
        summary = summarize_recovery_candidates(session, source=args.source)
        sample = fetch_recovery_sample(session, source=args.source, limit=max(args.sample, 0))
        result = reset_incident_check_failed_jobs(
            session,
            source=args.source,
            dry_run=dry_run,
        )
        if not dry_run:
            session.commit()

    payload = {
        "dry_run": dry_run,
        "source": args.source,
        "summary": summary,
        "result": {
            "matched": result.matched,
            "reset": result.reset,
            "skipped_non_incident": result.skipped,
        },
        "sample": sample,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"=== check_failed recovery ({mode}) ===")
    print(f"source={args.source}")
    print(f"candidates={summary['total_candidates']} (paused={summary['paused_candidates']})")
    print(f"by_reason_group={summary['by_reason_group']}")
    print(f"matched={result.matched} reset={result.reset} skipped_non_incident={result.skipped}")
    if sample:
        print("\nSample rows:")
        for row in sample:
            print(
                f"  id={row['id']} key={row['job_key_v2']} "
                f"reason={row['listing_status_reason']}"
            )
    if dry_run:
        print("\nNo changes written. Re-run with --apply to reset matched jobs to open.")
    else:
        print("\nReset complete. Matched jobs are now listing_status=open for recheck.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
