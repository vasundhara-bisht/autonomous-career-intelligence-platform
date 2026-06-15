"""Job Listings editor helpers (dirty detection, etc.)."""

from __future__ import annotations

import pandas as pd


def job_editor_return_differs_input(before_df: pd.DataFrame, after_df: pd.DataFrame) -> bool:
    cols = ["Status", "Notes", "Hiring Manager"]
    for c in cols:
        if c not in before_df.columns or c not in after_df.columns:
            continue
        a = (
            before_df[c]
            .fillna("")
            .astype(str)
            .str.strip()
            .reset_index(drop=True)
        )
        b = (
            after_df[c]
            .fillna("")
            .astype(str)
            .str.strip()
            .reset_index(drop=True)
        )
        if not a.equals(b):
            return True
    return False
