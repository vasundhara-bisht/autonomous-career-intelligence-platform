"""SQLAlchemy declarative base for MVP schema."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata registry for Alembic autogenerate and migrations."""

    pass
