"""Normalize DB read rows toward CSV/dashboard semantics."""

from __future__ import annotations

import pandas as pd


def is_bangalore_priority(location: object) -> bool:
    if pd.isna(location):
        return False
    loc = str(location).lower()
    return any(token in loc for token in ("bangalore", "karnataka"))


def apply_export_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror save_to_csv rules used for jobs.csv export shape."""
    if df.empty:
        return df

    out = df.copy()
    if "location" in out.columns:
        out["location"] = out["location"].fillna("Unknown")
        out["location"] = out["location"].apply(
            lambda x: x.replace("Bengaluru", "Bangalore")
            if isinstance(x, str)
            else x
        )
        out["priority"] = out["location"].apply(is_bangalore_priority)
    else:
        out["priority"] = False

    if "ai_status" in out.columns:
        out["ai_status"] = (
            out["ai_status"].fillna("").astype(str).str.strip().str.lower()
        )
    else:
        out["ai_status"] = "pending"

    if "ai_score" in out.columns:
        out["ai_score"] = pd.to_numeric(out["ai_score"], errors="coerce")
        out.loc[out["ai_status"] != "scored", "ai_score"] = pd.NA
    else:
        out["ai_score"] = pd.NA

    if "reason" not in out.columns:
        out["reason"] = ""
    else:
        out["reason"] = out["reason"].fillna("").astype(str)

    for col in ("applied", "rejected"):
        if col in out.columns:
            out[col] = out[col].fillna(False)

    return out


def normalize_key(value: object) -> str:
    return str(value or "").strip()


def merge_keys_from_jobs_frame(df: pd.DataFrame) -> set[str]:
    """V2-first merge keys for jobs / historical frames."""
    if df.empty:
        return set()
    work = df.copy()
    if "JOB_KEY_V2" not in work.columns:
        work["JOB_KEY_V2"] = ""
    if "JOB_KEY" not in work.columns:
        work["JOB_KEY"] = ""
    v2 = work["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    leg = work["JOB_KEY"].fillna("").astype(str).str.strip()
    keys = v2.where(v2 != "", leg)
    return {normalize_key(k) for k in keys if normalize_key(k)}


def add_merge_key_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "JOB_KEY" not in out.columns:
        out["JOB_KEY"] = ""
    if "JOB_KEY_V2" not in out.columns:
        out["JOB_KEY_V2"] = ""
    leg = out["JOB_KEY"].fillna("").astype(str).str.strip()
    v2 = out["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    out["__merge_key"] = v2.where(v2 != "", leg)
    return out


def apply_dashboard_job_ai_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Derive ai_status, is_ai_scored, score for dashboard filters and badges."""
    if df.empty:
        return df

    out = df.copy()
    if "ai_score" in out.columns:
        ai_score_numeric = pd.to_numeric(out["ai_score"], errors="coerce")
    elif "score" in out.columns:
        ai_score_numeric = pd.to_numeric(out["score"], errors="coerce")
    else:
        ai_score_numeric = pd.Series(pd.NA, index=out.index, dtype="Float64")

    if "reason" not in out.columns:
        out["reason"] = ""

    if "ai_status" not in out.columns:
        has_score = ai_score_numeric.notna()
        has_reason = out["reason"].fillna("").astype(str).str.strip() != ""
        out["ai_status"] = (has_score | has_reason).map(
            {True: "scored", False: "pending"}
        )
    else:
        out["ai_status"] = (
            out["ai_status"].fillna("").astype(str).str.strip().str.lower()
        )
        missing_status = out["ai_status"].isin(["", "nan", "none"])
        has_score = ai_score_numeric.notna()
        has_reason = out["reason"].fillna("").astype(str).str.strip() != ""
        out.loc[missing_status & (has_score | has_reason), "ai_status"] = "scored"
        out.loc[missing_status & ~(has_score | has_reason), "ai_status"] = "pending"

    out["is_ai_scored"] = out["ai_status"].eq("scored")
    out["score_available"] = out["is_ai_scored"] & ai_score_numeric.notna()
    out["score"] = ai_score_numeric.where(out["score_available"], 0).fillna(0)
    return out


def format_datetime_for_csv_compare(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ", timespec="seconds")
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return text
        return parsed.isoformat(sep=" ", timespec="seconds")
    except Exception:
        return text
