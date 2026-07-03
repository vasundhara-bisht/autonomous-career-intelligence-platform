"""Listing status columns, lifecycle_monitor_runs, historical_jobs_view rebuild (Scheduler B T1A).

Revision ID: 009_listing_status
Revises: 008_outreach_type
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_listing_status"
down_revision: Union[str, None] = "008_outreach_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USER_MANAGED_STAGES: tuple[str, ...] = (
    "Applied",
    "HR Screen",
    "Interview",
    "Final Round",
    "Offer",
    "Rejected",
    "Ghosted",
)

_HISTORICAL_JOBS_VIEW_V009 = """
CREATE VIEW historical_jobs_view AS
SELECT
    j.job_key AS JOB_KEY,
    j.job_key_v2 AS JOB_KEY_V2,
    j.title AS title,
    j.company AS company,
    j.location AS location,
    j.source AS source,
    j.link AS link,
    e.ai_score AS ai_score,
    e.ai_status AS ai_status,
    e.reason AS reason,
    j.hiring_manager AS hiring_manager,
    o.first_seen AS first_seen,
    o.last_seen AS last_seen,
    o.times_seen AS times_seen,
    o.currently_active AS currently_active,
    COALESCE(u.applied, 0) AS applied,
    COALESCE(u.rejected, 0) AS rejected,
    COALESCE(u.interview, 0) AS interview,
    COALESCE(u.offer, 0) AS offer,
    u.notes AS notes,
    j.posted_at_date AS posted_at_date,
    j.age_days AS age_days,
    u.pipeline_stage AS pipeline_stage,
    j.listing_status AS listing_status,
    j.listing_status_reason AS listing_status_reason,
    j.listing_checked_at AS listing_checked_at,
    j.listing_check_attempted_at AS listing_check_attempted_at,
    j.listing_closed_at AS listing_closed_at,
    j.listing_removed_at AS listing_removed_at,
    j.consecutive_check_failures AS consecutive_check_failures,
    j.listing_check_paused_at AS listing_check_paused_at
FROM jobs j
LEFT JOIN latest_ai_evaluations_view e ON e.job_id = j.id
LEFT JOIN user_job_state u ON u.job_id = j.id
LEFT JOIN job_observation_stats_view o ON o.job_id = j.id
"""

_HISTORICAL_JOBS_VIEW_V002 = """
CREATE VIEW historical_jobs_view AS
SELECT
    j.job_key AS JOB_KEY,
    j.job_key_v2 AS JOB_KEY_V2,
    j.title AS title,
    j.company AS company,
    j.location AS location,
    j.source AS source,
    j.link AS link,
    e.ai_score AS ai_score,
    e.ai_status AS ai_status,
    e.reason AS reason,
    j.hiring_manager AS hiring_manager,
    o.first_seen AS first_seen,
    o.last_seen AS last_seen,
    o.times_seen AS times_seen,
    o.currently_active AS currently_active,
    COALESCE(u.applied, 0) AS applied,
    COALESCE(u.rejected, 0) AS rejected,
    COALESCE(u.interview, 0) AS interview,
    COALESCE(u.offer, 0) AS offer,
    u.notes AS notes,
    j.posted_at_date AS posted_at_date,
    j.age_days AS age_days,
    u.pipeline_stage AS pipeline_stage
FROM jobs j
LEFT JOIN latest_ai_evaluations_view e ON e.job_id = j.id
LEFT JOIN user_job_state u ON u.job_id = j.id
LEFT JOIN job_observation_stats_view o ON o.job_id = j.id
"""


def _stage_in_list(stages: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{stage}'" for stage in stages)
    return f"({quoted})"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("listing_status", sa.String(32), nullable=False, server_default="open"),
    )
    op.add_column("jobs", sa.Column("listing_status_reason", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("listing_checked_at", sa.DateTime(), nullable=True))
    op.add_column(
        "jobs", sa.Column("listing_check_attempted_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "jobs",
        sa.Column(
            "consecutive_check_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "jobs", sa.Column("listing_check_paused_at", sa.DateTime(), nullable=True)
    )
    op.add_column("jobs", sa.Column("listing_closed_at", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("listing_removed_at", sa.DateTime(), nullable=True))

    op.create_index("ix_jobs_listing_status_source", "jobs", ["listing_status", "source"])

    op.create_table(
        "lifecycle_monitor_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("cohort_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("removed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("check_failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paused_skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("terminal_skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("check_failed_rate", sa.Float(), nullable=True),
        sa.Column("monitor_health", sa.String(16), nullable=True),
        sa.Column("systemic_alert", sa.String(64), nullable=True),
        sa.Column("auth_health", sa.String(16), nullable=True),
        sa.Column("parity_warning_summary", sa.Text(), nullable=True),
    )

    # §2.4 backfill: default open; user-managed CRM stages → monitor_exempt.
    op.execute(
        f"""
        UPDATE jobs
        SET listing_status = 'monitor_exempt'
        WHERE id IN (
            SELECT u.job_id
            FROM user_job_state u
            WHERE COALESCE(u.pipeline_stage, 'New') IN {_stage_in_list(_USER_MANAGED_STAGES)}
        )
        """
    )

    op.execute("DROP VIEW IF EXISTS historical_jobs_view")
    op.execute(_HISTORICAL_JOBS_VIEW_V009)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS historical_jobs_view")
    op.execute(_HISTORICAL_JOBS_VIEW_V002)

    op.drop_table("lifecycle_monitor_runs")
    op.drop_index("ix_jobs_listing_status_source", table_name="jobs")

    op.drop_column("jobs", "listing_removed_at")
    op.drop_column("jobs", "listing_closed_at")
    op.drop_column("jobs", "listing_check_paused_at")
    op.drop_column("jobs", "consecutive_check_failures")
    op.drop_column("jobs", "listing_check_attempted_at")
    op.drop_column("jobs", "listing_checked_at")
    op.drop_column("jobs", "listing_status_reason")
    op.drop_column("jobs", "listing_status")
