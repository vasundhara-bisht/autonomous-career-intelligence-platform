#!/usr/bin/env python3
"""
One-time identity alignment for job_descriptions.csv (V2-primary index).

Default: dry-run report only. Use --apply to write changes.
Run ./scripts/archive_state.sh before --apply.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
for entry in (str(_REPO), str(_REPO / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from agent.historical_persistence import generate_job_key
from agent.job_identity import generate_job_key_v2


def _job_dict_from_row(row: pd.Series) -> dict:
    return {
        "title": str(row.get("title", "") or ""),
        "company": str(row.get("company", "") or ""),
        "link": str(row.get("link", "") or ""),
        "source": str(row.get("source", "") or ""),
        "normalized_title": str(row.get("title", "") or "").strip().lower(),
        "normalized_company": str(row.get("company", "") or "").strip().lower(),
    }


def migrate_descriptions(*, apply: bool) -> int:
    desc_path = paths.job_descriptions_csv()
    hist_path = paths.historical_jobs_csv()

    if not desc_path.is_file():
        print(f"Missing {desc_path}")
        return 1

    desc = pd.read_csv(str(desc_path), dtype=str, keep_default_na=False)
    hist_links: dict[str, dict] = {}
    if hist_path.is_file():
        hist = pd.read_csv(str(hist_path), dtype=str, keep_default_na=False)
        for _, row in hist.iterrows():
            v2 = str(row.get("JOB_KEY_V2", "") or "").strip()
            if v2:
                hist_links[v2] = row.to_dict()

    by_v2: dict[str, dict] = {}
    collisions = 0
    backfilled_v2 = 0

    for _, row in desc.iterrows():
        legacy = str(row.get("JOB_KEY", "") or "").strip()
        if not legacy:
            continue
        v2 = str(row.get("JOB_KEY_V2", "") or "").strip()
        if not v2:
            for hv2, hrow in hist_links.items():
                if str(hrow.get("JOB_KEY", "")).strip() == legacy:
                    v2 = hv2
                    break
            if not v2:
                parts = legacy.split("::", 1)
                nt = parts[0] if parts else legacy
                nc = parts[1] if len(parts) > 1 else ""
                job = {
                    "title": nt,
                    "company": nc,
                    "link": "",
                    "source": str(row.get("source", "") or ""),
                    "normalized_title": nt,
                    "normalized_company": nc,
                }
                v2, _ = generate_job_key_v2(job)
                v2 = str(v2 or "").strip()
            if v2:
                backfilled_v2 += 1

        rec = {
            "JOB_KEY": legacy,
            "JOB_KEY_V2": v2,
            "description": str(row.get("description", "")),
            "last_updated": str(row.get("last_updated", "")),
            "source": str(row.get("source", "") or ""),
        }
        if v2:
            if v2 in by_v2 and by_v2[v2]["last_updated"] >= rec["last_updated"]:
                collisions += 1
                continue
            by_v2[v2] = rec
        else:
            pseudo = f"legacy-only:{legacy}"
            by_v2[pseudo] = rec

    print(f"Description rows read: {len(desc)}")
    print(f"V2 keys after merge: {len(by_v2)}")
    print(f"V2 backfilled from historical/link: {backfilled_v2}")
    print(f"Skipped duplicate V2 (older): {collisions}")

    if not apply:
        print("\nDry run only. Re-run with --apply to write job_descriptions.csv")
        return 0

    rows = list(by_v2.values())
    out = pd.DataFrame(
        rows,
        columns=["JOB_KEY", "JOB_KEY_V2", "description", "last_updated", "source"],
    )
    out.to_csv(str(desc_path), index=False)
    print(f"\nWrote {len(out)} rows to {desc_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write migrated job_descriptions.csv (default: dry-run)",
    )
    args = parser.parse_args()
    return migrate_descriptions(apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
