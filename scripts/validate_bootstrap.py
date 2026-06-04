#!/usr/bin/env python3
"""
Post-bootstrap validation after a clean reset + first main.py run.
Read-only on historical data semantics; only reads CSVs and optional log file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.bootstrap_schema import derive_all_reset_schemas
from agent.historical_persistence import historical_jobs_schema_columns as persistence_hist_cols


def _fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)
    print(f"FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def validate(
    repo_root: Path,
    *,
    min_v2_fill_rate: float,
    min_historical_rows: int,
    log_path: Path | None,
) -> int:
    errors: list[str] = []
    import paths

    paths.ensure_data_dir()
    hist_path = paths.historical_jobs_csv()
    jobs_path = paths.jobs_csv()

    if not hist_path.is_file():
        _fail(f"missing {hist_path}", errors)
    else:
        try:
            hist = pd.read_csv(hist_path)
            n = len(hist)
            if n < min_historical_rows:
                _fail(
                    f"historical_jobs row count {n} < {min_historical_rows}",
                    errors,
                )
            else:
                _ok(f"historical_jobs rows={n}")

            if "JOB_KEY_V2" not in hist.columns:
                _fail("historical_jobs missing JOB_KEY_V2 column", errors)
            else:
                filled = (hist["JOB_KEY_V2"].fillna("").astype(str).str.strip() != "").sum()
                rate = (filled / n) if n else 0.0
                if rate < min_v2_fill_rate:
                    _fail(
                        f"JOB_KEY_V2 fill rate {rate:.1%} < {min_v2_fill_rate:.1%}",
                        errors,
                    )
                else:
                    _ok(f"JOB_KEY_V2 fill rate={rate:.1%}")

            if "JOB_KEY" in hist.columns and hist["JOB_KEY"].duplicated().any():
                dup = int(hist["JOB_KEY"].duplicated().sum())
                _fail(f"duplicate JOB_KEY count={dup}", errors)
            else:
                _ok("JOB_KEY unique")

            if "JOB_KEY_V2" in hist.columns:
                v2s = hist["JOB_KEY_V2"].fillna("").astype(str).str.strip()
                nonempty = hist[v2s != ""]
                if len(nonempty) and nonempty["JOB_KEY_V2"].duplicated().any():
                    dup_v2 = int(nonempty["JOB_KEY_V2"].duplicated().sum())
                    _fail(f"duplicate JOB_KEY_V2 count={dup_v2}", errors)
                else:
                    _ok("JOB_KEY_V2 unique (non-empty)")

            expected = set(persistence_hist_cols())
            actual = set(hist.columns)
            if not expected.issubset(actual):
                missing = sorted(expected - actual)
                _fail(f"historical missing persistence columns: {missing}", errors)
            else:
                _ok("historical header includes persistence schema columns")

        except Exception as e:
            _fail(f"historical_jobs read error: {e}", errors)

    desc_path = paths.job_descriptions_csv()
    if desc_path.is_file():
        try:
            desc = pd.read_csv(desc_path)
            dn = len(desc)
            if "JOB_KEY_V2" in desc.columns:
                dfilled = (
                    desc["JOB_KEY_V2"].fillna("").astype(str).str.strip() != ""
                ).sum()
                rate = (dfilled / dn) if dn else 0.0
                if rate < min_v2_fill_rate:
                    _fail(
                        f"job_descriptions JOB_KEY_V2 fill rate {rate:.1%} < {min_v2_fill_rate:.1%}",
                        errors,
                    )
                else:
                    _ok(f"job_descriptions JOB_KEY_V2 fill rate={rate:.1%}")
            else:
                _fail("job_descriptions missing JOB_KEY_V2 column", errors)
        except Exception as e:
            _fail(f"job_descriptions read error: {e}", errors)
    else:
        _fail(f"missing {desc_path}", errors)

    if not jobs_path.is_file():
        _fail(f"missing {jobs_path}", errors)
    else:
        try:
            jobs = pd.read_csv(jobs_path, nrows=0)
            if "JOB_KEY_V2" not in jobs.columns:
                _fail("jobs.csv missing JOB_KEY_V2 column (run pipeline after Phase 5)", errors)
            else:
                _ok("jobs.csv has JOB_KEY_V2 column")
        except Exception as e:
            _fail(f"jobs.csv read error: {e}", errors)

    schemas = derive_all_reset_schemas()
    print("\nDerived schemas (audit):")
    for key, val in schemas.items():
        if key == "linkedin_query_state":
            print(f"  {key}: {val}")
        else:
            print(f"  {key}: {len(val)} columns")

    if log_path and log_path.is_file():
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if "final_merge_authority=v2_only" in text:
            _ok("log contains final_merge_authority=v2_only")
        else:
            _fail("log missing final_merge_authority=v2_only", errors)
    elif log_path:
        _fail(f"log file not found: {log_path}", errors)

    print()
    if errors:
        print(f"Validation FAILED ({len(errors)} issue(s))")
        return 1
    print("Validation PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate post-reset bootstrap state")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--min-v2-fill-rate",
        type=float,
        default=0.95,
        help="Minimum fraction of historical rows with non-empty JOB_KEY_V2",
    )
    parser.add_argument(
        "--min-historical-rows",
        type=int,
        default=1,
        help="Minimum historical_jobs row count after bootstrap run",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Optional main.py log file to grep for V2 merge authority",
    )
    args = parser.parse_args()
    return validate(
        args.repo_root.resolve(),
        min_v2_fill_rate=args.min_v2_fill_rate,
        min_historical_rows=args.min_historical_rows,
        log_path=args.log,
    )


if __name__ == "__main__":
    raise SystemExit(main())
