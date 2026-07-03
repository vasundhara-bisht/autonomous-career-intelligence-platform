#!/usr/bin/env python3
"""One-time backfill: re-extract LinkedIn time_posted via Playwright and derive posted_at_date."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths  # noqa: E402
from agent.posted_date_derive import derive_posted_at_date  # noqa: E402
from db.bootstrap import ensure_database_ready  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models.schema import AcquisitionRun, Job, JobObservation  # noqa: E402
from scraper.linkedin import _li_extract_time_posted_from_page  # noqa: E402

_COHORT_SQL = """
SELECT j.id, j.job_key_v2, j.title, j.link, j.time_posted, j.posted_at_date
FROM jobs j
WHERE j.source = 'linkedin'
  AND j.time_posted = 'Unknown'
  AND (j.posted_at_date IS NULL OR TRIM(j.posted_at_date) = '')
  AND j.link IS NOT NULL AND TRIM(j.link) != ''
ORDER BY j.updated_at DESC
"""

_SAMPLE_LIMIT = 15
_JOB_DELAY_SEC = 2.0
_GOTO_TIMEOUT_MS = 45_000
_POST_CLICK_WAIT_MS = 2000


def _has_posted_at_date(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def fetch_cohort(
    session: Session,
    *,
    limit: int | None = None,
    job_key_v2: str | None = None,
) -> list[dict[str, Any]]:
    sql = _COHORT_SQL
    params: dict[str, Any] = {}
    if job_key_v2:
        sql = sql.replace("ORDER BY", "AND j.job_key_v2 = :job_key_v2 ORDER BY")
        params["job_key_v2"] = job_key_v2
    if limit is not None:
        sql = f"{sql}\nLIMIT :limit"
        params["limit"] = limit
    return list(session.execute(text(sql), params).mappings().all())


def _sql_validation(session: Session) -> dict[str, int]:
    return {
        "linkedin_affected_cohort": session.execute(
            text(
                "SELECT COUNT(*) FROM jobs "
                "WHERE source='linkedin' AND time_posted='Unknown' "
                "AND (posted_at_date IS NULL OR TRIM(posted_at_date)='')"
            )
        ).scalar_one(),
        "linkedin_posted_at_date_populated": session.execute(
            text(
                "SELECT COUNT(*) FROM jobs "
                "WHERE source='linkedin' AND posted_at_date IS NOT NULL "
                "AND TRIM(posted_at_date) != ''"
            )
        ).scalar_one(),
        "job_observations": session.execute(
            select(func.count()).select_from(JobObservation)
        ).scalar_one(),
        "acquisition_runs": session.execute(
            select(func.count()).select_from(AcquisitionRun)
        ).scalar_one(),
    }


def derive_update_payload(
    time_posted: str,
    *,
    anchor_date: date,
) -> dict[str, Any] | None:
    if time_posted == "Unknown":
        return None
    derived = derive_posted_at_date(
        {"time_posted": time_posted, "posted_at_date": None},
        anchor_date,
    )
    posted = derived.get("posted_at_date")
    if not posted:
        return None
    return {
        "time_posted": time_posted,
        "posted_at_date": posted,
        "age_days": derived.get("age_days"),
    }


def apply_job_update(
    session: Session,
    *,
    job_key_v2: str,
    payload: dict[str, Any],
    updated_at: datetime,
) -> int:
    result = session.execute(
        update(Job)
        .where(
            Job.job_key_v2 == job_key_v2,
            (Job.posted_at_date.is_(None)) | (func.trim(Job.posted_at_date) == ""),
        )
        .values(
            time_posted=payload["time_posted"],
            posted_at_date=payload["posted_at_date"],
            age_days=payload["age_days"],
            updated_at=updated_at,
        )
    )
    return result.rowcount or 0


def write_manifest(rows: list[dict[str, Any]], *, manifest_path: Path) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(rows, indent=2, default=str),
        encoding="utf-8",
    )
    return manifest_path


def _visit_jobs_with_playwright(
    cohort: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    auth_path = paths.linkedin_auth_json()
    if not auth_path.is_file():
        raise FileNotFoundError(
            f"Missing LinkedIn session at {auth_path}. "
            "Run save_linkedin_session() from scraper/linkedin.py first."
        )

    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, channel="chrome")
        try:
            context = browser.new_context(storage_state=str(auth_path))
            page = context.new_page()
            for idx, row in enumerate(cohort):
                link = str(row["link"]).strip()
                print(f"  [{idx + 1}/{len(cohort)}] {row['job_key_v2'][:12]}… {link[:80]}")
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
                    page.wait_for_timeout(_POST_CLICK_WAIT_MS)
                    time_posted = _li_extract_time_posted_from_page(page)
                except Exception as exc:
                    print(f"    extraction_error: {exc!r}")
                    time_posted = "Unknown"
                results.append({**dict(row), "extracted_time_posted": time_posted})
                if idx + 1 < len(cohort):
                    time.sleep(_JOB_DELAY_SEC)
        finally:
            browser.close()
    return results


def run_backfill(
    *,
    apply: bool,
    limit: int | None = None,
    job_key_v2: str | None = None,
) -> int:
    ensure_database_ready()
    anchor_today = datetime.now(UTC).date()
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    with get_session() as session:
        assert isinstance(session, Session)
        baseline = _sql_validation(session)
        print("=== SQL validation (current DB) ===")
        for key, value in baseline.items():
            print(f"  {key}: {value}")

        cohort = fetch_cohort(session, limit=limit, job_key_v2=job_key_v2)
        print(f"\n=== Cohort: {len(cohort)} job(s) ===")
        if not cohort:
            print("(nothing to process)")
            return 0

        if apply:
            backup_dir = paths.ensure_data_dir() / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            print(
                "\n=== Operator reminder ===\n"
                f"  Copy DB to {backup_dir}/ai_job_agent-{stamp}.db before continuing.\n"
                f"  Example: cp {paths.ensure_data_dir() / 'ai_job_agent.db'} "
                f"{backup_dir}/ai_job_agent-{stamp}.db"
            )
            manifest_path = backup_dir / f"linkedin_posted_backfill_manifest-{stamp}.json"
            write_manifest(
                [
                    {
                        "job_key_v2": row["job_key_v2"],
                        "time_posted": row.get("time_posted"),
                        "posted_at_date": row.get("posted_at_date"),
                        "age_days": None,
                    }
                    for row in cohort
                ],
                manifest_path=manifest_path,
            )
            print(f"  Pre-update manifest written: {manifest_path}")

        print("\n=== Playwright extraction ===")
        extracted = _visit_jobs_with_playwright(cohort)

        skipped_extraction_failed = 0
        skipped_derive_failed = 0
        would_update = 0
        updates: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []

        for row in extracted:
            payload = derive_update_payload(
                str(row.get("extracted_time_posted") or "Unknown"),
                anchor_date=anchor_today,
            )
            if row.get("extracted_time_posted") == "Unknown":
                skipped_extraction_failed += 1
                continue
            if payload is None:
                skipped_derive_failed += 1
                continue
            would_update += 1
            updates.append({"job_key_v2": row["job_key_v2"], **payload})
            if len(samples) < _SAMPLE_LIMIT:
                samples.append(
                    {
                        "job_key_v2": row["job_key_v2"],
                        "title": row.get("title"),
                        "time_posted": payload["time_posted"],
                        "posted_at_date": payload["posted_at_date"],
                        "age_days": payload["age_days"],
                    }
                )

        print("\n=== Backfill summary ===")
        print(f"  mode: {'apply' if apply else 'dry-run'}")
        print(f"  anchor_date: {anchor_today.isoformat()}")
        print(f"  cohort_size: {len(cohort)}")
        print(f"  would_update: {would_update}")
        print(f"  skipped_extraction_failed: {skipped_extraction_failed}")
        print(f"  skipped_derive_failed: {skipped_derive_failed}")

        print(f"\n=== Sample conversions (up to {_SAMPLE_LIMIT}) ===")
        for sample in samples:
            print(
                f"  {sample['job_key_v2'][:12]}… "
                f"time_posted={sample['time_posted']!r} "
                f"-> posted_at_date={sample['posted_at_date']} "
                f"age_days={sample['age_days']}"
            )

        if apply:
            applied = 0
            for payload in updates:
                applied += apply_job_update(
                    session,
                    job_key_v2=payload["job_key_v2"],
                    payload=payload,
                    updated_at=now_utc,
                )
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
        description=(
            "Re-extract LinkedIn time_posted for affected jobs and derive posted_at_date "
            "(default: dry-run)"
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updates to SQLite (default is dry-run only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process first N cohort rows only",
    )
    parser.add_argument(
        "--job-key-v2",
        dest="job_key_v2",
        default=None,
        help="Single-job repair by job_key_v2",
    )
    args = parser.parse_args()
    return run_backfill(
        apply=args.apply,
        limit=args.limit,
        job_key_v2=args.job_key_v2,
    )


if __name__ == "__main__":
    raise SystemExit(main())
