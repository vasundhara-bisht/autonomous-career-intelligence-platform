"""SQLite table truncation for profile-driven reset (D7)."""

from __future__ import annotations

import os
from typing import Literal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import (
    AcquisitionQueryRun,
    AcquisitionRun,
    AiEvaluation,
    Job,
    JobDescription,
    JobObservation,
    QueryCooldownState,
    Recruiter,
    RecruiterJobLink,
    UserJobState,
)

ResetProfileName = Literal["bootstrap", "acquisition", "crm-preserving", "full"]

# Child tables first (FK-safe DELETE order).
_ALL_TABLES: tuple[str, ...] = (
    "job_observations",
    "ai_evaluations",
    "job_descriptions",
    "user_job_state",
    "recruiter_job_links",
    "acquisition_query_runs",
    "jobs",
    "acquisition_runs",
    "recruiters",
    "query_cooldown_state",
)

_PROFILE_TABLES: dict[str, tuple[str, ...]] = {
    "bootstrap": _ALL_TABLES,
    "full": _ALL_TABLES,
    "acquisition": (
        "job_observations",
        "acquisition_query_runs",
        "acquisition_runs",
        "query_cooldown_state",
    ),
    "crm-preserving": (
        "job_observations",
        "ai_evaluations",
        "job_descriptions",
        "user_job_state",
        "acquisition_query_runs",
        "jobs",
        "acquisition_runs",
        "query_cooldown_state",
    ),
}

_MODEL_BY_TABLE = {
    "job_observations": JobObservation,
    "ai_evaluations": AiEvaluation,
    "job_descriptions": JobDescription,
    "user_job_state": UserJobState,
    "recruiter_job_links": RecruiterJobLink,
    "acquisition_query_runs": AcquisitionQueryRun,
    "jobs": Job,
    "acquisition_runs": AcquisitionRun,
    "recruiters": Recruiter,
    "query_cooldown_state": QueryCooldownState,
}


def sqlite_reset_enabled() -> bool:
    from db.config import sqlite_flag

    return sqlite_flag("SQLITE_ENABLED")


def tables_for_profile(profile: str) -> tuple[str, ...]:
    if profile not in _PROFILE_TABLES:
        raise ValueError(f"unknown reset profile: {profile!r}")
    return _PROFILE_TABLES[profile]


def _table_row_count(session: Session, table: str) -> int:
    model = _MODEL_BY_TABLE[table]
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def truncate_profile_tables(
    profile: str,
    *,
    dry_run: bool = False,
) -> list[str]:
    """
    Delete rows from SQLite product-memory tables for a reset profile.

    Does not remove the database file or Alembic version. No-op when SQLITE_ENABLED=0.
    """
    if not sqlite_reset_enabled():
        return []

    tables = list(tables_for_profile(profile))
    ensure_database_ready()

    with get_session() as session:
        assert isinstance(session, Session)
        session.execute(text("PRAGMA foreign_keys = ON"))
        before = {t: _table_row_count(session, t) for t in tables}
        if dry_run:
            print("SQLite truncate (dry-run):")
            for table in tables:
                print(f"  - {table}: would delete {before[table]} rows")
            return tables

        for table in tables:
            model = _MODEL_BY_TABLE[table]
            session.execute(delete(model))
            print(f"sqlite truncate: {table} ({before[table]} rows)")

        session.commit()

    return tables


def product_table_counts() -> dict[str, int]:
    """Row counts for all MVP product tables (diagnostics)."""
    ensure_database_ready()
    with get_session() as session:
        return {t: _table_row_count(session, t) for t in _ALL_TABLES}
