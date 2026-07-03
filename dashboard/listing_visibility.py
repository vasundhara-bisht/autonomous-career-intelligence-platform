"""Listing-status visibility helpers (TD5 / Product §5A)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from agent.pipeline_stages import is_user_managed_pipeline_stage

LISTING_STATUS_OPEN = "open"
LISTING_STATUS_CLOSED = "closed"
LISTING_STATUS_REMOVED = "removed"
LISTING_STATUS_CHECK_FAILED = "check_failed"
LISTING_STATUS_MONITOR_EXEMPT = "monitor_exempt"

AGE_BUCKET_FRESH = "fresh"
AGE_BUCKET_AGING = "aging"
AGE_BUCKET_STALE = "stale"


def normalize_listing_status(value: object) -> str:
    return str(value or LISTING_STATUS_OPEN).strip().lower() or LISTING_STATUS_OPEN


def derive_age_days(
    *,
    posted_at_date: object,
    first_seen: object,
    reference: date | None = None,
) -> int | None:
    """TD8: posted_at_date primary, first_seen fallback."""
    ref = reference or date.today()
    for candidate in (posted_at_date, first_seen):
        if candidate is None or (isinstance(candidate, float) and pd.isna(candidate)):
            continue
        text = str(candidate).strip()
        if not text or text.lower() in {"nan", "none", "nat"}:
            continue
        if "T" in text:
            text = text.split("T", 1)[0]
        parsed = pd.to_datetime(text[:10], errors="coerce")
        if pd.isna(parsed):
            continue
        seen = parsed.date() if hasattr(parsed, "date") else None
        if seen is None:
            continue
        return max(0, (ref - seen).days)
    return None


def derive_age_bucket(age_days: int | None) -> str | None:
    if age_days is None:
        return None
    if age_days <= 3:
        return AGE_BUCKET_FRESH
    if age_days <= 13:
        return AGE_BUCKET_AGING
    return AGE_BUCKET_STALE


def apply_age_bucket_columns(
    df: pd.DataFrame,
    *,
    reference: date | None = None,
) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    posted = out["posted_at_date"] if "posted_at_date" in out.columns else pd.Series(dtype=object)
    first_seen = out["first_seen"] if "first_seen" in out.columns else pd.Series(dtype=object)
    out["age_days_derived"] = [
        derive_age_days(
            posted_at_date=posted.iloc[i] if len(posted) else None,
            first_seen=first_seen.iloc[i] if len(first_seen) else None,
            reference=reference,
        )
        for i in range(len(out))
    ]
    out["age_bucket"] = out["age_days_derived"].map(derive_age_bucket)
    return out


def listing_status_badge(
    *,
    listing_status: object,
    listing_check_paused_at: object = None,
    consecutive_check_failures: object = None,
) -> str:
    status = normalize_listing_status(listing_status)
    if status == LISTING_STATUS_OPEN:
        return "Open"
    if status == LISTING_STATUS_CLOSED:
        return "Closed"
    if status == LISTING_STATUS_MONITOR_EXEMPT:
        return "Monitor exempt"
    if status == LISTING_STATUS_CHECK_FAILED:
        if listing_check_paused_at is not None and not (
            isinstance(listing_check_paused_at, float) and pd.isna(listing_check_paused_at)
        ):
            return "Check paused"
        return "Check pending"
    if status == LISTING_STATUS_REMOVED:
        return "Removed"
    return status.title()


def format_age_chip(age_bucket: object) -> str:
    bucket = str(age_bucket or "").strip().lower()
    if bucket == AGE_BUCKET_FRESH:
        return "Fresh"
    if bucket == AGE_BUCKET_AGING:
        return "Aging"
    if bucket == AGE_BUCKET_STALE:
        return "Stale"
    return ""


def is_row_visible_for_listing_status(row: pd.Series) -> bool:
    status = normalize_listing_status(row.get("listing_status"))
    if status == LISTING_STATUS_REMOVED:
        return False
    if status == LISTING_STATUS_MONITOR_EXEMPT:
        stage = row.get("pipeline_stage", row.get("Status", "New"))
        return is_user_managed_pipeline_stage(stage)
    return True


def apply_listing_visibility(df: pd.DataFrame) -> pd.DataFrame:
    """Product §5A listing-status visibility.

    Visible: open, closed (all stages), check_failed, monitor_exempt when user-managed.
    Hidden: removed only.
    """
    if df.empty:
        return df
    out = df.copy()
    if "pipeline_stage" not in out.columns:
        out["pipeline_stage"] = "New"
    out["pipeline_stage"] = out["pipeline_stage"].fillna("New").astype(str).str.strip()
    if "listing_status" not in out.columns:
        out["listing_status"] = LISTING_STATUS_OPEN
    visible = out.apply(is_row_visible_for_listing_status, axis=1)
    return out.loc[visible].copy()


def is_listing_open_for_recommended_actions(row: pd.Series) -> bool:
    return normalize_listing_status(row.get("listing_status")) == LISTING_STATUS_OPEN


def format_listing_badge_row(row: pd.Series) -> str:
    return listing_status_badge(
        listing_status=row.get("listing_status"),
        listing_check_paused_at=row.get("listing_check_paused_at"),
        consecutive_check_failures=row.get("consecutive_check_failures"),
    )


def count_check_failed_jobs(
    df: pd.DataFrame,
    *,
    source: str | None = None,
) -> tuple[int, int]:
    """Return (active check_failed, paused check_failed) from a dashboard cohort."""
    if df.empty or "listing_status" not in df.columns:
        return 0, 0
    working = df
    if source is not None and "source" in df.columns:
        src = (source or "").strip().lower()
        working = df[df["source"].astype(str).str.strip().str.lower() == src]
        if working.empty:
            return 0, 0
    statuses = working["listing_status"].map(normalize_listing_status)
    failed = statuses == LISTING_STATUS_CHECK_FAILED
    if "listing_check_paused_at" not in working.columns:
        return int(failed.sum()), 0
    paused = working["listing_check_paused_at"].notna() & (
        working["listing_check_paused_at"].astype(str).str.strip() != ""
    )
    paused_failed = failed & paused
    active_failed = failed & ~paused_failed
    return int(active_failed.sum()), int(paused_failed.sum())
