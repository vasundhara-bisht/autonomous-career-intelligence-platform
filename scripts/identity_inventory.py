#!/usr/bin/env python3
"""Read-only V2 vs legacy identity inventory for data/ CSVs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

import paths


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as e:
        print(f"FAIL read {path}: {e}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Identity inventory (read-only)")
    parser.parse_args()

    hist_path = paths.historical_jobs_csv()
    desc_path = paths.job_descriptions_csv()
    jobs_path = paths.jobs_csv()

    print("Identity inventory (read-only)")
    print(f"  data dir: {paths.DATA_DIR}\n")

    hist = _read_csv(hist_path)
    if hist is not None:
        n = len(hist)
        v2_col = "JOB_KEY_V2" if "JOB_KEY_V2" in hist.columns else None
        v2_filled = 0
        if v2_col:
            v2_filled = (hist[v2_col].fillna("").astype(str).str.strip() != "").sum()
        dup_legacy = int(hist["JOB_KEY"].duplicated().sum()) if "JOB_KEY" in hist.columns else 0
        dup_v2 = int(hist[v2_col].duplicated().sum()) if v2_col and v2_filled else 0
        print(f"historical_jobs.csv: rows={n}")
        print(f"  JOB_KEY_V2 filled: {v2_filled}/{n} ({(v2_filled/n*100 if n else 0):.1f}%)")
        print(f"  duplicate JOB_KEY rows: {dup_legacy}")
        if v2_col:
            print(f"  duplicate JOB_KEY_V2 (non-empty): {dup_v2}")
    else:
        print("historical_jobs.csv: missing")

    desc = _read_csv(desc_path)
    hist_v2_set: set[str] = set()
    if hist is not None and "JOB_KEY_V2" in hist.columns:
        hist_v2_set = set(
            hist["JOB_KEY_V2"].fillna("").astype(str).str.strip().unique()
        ) - {""}

    if desc is not None:
        n = len(desc)
        v2_filled = 0
        if "JOB_KEY_V2" in desc.columns:
            v2_filled = (desc["JOB_KEY_V2"].fillna("").astype(str).str.strip() != "").sum()
        orphans = 0
        if "JOB_KEY_V2" in desc.columns and hist_v2_set:
            for v2 in desc["JOB_KEY_V2"].fillna("").astype(str).str.strip():
                if v2 and v2 not in hist_v2_set:
                    orphans += 1
        print(f"\njob_descriptions.csv: rows={n}")
        print(f"  JOB_KEY_V2 filled: {v2_filled}/{n}")
        print(f"  description rows with V2 not in historical: {orphans}")
    else:
        print("\njob_descriptions.csv: missing")

    jobs = _read_csv(jobs_path)
    if jobs is not None:
        n = len(jobs)
        has_v2 = "JOB_KEY_V2" in jobs.columns
        v2_filled = (
            (jobs["JOB_KEY_V2"].fillna("").astype(str).str.strip() != "").sum()
            if has_v2
            else 0
        )
        print(f"\njobs.csv: rows={n}")
        print(f"  has JOB_KEY_V2 column: {has_v2}")
        if has_v2:
            print(f"  JOB_KEY_V2 filled: {v2_filled}/{n}")
    else:
        print("\njobs.csv: missing")

    print("\nInventory complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
