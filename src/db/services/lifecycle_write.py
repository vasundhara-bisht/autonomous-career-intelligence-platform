"""Atomic listing_status updates for Scheduler B (transition guards per TD2 / §4.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from db.listing_status import (
    CHECK_FAILED_MAX_CONSECUTIVE,
    LISTING_STATUS_CHECK_FAILED,
    LISTING_STATUS_CLOSED,
    LISTING_STATUS_MONITOR_EXEMPT,
    LISTING_STATUS_REMOVED,
    SCHEDULER_B_WRITABLE_STATUSES,
    TERMINAL_LISTING_STATUSES,
)
from db.models.schema import Job

SkipReason = Literal[
    "terminal_state",
    "illegal_reopen",
    "invalid_target_status",
    "already_monitor_exempt",
]


@dataclass(frozen=True)
class ListingWriteResult:
    applied: bool
    skipped: bool
    skip_reason: SkipReason | None = None


def normalize_listing_status(status: object) -> str:
    return str(status or "").strip().lower()


def is_terminal_listing_status(status: object) -> bool:
    return normalize_listing_status(status) in TERMINAL_LISTING_STATUSES


def validate_scheduler_b_transition(
    current_status: object, target_status: object
) -> ListingWriteResult | None:
    """Return a skip result when the transition must not be applied."""
    current = normalize_listing_status(current_status)
    target = normalize_listing_status(target_status)

    if target not in SCHEDULER_B_WRITABLE_STATUSES:
        return ListingWriteResult(applied=False, skipped=True, skip_reason="invalid_target_status")

    if current in TERMINAL_LISTING_STATUSES:
        return ListingWriteResult(applied=False, skipped=True, skip_reason="terminal_state")

    return None


def apply_scheduler_b_outcome(
    session: Session,
    job: Job,
    *,
    listing_status: str,
    listing_status_reason: str | None,
    attempted_at: datetime,
    classification_succeeded: bool,
) -> ListingWriteResult:
    """
  Apply a Scheduler B classification outcome to a job row.

  classification_succeeded=False → check_failed attempt semantics (no listing_checked_at).
  classification_succeeded=True → successful parse (open/closed/removed); sets listing_checked_at.
    """
    target = normalize_listing_status(listing_status)
    skip = validate_scheduler_b_transition(job.listing_status, target)
    if skip is not None:
        return skip

    reason = (listing_status_reason or "").strip() or None
    job.listing_check_attempted_at = attempted_at

    if not classification_succeeded or target == LISTING_STATUS_CHECK_FAILED:
        job.listing_status = LISTING_STATUS_CHECK_FAILED
        job.listing_status_reason = reason
        failures = int(job.consecutive_check_failures or 0) + 1
        job.consecutive_check_failures = failures
        if failures >= CHECK_FAILED_MAX_CONSECUTIVE and job.listing_check_paused_at is None:
            job.listing_check_paused_at = attempted_at
        session.flush()
        return ListingWriteResult(applied=True, skipped=False)

    job.listing_status = target
    job.listing_status_reason = reason
    job.listing_checked_at = attempted_at
    job.consecutive_check_failures = 0
    job.listing_check_paused_at = None

    if target == LISTING_STATUS_CLOSED and job.listing_closed_at is None:
        job.listing_closed_at = attempted_at
    if target == LISTING_STATUS_REMOVED and job.listing_removed_at is None:
        job.listing_removed_at = attempted_at

    session.flush()
    return ListingWriteResult(applied=True, skipped=False)


def set_monitor_exempt(session: Session, job: Job, *, updated_at: datetime | None = None) -> ListingWriteResult:
    """CRM hook: idempotent promotion to monitor_exempt (§3.5)."""
    current = normalize_listing_status(job.listing_status)
    if current == LISTING_STATUS_MONITOR_EXEMPT:
        return ListingWriteResult(applied=False, skipped=True, skip_reason="already_monitor_exempt")

    if current in TERMINAL_LISTING_STATUSES:
        return ListingWriteResult(applied=False, skipped=True, skip_reason="terminal_state")

    job.listing_status = LISTING_STATUS_MONITOR_EXEMPT
    job.listing_status_reason = None
    if updated_at is not None:
        job.listing_check_attempted_at = updated_at
    session.flush()
    return ListingWriteResult(applied=True, skipped=False)
