"""Latest evaluation lookups (view-backed)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def fetch_latest_eval_row(session: Session, job_key_v2: str) -> dict[str, object] | None:
    row = session.execute(
        text(
            """
            SELECT job_id, job_key_v2, ai_status, ai_score, reason, model, evaluated_at, run_id
            FROM latest_ai_evaluations_view
            WHERE job_key_v2 = :key
            """
        ),
        {"key": job_key_v2},
    ).mappings().first()
    return dict(row) if row else None
