"""SQLite feature flags and connection settings (scaffolding only)."""

from __future__ import annotations

import os

import paths

# D8B canonical defaults — single source for runtime gate evaluation.
_FLAG_DEFAULTS: dict[str, bool] = {
    "SQLITE_ENABLED": True,
    "SQLITE_DUAL_WRITE": True,
    "SQLITE_READ": True,
    "SQLITE_PIPELINE_READ": True,
    "SQLITE_QUERY_STATE_READ": False,
    "SQLITE_WRITE_PRIMARY": True,
    "SQLITE_EXPORT_JOBS_CSV": True,
    "SQLITE_EXPORT_HISTORICAL_CSV": False,
    "SQLITE_EXPORT_DESCRIPTIONS_CSV": False,
    "SQLITE_EXPORT_CRM_CSV": False,
    "SQLITE_DASHBOARD_WRITE": True,
    "SQLITE_EXPORT_FROM_DB": True,
    "SQLITE_METADATA_HARD_PARITY": False,
    "SQLITE_FAIL_ON_ERROR": False,
}


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def sqlite_flag(name: str) -> bool:
    """Evaluate a SQLite feature flag; unset env uses D8B default from _FLAG_DEFAULTS."""
    if name not in _FLAG_DEFAULTS:
        raise KeyError(f"unknown SQLite flag: {name!r}")
    return _env_truthy(name, default=_FLAG_DEFAULTS[name])


# Module-level constants (evaluated at import; use sqlite_flag() for runtime checks).
SQLITE_ENABLED: bool = sqlite_flag("SQLITE_ENABLED")
SQLITE_DUAL_WRITE: bool = sqlite_flag("SQLITE_DUAL_WRITE")
SQLITE_READ: bool = sqlite_flag("SQLITE_READ")
SQLITE_PIPELINE_READ: bool = sqlite_flag("SQLITE_PIPELINE_READ")
SQLITE_QUERY_STATE_READ: bool = sqlite_flag("SQLITE_QUERY_STATE_READ")
SQLITE_WRITE_PRIMARY: bool = sqlite_flag("SQLITE_WRITE_PRIMARY")
SQLITE_EXPORT_JOBS_CSV: bool = sqlite_flag("SQLITE_EXPORT_JOBS_CSV")
SQLITE_EXPORT_HISTORICAL_CSV: bool = sqlite_flag("SQLITE_EXPORT_HISTORICAL_CSV")
SQLITE_EXPORT_DESCRIPTIONS_CSV: bool = sqlite_flag("SQLITE_EXPORT_DESCRIPTIONS_CSV")
SQLITE_EXPORT_CRM_CSV: bool = sqlite_flag("SQLITE_EXPORT_CRM_CSV")
SQLITE_DASHBOARD_WRITE: bool = sqlite_flag("SQLITE_DASHBOARD_WRITE")


def database_url() -> str:
    """SQLAlchemy URL for the local SQLite database file."""
    db_path = paths.jobs_db()
    return f"sqlite:///{db_path.as_posix()}"


def sqlite_flags_summary() -> dict[str, bool]:
    return {
        "SQLITE_ENABLED": sqlite_flag("SQLITE_ENABLED"),
        "SQLITE_DUAL_WRITE": sqlite_flag("SQLITE_DUAL_WRITE"),
        "SQLITE_READ": sqlite_flag("SQLITE_READ"),
        "SQLITE_PIPELINE_READ": sqlite_flag("SQLITE_PIPELINE_READ"),
        "SQLITE_QUERY_STATE_READ": sqlite_flag("SQLITE_QUERY_STATE_READ"),
        "SQLITE_WRITE_PRIMARY": sqlite_flag("SQLITE_WRITE_PRIMARY"),
        "SQLITE_EXPORT_JOBS_CSV": sqlite_flag("SQLITE_EXPORT_JOBS_CSV"),
        "SQLITE_EXPORT_HISTORICAL_CSV": sqlite_flag("SQLITE_EXPORT_HISTORICAL_CSV"),
        "SQLITE_EXPORT_DESCRIPTIONS_CSV": sqlite_flag("SQLITE_EXPORT_DESCRIPTIONS_CSV"),
        "SQLITE_EXPORT_CRM_CSV": sqlite_flag("SQLITE_EXPORT_CRM_CSV"),
        "SQLITE_DASHBOARD_WRITE": sqlite_flag("SQLITE_DASHBOARD_WRITE"),
    }
