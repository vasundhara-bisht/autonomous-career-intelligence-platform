"""Read-path session helpers (D0 infrastructure; D1 dashboard reads)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from db.config import sqlite_flag
from db.engine import get_session

_log = logging.getLogger(__name__)
_warned_sqlite_read_without_enabled = False


def read_access_enabled() -> bool:
    """True when SQLite is enabled for read-model / shadow tooling."""
    return sqlite_flag("SQLITE_ENABLED")


def dashboard_read_enabled() -> bool:
    """True when dashboard may read from SQLite (requires SQLITE_ENABLED + SQLITE_READ)."""
    return read_access_enabled() and sqlite_flag("SQLITE_READ")


def pipeline_read_enabled() -> bool:
    """True when acquisition pipeline may read product memory from SQLite (D4)."""
    return read_access_enabled() and sqlite_flag("SQLITE_PIPELINE_READ")


def query_state_read_enabled() -> bool:
    """True when LinkedIn orchestrator reads cooldown state from SQLite (D4 opt-in)."""
    return read_access_enabled() and sqlite_flag("SQLITE_QUERY_STATE_READ")


def dashboard_write_enabled() -> bool:
    """True when Streamlit may persist edits to SQLite (D6)."""
    return dashboard_read_enabled() and sqlite_flag("SQLITE_DASHBOARD_WRITE")


def warn_if_sqlite_read_without_enabled() -> None:
    """Log once when SQLITE_READ=1 but SQLITE_ENABLED is off."""
    global _warned_sqlite_read_without_enabled
    if _warned_sqlite_read_without_enabled:
        return
    if sqlite_flag("SQLITE_READ") and not read_access_enabled():
        _log.warning(
            "SQLITE_READ=1 is ignored until SQLITE_ENABLED=1; dashboard uses CSV."
        )
        _warned_sqlite_read_without_enabled = True


def get_read_session() -> Session:
    if not read_access_enabled():
        raise RuntimeError(
            "SQLite read models require SQLITE_ENABLED=1 (D0 shadow tooling only)."
        )
    return get_session()


def get_dashboard_read_session() -> Session:
    if not dashboard_read_enabled():
        raise RuntimeError(
            "Dashboard SQLite reads require SQLITE_ENABLED=1 and SQLITE_READ=1."
        )
    return get_read_session()
