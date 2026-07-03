"""Monitor provider state reads for dashboard (OHM Phase 5)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def load_provider_states(session: Session) -> list[dict[str, object]]:
    rows = session.execute(
        text(
            """
            SELECT
                source,
                health,
                reason,
                detected_at,
                backoff_until,
                consecutive_failures,
                updated_at
            FROM monitor_provider_state
            ORDER BY source ASC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_provider_state_map(session: Session) -> dict[str, dict[str, object]]:
    return {
        str(row.get("source") or "").strip().lower(): row
        for row in load_provider_states(session)
        if row.get("source")
    }
