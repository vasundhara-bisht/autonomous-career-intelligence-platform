"""Dashboard data loaders (Phase D1: SQLITE_READ with CSV fallback)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

import paths
from db.bootstrap import ensure_database_ready
from db.read.engine import (
    dashboard_read_enabled,
    get_dashboard_read_session,
    warn_if_sqlite_read_without_enabled,
)
from db.read.crm import load_active_recruiters_view_df
from db.read.export_cohort import load_jobs_csv_aligned_view_df
from db.read.historical import load_historical_jobs_view_df
from db.read.transforms import apply_dashboard_job_ai_columns
from db.read.views import assert_read_views_present

_log = logging.getLogger(__name__)

_loader_diagnostics: dict[str, Any] = {
    "jobs_source": "csv",
    "historical_source": "csv",
    "crm_source": "csv",
    "outreach_source": "csv",
    "jobs_csv_fallback_rows": 0,
    "historical_full_csv_fallback": False,
    "crm_full_csv_fallback": False,
}


def reset_loader_diagnostics() -> None:
    _loader_diagnostics.update(
        {
            "jobs_source": "csv",
            "historical_source": "csv",
            "crm_source": "csv",
            "outreach_source": "csv",
            "jobs_csv_fallback_rows": 0,
            "historical_full_csv_fallback": False,
            "crm_full_csv_fallback": False,
        }
    )


def get_loader_diagnostics() -> dict[str, Any]:
    return dict(_loader_diagnostics)


def _normalize_jobs_export_columns(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = [
        "title",
        "company",
        "location",
        "score",
        "link",
        "hiring_manager",
        "time_posted",
        "source",
    ]
    out = df.copy()
    for col in required_cols:
        if col not in out.columns:
            out[col] = "Unknown"

    if "source" not in out.columns:
        out["source"] = "unknown"

    if "time_posted" not in out.columns:
        out["time_posted"] = "Unknown"
    else:
        out["time_posted"] = out["time_posted"].fillna("Unknown")

    if "hiring_manager" not in out.columns:
        out["hiring_manager"] = "Not Specified"
    else:
        out["hiring_manager"] = out["hiring_manager"].fillna("Not Specified")

    if "JOB_KEY_V2" not in out.columns:
        out["JOB_KEY_V2"] = ""
    else:
        out["JOB_KEY_V2"] = out["JOB_KEY_V2"].fillna("").astype(str)

    return apply_dashboard_job_ai_columns(out)


def _load_jobs_from_csv() -> pd.DataFrame:
    df = pd.read_csv(str(paths.jobs_csv()))
    return _normalize_jobs_export_columns(df)


def _load_jobs_from_sqlite() -> pd.DataFrame:
    ensure_database_ready()
    with get_dashboard_read_session() as session:
        assert_read_views_present(session)
        df, fallback_count = load_jobs_csv_aligned_view_df(session, paths.jobs_csv())
    _loader_diagnostics["jobs_csv_fallback_rows"] = fallback_count
    if df.empty and paths.jobs_csv().is_file() and paths.jobs_csv().stat().st_size > 0:
        _log.warning(
            "SQLite jobs read returned empty; falling back to full jobs.csv"
        )
        return _load_jobs_from_csv()
    return _normalize_jobs_export_columns(df)


def load_dashboard_jobs_df() -> pd.DataFrame:
    """Session export frame (jobs.csv shape) for dashboard metrics."""
    warn_if_sqlite_read_without_enabled()

    if not dashboard_read_enabled():
        return _load_jobs_from_csv()

    try:
        df = _load_jobs_from_sqlite()
        _loader_diagnostics["jobs_source"] = "sqlite"
        return df
    except Exception:
        _log.exception("Dashboard SQLite jobs load failed; using jobs.csv")
        return _load_jobs_from_csv()


def _normalize_historical_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    out.columns = out.columns.str.strip()
    out.rename(
        columns={
            "job_key": "JOB_KEY",
            "Job_Key": "JOB_KEY",
            "APPLIED": "applied",
            "REJECTED": "rejected",
        },
        inplace=True,
    )
    if "currently_active" in out.columns:
        out["currently_active"] = (
            out["currently_active"]
            .astype(str)
            .str.lower()
            .isin(("true", "1", "yes"))
        )
    return out


def _load_historical_from_csv() -> pd.DataFrame:
    historical_path = paths.historical_jobs_csv()
    if not historical_path.is_file():
        return _empty_historical_df()

    df = pd.read_csv(str(historical_path))
    return _normalize_historical_columns(df)


def _empty_historical_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "JOB_KEY",
            "applied",
            "rejected",
            "interview",
            "offer",
            "pipeline_stage",
            "notes",
        ]
    )


def _load_historical_from_sqlite() -> pd.DataFrame:
    ensure_database_ready()
    with get_dashboard_read_session() as session:
        assert_read_views_present(session)
        df = load_historical_jobs_view_df(session)

    df = _normalize_historical_columns(df)
    csv_df = _load_historical_from_csv()
    if df.empty and not csv_df.empty:
        _log.warning(
            "SQLite historical_jobs_view empty but CSV has rows; using historical_jobs.csv"
        )
        _loader_diagnostics["historical_full_csv_fallback"] = True
        return csv_df

    return df


def load_dashboard_historical_df() -> pd.DataFrame:
    """Historical memory frame for dashboard listing and pipeline merge."""
    warn_if_sqlite_read_without_enabled()

    if not dashboard_read_enabled():
        try:
            return _load_historical_from_csv()
        except Exception:
            _log.exception("Failed to load historical_jobs.csv")
            return _empty_historical_df()

    try:
        df = _load_historical_from_sqlite()
        _loader_diagnostics["historical_source"] = "sqlite"
        return df
    except Exception:
        _log.exception(
            "Dashboard SQLite historical load failed; using historical_jobs.csv"
        )
        try:
            return _load_historical_from_csv()
        except Exception:
            return _empty_historical_df()


def apply_historical_display_columns(df: pd.DataFrame) -> pd.DataFrame:
    """AI columns for dashboard display; preserves posted_at_date for Posted UI."""
    if df.empty:
        return df

    return apply_dashboard_job_ai_columns(df.copy())


def _empty_recruiter_crm_df() -> pd.DataFrame:
    from agent.bootstrap_schema import RECRUITER_CRM_SCHEMA_COLUMNS

    return pd.DataFrame(columns=list(RECRUITER_CRM_SCHEMA_COLUMNS))


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    """Coerce SQLite ints, Python bools, and string literals to bool."""
    if series.empty:
        return pd.Series(dtype=bool)

    def _one(value: object) -> bool:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return bool(int(value))
        text = str(value).strip().lower()
        if text in {"", "nan", "none", "null"}:
            return False
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
        return False

    return series.map(_one).astype(bool)


def normalize_recruiter_crm_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize CRM frame dtypes for dashboard display and save."""
    if df.empty:
        return _empty_recruiter_crm_df()

    out = df.copy()
    out.columns = out.columns.str.strip()

    out["notes"] = out["notes"].fillna("").astype(str)
    out["recruiter_stage"] = out["recruiter_stage"].fillna("discovered").astype(str)

    for col in ("outreach_sent", "recruiter_replied", "currently_active"):
        if col in out.columns:
            out[col] = _coerce_bool_series(out[col])

    _crm_interaction_defaults = {
        "last_outreach_date": "",
        "last_response_date": "",
        "touchpoint_count": 0,
        "last_interaction_note": "",
        "recruiter_title": "",
        "recruiter_company": "",
    }
    for col, default_value in _crm_interaction_defaults.items():
        if col not in out.columns:
            out[col] = default_value

    out["last_outreach_date"] = (
        out["last_outreach_date"].fillna("").astype(str).str.strip()
    )
    out["last_response_date"] = (
        out["last_response_date"].fillna("").astype(str).str.strip()
    )
    out["touchpoint_count"] = (
        pd.to_numeric(out["touchpoint_count"], errors="coerce").fillna(0).astype(int)
    )
    out["last_interaction_note"] = (
        out["last_interaction_note"].fillna("").astype(str)
    )
    return out


def _load_recruiter_crm_from_csv() -> pd.DataFrame:
    crm_path = paths.recruiter_crm_csv()
    if not crm_path.is_file():
        return _empty_recruiter_crm_df()
    return normalize_recruiter_crm_columns(pd.read_csv(str(crm_path)))


def _apply_listing_visible_jobs_connected(df: pd.DataFrame, session) -> pd.DataFrame:
    from db.read.monitor_runs import load_recruiter_visible_jobs_connected

    if df.empty:
        return df

    visible_counts = load_recruiter_visible_jobs_connected(session)
    if not visible_counts:
        return df
    out = df.copy()
    key_col = "RECRUITER_KEY" if "RECRUITER_KEY" in out.columns else "recruiter_key"
    if key_col not in out.columns:
        return out
    out["jobs_connected"] = out[key_col].map(
        lambda key: visible_counts.get(str(key or "").strip(), 0)
    )
    return out


def _load_recruiter_crm_from_sqlite() -> pd.DataFrame:
    ensure_database_ready()
    with get_dashboard_read_session() as session:
        assert_read_views_present(session)
        df = load_active_recruiters_view_df(session)
        df = _apply_listing_visible_jobs_connected(df, session)

    df = normalize_recruiter_crm_columns(df)
    csv_df = _load_recruiter_crm_from_csv()
    if df.empty and not csv_df.empty:
        _log.warning(
            "SQLite active_recruiters_view empty but CSV has rows; using recruiter_crm.csv"
        )
        _loader_diagnostics["crm_full_csv_fallback"] = True
        return csv_df
    return df


def load_recruiter_crm_df() -> pd.DataFrame:
    """Recruiter CRM frame for dashboard table and analytics."""
    warn_if_sqlite_read_without_enabled()

    if not dashboard_read_enabled():
        try:
            return _load_recruiter_crm_from_csv()
        except Exception:
            _log.exception("Failed to load recruiter_crm.csv")
            return _empty_recruiter_crm_df()

    try:
        df = _load_recruiter_crm_from_sqlite()
        _loader_diagnostics["crm_source"] = "sqlite"
        return df
    except Exception:
        _log.exception(
            "Dashboard SQLite CRM load failed; using recruiter_crm.csv"
        )
        try:
            return _load_recruiter_crm_from_csv()
        except Exception:
            return _empty_recruiter_crm_df()


def _empty_outreach_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "id",
            "person_name",
            "company",
            "designation",
            "linkedin_url",
            "outreach_channel",
            "outreach_message",
            "date_contacted",
            "follow_up_date",
            "status",
            "notes",
            "opportunity_id",
            "opportunity_url",
            "hiring_signal_type",
            "hiring_signal_url",
            "created_at",
            "updated_at",
        ]
    )


def normalize_outreach_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return _empty_outreach_df()

    out = df.copy()
    out.columns = out.columns.str.strip()
    for col in (
        "person_name",
        "company",
        "designation",
        "linkedin_url",
        "outreach_channel",
        "outreach_message",
        "date_contacted",
        "follow_up_date",
        "status",
        "notes",
        "opportunity_id",
        "opportunity_url",
        "hiring_signal_type",
        "hiring_signal_url",
    ):
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()

    if "id" in out.columns:
        out["id"] = pd.to_numeric(out["id"], errors="coerce").astype("Int64")

    return out


def _load_outreach_from_sqlite() -> pd.DataFrame:
    from db.engine import get_session
    from db.services.outreach_write import load_outreach_attempts_ordered

    ensure_database_ready()
    with get_session() as session:
        rows = load_outreach_attempts_ordered(session)
    if not rows:
        return _empty_outreach_df()
    records = [
        {
            "id": row.id,
            "person_name": row.person_name,
            "company": row.company,
            "designation": row.designation or "",
            "linkedin_url": row.linkedin_url or "",
            "outreach_channel": row.outreach_channel,
            "outreach_message": row.outreach_message or "",
            "date_contacted": row.date_contacted,
            "follow_up_date": row.follow_up_date or "",
            "status": row.status,
            "notes": row.notes or "",
            "opportunity_id": row.opportunity_id or "",
            "opportunity_url": row.opportunity_url or "",
            "hiring_signal_type": row.hiring_signal_type or "",
            "hiring_signal_url": row.hiring_signal_url or "",
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]
    return normalize_outreach_columns(pd.DataFrame.from_records(records))


def load_outreach_df() -> pd.DataFrame:
    """Outreach attempt log for dashboard (SQLite only in V1)."""
    warn_if_sqlite_read_without_enabled()

    if not dashboard_read_enabled():
        return _empty_outreach_df()

    try:
        df = _load_outreach_from_sqlite()
        _loader_diagnostics["outreach_source"] = "sqlite"
        return df
    except Exception:
        _log.exception("Dashboard SQLite outreach load failed")
        return _empty_outreach_df()
