"""MVP product memory schema (tables only; views deferred).

Revision ID: 001_mvp_schema
Revises:
Create Date: 2026-05-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_mvp_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "acquisition_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_key", sa.String(length=512), nullable=False),
        sa.Column("job_key_v2", sa.String(length=255), nullable=False),
        sa.Column("identity_source", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("company", sa.String(length=512), nullable=False),
        sa.Column("location", sa.String(length=512), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("hiring_manager", sa.String(length=512), nullable=True),
        sa.Column("time_posted", sa.String(length=128), nullable=True),
        sa.Column("posted_at_date", sa.String(length=32), nullable=True),
        sa.Column("age_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_key_v2"),
    )
    op.create_index("ix_jobs_job_key_v2", "jobs", ["job_key_v2"], unique=False)
    op.create_index("ix_jobs_source", "jobs", ["source"], unique=False)
    op.create_table(
        "query_cooldown_state",
        sa.Column("query_id", sa.String(length=128), nullable=False),
        sa.Column("last_run_at", sa.Float(), nullable=True),
        sa.Column("domain_rotation_index", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("query_id"),
    )
    op.create_table(
        "recruiters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recruiter_key", sa.String(length=255), nullable=False),
        sa.Column("recruiter_name", sa.String(length=255), nullable=False),
        sa.Column("current_company", sa.String(length=512), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("recruiter_title", sa.String(length=255), nullable=True),
        sa.Column("recruiter_company", sa.String(length=512), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("jobs_connected", sa.Integer(), nullable=False),
        sa.Column("recruiter_stage", sa.String(length=64), nullable=True),
        sa.Column("outreach_sent", sa.Boolean(), nullable=False),
        sa.Column("recruiter_replied", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_outreach_date", sa.String(length=32), nullable=True),
        sa.Column("last_response_date", sa.String(length=32), nullable=True),
        sa.Column("touchpoint_count", sa.Integer(), nullable=False),
        sa.Column("last_interaction_note", sa.Text(), nullable=True),
        sa.Column("currently_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recruiter_key"),
    )
    op.create_index(
        "ix_recruiters_recruiter_key", "recruiters", ["recruiter_key"], unique=False
    )
    op.create_table(
        "acquisition_query_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("query_id", sa.String(length=128), nullable=False),
        sa.Column("query_label", sa.String(length=255), nullable=True),
        sa.Column("query_role", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("jobs_collected", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["acquisition_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_acquisition_query_runs_query_id",
        "acquisition_query_runs",
        ["query_id"],
        unique=False,
    )
    op.create_index(
        "ix_acquisition_query_runs_run_id",
        "acquisition_query_runs",
        ["run_id"],
        unique=False,
    )
    op.create_table(
        "ai_evaluations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("ai_status", sa.String(length=32), nullable=False),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["acquisition_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_evaluations_ai_status", "ai_evaluations", ["ai_status"], unique=False
    )
    op.create_index(
        "ix_ai_evaluations_evaluated_at", "ai_evaluations", ["evaluated_at"], unique=False
    )
    op.create_index("ix_ai_evaluations_job_id", "ai_evaluations", ["job_id"], unique=False)
    op.create_index("ix_ai_evaluations_run_id", "ai_evaluations", ["run_id"], unique=False)
    op.create_table(
        "job_descriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("job_key_v2", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_descriptions_job_id", "job_descriptions", ["job_id"], unique=False
    )
    op.create_index(
        "ix_job_descriptions_job_key_v2", "job_descriptions", ["job_key_v2"], unique=False
    )
    op.create_table(
        "job_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("query_run_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("currently_active", sa.Boolean(), nullable=False),
        sa.Column("times_seen", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["query_run_id"], ["acquisition_query_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["acquisition_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_observations_job_id", "job_observations", ["job_id"], unique=False
    )
    op.create_index(
        "ix_job_observations_query_run_id",
        "job_observations",
        ["query_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_observations_run_id", "job_observations", ["run_id"], unique=False
    )
    op.create_table(
        "recruiter_job_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recruiter_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recruiter_id"], ["recruiters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recruiter_id", "job_id", name="uq_recruiter_job"),
    )
    op.create_index(
        "ix_recruiter_job_links_job_id", "recruiter_job_links", ["job_id"], unique=False
    )
    op.create_index(
        "ix_recruiter_job_links_recruiter_id",
        "recruiter_job_links",
        ["recruiter_id"],
        unique=False,
    )
    op.create_table(
        "user_job_state",
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("rejected", sa.Boolean(), nullable=False),
        sa.Column("interview", sa.Boolean(), nullable=False),
        sa.Column("offer", sa.Boolean(), nullable=False),
        sa.Column("pipeline_stage", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("user_job_state")
    op.drop_table("recruiter_job_links")
    op.drop_table("job_observations")
    op.drop_table("job_descriptions")
    op.drop_table("ai_evaluations")
    op.drop_table("acquisition_query_runs")
    op.drop_table("recruiters")
    op.drop_table("query_cooldown_state")
    op.drop_table("jobs")
    op.drop_table("acquisition_runs")
