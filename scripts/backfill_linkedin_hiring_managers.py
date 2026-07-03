#!/usr/bin/env python3
"""One-time backfill: re-extract LinkedIn hiring_manager and apply via recoverable manifest."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, or_, select, text, update
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths  # noqa: E402
from db.bootstrap import ensure_database_ready  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models.schema import Job, RecruiterJobLink  # noqa: E402
from db.services.recruiter_enrichment import is_valid_recruiter_name  # noqa: E402
from scraper.linkedin import (  # noqa: E402
    _li_extract_hiring_manager_from_page,
    _li_is_valid_hiring_manager,
    _li_normalize_hiring_manager,
)

_MANIFEST_VERSION = 1
_REQUIRED_ROW_FIELDS = (
    "job_key_v2",
    "title",
    "company",
    "extracted_hiring_manager",
    "url",
)

_COHORT_SQL = """
SELECT j.id, j.job_key_v2, j.title, j.company, j.link, j.hiring_manager
FROM jobs j
WHERE j.source = 'linkedin'
  AND (
    j.hiring_manager IS NULL
    OR TRIM(j.hiring_manager) = ''
    OR LOWER(TRIM(j.hiring_manager)) IN ('not specified', 'unknown', 'nan')
  )
  AND NOT EXISTS (
    SELECT 1 FROM recruiter_job_links rjl WHERE rjl.job_id = j.id
  )
  AND j.link IS NOT NULL AND TRIM(j.link) != ''
  AND LOWER(j.link) LIKE '%linkedin.com/jobs/view/%'
ORDER BY j.updated_at DESC
"""

_SAMPLE_LIMIT = 15
_JOB_DELAY_SEC = 2.0
_GOTO_TIMEOUT_MS = 45_000
_POST_NAV_WAIT_MS = 2000


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
        "linkedin_hm_affected_cohort": session.execute(
            text(
                """
                SELECT COUNT(*) FROM jobs j
                WHERE j.source = 'linkedin'
                  AND (
                    j.hiring_manager IS NULL
                    OR TRIM(j.hiring_manager) = ''
                    OR LOWER(TRIM(j.hiring_manager)) IN ('not specified', 'unknown', 'nan')
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM recruiter_job_links rjl WHERE rjl.job_id = j.id
                  )
                  AND j.link IS NOT NULL AND TRIM(j.link) != ''
                  AND LOWER(j.link) LIKE '%linkedin.com/jobs/view/%'
                """
            )
        ).scalar_one(),
        "linkedin_hm_populated": session.execute(
            text(
                """
                SELECT COUNT(*) FROM jobs
                WHERE source = 'linkedin'
                  AND hiring_manager IS NOT NULL
                  AND TRIM(hiring_manager) != ''
                  AND LOWER(TRIM(hiring_manager)) NOT IN ('not specified', 'unknown', 'nan')
                """
            )
        ).scalar_one(),
        "linkedin_recruiter_job_links": session.execute(
            text(
                """
                SELECT COUNT(DISTINCT rjl.job_id)
                FROM recruiter_job_links rjl
                JOIN jobs j ON j.id = rjl.job_id
                WHERE j.source = 'linkedin'
                """
            )
        ).scalar_one(),
    }


def derive_update_payload(extracted_hm: str) -> dict[str, Any] | None:
    if not _li_is_valid_hiring_manager(extracted_hm):
        return None
    normalized = _li_normalize_hiring_manager(extracted_hm)
    if not is_valid_recruiter_name(normalized):
        return None
    return {"hiring_manager": normalized}


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
            or_(
                Job.hiring_manager.is_(None),
                func.trim(Job.hiring_manager) == "",
                func.lower(func.trim(Job.hiring_manager)).in_(
                    ["not specified", "unknown", "nan"]
                ),
            ),
            ~exists(select(1).where(RecruiterJobLink.job_id == Job.id)),
        )
        .values(
            hiring_manager=payload["hiring_manager"],
            updated_at=updated_at,
        )
    )
    return result.rowcount or 0


def write_manifest(doc: dict[str, Any], *, manifest_path: Path) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(doc, indent=2, default=str),
        encoding="utf-8",
    )
    return manifest_path


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object envelope")
    version = raw.get("manifest_version")
    if version != _MANIFEST_VERSION:
        raise ValueError(
            f"unsupported manifest_version={version!r} (expected {_MANIFEST_VERSION})"
        )
    rows = raw.get("rows")
    if not isinstance(rows, list):
        raise ValueError("manifest.rows must be a list")
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"manifest.rows[{idx}] must be an object")
        missing = [field for field in _REQUIRED_ROW_FIELDS if not str(row.get(field) or "").strip()]
        if missing:
            raise ValueError(
                f"manifest.rows[{idx}] missing required fields: {', '.join(missing)}"
            )
        if not is_valid_recruiter_name(str(row["extracted_hiring_manager"])):
            raise ValueError(
                f"manifest.rows[{idx}] has invalid extracted_hiring_manager: "
                f"{row['extracted_hiring_manager']!r}"
            )
    return raw


def _default_manifest_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return paths.ensure_data_dir() / "backups" / f"linkedin_hm_recoverable-{stamp}.json"


def _build_recoverable_row(row: dict[str, Any], *, extracted: str) -> dict[str, Any]:
    return {
        "job_key_v2": row["job_key_v2"],
        "title": row.get("title") or "",
        "company": row.get("company") or "",
        "extracted_hiring_manager": extracted,
        "url": str(row.get("link") or row.get("url") or "").strip(),
    }


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
                extracted = "Not Specified"
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
                    page.wait_for_timeout(_POST_NAV_WAIT_MS)
                    extracted = _li_extract_hiring_manager_from_page(page)
                except Exception as exc:
                    print(f"    extraction_error: {exc!r}")
                results.append({**dict(row), "extracted_hiring_manager": extracted})
                if idx + 1 < len(cohort):
                    time.sleep(_JOB_DELAY_SEC)
        finally:
            browser.close()
    return results


def run_extract(
    *,
    limit: int | None = None,
    job_key_v2: str | None = None,
    manifest_out: Path | None = None,
) -> int:
    ensure_database_ready()
    out_path = manifest_out or _default_manifest_out()

    with get_session() as session:
        baseline = _sql_validation(session)
        print("=== SQL validation (current DB) ===")
        for key, value in baseline.items():
            print(f"  {key}: {value}")

        cohort = fetch_cohort(session, limit=limit, job_key_v2=job_key_v2)
        print(f"\n=== Cohort: {len(cohort)} job(s) ===")
        if not cohort:
            print("(nothing to process)")
            return 0

        print("\n=== Playwright extraction (extract mode) ===")
        extracted = _visit_jobs_with_playwright(cohort)

        recoverable_rows: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []
        extraction_failures = 0

        for row in extracted:
            extracted_hm = str(row.get("extracted_hiring_manager") or "")
            payload = derive_update_payload(extracted_hm)
            if payload is None:
                extraction_failures += 1
                continue
            recoverable = _build_recoverable_row(
                row,
                extracted=payload["hiring_manager"],
            )
            recoverable_rows.append(recoverable)
            if len(samples) < _SAMPLE_LIMIT:
                samples.append(recoverable)

        cohort_size = len(cohort)
        extraction_successes = len(recoverable_rows)
        manifest_doc = {
            "manifest_version": _MANIFEST_VERSION,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "mode": "extract",
            "cohort_size": cohort_size,
            "extraction_successes": extraction_successes,
            "extraction_failures": extraction_failures,
            "would_update": extraction_successes,
            "rows": recoverable_rows,
        }
        written = write_manifest(manifest_doc, manifest_path=out_path)

        print("\n=== Extract summary ===")
        print("  mode: extract (dry-run)")
        print(f"  cohort_size: {cohort_size}")
        print(f"  extraction_successes: {extraction_successes}")
        print(f"  extraction_failures: {extraction_failures}")
        print(f"  would_update: {extraction_successes}")
        print(f"  manifest_path: {written}")

        print(f"\n=== Sample recoveries (up to {_SAMPLE_LIMIT}) ===")
        for sample in samples:
            print(
                f"  {sample['job_key_v2'][:12]}… "
                f"{sample['extracted_hiring_manager']!r} "
                f"@ {sample.get('company', '')!r}"
            )

        print("\n(extract complete: no database writes; apply via --apply-from-manifest)")

    return 0


def run_apply_from_manifest(
    *,
    manifest_path: Path,
    limit: int | None = None,
) -> int:
    ensure_database_ready()
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    doc = load_manifest(manifest_path)
    rows: list[dict[str, Any]] = list(doc.get("rows") or [])
    apply_rows = rows[:limit] if limit is not None else rows

    backup_dir = paths.ensure_data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    print(
        "\n=== Operator reminder ===\n"
        f"  Copy DB to {backup_dir}/ai_job_agent-{stamp}.db before continuing.\n"
        f"  Example: cp {paths.ensure_data_dir() / 'ai_job_agent.db'} "
        f"{backup_dir}/ai_job_agent-{stamp}.db"
    )

    print("\n=== Manifest metadata ===")
    print(f"  manifest_path: {manifest_path}")
    print(f"  manifest_version: {doc.get('manifest_version')}")
    print(f"  created_at: {doc.get('created_at')}")
    print(f"  cohort_size: {doc.get('cohort_size')}")
    print(f"  would_update: {doc.get('would_update')}")
    print(f"  manifest_rows: {len(rows)}")
    print(f"  apply_slice: {len(apply_rows)}")

    with get_session() as session:
        baseline = _sql_validation(session)
        print("\n=== SQL validation (pre-apply) ===")
        for key, value in baseline.items():
            print(f"  {key}: {value}")

        rows_updated = 0
        rows_skipped_guard = 0
        rows_skipped_invalid = 0

        for row in apply_rows:
            payload = derive_update_payload(str(row.get("extracted_hiring_manager") or ""))
            if payload is None:
                rows_skipped_invalid += 1
                print(
                    f"  skip invalid: {row.get('job_key_v2', '')} "
                    f"extracted_hiring_manager={row.get('extracted_hiring_manager')!r}"
                )
                continue
            applied = apply_job_update(
                session,
                job_key_v2=str(row["job_key_v2"]),
                payload=payload,
                updated_at=now_utc,
            )
            if applied:
                rows_updated += applied
            else:
                rows_skipped_guard += 1

        session.commit()

        post = _sql_validation(session)
        print("\n=== Apply summary ===")
        print("  mode: apply-from-manifest")
        print(f"  manifest_path: {manifest_path}")
        print(f"  manifest_rows: {len(rows)}")
        print(f"  apply_slice: {len(apply_rows)}")
        print(f"  rows_updated: {rows_updated}")
        print(f"  rows_skipped_guard: {rows_skipped_guard}")
        print(f"  rows_skipped_invalid: {rows_skipped_invalid}")

        print("\n=== SQL validation (post-apply) ===")
        for key, value in post.items():
            print(f"  {key}: {value}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "LinkedIn hiring_manager backfill: extract mode writes recoverable manifest; "
            "apply mode replays manifest (no re-scrape)"
        )
    )
    parser.add_argument(
        "--manifest-out",
        default=None,
        help="Extract mode: write recoverable manifest to PATH",
    )
    parser.add_argument(
        "--apply-from-manifest",
        dest="apply_from_manifest",
        default=None,
        help="Apply mode: replay recoverable manifest at PATH (no Playwright)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Extract: first N cohort rows; Apply: first N manifest rows",
    )
    parser.add_argument(
        "--job-key-v2",
        dest="job_key_v2",
        default=None,
        help="Extract mode: single job by job_key_v2",
    )
    args = parser.parse_args()

    if args.apply_from_manifest:
        if args.job_key_v2 or args.manifest_out:
            parser.error(
                "--apply-from-manifest cannot be combined with --job-key-v2 or --manifest-out"
            )
        return run_apply_from_manifest(
            manifest_path=Path(args.apply_from_manifest),
            limit=args.limit,
        )

    if args.manifest_out:
        manifest_out = Path(args.manifest_out)
    else:
        manifest_out = None

    return run_extract(
        limit=args.limit,
        job_key_v2=args.job_key_v2,
        manifest_out=manifest_out,
    )


if __name__ == "__main__":
    raise SystemExit(main())
