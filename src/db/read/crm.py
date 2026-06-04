"""active_recruiters_view loader (D6 dashboard CRM reads)."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.read.transforms import format_datetime_for_csv_compare


def load_active_recruiters_view_df(session: Session) -> pd.DataFrame:
    df = pd.read_sql_query(text("SELECT * FROM active_recruiters_view"), session.bind)
    if df.empty:
        return df
    for col in ("first_seen", "last_seen"):
        if col in df.columns:
            df[col] = df[col].map(format_datetime_for_csv_compare)
    return df
