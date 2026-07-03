"""Job-linked outreach prefill from Job Listings cohort (dashboard-only)."""

from __future__ import annotations

import pandas as pd

from date_display import parse_dashboard_date_input


_NONE_KEY = ""
_INVALID_HM = frozenset({"", "not specified", "nan", "none"})


def _clean_hiring_manager(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in _INVALID_HM:
        return ""
    return text


def build_job_prefill_options(
    editor_df: pd.DataFrame,
) -> list[tuple[str, dict[str, str]]]:
    """Return (label, prefill_dict) pairs for job-linked outreach creation."""
    if editor_df is None or editor_df.empty:
        return [("None", {})]

    options: list[tuple[str, dict[str, str]]] = [("None", {})]
    sorted_df = editor_df.copy()
    if "Posted" in sorted_df.columns:
        sorted_df["_sort_posted"] = sorted_df["Posted"].map(
            lambda v: parse_dashboard_date_input(v) or ""
        )
        sorted_df = sorted_df.sort_values(
            "_sort_posted",
            ascending=False,
            na_position="last",
        )
        sorted_df = sorted_df.drop(columns=["_sort_posted"])
    for _, row in sorted_df.iterrows():
        job_key_v2 = str(row.get("JOB_KEY_V2", "") or "").strip()
        if not job_key_v2:
            continue
        title = str(row.get("Title", "") or "").strip()
        company = str(row.get("Company", "") or "").strip()
        location = str(row.get("Location", "") or "").strip()
        posted_at_date = str(row.get("Posted", "") or row.get("posted_at_date", "") or "").strip()
        base = f"{title} @ {company}" if title or company else job_key_v2
        suffix_parts = []
        if location:
            suffix_parts.append(location)
        if posted_at_date:
            suffix_parts.append(f"({posted_at_date})")
        label = f"{base} — {' '.join(suffix_parts)}" if suffix_parts else base
        person_name = _clean_hiring_manager(row.get("Hiring Manager"))
        options.append(
            (
                label,
                {
                    "person_name": person_name,
                    "company": company,
                    "opportunity_id": job_key_v2,
                    "opportunity_url": str(row.get("Link", "") or "").strip(),
                    "designation": "",
                },
            )
        )
    return options


def prefill_for_job_label(
    editor_df: pd.DataFrame,
    label: str,
) -> dict[str, str]:
    for option_label, prefill in build_job_prefill_options(editor_df):
        if option_label == label:
            return dict(prefill)
    return {}
