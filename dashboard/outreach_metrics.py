"""Outreach Intelligence KPI computation (dashboard-only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from outreach_status import (
    ACTIVE_OUTREACH_STATUSES,
    TERMINAL_FOLLOWUP_STATUSES,
    normalize_outreach_status,
)


@dataclass(frozen=True)
class OutreachMetrics:
    total: int
    active: int
    follow_ups_due_today: int
    overdue_follow_ups: int


def _iso_date_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()[:10]


def _parse_iso_date(value: object) -> date | None:
    text = _iso_date_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def compute_outreach_metrics(
    df: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> OutreachMetrics:
    ref = reference_date or date.today()
    if df is None or df.empty:
        return OutreachMetrics(total=0, active=0, follow_ups_due_today=0, overdue_follow_ups=0)

    statuses = df["status"].map(normalize_outreach_status)
    total = len(df)
    active = int(statuses.isin(ACTIVE_OUTREACH_STATUSES).sum())

    due_today = 0
    overdue = 0
    for status, follow_up in zip(statuses, df.get("follow_up_date", pd.Series(dtype=object))):
        if status in TERMINAL_FOLLOWUP_STATUSES:
            continue
        follow_date = _parse_iso_date(follow_up)
        if follow_date is None:
            continue
        if follow_date == ref:
            due_today += 1
        elif follow_date < ref:
            overdue += 1

    return OutreachMetrics(
        total=total,
        active=active,
        follow_ups_due_today=due_today,
        overdue_follow_ups=overdue,
    )
