#!/usr/bin/env python3
"""Initialize SQLite product memory DB and apply Alembic migrations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from db.bootstrap import ensure_database_ready, print_database_status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the SQLite DB file and migrate schema to head."
    )
    parser.add_argument(
        "--revision",
        default="head",
        help="Alembic revision target (default: head)",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Print DB/schema status without running migrations",
    )
    args = parser.parse_args()

    if args.status_only:
        print_database_status()
        return 0

    db_path = ensure_database_ready(revision=args.revision)
    print(f"Database ready: {db_path}")
    print_database_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
