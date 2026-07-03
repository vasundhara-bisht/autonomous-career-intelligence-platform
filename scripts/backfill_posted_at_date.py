#!/usr/bin/env python3
"""Backfill posted_at_date from time_posted using last_seen as anchor date."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.posted_date_derive import derive_posted_at_date  # noqa: E402
from db.bootstrap import ensure_database_ready  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models.schema import Job  # noqa: E402

_SAMPLE_LIMIT = 15


def _has_posted_at_date(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _anchor_from_last_seen(last_seen: object) -> date | None:
    text_val = str(last_seen or "").strip()
    if not text_val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_val[: len(fmt)], fmt).date()
        except ValueError:
            continue
    if " " in text_val:
        try:
            return datetime.strptime(text_val.split()[0], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _sql_validation(session: Session) -> dict[str, int]:
    return {
        "total_jobs": session.execute(select(func.count()).select_from(Job)).scalar_one(),
        "posted_at_date_populated": session.execute(
            text(
                "SELECT COUNT(*) FROM jobs "
                "WHERE posted_at_date IS NOT NULL AND TRIM(posted_at_date) != ''"
            )
        ).scalar_one(),
        "posted_at_date_null_or_blank": session.execute(
            text(
                "SELECT COUNT(*) FROM jobs "
                "WHERE posted_at_date IS NULL OR TRIM(posted_at_date) = ''"
            )
        ).scalar_one(),
        "age_days_null_with_posted": session.execute(
            text(
                "SELECT COUNT(*) FROM jobs "
                "WHERE posted_at_date IS NOT NULL AND TRIM(posted_at_date) != '' "
                "AND age_days IS NULL"
            )
        ).scalar_one(),
    }


def run_backfill(*, apply: bool) -> int:
    ensure_database_ready()

    with get_session() as session:
        assert isinstance(session, Session)
        rows = session.execute(
            text(
                """
                SELECT
                    j.id,
                    j.job_key_v2,
                    j.source,
                    j.time_posted,
                    j.posted_at_date,
                    o.last_seen
                FROM jobs j
                LEFT JOIN job_observation_stats_view o ON o.job_id = j.id
                ORDER BY j.id
                """
            )
        ).mappings().all()

        baseline = _sql_validation(session)
        print("=== SQL validation (current DB) ===")
        for key, value in baseline.items():
            print(f"  {key}: {value}")

        already_populated = 0
        skipped_no_anchor = 0
        skipped_unparseable = 0
        would_convert = 0
        by_source_convert: Counter[str] = Counter()
        by_source_skip: Counter[str] = Counter()
        samples: list[dict[str, object]] = []
        updates: list[dict[str, object]] = []

        for row in rows:
            source = str(row.get("source") or "unknown")
            if _has_posted_at_date(row.get("posted_at_date")):
                already_populated += 1
                continue

            anchor = _anchor_from_last_seen(row.get("last_seen"))
            if anchor is None:
                skipped_no_anchor += 1
                by_source_skip[source] += 1
                continue

            derived = derive_posted_at_date(
                {
                    "time_posted": row.get("time_posted"),
                    "posted_at_date": row.get("posted_at_date"),
                },
                anchor,
            )
            posted = derived.get("posted_at_date")
            if not posted:
                skipped_unparseable += 1
                by_source_skip[source] += 1
                continue

            would_convert += 1
            by_source_convert[source] += 1
            updates.append(
                {
                    "job_key_v2": row["job_key_v2"],
                    "posted_at_date": posted,
                    "age_days": derived.get("age_days"),
                }
            )
            if len(samples) < _SAMPLE_LIMIT:
                samples.append(
                    {
                        "job_key_v2": row["job_key_v2"],
                        "source": source,
                        "time_posted": row.get("time_posted"),
                        "anchor": anchor.isoformat(),
                        "posted_at_date": posted,
                        "age_days": derived.get("age_days"),
                    }
                )

        projected_populated = baseline["posted_at_date_populated"] + would_convert
        total = baseline["total_jobs"]
        print("\n=== Backfill summary ===")
        print(f"  mode: {'apply' if apply else 'dry-run'}")
        print(f"  total_jobs: {total}")
        print(f"  already_populated: {already_populated}")
        print(f"  would_convert: {would_convert}")
        print(f"  skipped_no_anchor: {skipped_no_anchor}")
        print(f"  skipped_unparseable: {skipped_unparseable}")
        print(f"  projected_posted_at_date_populated: {projected_populated}")
        if total:
            pct = 100.0 * projected_populated / total
            print(f"  projected_coverage_pct: {pct:.1f}%")

        print("\n=== Would convert by source ===")
        for source, count in sorted(by_source_convert.items()):
            print(f"  {source}: {count}")

        print("\n=== Skipped by source (no anchor or unparseable) ===")
        for source, count in sorted(by_source_skip.items()):
            print(f"  {source}: {count}")

        print(f"\n=== Sample conversions (up to {_SAMPLE_LIMIT}) ===")
        for sample in samples:
            print(
                f"  {sample['job_key_v2'][:12]}… "
                f"src={sample['source']} "
                f"time_posted={sample['time_posted']!r} "
                f"anchor={sample['anchor']} "
                f"-> posted_at_date={sample['posted_at_date']} "
                f"age_days={sample['age_days']}"
            )

        if apply:
            applied = 0
            for payload in updates:
                result = session.execute(
                    update(Job)
                    .where(
                        Job.job_key_v2 == payload["job_key_v2"],
                        (Job.posted_at_date.is_(None)) | (func.trim(Job.posted_at_date) == ""),
                    )
                    .values(
                        posted_at_date=payload["posted_at_date"],
                        age_days=payload["age_days"],
                    )
                )
                applied += result.rowcount or 0
            session.commit()
            post = _sql_validation(session)
            print("\n=== Post-apply SQL validation ===")
            for key, value in post.items():
                print(f"  {key}: {value}")
            print(f"  rows_updated: {applied}")
        else:
            print("\n(dry-run: no database writes)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill posted_at_date from time_posted (default: dry-run)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updates to SQLite (default is dry-run only)",
    )
    args = parser.parse_args()
    return run_backfill(apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
