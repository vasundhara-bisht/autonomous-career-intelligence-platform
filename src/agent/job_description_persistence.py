"""
Lightweight persistence for enriched job descriptions (job_descriptions.csv).

V2-primary lookup (JOB_KEY_V2) with legacy JOB_KEY fallback during migration.
Separate from historical_jobs.csv; both files share canonical V2 when possible.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd

from agent.description_fetcher import fetch_job_description
from agent.historical_persistence import generate_job_key
from agent.job_identity import generate_job_key_v2

import paths


def _descriptions_path():
    return paths.job_descriptions_csv()


MIN_PERSISTABLE_CHARS = 200

JOB_DESCRIPTIONS_SCHEMA_COLUMNS = [
    "JOB_KEY",
    "JOB_KEY_V2",
    "description",
    "last_updated",
    "source",
]


def job_descriptions_schema_columns() -> list[str]:
    """Column order for empty job_descriptions.csv (flush_description_store contract)."""
    return list(JOB_DESCRIPTIONS_SCHEMA_COLUMNS)


def _is_persistable_description(text: object) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip()
    if len(t) < MIN_PERSISTABLE_CHARS:
        return False
    low = t.lower()
    if low == "description unavailable":
        return False
    return True


def _job_key_legacy(job: dict) -> str:
    key = str(job.get("JOB_KEY", "")).strip()
    if key:
        return key
    key = generate_job_key(job)
    job["JOB_KEY"] = key
    return key


def _job_key_v2(job: dict) -> str:
    v2 = str(job.get("JOB_KEY_V2", "") or "").strip()
    if v2:
        return v2
    try:
        v2, _ = generate_job_key_v2(job)
        v2 = str(v2 or "").strip()
        if v2:
            job["JOB_KEY_V2"] = v2
        return v2
    except Exception:
        return ""


def _identity_log_enabled() -> bool:
    return os.environ.get("DEBUG_IDENTITY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _log_description_action(
    action: str,
    *,
    bucket: str,
    legacy_key: str,
    v2_key: str,
    via: str = "",
) -> None:
    if not _identity_log_enabled():
        return
    extra = f" via={via}" if via else ""
    print(
        f"  [identity:desc] {action} bucket={bucket} "
        f"JOB_KEY={legacy_key!r} JOB_KEY_V2={v2_key!r}{extra}"
    )


class DescriptionStore:
    """In-memory description cache with V2-primary and legacy fallback indexes."""

    def __init__(self) -> None:
        self.by_v2: dict[str, dict[str, Any]] = {}
        self.by_legacy: dict[str, dict[str, Any]] = {}

    def put(self, *, legacy_key: str, v2_key: str, record: dict[str, Any]) -> None:
        rec = dict(record)
        rec["job_key"] = legacy_key
        rec["job_key_v2"] = v2_key
        if v2_key:
            prev = self.by_v2.get(v2_key)
            if prev is None or rec["last_updated"] >= prev["last_updated"]:
                self.by_v2[v2_key] = rec
        if legacy_key:
            prev = self.by_legacy.get(legacy_key)
            if prev is None or rec["last_updated"] >= prev["last_updated"]:
                self.by_legacy[legacy_key] = rec

    def resolve(self, job: dict) -> tuple[dict[str, Any] | None, str]:
        """Return (record, via) where via is 'v2', 'legacy', or ''."""
        v2_key = _job_key_v2(job)
        if v2_key:
            rec = self.by_v2.get(v2_key)
            if rec and _is_persistable_description(rec.get("description", "")):
                return rec, "v2"
        legacy_key = _job_key_legacy(job)
        rec = self.by_legacy.get(legacy_key)
        if rec and _is_persistable_description(rec.get("description", "")):
            return rec, "legacy"
        return None, ""


def _populate_description_store_from_csv(store: DescriptionStore) -> None:
    path = _descriptions_path()
    if not path.is_file():
        return

    try:
        df = pd.read_csv(str(path), dtype=str, keep_default_na=False)
    except Exception:
        return

    required = {"JOB_KEY", "description", "last_updated"}
    if not required.issubset(set(df.columns)):
        return

    for _, row in df.iterrows():
        legacy_key = str(row.get("JOB_KEY", "")).strip()
        if not legacy_key:
            continue
        desc = str(row.get("description", ""))
        if not _is_persistable_description(desc):
            continue
        ts = str(row.get("last_updated", "")).strip()
        src = str(row.get("source", "")).strip() if "source" in df.columns else ""
        v2 = ""
        if "JOB_KEY_V2" in df.columns:
            v2 = str(row.get("JOB_KEY_V2", "") or "").strip()

        record = {
            "description": desc,
            "last_updated": ts,
            "source": src,
            "job_key": legacy_key,
            "job_key_v2": v2,
        }
        store.put(legacy_key=legacy_key, v2_key=v2, record=record)


def load_description_store() -> DescriptionStore:
    """
    Load description cache into V2-primary and legacy indexes.

    When SQLITE_PIPELINE_READ=1, reads from job_descriptions table; CSV fallback on error
    or empty DB cache.
    """
    store = DescriptionStore()
    from db.read.engine import pipeline_read_enabled

    if pipeline_read_enabled():
        try:
            from db.read.description_store import load_description_store_from_db

            load_description_store_from_db(store)
            if store.by_v2 or store.by_legacy:
                print("  Pipeline description store: SQLite (SQLITE_PIPELINE_READ=1)")
                return store
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "SQLite description store failed; falling back to CSV"
            )

    _populate_description_store_from_csv(store)
    return store


def flush_description_store(store: DescriptionStore) -> None:
    """Write store to CSV; one row per V2 when present, else per legacy key."""
    from db.write.engine import write_primary_enabled

    if write_primary_enabled():
        return

    seen_legacy: set[str] = set()
    rows: list[dict[str, str]] = []

    for v2_key, rec in store.by_v2.items():
        legacy_key = str(rec.get("job_key", "") or "").strip()
        if not legacy_key:
            legacy_key = v2_key
        seen_legacy.add(legacy_key)
        rows.append(
            {
                "JOB_KEY": legacy_key,
                "JOB_KEY_V2": v2_key,
                "description": rec["description"],
                "last_updated": rec["last_updated"],
                "source": str(rec.get("source", "") or ""),
            }
        )

    for legacy_key, rec in store.by_legacy.items():
        if legacy_key in seen_legacy:
            continue
        rows.append(
            {
                "JOB_KEY": legacy_key,
                "JOB_KEY_V2": str(rec.get("job_key_v2", "") or ""),
                "description": rec["description"],
                "last_updated": rec["last_updated"],
                "source": str(rec.get("source", "") or ""),
            }
        )

    df = pd.DataFrame(rows, columns=job_descriptions_schema_columns())
    df.to_csv(str(_descriptions_path()), index=False)


def _bump_reuse_stats(stats: dict, bucket: str, via: str) -> None:
    stats["reused"] = stats.get("reused", 0) + 1
    stats[f"reused_{bucket}"] = stats.get(f"reused_{bucket}", 0) + 1
    if via:
        stats[f"reused_via_{via}"] = stats.get(f"reused_via_{via}", 0) + 1


def _persist_job_description(
    job: dict,
    store: DescriptionStore,
    stats: dict,
    desc: str,
    *,
    legacy_key: str,
    v2_key: str,
    from_scrape: bool,
) -> None:
    if not _is_persistable_description(desc):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "description": desc.strip(),
        "last_updated": now,
        "source": str(job.get("source", "") or "").strip(),
        "job_key": legacy_key,
        "job_key_v2": v2_key,
    }
    store.put(legacy_key=legacy_key, v2_key=v2_key, record=record)
    job["description"] = desc.strip()
    stats["persisted"] = stats.get("persisted", 0) + 1
    if from_scrape:
        stats["persisted_from_scrape"] = stats.get("persisted_from_scrape", 0) + 1
    else:
        stats["persisted_from_fetch"] = stats.get("persisted_from_fetch", 0) + 1


def _merge_fetched_description(
    original: str, fetched: str, stats: dict
) -> tuple[str, bool]:
    """
    Choose description after HTTP fetch without degrading valid scrape-time text.

    Returns (description_to_use, persist_from_scrape).
    """
    orig = (original or "").strip()
    fch = (fetched or "").strip()
    had_usable_scrape = _is_persistable_description(orig)

    if had_usable_scrape:
        if not _is_persistable_description(fch):
            stats["fetch_would_have_overwritten_valid_description"] = (
                stats.get("fetch_would_have_overwritten_valid_description", 0) + 1
            )
            return orig, True
        if len(fch) > len(orig):
            stats["fetch_improved"] = stats.get("fetch_improved", 0) + 1
            return fch, False
        return orig, True

    if _is_persistable_description(fch):
        if len(fch) > len(orig):
            stats["fetch_improved"] = stats.get("fetch_improved", 0) + 1
        return fch, False

    return orig or fch, False


def ensure_description_for_job(
    job: dict,
    store: DescriptionStore,
    stats: dict,
    *,
    bucket: str = "brand_new",
) -> None:
    """
    V2-primary cache lookup; legacy fallback; fetch on miss.

    InstaHyre (and other sources): persist valid scrape-time descriptions before
    generic HTTP fetch. Never replace a persistable scrape description with empty,
    shorter, or non-persistable fetch output.
    """
    legacy_key = _job_key_legacy(job)
    v2_key = _job_key_v2(job)

    rec, via = store.resolve(job)
    if rec:
        job["description"] = rec["description"]
        _bump_reuse_stats(stats, bucket, via)
        _log_description_action("reuse", bucket=bucket, legacy_key=legacy_key, v2_key=v2_key, via=via)
        return

    scrape_desc = str(job.get("description") or "")
    if _is_persistable_description(scrape_desc):
        stats["scrape_description_usable"] = stats.get("scrape_description_usable", 0) + 1
        _persist_job_description(
            job,
            store,
            stats,
            scrape_desc,
            legacy_key=legacy_key,
            v2_key=v2_key,
            from_scrape=True,
        )
        _log_description_action(
            "persist_scrape",
            bucket=bucket,
            legacy_key=legacy_key,
            v2_key=v2_key,
        )
        return

    original = scrape_desc
    stats["fetch_attempted"] = stats.get("fetch_attempted", 0) + 1
    fetch_job_description(job)
    stats["fetched"] = stats.get("fetched", 0) + 1
    _log_description_action("fetch", bucket=bucket, legacy_key=legacy_key, v2_key=v2_key)

    merged, from_scrape = _merge_fetched_description(
        original, str(job.get("description") or ""), stats
    )
    job["description"] = merged
    if _is_persistable_description(merged):
        _persist_job_description(
            job,
            store,
            stats,
            merged,
            legacy_key=legacy_key,
            v2_key=v2_key,
            from_scrape=from_scrape,
        )


def try_hydrate_from_store(
    job: dict,
    store: DescriptionStore,
    stats: dict,
    *,
    bucket: str = "needs_ai_only",
) -> None:
    """Read-only V2-primary hydrate for needs_ai_only jobs (no fetch)."""
    if _is_persistable_description(job.get("description", "")):
        return

    legacy_key = _job_key_legacy(job)
    v2_key = _job_key_v2(job)
    rec, via = store.resolve(job)
    if not rec:
        return

    job["description"] = rec["description"]
    _bump_reuse_stats(stats, bucket, via)
    _log_description_action("hydrate", bucket=bucket, legacy_key=legacy_key, v2_key=v2_key, via=via)
