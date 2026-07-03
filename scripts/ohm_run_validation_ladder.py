#!/usr/bin/env python3
"""Run OHM Phase 6 automated validation ladder (steps 1–4)."""

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

from agent.ohm_validation_ladder import run_automated_validation_ladder  # noqa: E402
from db.bootstrap import ensure_database_ready  # noqa: E402
from db.engine import get_session  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run OHM Phase 6 automated validation ladder (steps 1–4).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_database_ready()
    with get_session() as session:
        payload = run_automated_validation_ladder(session)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("=== OHM Phase 6 validation ladder (automated steps 1–4) ===")
        for step in payload["steps"]:
            status = "PASS" if step["passed"] else "FAIL"
            print(f"[{status}] {step['step']}: {step['detail']}")
        print(f"\nOverall: {'PASS' if payload['passed'] else 'FAIL'}")
        if payload["passed"]:
            print(
                "Next: complete manual apply steps 5–9, then record sign-off via "
                "scripts/ohm_record_signoff.py"
            )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
