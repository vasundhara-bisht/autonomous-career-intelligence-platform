"""Introspection helpers for D0 read views."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.read.contracts import READ_VIEW_NAMES


def list_read_views(session: Session) -> list[str]:
    rows = session.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name")
    ).all()
    return [str(row[0]) for row in rows]


def missing_read_views(session: Session) -> list[str]:
    present = set(list_read_views(session))
    return [name for name in READ_VIEW_NAMES if name not in present]


def assert_read_views_present(session: Session) -> None:
    missing = missing_read_views(session)
    if missing:
        raise RuntimeError(
            "Missing SQLite read views (run alembic upgrade head): "
            + ", ".join(missing)
        )
