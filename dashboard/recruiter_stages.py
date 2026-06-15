"""Canonical recruiter CRM workflow stages (dashboard-only)."""

from __future__ import annotations

import pandas as pd

ENGAGEMENT_STAGES: tuple[str, ...] = (
    "discovered",
    "warm",
    "active",
    "responded",
)
OUTCOME_STAGES: tuple[str, ...] = ("ghosted", "archived")
ALL_RECRUITER_STAGES: tuple[str, ...] = ENGAGEMENT_STAGES + OUTCOME_STAGES
CRM_STATUS_OPTIONS: list[str] = list(ALL_RECRUITER_STAGES)

_STAGE_LABELS: dict[str, str] = {
    "discovered": "Discovered",
    "warm": "Warm",
    "active": "Active",
    "responded": "Responded",
    "ghosted": "Ghosted",
    "archived": "Archived",
}


def normalize_recruiter_stage(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "discovered"
    text = str(value).strip().lower()
    if text in {"", "nan", "none"}:
        return "discovered"
    if text in ALL_RECRUITER_STAGES:
        return text
    return "discovered"


def recruiter_stage_label(stage: str) -> str:
    return _STAGE_LABELS.get(stage, stage.replace("_", " ").title())
