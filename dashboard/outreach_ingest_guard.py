"""Outreach ingest guards: duplicate detection and save confirmation state."""

from __future__ import annotations

from typing import Any

import pandas as pd

from date_display import format_dashboard_date
from outreach_status import outreach_status_label

try:
    from outreach.linkedin_post_url import LinkedInPostUrlError, validate_linkedin_post_url
except ImportError:  # pragma: no cover - dashboard path setup in tests
    LinkedInPostUrlError = ValueError  # type: ignore[misc, assignment]

    def validate_linkedin_post_url(url: str) -> str:
        raise LinkedInPostUrlError("LinkedIn post validation unavailable.")

_SAVE_SUCCESS_PENDING_KEY = "outreach_save_success_pending"
_DUPLICATE_RECORD_KEY = "outreach_duplicate_hiring_signal"
_FOCUS_RECORD_KEY = "outreach_focus_record_id"
SAVE_SUCCESS_MESSAGE = "✓ Outreach saved successfully"


def normalize_hiring_signal_url_for_match(url: str) -> str:
    """Canonicalize hiring signal URLs for duplicate comparison."""
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        canonical = validate_linkedin_post_url(text)
        return canonical.split("?")[0].rstrip("/").lower()
    except LinkedInPostUrlError:
        return text.rstrip("/").lower()


def find_existing_outreach_by_hiring_signal_url(
    outreach_df: pd.DataFrame,
    signal_url: str,
) -> dict[str, Any] | None:
    """Return the first outreach row matching ``signal_url``, if any."""
    target = normalize_hiring_signal_url_for_match(signal_url)
    if not target or outreach_df.empty or "hiring_signal_url" not in outreach_df.columns:
        return None
    for _, row in outreach_df.iterrows():
        stored = str(row.get("hiring_signal_url") or "").strip()
        if not stored:
            continue
        if normalize_hiring_signal_url_for_match(stored) == target:
            return row.to_dict()
    return None


def should_fetch_hiring_signal_details(
    outreach_df: pd.DataFrame,
    signal_url: str,
) -> bool:
    """Return False when the hiring signal URL already exists in outreach records."""
    return find_existing_outreach_by_hiring_signal_url(outreach_df, signal_url) is None


def find_existing_outreach_by_opportunity_id(
    outreach_df: pd.DataFrame,
    job_key_v2: str,
) -> dict[str, Any] | None:
    """Return the first outreach row whose opportunity_id matches job_key_v2, if any.

    Used for Job Outreach duplicate detection. Does not affect Hiring Signal
    duplicate detection (which operates on hiring_signal_url).
    """
    target = str(job_key_v2 or "").strip()
    if not target or outreach_df.empty or "opportunity_id" not in outreach_df.columns:
        return None
    for _, row in outreach_df.iterrows():
        stored = str(row.get("opportunity_id") or "").strip()
        if stored and stored == target:
            return row.to_dict()
    return None


def format_outreach_created_at(value: object) -> str:
    return format_dashboard_date(value)


def existing_outreach_record_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "").strip()
    return {
        "id": int(row["id"]),
        "person_name": str(row.get("person_name") or "").strip(),
        "company": str(row.get("company") or "").strip(),
        "status": status,
        "status_label": outreach_status_label(status) if status else "Not set",
        "created_at": format_outreach_created_at(row.get("created_at")),
    }


def duplicate_hiring_signal_warning_lines(record: dict[str, Any]) -> list[str]:
    snapshot = existing_outreach_record_snapshot(record)
    return [
        "This hiring signal already exists.",
        f"Person: {snapshot['person_name']}",
        f"Company: {snapshot['company']}",
        f"Existing outreach status: {snapshot['status_label']}",
        f"Creation date: {snapshot['created_at']}",
    ]


def _session_get(session_state: object, key: str, default: object = "") -> object:
    if isinstance(session_state, dict):
        return session_state.get(key, default)
    return getattr(session_state, key, default)


def _session_set(session_state: object, key: str, value: object) -> None:
    if isinstance(session_state, dict):
        session_state[key] = value
    else:
        setattr(session_state, key, value)


def _session_delete(session_state: object, key: str) -> None:
    if isinstance(session_state, dict):
        session_state.pop(key, None)
        return
    if hasattr(session_state, key):
        delattr(session_state, key)


def request_outreach_save_success(session_state: object) -> None:
    _session_set(session_state, _SAVE_SUCCESS_PENDING_KEY, True)


def consume_outreach_save_success(session_state: object) -> bool:
    """Return True once after save, then clear the pending flag."""
    if not _session_get(session_state, _SAVE_SUCCESS_PENDING_KEY, False):
        return False
    _session_set(session_state, _SAVE_SUCCESS_PENDING_KEY, False)
    return True


def store_duplicate_hiring_signal(session_state: object, record: dict[str, Any]) -> None:
    _session_set(
        session_state,
        _DUPLICATE_RECORD_KEY,
        existing_outreach_record_snapshot(record),
    )


def get_duplicate_hiring_signal(session_state: object) -> dict[str, Any] | None:
    value = _session_get(session_state, _DUPLICATE_RECORD_KEY, None)
    return value if isinstance(value, dict) else None


def clear_duplicate_hiring_signal(session_state: object) -> None:
    _session_delete(session_state, _DUPLICATE_RECORD_KEY)


def request_open_existing_outreach_record(session_state: object, record_id: int) -> None:
    _session_set(session_state, _FOCUS_RECORD_KEY, int(record_id))
    clear_duplicate_hiring_signal(session_state)


def get_focus_outreach_record_id(session_state: object) -> int | None:
    value = _session_get(session_state, _FOCUS_RECORD_KEY, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clear_focus_outreach_record(session_state: object) -> None:
    _session_delete(session_state, _FOCUS_RECORD_KEY)
