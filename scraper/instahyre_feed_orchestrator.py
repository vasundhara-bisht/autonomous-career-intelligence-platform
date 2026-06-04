"""
Instahyre feed-driven acquisition (two curated feeds only).

Loads config/instahyre_feeds.json and runs each enabled feed sequentially.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.job_identity import extract_instahyre_job_id
from scraper.acquisition_gate import effective_session_cap
from scraper.instahyre_logging import (
    debug_instahyre_enabled,
    log_debug,
    log_failure_with_trace,
    log_ok,
    log_warn,
)

import paths

_ROOT = paths.REPO_ROOT
_CONFIG_PATH = paths.instahyre_feeds_json()


@dataclass
class InstahyreFeed:
    id: str
    label: str
    url: str


@dataclass
class InstahyreSessionResult:
    jobs: list[dict] = field(default_factory=list)
    feeds_executed: int = 0
    unique_jobs_collected: int = 0
    duplicates_skipped: int = 0
    recruiters_added: int = 0
    recruiters_updated: int = 0
    duration_sec: float = 0.0


def load_instahyre_feed_catalog(
    config_path: Path | None = None,
) -> tuple[dict, list[InstahyreFeed]]:
    path = config_path or _CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    out: list[InstahyreFeed] = []
    for feed in cfg.get("feeds") or []:
        if not feed.get("enabled", True):
            continue
        fid = str(feed.get("id", "")).strip()
        url = str(feed.get("url", "")).strip()
        if not fid or not url:
            log_debug(f"[debug] skip feed missing id/url: {feed!r}")
            continue
        out.append(
            InstahyreFeed(
                id=fid,
                label=str(feed.get("label", "")).strip() or fid,
                url=url,
            )
        )

    return cfg, out


def _stamp_feed_metadata(jobs: list[dict], feed: InstahyreFeed) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        job["instahyre_feed_id"] = feed.id
        job["instahyre_feed_label"] = feed.label
        job["instahyre_run_ts"] = ts
        job["instahyre_query_id"] = feed.id
        job["instahyre_query_label"] = feed.label
        job["instahyre_query_keywords"] = ""
        job["instahyre_query_location"] = ""
        job["instahyre_filter_profile"] = feed.id


def _valid_recruiter_name(name: str) -> bool:
    cleaned = (name or "").strip()
    if not cleaned:
        return False
    return cleaned.lower() not in ("not specified", "unknown", "nan")


def _unpack_scrape_result(result: Any) -> tuple[list[dict], dict[str, Any]]:
    if isinstance(result, tuple) and len(result) == 2:
        jobs, stats = result
        return list(jobs or []), dict(stats or {})
    return list(result or []), {}


def run_instahyre_feed_session(
    scrape_fn,
    *,
    max_feeds: int | None = None,
    config_path: Path | None = None,
) -> InstahyreSessionResult:
    """
    Run Instahyre feeds in config order.
    ``scrape_fn(url, feed_run=...)`` returns (jobs, feed_stats).
    """
    session = InstahyreSessionResult()
    if max_feeds is not None and int(max_feeds) <= 0:
        return session

    session_t0 = time.monotonic()

    cfg, catalog = load_instahyre_feed_catalog(config_path)
    if not catalog:
        log_warn("⚠️ Instahyre: no enabled feeds in catalog")
        return session

    allow_ids: set[str] | None = None
    env_ids = os.environ.get("INSTAHYRE_FEED_IDS", "").strip()
    if not env_ids:
        env_ids = os.environ.get("INSTAHYRE_QUERY_IDS", "").strip()
    if env_ids:
        allow_ids = {x.strip() for x in env_ids.split(",") if x.strip()}
        catalog = [f for f in catalog if f.id in allow_ids]

    defaults = cfg.get("defaults") or {}
    cap = effective_session_cap(
        max_feeds,
        int(defaults.get("max_feeds_per_session", 2)),
    )
    cap = max(1, min(int(cap), len(catalog)))
    picks = catalog[:cap]

    pause_sec = int(defaults.get("inter_feed_pause_sec", 30))

    for feed in picks:
        log_ok(f"🔵 Feed: {feed.label}")

    if debug_instahyre_enabled():
        log_debug(f"[debug] session feed cap={cap}")
        for feed in picks:
            log_debug(f"[debug]   {feed.id} -> {feed.url}")
        if len(catalog) > len(picks):
            for feed in catalog[len(picks) :]:
                log_debug(f"[debug] skipped feed (cap): {feed.label} ({feed.id})")

    all_jobs: list[dict] = []
    seen_job_ids: set[str] = set()
    session_recruiters: set[str] = set()

    for i, feed in enumerate(picks):
        if i > 0 and pause_sec > 0:
            log_debug(f"[debug] inter-feed pause {pause_sec}s")
            time.sleep(pause_sec)

        feed_run = {"feed_id": feed.id, "label": feed.label}
        feed_t0 = time.monotonic()
        jobs: list[dict] = []
        feed_stats: dict[str, Any] = {}

        try:
            raw = scrape_fn(feed.url, feed_run=feed_run)
            jobs, feed_stats = _unpack_scrape_result(raw)
            _stamp_feed_metadata(jobs, feed)
        except Exception as exc:
            log_failure_with_trace(f"Instahyre feed failed ({feed.label})", exc)
            continue

        log_debug(
            f"[debug] feed {feed.id} duration_sec={round(time.monotonic() - feed_t0, 1)}"
        )

        feed_unique: list[dict] = []
        for job in jobs:
            link = job.get("link") or ""
            jid = extract_instahyre_job_id(link)
            if jid and jid in seen_job_ids:
                session.duplicates_skipped += 1
                log_warn(f"⚠️ Duplicate skipped: {jid}")
                continue
            if jid:
                seen_job_ids.add(jid)

            recruiter_name = str(job.get("recruiter_name") or job.get("hiring_manager") or "")
            if _valid_recruiter_name(recruiter_name):
                recruiter_key = recruiter_name.strip().lower()
                if recruiter_key in session_recruiters:
                    session.recruiters_updated += 1
                else:
                    session_recruiters.add(recruiter_key)
                    session.recruiters_added += 1

            feed_unique.append(job)

        all_jobs.extend(feed_unique)

    session.jobs = all_jobs
    session.feeds_executed = len(picks)
    session.unique_jobs_collected = len(all_jobs)
    session.duration_sec = round(time.monotonic() - session_t0, 1)

    log_ok("\n🟣 INSTAHYRE SESSION COMPLETE")
    log_ok(f"✅ Feeds executed: {session.feeds_executed}")
    log_ok(f"✅ Unique jobs collected: {session.unique_jobs_collected}")
    log_ok(f"✅ Recruiters added: {session.recruiters_added}")
    log_ok(f"✅ Recruiters updated: {session.recruiters_updated}")
    log_ok(f"✅ Duplicates skipped: {session.duplicates_skipped}")
    log_debug(f"[debug] session duration_sec={session.duration_sec}")

    return session
