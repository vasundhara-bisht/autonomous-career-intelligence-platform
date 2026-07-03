"""Acquisition run reads for dashboard (Acquisition Health section)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

INSTAHYRE_INTERESTED_SYNC_NOTES = "instahyre_interested_sync"
MAIN_ACQUISITION_NOTES = "phase_c_runtime_dual_write"
INTERESTED_SYNC_LINK_WINDOW_HOURS = 12

_ACQUISITION_RUN_DASHBOARD_COLUMNS = """
    ar.id AS run_id,
    ar.started_at,
    ar.completed_at,
    ar.status,
    ar.run_trigger,
    ar.notes,
    COALESCE(obs.jobs_discovered, 0) AS jobs_discovered,
    COALESCE(obs.new_jobs, 0) AS new_jobs,
    COALESCE(obs.existing_jobs, 0) AS existing_jobs,
    COALESCE(src.sources_run, 0) AS sources_run,
    src.sources_list AS sources_list
"""

_ACQUISITION_RUN_FROM = """
    FROM acquisition_runs ar
    LEFT JOIN (
        SELECT
            run_id,
            COUNT(DISTINCT job_id) AS jobs_discovered,
            SUM(CASE WHEN times_seen = 1 THEN 1 ELSE 0 END) AS new_jobs,
            SUM(CASE WHEN times_seen > 1 THEN 1 ELSE 0 END) AS existing_jobs
        FROM job_observations
        GROUP BY run_id
    ) obs ON obs.run_id = ar.id
    LEFT JOIN (
        SELECT
            run_id,
            COUNT(DISTINCT source) AS sources_run,
            GROUP_CONCAT(DISTINCT source) AS sources_list
        FROM (
            SELECT run_id, source
            FROM acquisition_query_runs
            WHERE source IS NOT NULL AND TRIM(source) != ''
            UNION
            SELECT run_id, source
            FROM job_observations
            WHERE source IS NOT NULL AND TRIM(source) != ''
        ) s
        GROUP BY run_id
    ) src ON src.run_id = ar.id
"""


def acquisition_run_type(notes: object) -> str:
    text_value = str(notes or "").strip()
    if text_value == INSTAHYRE_INTERESTED_SYNC_NOTES:
        return "instahyre_interested_sync"
    if text_value == MAIN_ACQUISITION_NOTES:
        return "main"
    if text_value:
        return text_value
    return "main"


def _parse_started_at(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text_value, fmt)
        except ValueError:
            continue
    return None


def group_acquisition_runs_for_dashboard(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """
    Fold instahyre_interested_sync rows into the following main acquisition run.

    Persistence rows are unchanged; this is a read-layer presentation grouping only.
    """
    if not rows:
        return []

    interested_rows = [
        row
        for row in rows
        if str(row.get("notes") or "") == INSTAHYRE_INTERESTED_SYNC_NOTES
    ]
    parent_rows = [
        row
        for row in rows
        if str(row.get("notes") or "") != INSTAHYRE_INTERESTED_SYNC_NOTES
    ]
    attached_interested_ids: set[int] = set()
    grouped: list[dict[str, object]] = []

    for parent in parent_rows:
        grouped_parent = dict(parent)
        grouped_parent["run_type"] = acquisition_run_type(parent.get("notes"))
        grouped_parent["interested_sync"] = None

        parent_started = _parse_started_at(parent.get("started_at"))
        if parent_started is not None:
            candidates: list[tuple[float, dict[str, object]]] = []
            for interested in interested_rows:
                interested_id = int(interested.get("run_id") or 0)
                if interested_id in attached_interested_ids:
                    continue
                interested_started = _parse_started_at(interested.get("started_at"))
                if interested_started is None:
                    continue
                delta = parent_started - interested_started
                if timedelta(0) <= delta <= timedelta(hours=INTERESTED_SYNC_LINK_WINDOW_HOURS):
                    candidates.append((delta.total_seconds(), interested))
            if candidates:
                candidates.sort(key=lambda item: item[0])
                sync_row = dict(candidates[0][1])
                attached_interested_ids.add(int(sync_row.get("run_id") or 0))
                sync_row["run_type"] = "instahyre_interested_sync"
                grouped_parent["interested_sync"] = sync_row

        grouped.append(grouped_parent)

    return grouped


def _load_acquisition_run_rows(session: Session, *, limit: int) -> list[dict[str, object]]:
    rows = session.execute(
        text(
            f"""
            SELECT
                {_ACQUISITION_RUN_DASHBOARD_COLUMNS}
            {_ACQUISITION_RUN_FROM}
            ORDER BY COALESCE(ar.completed_at, ar.started_at) DESC, ar.id DESC
            LIMIT :limit
            """
        ),
        {"limit": int(limit)},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_latest_acquisition_run_dashboard_info(session: Session) -> dict[str, object] | None:
    rows = session.execute(
        text(
            f"""
            SELECT
                {_ACQUISITION_RUN_DASHBOARD_COLUMNS}
            {_ACQUISITION_RUN_FROM}
            WHERE ar.status = 'completed'
              AND ar.completed_at IS NOT NULL
            ORDER BY ar.completed_at DESC, ar.id DESC
            LIMIT 25
            """
        )
    ).mappings().all()
    grouped = group_acquisition_runs_for_dashboard([dict(row) for row in rows])
    for row in grouped:
        if str(row.get("notes") or "") != INSTAHYRE_INTERESTED_SYNC_NOTES:
            return row
    return grouped[0] if grouped else None


def load_acquisition_run_history(session: Session, *, limit: int = 100) -> list[dict[str, object]]:
    """Grouped acquisition runs for dashboard history (interested sync folded into parent)."""
    rows = _load_acquisition_run_rows(session, limit=limit)
    return group_acquisition_runs_for_dashboard(rows)
