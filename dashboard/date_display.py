"""Shared dashboard date presentation helpers (display only; storage stays ISO)."""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

DASHBOARD_DATE_DISPLAY_FORMAT = "%d-%m-%Y"
DASHBOARD_DATE_INPUT_HINT = "DD-MM-YYYY"
_ISO_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _parse_for_display(text: str) -> pd.Timestamp:
    """Parse storage ISO or user-facing DD-MM-YYYY for display formatting."""
    if _ISO_DATE_PREFIX.match(text):
        return pd.to_datetime(text, errors="coerce", dayfirst=False)
    return pd.to_datetime(text, errors="coerce", dayfirst=True)


def format_dashboard_date(value: object) -> str:
    """Format a date or datetime value for dashboard display (DD-MM-YYYY)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime(DASHBOARD_DATE_DISPLAY_FORMAT)

    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "nat"}:
        return ""

    parsed = _parse_for_display(text)
    if pd.isna(parsed):
        return text

    has_time = " " in text or "T" in text
    if has_time and (parsed.hour or parsed.minute or parsed.second):
        return parsed.strftime(f"{DASHBOARD_DATE_DISPLAY_FORMAT} %H:%M")
    return parsed.strftime(DASHBOARD_DATE_DISPLAY_FORMAT)


def format_dashboard_date_column(series: pd.Series) -> pd.Series:
    return series.map(format_dashboard_date)


def dashboard_date_input_value(value: date | datetime | None) -> str:
    """Default value for dashboard date text inputs."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().strftime(DASHBOARD_DATE_DISPLAY_FORMAT)
    return value.strftime(DASHBOARD_DATE_DISPLAY_FORMAT)


def parse_dashboard_date_input(value: object) -> str | None:
    """
    Parse user-facing date text to ISO YYYY-MM-DD for persistence.

    Accepts DD-MM-YYYY (primary), DD/MM/YYYY, and legacy YYYY-MM-DD.
    """
    text = str(value or "").strip()
    if not text:
        return None

    for fmt in (DASHBOARD_DATE_DISPLAY_FORMAT, "%d/%m/%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:10], fmt).date()
            return parsed.isoformat()
        except ValueError:
            continue

    parsed_ts = _parse_for_display(text)
    if pd.isna(parsed_ts):
        return None
    return parsed_ts.date().isoformat()
