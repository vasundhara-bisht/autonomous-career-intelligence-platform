"""Listing availability status constants (Scheduler B / lifecycle monitor)."""

from __future__ import annotations

import os

LISTING_STATUS_OPEN = "open"
LISTING_STATUS_CLOSED = "closed"
LISTING_STATUS_REMOVED = "removed"
LISTING_STATUS_CHECK_FAILED = "check_failed"
LISTING_STATUS_MONITOR_EXEMPT = "monitor_exempt"

ALL_LISTING_STATUSES: tuple[str, ...] = (
    LISTING_STATUS_OPEN,
    LISTING_STATUS_CLOSED,
    LISTING_STATUS_REMOVED,
    LISTING_STATUS_CHECK_FAILED,
    LISTING_STATUS_MONITOR_EXEMPT,
)

TERMINAL_LISTING_STATUSES: frozenset[str] = frozenset(
    {LISTING_STATUS_CLOSED, LISTING_STATUS_REMOVED}
)

MONITORABLE_LISTING_STATUSES: frozenset[str] = frozenset(
    {LISTING_STATUS_OPEN, LISTING_STATUS_CHECK_FAILED}
)

SCHEDULER_B_WRITABLE_STATUSES: frozenset[str] = frozenset(
    {
        LISTING_STATUS_OPEN,
        LISTING_STATUS_CLOSED,
        LISTING_STATUS_REMOVED,
        LISTING_STATUS_CHECK_FAILED,
    }
)

CHECK_FAILED_MAX_CONSECUTIVE = 10


def monitor_pause_threshold() -> int:
    """Consecutive check failures before a job is paused out of the monitor cohort."""
    raw = os.environ.get("LIFECYCLE_MONITOR_CHECK_FAILED_PAUSE_THRESHOLD", "").strip()
    if not raw:
        return CHECK_FAILED_MAX_CONSECUTIVE
    try:
        return max(1, int(raw))
    except ValueError:
        return CHECK_FAILED_MAX_CONSECUTIVE


MONITOR_RUN_STATUS_RUNNING = "running"
MONITOR_RUN_STATUS_COMPLETED = "completed"
MONITOR_RUN_STATUS_INTERRUPTED = "interrupted"
MONITOR_RUN_STATUS_FAILED = "failed"
MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED = "skipped_budget_exhausted"

MONITOR_HEALTH_OK = "ok"
MONITOR_HEALTH_DEGRADED = "degraded"

AUTH_HEALTH_OK = "ok"
AUTH_HEALTH_DEGRADED = "degraded"

PROVIDER_HEALTH_OK = "ok"
PROVIDER_HEALTH_DEGRADED = "degraded"
PROVIDER_HEALTH_PROTECTION = "protection"

SYSTEMIC_ALERT_NONE = "none"
SYSTEMIC_ALERT_HIGH_CHECK_FAILED_RATE = "high_check_failed_rate"
SYSTEMIC_ALERT_PROVIDER_PROTECTION = "provider_protection"

CHECK_FAILED_RATE_DEGRADED_THRESHOLD = 0.30
