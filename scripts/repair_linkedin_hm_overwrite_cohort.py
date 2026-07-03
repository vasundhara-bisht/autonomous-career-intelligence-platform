#!/usr/bin/env python3
"""One-time repair: restore jobs.hiring_manager from linked recruiter for overwrite cohort."""

from __future__ import annotations

import argparse
import json
import sys
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
from db.models.schema import Job, Recruiter, RecruiterJobLink  # noqa: E402
from db.services.recruiter_enrichment import (  # noqa: E402
    HM_SENTINELS,
    is_valid_recruiter_name,
)

_MANIFEST_VERSION = 1
_REQUIRED_ROW_FIELDS = (
    "job_id",
    "job_key_v2",
    "title",
    "company",
    "current_hiring_manager",
    "proposed_hiring_manager",
    "recruiter_id",
    "recruiter_key",
)
_SAMPLE_LIMIT = 15

_COHORT_SQL = """
SELECT
  j.id AS job_id,
  j.job_key_v2,
  j.title,
  j.company,
  j.hiring_manager AS current_hiring_manager,
  r.id AS recruiter_id,
  r.recruiter_name AS proposed_hiring_manager,
  r.recruiter_key,
  rjl.linked_at
FROM jobs j
INNER JOIN recruiter_job_links rjl ON rjl.job_id = j.id
INNER JOIN recruiters r ON r.id = rjl.recruiter_id
WHERE j.source = 'linkedin'
  AND (
    j.hiring_manager IS NULL
    OR TRIM(j.hiring_manager) = ''
    OR LOWER(TRIM(j.hiring_manager)) IN ('not specified', 'unknown', 'nan', 'none')
  )
  AND LOWER(TRIM(r.recruiter_name)) NOT IN ('not specified', 'unknown', 'nan', 'none')
  AND TRIM(r.recruiter_name) != ''
  AND j.id IN (
    SELECT rjl2.job_id
    FROM recruiter_job_links rjl2
    GROUP BY rjl2.job_id
    HAVING COUNT(*) = 1
  )
ORDER BY j.updated_at DESC
"""


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
        "overwrite_cohort_count": session.execute(
            text(
                """
                SELECT COUNT(*) FROM jobs j
                WHERE j.source = 'linkedin'
                  AND (
                    j.hiring_manager IS NULL
                    OR TRIM(j.hiring_manager) = ''
                    OR LOWER(TRIM(j.hiring_manager)) IN ('not specified', 'unknown', 'nan', 'none')
                  )
                  AND EXISTS (
                    SELECT 1 FROM recruiter_job_links rjl WHERE rjl.job_id = j.id
                  )
                """
            )
        ).scalar_one(),
        "repair_cohort_count": session.execute(
            text(f"SELECT COUNT(*) FROM ({_COHORT_SQL}) AS repair_cohort")
        ).scalar_one(),
        "multi_link_sentinel_hm": session.execute(
            text(
                """
                SELECT COUNT(*) FROM jobs j
                WHERE j.source = 'linkedin'
                  AND (
                    j.hiring_manager IS NULL
                    OR TRIM(j.hiring_manager) = ''
                    OR LOWER(TRIM(j.hiring_manager)) IN ('not specified', 'unknown', 'nan', 'none')
                  )
                  AND j.id IN (
                    SELECT job_id FROM recruiter_job_links GROUP BY job_id HAVING COUNT(*) > 1
                  )
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
                  AND LOWER(TRIM(hiring_manager)) NOT IN ('not specified', 'unknown', 'nan', 'none')
                """
            )
        ).scalar_one(),
        "recruiter_job_links_total": session.execute(
            text("SELECT COUNT(*) FROM recruiter_job_links")
        ).scalar_one(),
    }


def _build_manifest_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": int(row["job_id"]),
        "job_key_v2": str(row["job_key_v2"]),
        "title": str(row.get("title") or ""),
        "company": str(row.get("company") or ""),
        "current_hiring_manager": str(row.get("current_hiring_manager") or ""),
        "proposed_hiring_manager": str(row["proposed_hiring_manager"]),
        "recruiter_id": int(row["recruiter_id"]),
        "recruiter_key": str(row["recruiter_key"]),
        "linked_at": str(row.get("linked_at") or ""),
    }


def _validate_cohort_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    recoverable: list[dict[str, Any]] = []
    excluded_invalid = 0
    seen_v2: set[str] = set()
    duplicate_v2 = 0

    for row in rows:
        v2 = str(row.get("job_key_v2") or "").strip()
        if v2 in seen_v2:
            duplicate_v2 += 1
            continue
        seen_v2.add(v2)

        proposed = str(row.get("proposed_hiring_manager") or "")
        if not is_valid_recruiter_name(proposed):
            excluded_invalid += 1
            continue
        recoverable.append(_build_manifest_row(row))

    if duplicate_v2:
        raise ValueError(f"cohort contains duplicate job_key_v2 rows: {duplicate_v2}")

    return recoverable, excluded_invalid, duplicate_v2


def apply_job_update(
    session: Session,
    *,
    job_key_v2: str,
    proposed_hiring_manager: str,
    recruiter_id: int,
    updated_at: datetime,
) -> int:
    if not is_valid_recruiter_name(proposed_hiring_manager):
        return 0

    single_link_job_ids = (
        select(RecruiterJobLink.job_id)
        .group_by(RecruiterJobLink.job_id)
        .having(func.count() == 1)
    )

    result = session.execute(
        update(Job)
        .where(
            Job.job_key_v2 == job_key_v2,
            Job.source == "linkedin",
            or_(
                Job.hiring_manager.is_(None),
                func.trim(Job.hiring_manager) == "",
                func.lower(func.trim(Job.hiring_manager)).in_(list(HM_SENTINELS)),
            ),
            Job.id.in_(single_link_job_ids),
            exists(
                select(1).where(
                    RecruiterJobLink.job_id == Job.id,
                    RecruiterJobLink.recruiter_id == recruiter_id,
                )
            ),
            exists(
                select(1)
                .select_from(Recruiter)
                .join(RecruiterJobLink, RecruiterJobLink.recruiter_id == Recruiter.id)
                .where(
                    RecruiterJobLink.job_id == Job.id,
                    Recruiter.id == recruiter_id,
                    Recruiter.recruiter_name == proposed_hiring_manager,
                )
            ),
        )
        .values(
            hiring_manager=proposed_hiring_manager,
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
        missing: list[str] = []
        for field in _REQUIRED_ROW_FIELDS:
            if field == "job_id":
                if row.get(field) is None:
                    missing.append(field)
            elif not str(row.get(field) or "").strip():
                missing.append(field)
        if missing:
            raise ValueError(
                f"manifest.rows[{idx}] missing required fields: {', '.join(missing)}"
            )
        if not is_valid_recruiter_name(str(row["proposed_hiring_manager"])):
            raise ValueError(
                f"manifest.rows[{idx}] has invalid proposed_hiring_manager: "
                f"{row['proposed_hiring_manager']!r}"
            )
    return raw


def _default_manifest_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return paths.ensure_data_dir() / "manifests" / f"repair_hm_overwrite-{stamp}.json"


def run_dry_run(
    *,
    limit: int | None = None,
    job_key_v2: str | None = None,
    manifest_out: Path | None = None,
    expect_count: int | None = None,
) -> int:
    ensure_database_ready()
    out_path = manifest_out or _default_manifest_out()

    with get_session() as session:
        baseline = _sql_validation(session)
        print("=== SQL validation (current DB) ===")
        for key, value in baseline.items():
            print(f"  {key}: {value}")

        cohort = fetch_cohort(session, limit=limit, job_key_v2=job_key_v2)
        cohort_size = len(cohort)
        print(f"\n=== Cohort: {cohort_size} job(s) ===")
        if not cohort:
            print("(nothing to process)")
            return 0

        recoverable_rows, excluded_invalid, _ = _validate_cohort_rows(cohort)
        would_update = len(recoverable_rows)

        if expect_count is not None and would_update != expect_count:
            raise ValueError(
                f"cohort would_update={would_update} does not match --expect-count {expect_count}"
            )

        manifest_doc = {
            "manifest_version": _MANIFEST_VERSION,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "mode": "dry-run",
            "cohort_size": cohort_size,
            "would_update": would_update,
            "excluded_invalid_recruiter_name": excluded_invalid,
            "rows": recoverable_rows,
        }
        written = write_manifest(manifest_doc, manifest_path=out_path)

        print("\n=== Dry-run summary ===")
        print("  mode: dry-run (no database writes)")
        print(f"  cohort_size: {cohort_size}")
        print(f"  would_update: {would_update}")
        print(f"  excluded_invalid_recruiter_name: {excluded_invalid}")
        print(f"  manifest_path: {written}")

        print(f"\n=== Sample repairs (up to {_SAMPLE_LIMIT}) ===")
        for sample in recoverable_rows[:_SAMPLE_LIMIT]:
            print(
                f"  {sample['job_key_v2'][:20]}… "
                f"{sample['current_hiring_manager']!r} -> "
                f"{sample['proposed_hiring_manager']!r}"
            )

        print("\n(dry-run complete: apply via --apply-from-manifest)")

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
        f"  Copy DB to {backup_dir}/ai_job_agent-pre-task-e-{stamp}.db before continuing.\n"
        f"  Example: cp {paths.ensure_data_dir() / 'ai_job_agent.db'} "
        f"{backup_dir}/ai_job_agent-pre-task-e-{stamp}.db"
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
            proposed = str(row.get("proposed_hiring_manager") or "")
            if not is_valid_recruiter_name(proposed):
                rows_skipped_invalid += 1
                print(
                    f"  skip invalid: {row.get('job_key_v2', '')} "
                    f"proposed_hiring_manager={proposed!r}"
                )
                continue
            applied = apply_job_update(
                session,
                job_key_v2=str(row["job_key_v2"]),
                proposed_hiring_manager=proposed,
                recruiter_id=int(row["recruiter_id"]),
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
            "Repair LinkedIn HM overwrite cohort: dry-run writes manifest from "
            "recruiter_job_links; apply mode replays manifest (jobs.hiring_manager only)"
        )
    )
    parser.add_argument(
        "--manifest-out",
        default=None,
        help="Dry-run: write repair manifest to PATH",
    )
    parser.add_argument(
        "--apply-from-manifest",
        dest="apply_from_manifest",
        default=None,
        help="Apply mode: replay manifest at PATH (no recruiter/link writes)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Dry-run: first N cohort rows; Apply: first N manifest rows",
    )
    parser.add_argument(
        "--job-key-v2",
        dest="job_key_v2",
        default=None,
        help="Dry-run: single job by job_key_v2",
    )
    parser.add_argument(
        "--expect-count",
        type=int,
        default=None,
        help="Dry-run: abort unless would_update equals this count (e.g. 33)",
    )
    args = parser.parse_args()

    if args.apply_from_manifest:
        if args.job_key_v2 or args.manifest_out or args.expect_count is not None:
            parser.error(
                "--apply-from-manifest cannot be combined with --job-key-v2, "
                "--manifest-out, or --expect-count"
            )
        return run_apply_from_manifest(
            manifest_path=Path(args.apply_from_manifest),
            limit=args.limit,
        )

    manifest_out = Path(args.manifest_out) if args.manifest_out else None
    return run_dry_run(
        limit=args.limit,
        job_key_v2=args.job_key_v2,
        manifest_out=manifest_out,
        expect_count=args.expect_count,
    )


if __name__ == "__main__":
    raise SystemExit(main())
