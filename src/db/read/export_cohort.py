"""current_jobs_view and export cohort loaders."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.read.transforms import (
    add_merge_key_column,
    apply_export_transforms,
    merge_keys_from_jobs_frame,
    normalize_key,
)


def load_latest_run_info(session: Session) -> dict[str, object] | None:
    row = session.execute(
        text(
            """
            SELECT run_id, started_at, completed_at, status, notes
            FROM latest_acquisition_run_view
            """
        )
    ).mappings().first()
    return dict(row) if row else None


def load_export_cohort_keys(session: Session) -> set[str]:
    rows = session.execute(
        text("SELECT job_key_v2 FROM current_export_cohort_view")
    ).all()
    return {str(row[0]).strip() for row in rows if row[0]}


def load_current_jobs_view_df(
    session: Session, *, apply_transforms: bool = True
) -> pd.DataFrame:
    df = pd.read_sql_query(text("SELECT * FROM current_jobs_view"), session.bind)
    if "JOB_KEY_V2" in df.columns:
        df["JOB_KEY_V2"] = df["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    if apply_transforms:
        df = apply_export_transforms(df)
    return df


def load_current_jobs_export_source_df(session: Session) -> pd.DataFrame:
    """
    Raw latest-run export source rows from current_jobs_view.

    D2 uses this as the source for jobs.csv generation, then applies
    the same export semantics as legacy save_to_csv().
    """
    return load_current_jobs_view_df(session, apply_transforms=False)


def load_jobs_csv_aligned_view_df(
    session: Session, jobs_csv_path: Path
) -> tuple[pd.DataFrame, int]:
    """
    Load current_jobs_view rows aligned to jobs.csv merge keys.

    Returns (dataframe, csv_fallback_row_count) for keys missing from the view.
    """
    if not jobs_csv_path.is_file() or jobs_csv_path.stat().st_size == 0:
        return pd.DataFrame(), 0

    jobs_csv = pd.read_csv(jobs_csv_path, dtype=str, keep_default_na=False)
    target_keys = merge_keys_from_jobs_frame(jobs_csv)
    if not target_keys:
        return pd.DataFrame(), 0

    view_df = load_current_jobs_view_df(session, apply_transforms=True)
    csv_fallback_count = 0

    if view_df.empty:
        keyed_csv = add_merge_key_column(jobs_csv)
        fallback = keyed_csv[keyed_csv["__merge_key"].isin(target_keys)].copy()
        csv_fallback_count = len(fallback)
        return fallback.drop(columns=["__merge_key"], errors="ignore"), csv_fallback_count

    keyed_view = add_merge_key_column(view_df)
    filtered = keyed_view[keyed_view["__merge_key"].isin(target_keys)].copy()
    found_keys = set(filtered["__merge_key"].astype(str))

    missing_keys = target_keys - {normalize_key(k) for k in found_keys if k}
    if missing_keys:
        keyed_csv = add_merge_key_column(jobs_csv)
        fallback = keyed_csv[keyed_csv["__merge_key"].isin(missing_keys)].copy()
        csv_fallback_count = len(fallback)
        if not fallback.empty:
            fallback = fallback.drop(columns=["__merge_key"], errors="ignore")
            filtered = filtered.drop(columns=["__merge_key"], errors="ignore")
            filtered = pd.concat([filtered, fallback], ignore_index=True)
        else:
            filtered = filtered.drop(columns=["__merge_key"], errors="ignore")
    else:
        filtered = filtered.drop(columns=["__merge_key"], errors="ignore")

    return filtered, csv_fallback_count
