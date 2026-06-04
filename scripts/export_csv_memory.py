#!/usr/bin/env python3
"""Export SQLite product memory to CSV/JSON (inverse of import_csv_memory.py, D7)."""

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export SQLite product memory to CSV/JSON files."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for exports (default: data/ paths from paths.py)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print targets only")
    parser.add_argument("--historical", action="store_true", help="Export historical_jobs.csv")
    parser.add_argument("--jobs", action="store_true", help="Export jobs.csv from current_jobs_view")
    parser.add_argument("--descriptions", action="store_true", help="Export job_descriptions.csv")
    parser.add_argument("--crm", action="store_true", help="Export recruiter_crm.csv")
    parser.add_argument(
        "--query-state",
        action="store_true",
        help="Export .linkedin_query_state.json mirror",
    )
    parser.add_argument("--all", action="store_true", help="Export all supported artifacts")
    args = parser.parse_args()

    if not os.environ.get("SQLITE_ENABLED", "").strip():
        os.environ["SQLITE_ENABLED"] = "1"

    export_historical = args.all or args.historical
    export_jobs = args.all or args.jobs
    export_descriptions = args.all or args.descriptions
    export_crm = args.all or args.crm
    export_query_state = args.all or args.query_state

    if not any(
        (export_historical, export_jobs, export_descriptions, export_crm, export_query_state)
    ):
        parser.error(
            "Specify --all or one of --historical, --jobs, --descriptions, --crm, --query-state"
        )

    from db.write.csv_export import export_csv_memory

    if args.dry_run:
        import paths

        def _show(flag: bool, path_fn) -> None:
            if flag:
                dest = (
                    args.output_dir / path_fn().name
                    if args.output_dir
                    else path_fn()
                )
                print(f"  would export -> {dest}")

        print("Export dry-run (SQLITE_ENABLED=1):")
        _show(export_historical, paths.historical_jobs_csv)
        _show(export_jobs, paths.jobs_csv)
        _show(export_descriptions, paths.job_descriptions_csv)
        _show(export_crm, paths.recruiter_crm_csv)
        _show(export_query_state, paths.linkedin_query_state_json)
        return 0

    counts = export_csv_memory(
        output_dir=args.output_dir,
        export_historical=export_historical,
        export_jobs=export_jobs,
        export_descriptions=export_descriptions,
        export_crm=export_crm,
        export_query_state=export_query_state,
    )
    print(f"Export complete: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
