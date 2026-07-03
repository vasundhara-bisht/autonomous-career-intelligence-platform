#!/usr/bin/env python3
"""Record OHM Phase 6 validation ladder and lifecycle re-enable sign-off."""

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

from agent.ohm_signoff import (  # noqa: E402
    approve_lifecycle_resume,
    load_ohm_signoff_state,
    record_validation_ladder_passed,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record OHM Phase 6 operator sign-off state.")
    parser.add_argument("--status", action="store_true", help="Print current sign-off JSON.")
    parser.add_argument(
        "--record-validation-ladder",
        action="store_true",
        help="Mark automated validation ladder (steps 1–4) as passed.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Record explicit operator approval to re-enable lifecycle LaunchAgent.",
    )
    parser.add_argument("--operator", default="", help="Operator name (required with --approve).")
    parser.add_argument("--notes", default="", help="Optional sign-off notes.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.record_validation_ladder:
        state = record_validation_ladder_passed(notes=args.notes)
    elif args.approve:
        if not str(args.operator or "").strip():
            print("ERROR: --operator is required with --approve", file=sys.stderr)
            return 2
        state = approve_lifecycle_resume(approved_by=args.operator, notes=args.notes)
    else:
        state = load_ohm_signoff_state()

    if args.json or args.status or not (args.record_validation_ladder or args.approve):
        print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
