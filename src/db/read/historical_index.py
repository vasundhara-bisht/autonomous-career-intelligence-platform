"""Build historical lookup index from SQLite (D4 pipeline read)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from db.bootstrap import ensure_database_ready
from db.read.engine import get_read_session
from db.read.historical import load_historical_jobs_view_df
from db.read.transforms import format_datetime_for_csv_compare

_log = logging.getLogger(__name__)

_EMPTY_INDEX: dict[str, dict[str, dict[str, Any]]] = {"by_v2": {}, "by_legacy": {}}


def _row_to_historical_dict(row: pd.Series) -> dict[str, Any]:
    """Shape a view row like historical_jobs.csv row dict for lookup_historical_row."""
    out: dict[str, Any] = {}
    for col in row.index:
        val = row[col]
        if col in ("first_seen", "last_seen"):
            out[col] = format_datetime_for_csv_compare(val)
        elif col in ("applied", "rejected", "interview", "offer", "currently_active"):
            if pd.isna(val):
                out[col] = False
            elif isinstance(val, bool):
                out[col] = val
            else:
                text = str(val).strip().lower()
                out[col] = text in ("1", "true", "yes")
        elif col == "ai_score" and not pd.isna(val):
            try:
                out[col] = float(val)
            except (TypeError, ValueError):
                out[col] = val
        elif pd.isna(val):
            out[col] = ""
        else:
            out[col] = val if isinstance(val, (int, float, bool)) else str(val).strip()
    return out


def build_historical_index_from_session(session: Session) -> dict[str, dict[str, dict[str, Any]]]:
    df = load_historical_jobs_view_df(session)
    if df.empty:
        return {"by_v2": {}, "by_legacy": {}}

    by_legacy: dict[str, dict[str, Any]] = {}
    by_v2: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        row_dict = _row_to_historical_dict(row)
        leg = str(row_dict.get("JOB_KEY", "")).strip()
        if leg:
            by_legacy[leg] = row_dict
        v2 = str(row_dict.get("JOB_KEY_V2", "")).strip()
        if v2:
            by_v2[v2] = row_dict
    return {"by_v2": by_v2, "by_legacy": by_legacy}


def load_historical_index_from_db() -> dict[str, dict[str, dict[str, Any]]]:
    """
    Load historical index from historical_jobs_view.

    Returns the same shape as historical_persistence.load_historical_index() CSV path.
    """
    ensure_database_ready()
    with get_read_session() as session:
        return build_historical_index_from_session(session)


def load_historical_index_with_fallback(
    csv_loader,
) -> tuple[dict[str, dict[str, dict[str, Any]]], str]:
    """
    Try SQLite index when pipeline read is enabled; fall back to csv_loader on error.

    Returns (index, source) where source is 'sqlite' or 'csv'.
    """
    from db.read.engine import pipeline_read_enabled

    if not pipeline_read_enabled():
        return csv_loader(), "csv"

    try:
        index = load_historical_index_from_db()
        _log.info(
            "Pipeline historical index: SQLite (v2=%s legacy=%s)",
            len(index.get("by_v2", {})),
            len(index.get("by_legacy", {})),
        )
        return index, "sqlite"
    except Exception:
        _log.exception("SQLite historical index failed; falling back to CSV")
        return csv_loader(), "csv"
