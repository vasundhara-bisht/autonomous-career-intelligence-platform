"""Column contracts for SQLite read models (aligned with CSV writers)."""

from __future__ import annotations

# Core export columns from save_to_csv / JOBS_CSV_SCHEMA_COLUMNS.
JOBS_EXPORT_CORE_COLUMNS: tuple[str, ...] = (
    "JOB_KEY",
    "JOB_KEY_V2",
    "identity_source",
    "title",
    "company",
    "location",
    "link",
    "source",
    "time_posted",
    "applied",
    "hiring_manager",
    "ai_score",
    "ai_status",
    "reason",
    "rejected",
    "priority",
)

# Compared in shadow parity (excludes id, priority, query metadata).
JOBS_SHADOW_COMPARE_COLUMNS: tuple[str, ...] = (
    "JOB_KEY_V2",
    "title",
    "company",
    "location",
    "link",
    "source",
    "ai_status",
    "ai_score",
    "reason",
)

JOBS_CSV_METADATA_COLUMNS: tuple[str, ...] = (
    "linkedin_query_id",
    "linkedin_query_group",
    "linkedin_query_label",
    "linkedin_filter_profile",
    "linkedin_query_role",
    "linkedin_run_ts",
    "instahyre_feed_id",
    "instahyre_query_id",
    "instahyre_query_label",
    "instahyre_run_ts",
)

HISTORICAL_VIEW_COLUMNS: tuple[str, ...] = (
    "JOB_KEY",
    "JOB_KEY_V2",
    "title",
    "company",
    "location",
    "source",
    "link",
    "ai_score",
    "ai_status",
    "reason",
    "hiring_manager",
    "first_seen",
    "last_seen",
    "times_seen",
    "applied",
    "rejected",
    "interview",
    "offer",
    "notes",
    "posted_at_date",
    "age_days",
    "pipeline_stage",
    "listing_status",
    "listing_status_reason",
    "listing_checked_at",
    "listing_check_attempted_at",
    "listing_closed_at",
    "listing_removed_at",
    "consecutive_check_failures",
    "listing_check_paused_at",
)

HISTORICAL_SHADOW_COMPARE_COLUMNS: tuple[str, ...] = (
    "JOB_KEY_V2",
    "title",
    "company",
    "ai_status",
    "ai_score",
)

READ_VIEW_NAMES: tuple[str, ...] = (
    "latest_ai_evaluations_view",
    "job_observation_stats_view",
    "latest_acquisition_run_view",
    "current_export_cohort_view",
    "historical_jobs_view",
    "current_jobs_view",
    "active_recruiters_view",
)
