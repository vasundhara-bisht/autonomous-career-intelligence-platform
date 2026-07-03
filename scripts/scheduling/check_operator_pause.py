#!/usr/bin/env python3
"""Exit non-zero when an operator soft-pause flag is set (OHM Phase 5)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.operator_scheduler import is_scheduler_paused  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe operator soft-pause flags before scheduled runs.",
    )
    parser.add_argument(
        "--scheduler",
        required=True,
        choices=["acquisition", "lifecycle"],
    )
    parser.add_argument(
        "--skip-message",
        default="",
        help="Printed to stdout when the scheduler is paused.",
    )
    args = parser.parse_args(argv)

    if not is_scheduler_paused(args.scheduler):
        return 0

    if args.skip_message:
        print(args.skip_message, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
