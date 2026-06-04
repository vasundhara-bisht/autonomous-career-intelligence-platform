"""historical_jobs_view loader."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.read.transforms import format_datetime_for_csv_compare


def load_historical_jobs_view_df(session: Session) -> pd.DataFrame:
    df = pd.read_sql_query(text("SELECT * FROM historical_jobs_view"), session.bind)
    if df.empty:
        return df
    for col in ("first_seen", "last_seen"):
        if col in df.columns:
            df[col] = df[col].map(format_datetime_for_csv_compare)
    for col in ("applied", "rejected", "interview", "offer", "currently_active"):
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)
    if "JOB_KEY_V2" in df.columns:
        df["JOB_KEY_V2"] = df["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    return df
