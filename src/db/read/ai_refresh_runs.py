"""AI refresh run reads for dashboard (Refresh AI Evaluations health)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

_AI_REFRESH_RUN_COLUMNS = """
    id AS run_id,
    started_at,
    completed_at,
    status,
    preset,
    cohort_size,
    eligible_count,
    scored_count,
    persist_skipped_count,
    skipped_no_description,
    skipped_by_cap_count,
    batch_failures,
    duration_sec,
    profile_path,
    error_summary
"""


def load_latest_ai_refresh_run_info(session: Session) -> dict[str, object] | None:
    row = session.execute(
        text(
            f"""
            SELECT
                {_AI_REFRESH_RUN_COLUMNS}
            FROM ai_refresh_runs
            WHERE status = 'completed'
              AND completed_at IS NOT NULL
            ORDER BY completed_at DESC, id DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    return dict(row) if row else None


def load_ai_refresh_run_history(
    session: Session, *, limit: int = 100
) -> list[dict[str, object]]:
    rows = session.execute(
        text(
            f"""
            SELECT
                {_AI_REFRESH_RUN_COLUMNS}
            FROM ai_refresh_runs
            ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
            LIMIT :limit
            """
        ),
        {"limit": int(limit)},
    ).mappings().all()
    return [dict(row) for row in rows]
