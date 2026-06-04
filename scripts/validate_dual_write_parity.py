#!/usr/bin/env python3
"""Deprecated: use validate_sqlite_parity.py --mode production for daily validation."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


def _load_sqlite_parity_module():
    spec = importlib.util.spec_from_file_location(
        "validate_sqlite_parity",
        _SCRIPT_DIR / "validate_sqlite_parity.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("validate_sqlite_parity.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    print(
        "DEPRECATED: validate_dual_write_parity.py — use "
        "validate_sqlite_parity.py --mode production for daily D8B validation, "
        "or --mode csv-mirror-sync for legacy strict CSV mirror checks.",
        file=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="Deprecated legacy CSV-mirror-sync parity (delegates to validate_sqlite_parity).",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit 1 when strict checks fail (warnings do not fail).",
    )
    args = parser.parse_args()
    parity = _load_sqlite_parity_module()
    return parity.run_csv_mirror_sync_mode(fail_on_error=args.fail_on_error)


if __name__ == "__main__":
    raise SystemExit(main())
