"""Derive posted_at_date from relative time_posted strings."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

_INVALID_TIME_POSTED = frozenset({"", "unknown", "n/a", "nan", "none"})


def _parse_iso_date(text: str) -> date | None:
    s = text.strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time_posted_to_date(time_posted: str, anchor: date) -> date | None:
    """Convert a relative or compact time_posted string to an ISO calendar date."""
    text = str(time_posted or "").strip()
    if not text or text.lower() in _INVALID_TIME_POSTED:
        return None

    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        parsed = _parse_iso_date(text)
        if parsed is not None:
            return parsed

    lower = text.lower()
    if "just now" in lower:
        return anchor

    if lower.endswith("d") and lower[:-1].isdigit():
        return anchor - timedelta(days=int(lower[:-1]))

    try:
        parts = lower.split()
        if not parts:
            return None
        n = int(parts[0])
        if "hour" in lower or "minute" in lower:
            return anchor
        if "day" in lower:
            return anchor - timedelta(days=n)
        if "week" in lower:
            return anchor - timedelta(days=n * 7)
        if "month" in lower:
            return anchor - timedelta(days=n * 30)
        if "year" in lower:
            return anchor - timedelta(days=n * 365)
    except (ValueError, IndexError):
        return None
    return None


def _has_posted_at_date(job: dict[str, Any]) -> bool:
    val = job.get("posted_at_date")
    return val is not None and str(val).strip() != ""


def derive_posted_at_date(job: dict[str, Any], anchor_date: date) -> dict[str, Any]:
    """
    Return a copy of job with posted_at_date/age_days set when derivable.

    Never overwrites an existing non-empty posted_at_date.
    """
    result = dict(job)
    if _has_posted_at_date(result):
        return result

    time_posted = str(result.get("time_posted") or "").strip()
    parsed = parse_time_posted_to_date(time_posted, anchor_date)
    if parsed is None:
        return result

    result["posted_at_date"] = parsed.isoformat()
    result["age_days"] = max(0, (anchor_date - parsed).days)
    return result
