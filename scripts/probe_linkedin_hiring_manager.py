#!/usr/bin/env python3
"""Operator probe for LinkedIn hiring-manager extraction (primary + flagship3 fallback)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths  # noqa: E402
from scraper.linkedin import (  # noqa: E402
    _LI_PRIMARY_HM_SELECTOR,
    _li_extract_hiring_manager_flagship3_fallback,
    _li_extract_hiring_manager_from_page,
    _li_is_valid_hiring_manager,
    _li_normalize_hiring_manager,
    _li_scroll_job_detail_for_hm,
)

_GOTO_TIMEOUT_MS = 45_000
_POST_NAV_WAIT_MS = 2000


def _hm_missing_sql(limit: int) -> str:
    return f"""
        SELECT j.job_key_v2, j.title, j.company, j.link, j.hiring_manager
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
        ORDER BY j.updated_at DESC
        LIMIT {int(limit)}
    """


def _hm_success_sql(limit: int) -> str:
    return f"""
        SELECT j.job_key_v2, j.title, j.company, j.link, j.hiring_manager
        FROM jobs j
        WHERE j.source = 'linkedin'
          AND j.hiring_manager IS NOT NULL
          AND TRIM(j.hiring_manager) != ''
          AND LOWER(TRIM(j.hiring_manager)) NOT IN ('not specified', 'unknown', 'nan')
        ORDER BY j.updated_at DESC
        LIMIT {int(limit)}
    """


def _fetch_rows(*, hm_missing_only: bool, limit: int) -> list[dict[str, str]]:
    from db.bootstrap import ensure_database_ready
    from db.engine import get_session
    from sqlalchemy import text

    ensure_database_ready()
    sql = _hm_missing_sql(limit) if hm_missing_only else _hm_success_sql(limit)
    with get_session() as session:
        return [dict(row) for row in session.execute(text(sql)).mappings().all()]


def _resolve_url(*, url: str | None, job_key_v2: str | None) -> str:
    if url:
        return url.strip()
    if not job_key_v2:
        raise ValueError("Provide --url or --job-key-v2")
    from db.bootstrap import ensure_database_ready
    from db.engine import get_session
    from sqlalchemy import text

    ensure_database_ready()
    with get_session() as session:
        row = session.execute(
            text("SELECT link FROM jobs WHERE job_key_v2 = :k"),
            {"k": job_key_v2},
        ).mappings().first()
    if not row or not row.get("link"):
        raise ValueError(f"No link for job_key_v2={job_key_v2!r}")
    return str(row["link"]).strip()


def _probe_page(page, *, save_html: Path | None) -> dict[str, str]:
    primary_raw = ""
    primary_status = "NOT FOUND"
    try:
        el = page.query_selector(_LI_PRIMARY_HM_SELECTOR)
        if el:
            primary_raw = el.inner_text() or ""
            primary_norm = _li_normalize_hiring_manager(primary_raw)
            if primary_norm:
                primary_status = "FOUND"
                primary_raw = primary_norm
    except Exception as exc:
        primary_raw = repr(exc)

    fallback_raw = ""
    fallback_status = "NOT FOUND"
    try:
        fb = _li_extract_hiring_manager_flagship3_fallback(page)
        if fb:
            fallback_status = "FOUND"
            fallback_raw = fb
    except Exception as exc:
        fallback_raw = repr(exc)

    final = _li_extract_hiring_manager_from_page(page)

    if save_html is not None:
        save_html.parent.mkdir(parents=True, exist_ok=True)
        save_html.write_text(page.content(), encoding="utf-8")
        print(f"HTML saved: {save_html}")

    return {
        "primary_status": primary_status,
        "primary_value": primary_raw or "",
        "fallback_status": fallback_status,
        "fallback_value": fallback_raw or "",
        "final": final,
    }


def _visit_url(url: str, *, save_html: Path | None) -> dict[str, str]:
    from playwright.sync_api import sync_playwright

    auth = paths.linkedin_auth_json()
    if not auth.is_file():
        raise FileNotFoundError(
            f"Missing LinkedIn session at {auth}. "
            "Run save_linkedin_session() from scraper/linkedin.py first."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chrome")
        try:
            page = browser.new_context(storage_state=str(auth)).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
            page.wait_for_timeout(_POST_NAV_WAIT_MS)
            _li_scroll_job_detail_for_hm(page)
            return _probe_page(page, save_html=save_html)
        finally:
            browser.close()


def _print_result(url: str, row: dict[str, str] | None, result: dict[str, str]) -> None:
    if row:
        print(
            f"\n=== {row.get('job_key_v2', '')} | {row.get('title', '')} @ "
            f"{row.get('company', '')} ==="
        )
        if row.get("hiring_manager"):
            print(f"DB hiring_manager: {row.get('hiring_manager')}")
    else:
        print(f"\n=== {url} ===")
    print(f"PRIMARY: {result['primary_status']}  value={result['primary_value']!r}")
    print(f"FALLBACK: {result['fallback_status']}  value={result['fallback_value']!r}")
    print(f"FINAL: {result['final']!r}")


def run_probe(
    *,
    url: str | None,
    job_key_v2: str | None,
    save_html: Path | None,
    hm_missing_only: bool,
    hm_success_only: bool,
    limit: int,
) -> int:
    if url or job_key_v2:
        target = _resolve_url(url=url, job_key_v2=job_key_v2)
        result = _visit_url(target, save_html=save_html)
        _print_result(target, None, result)
        return 0

    if hm_success_only:
        rows = _fetch_rows(hm_missing_only=False, limit=limit)
    else:
        rows = _fetch_rows(hm_missing_only=hm_missing_only, limit=limit)

    if not rows:
        print("(no cohort rows)")
        return 0

    found = 0
    for row in rows:
        link = str(row.get("link") or "").strip()
        if not link:
            continue
        result = _visit_url(link, save_html=None)
        _print_result(link, row, result)
        if _li_is_valid_hiring_manager(result["final"]):
            found += 1

    print(f"\n=== Summary: {found}/{len(rows)} FINAL != Not Specified ===")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe LinkedIn hiring-manager extraction (read-only)"
    )
    parser.add_argument("--url", default=None, help="Single job URL to probe")
    parser.add_argument("--job-key-v2", dest="job_key_v2", default=None)
    parser.add_argument(
        "--save-html",
        default=None,
        help="Write scroll-captured HTML snapshot to PATH",
    )
    parser.add_argument(
        "--hm-missing-only",
        action="store_true",
        help="Batch probe HM-missing cohort from SQLite",
    )
    parser.add_argument(
        "--hm-success-only",
        action="store_true",
        help="Batch probe HM-populated cohort (regression)",
    )
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    save_html = Path(args.save_html) if args.save_html else None
    return run_probe(
        url=args.url,
        job_key_v2=args.job_key_v2,
        save_html=save_html,
        hm_missing_only=args.hm_missing_only,
        hm_success_only=args.hm_success_only,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
