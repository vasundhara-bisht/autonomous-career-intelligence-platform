"""Shared pipeline stage constants for discovery vs user-managed CRM workflows."""

from __future__ import annotations

DISCOVERY_PIPELINE_STAGES = ("New", "Saved")

USER_MANAGED_PIPELINE_STAGES = (
    "Applied",
    "HR Screen",
    "Interview",
    "Final Round",
    "Offer",
    "Rejected",
    "Ghosted",
)

_EXPLICIT_AI_STATUSES = frozenset(
    {"scored", "pending", "skipped_by_cap", "not_required"}
)


def is_user_managed_pipeline_stage(stage: object) -> bool:
    return str(stage or "").strip() in USER_MANAGED_PIPELINE_STAGES


def is_discovery_pipeline_stage(stage: object) -> bool:
    return str(stage or "").strip() in DISCOVERY_PIPELINE_STAGES


def is_explicit_ai_status(status: object) -> bool:
    return str(status or "").strip().lower() in _EXPLICIT_AI_STATUSES


def should_skip_expensive_acquisition(job: dict, historical_row: dict | None) -> bool:
    """Route jobs that bypass Stage 1, description fetch, and AI scoring this run."""
    if historical_row is not None:
        stage = str(historical_row.get("pipeline_stage") or "New").strip()
        if is_user_managed_pipeline_stage(stage):
            return True
    source = str(job.get("source") or "").strip().lower()
    return source == "linkedin" and bool(job.get("applied"))
