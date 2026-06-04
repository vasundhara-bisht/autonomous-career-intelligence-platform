"""SQLite persistence foundation (Phase A — no pipeline integration yet)."""

from db.bootstrap import (
    ensure_database_ready,
    print_database_status,
    upgrade_schema,
)
from db.config import (
    SQLITE_DUAL_WRITE,
    SQLITE_ENABLED,
    SQLITE_READ,
    database_url,
    sqlite_flags_summary,
)

__all__ = [
    "SQLITE_ENABLED",
    "SQLITE_DUAL_WRITE",
    "SQLITE_READ",
    "database_url",
    "sqlite_flags_summary",
    "ensure_database_ready",
    "upgrade_schema",
    "print_database_status",
]
