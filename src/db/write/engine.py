"""Write-primary feature flags (D5)."""

from __future__ import annotations

import os

from db.config import sqlite_flag


def write_primary_enabled() -> bool:
    """True when SQLite dual-write is authoritative and CSV persistence writes are gated."""
    return (
        sqlite_flag("SQLITE_ENABLED")
        and sqlite_flag("SQLITE_DUAL_WRITE")
        and sqlite_flag("SQLITE_WRITE_PRIMARY")
    )


def export_jobs_csv_enabled() -> bool:
    """Gate jobs.csv export (D2 path). Falls back to SQLITE_EXPORT_FROM_DB when unset."""
    if not sqlite_flag("SQLITE_ENABLED"):
        return True
    if sqlite_flag("SQLITE_WRITE_PRIMARY"):
        return sqlite_flag("SQLITE_EXPORT_JOBS_CSV")
    raw = os.environ.get("SQLITE_EXPORT_JOBS_CSV")
    if raw is not None:
        return sqlite_flag("SQLITE_EXPORT_JOBS_CSV")
    return sqlite_flag("SQLITE_EXPORT_FROM_DB")


def export_historical_csv_enabled() -> bool:
    return sqlite_flag("SQLITE_EXPORT_HISTORICAL_CSV")


def export_descriptions_csv_enabled() -> bool:
    return sqlite_flag("SQLITE_EXPORT_DESCRIPTIONS_CSV")


def export_crm_csv_enabled() -> bool:
    return sqlite_flag("SQLITE_EXPORT_CRM_CSV")
