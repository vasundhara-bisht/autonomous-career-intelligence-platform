"""
Dynamic CSV/JSON schemas for clean-state archive and reset tooling.

Primary: derive columns from persistence/runtime modules.
Fallback: scripts/templates/*.header.csv
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

import paths

_REPO_ROOT = paths.REPO_ROOT
_TEMPLATES_DIR = paths.TEMPLATES_DIR

# Streamlit persists pipeline_stage on historical_jobs (not in persistence writer).
HISTORICAL_UI_EXTENSION_COLUMNS = ["pipeline_stage"]

JOB_STATE_DEFAULT_COLUMNS = ["JOB_KEY", "APPLIED", "REJECTED"]

RECRUITER_CRM_SCHEMA_COLUMNS = [
    "RECRUITER_KEY",
    "recruiter_name",
    "current_company",
    "source",
    "first_seen",
    "last_seen",
    "jobs_connected",
    "recruiter_stage",
    "outreach_sent",
    "recruiter_replied",
    "notes",
    "last_outreach_date",
    "last_response_date",
    "touchpoint_count",
    "last_interaction_note",
    "currently_active",
    "recruiter_title",
    "recruiter_company",
]

LINKEDIN_QUERY_EMPTY_STATE = {
    "last_run_by_query_id": {},
    "domain_rotation_index": 0,
}


def _read_template_header(name: str) -> list[str]:
    path = _TEMPLATES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing fallback template: {path}")
    with open(path, newline="", encoding="utf-8") as f:
        row = next(csv.reader(f), None)
    if not row:
        raise ValueError(f"Empty template header: {path}")
    return [str(c).strip() for c in row]


def historical_jobs_schema_columns(*, include_ui_extensions: bool = True) -> list[str]:
    try:
        from agent.historical_persistence import historical_jobs_schema_columns as _cols

        cols = _cols()
    except Exception:
        cols = _read_template_header("historical_jobs.header.csv")
    if include_ui_extensions:
        for c in HISTORICAL_UI_EXTENSION_COLUMNS:
            if c not in cols:
                cols.append(c)
    return cols


def jobs_csv_schema_columns(*, union_with_existing_file: bool = True) -> list[str]:
    try:
        from agent.main import jobs_csv_schema_columns as _cols

        return _cols(union_with_existing_file=union_with_existing_file)
    except Exception:
        return _read_template_header("jobs.header.csv")


def job_descriptions_schema_columns() -> list[str]:
    try:
        from agent.job_description_persistence import job_descriptions_schema_columns as _cols

        return _cols()
    except Exception:
        return _read_template_header("job_descriptions.header.csv")


def job_state_schema_columns() -> list[str]:
    path = paths.job_state_csv()
    if path.is_file():
        try:
            return pd.read_csv(path, nrows=0).columns.tolist()
        except Exception:
            pass
    try:
        return _read_template_header("job_state.header.csv")
    except Exception:
        return list(JOB_STATE_DEFAULT_COLUMNS)


def recruiter_crm_schema_columns() -> list[str]:
    return list(RECRUITER_CRM_SCHEMA_COLUMNS)


def linkedin_query_empty_state() -> dict:
    return dict(LINKEDIN_QUERY_EMPTY_STATE)


def write_empty_csv(path: str | Path, columns: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def write_empty_json(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def derive_all_reset_schemas(
    *,
    include_ui_extensions: bool = True,
    union_jobs_with_existing: bool = True,
) -> dict[str, Any]:
    """Snapshot of schemas used for reset (for MANIFEST audit)."""
    return {
        "historical_jobs": historical_jobs_schema_columns(
            include_ui_extensions=include_ui_extensions
        ),
        "jobs": jobs_csv_schema_columns(union_with_existing_file=union_jobs_with_existing),
        "job_descriptions": job_descriptions_schema_columns(),
        "job_state": job_state_schema_columns(),
        "recruiter_crm": recruiter_crm_schema_columns(),
        "linkedin_query_state": linkedin_query_empty_state(),
    }


def reset_runtime_files(
    repo_root: str | Path | None = None,
    *,
    include_ui_extensions: bool = True,
    union_jobs_with_existing: bool = False,
    reset_job_state: bool = False,
    reset_linkedin_query_state: bool = True,
) -> dict[str, str]:
    """
    Write header-only runtime files (destructive). Used by reset_state.sh via Python.
    Does NOT touch recruiter_crm.csv or linkedin_auth.json.
    """
    paths.ensure_data_dir()
    written: dict[str, str] = {}

    hist_path = paths.historical_jobs_csv()
    write_empty_csv(
        hist_path,
        historical_jobs_schema_columns(include_ui_extensions=include_ui_extensions),
    )
    written["historical_jobs.csv"] = str(hist_path)

    jobs_path = paths.jobs_csv()
    write_empty_csv(
        jobs_path,
        jobs_csv_schema_columns(union_with_existing_file=union_jobs_with_existing),
    )
    written["jobs.csv"] = str(jobs_path)

    desc_path = paths.job_descriptions_csv()
    write_empty_csv(desc_path, job_descriptions_schema_columns())
    written["job_descriptions.csv"] = str(desc_path)

    if reset_job_state:
        js_path = paths.job_state_csv()
        write_empty_csv(js_path, job_state_schema_columns())
        written["job_state.csv"] = str(js_path)

    if reset_linkedin_query_state:
        lq_path = paths.linkedin_query_state_json()
        write_empty_json(lq_path, linkedin_query_empty_state())
        written[".linkedin_query_state.json"] = str(lq_path)

    return written
