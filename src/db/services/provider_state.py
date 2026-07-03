"""Monitor provider state persistence (OHM Phase 2 / Phase 4 backoff)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.listing_status import PROVIDER_HEALTH_OK, PROVIDER_HEALTH_PROTECTION
from db.models.schema import MonitorProviderState
from db.services.monitor_governance import compute_backoff_until

MONITORED_PROVIDER_SOURCES: tuple[str, ...] = ("linkedin", "instahyre")


def get_provider_state(session: Session, source: str) -> MonitorProviderState | None:
    src = (source or "").strip().lower()
    return session.execute(
        select(MonitorProviderState).where(MonitorProviderState.source == src)
    ).scalar_one_or_none()


def is_provider_backoff_active(
    row: MonitorProviderState | None,
    *,
    now: datetime,
) -> bool:
    """Return True when provider backoff cooldown is still in effect."""
    if row is None or row.backoff_until is None:
        return False
    return row.backoff_until > now


def record_provider_protection(
    session: Session,
    *,
    source: str,
    reason: str,
    detected_at: datetime,
    backoff_base_hours: int = 6,
    backoff_max_hours: int = 48,
) -> MonitorProviderState:
    """Persist provider protection with exponential backoff (OHM Phase 4)."""
    src = (source or "").strip().lower()
    row = get_provider_state(session, src)
    if row is None:
        row = MonitorProviderState(source=src)
        session.add(row)

    failures = int(row.consecutive_failures or 0) + 1
    row.health = PROVIDER_HEALTH_PROTECTION
    row.reason = reason
    row.detected_at = detected_at
    row.updated_at = detected_at
    row.consecutive_failures = failures
    row.backoff_until = compute_backoff_until(
        consecutive_failures=failures,
        detected_at=detected_at,
        base_hours=backoff_base_hours,
        max_hours=backoff_max_hours,
    )
    session.flush()
    return row


def clear_provider_state_on_recovery(
    session: Session,
    *,
    source: str,
    recovered_at: datetime,
) -> None:
    """Clear protection state after a successful auth/protection probe."""
    src = (source or "").strip().lower()
    row = get_provider_state(session, src)
    if row is None:
        return
    row.health = PROVIDER_HEALTH_OK
    row.reason = None
    row.detected_at = None
    row.backoff_until = None
    row.consecutive_failures = 0
    row.updated_at = recovered_at
    session.flush()
