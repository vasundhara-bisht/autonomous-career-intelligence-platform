"""AI refresh run table and ai_evaluations.ai_refresh_run_id (Refresh AI Evaluations).

Revision ID: 011_ai_refresh_runs
Revises: 010_monitor_provider_state
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_ai_refresh_runs"
down_revision: Union[str, None] = "010_monitor_provider_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LATEST_AI_EVALUATIONS_VIEW = """
CREATE VIEW latest_ai_evaluations_view AS
SELECT
    e.job_id AS job_id,
    j.job_key_v2 AS job_key_v2,
    e.ai_status AS ai_status,
    e.ai_score AS ai_score,
    e.reason AS reason,
    e.model AS model,
    e.evaluated_at AS evaluated_at,
    e.run_id AS run_id
FROM ai_evaluations e
INNER JOIN jobs j ON j.id = e.job_id
WHERE e.id = (
    SELECT e2.id
    FROM ai_evaluations e2
    WHERE e2.job_id = e.job_id
    ORDER BY e2.evaluated_at DESC, e2.id DESC
    LIMIT 1
)
"""

_HISTORICAL_JOBS_VIEW = """
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

_CURRENT_JOBS_VIEW = """
CREATE VIEW current_jobs_view AS
SELECT
    j.job_key AS JOB_KEY,
    j.job_key_v2 AS JOB_KEY_V2,
    j.identity_source AS identity_source,
    j.title AS title,
    j.company AS company,
    j.location AS location,
    j.link AS link,
    j.source AS source,
    j.time_posted AS time_posted,
    j.posted_at_date AS posted_at_date,
    j.hiring_manager AS hiring_manager,
    e.ai_score AS ai_score,
    e.ai_status AS ai_status,
    e.reason AS reason,
    COALESCE(u.applied, 0) AS applied,
    COALESCE(u.rejected, 0) AS rejected,
    CASE WHEN aqr.source = 'linkedin' THEN aqr.query_id END AS linkedin_query_id,
    CASE WHEN aqr.source = 'linkedin' THEN aqr.query_group END AS linkedin_query_group,
    CASE WHEN aqr.source = 'linkedin' THEN aqr.query_label END AS linkedin_query_label,
    CASE WHEN aqr.source = 'linkedin' THEN aqr.filter_profile END AS linkedin_filter_profile,
    CASE WHEN aqr.source = 'linkedin' THEN aqr.query_role END AS linkedin_query_role,
    CASE WHEN aqr.source = 'linkedin' THEN aqr.run_ts END AS linkedin_run_ts,
    CASE WHEN aqr.source = 'instahyre' THEN aqr.query_id END AS instahyre_feed_id,
    CASE WHEN aqr.source = 'instahyre' THEN aqr.query_id END AS instahyre_query_id,
    CASE WHEN aqr.source = 'instahyre' THEN aqr.query_label END AS instahyre_query_label,
    CASE WHEN aqr.source = 'instahyre' THEN aqr.run_ts END AS instahyre_run_ts,
    c.run_id AS export_run_id
FROM current_export_cohort_view c
INNER JOIN jobs j ON j.id = c.job_id
LEFT JOIN job_observations obs ON obs.job_id = j.id AND obs.run_id = c.run_id
LEFT JOIN acquisition_query_runs aqr ON aqr.id = obs.query_run_id
LEFT JOIN latest_ai_evaluations_view e ON e.job_id = j.id
LEFT JOIN user_job_state u ON u.job_id = j.id
"""

_VIEWS_USING_LATEST_EVALS = (
    "current_jobs_view",
    "historical_jobs_view",
    "latest_ai_evaluations_view",
)


def _drop_eval_dependent_views() -> None:
    for name in _VIEWS_USING_LATEST_EVALS:
        op.execute(f"DROP VIEW IF EXISTS {name}")


def _recreate_eval_dependent_views() -> None:
    op.execute(_LATEST_AI_EVALUATIONS_VIEW)
    op.execute(_HISTORICAL_JOBS_VIEW)
    op.execute(_CURRENT_JOBS_VIEW)


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _index_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    if not _table_exists("ai_refresh_runs"):
        op.create_table(
            "ai_refresh_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
            sa.Column("preset", sa.String(length=32), nullable=False, server_default="backlog"),
            sa.Column("cohort_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scored_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_no_description", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_by_cap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("batch_failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_sec", sa.Float(), nullable=True),
            sa.Column("profile_path", sa.Text(), nullable=True),
            sa.Column("error_summary", sa.Text(), nullable=True),
        )

    _drop_eval_dependent_views()

    eval_columns = _column_names("ai_evaluations")
    eval_indexes = _index_names("ai_evaluations")
    if "ai_refresh_run_id" not in eval_columns:
        with op.batch_alter_table("ai_evaluations") as batch_op:
            batch_op.add_column(
                sa.Column("ai_refresh_run_id", sa.Integer(), nullable=True),
            )
            batch_op.create_foreign_key(
                "fk_ai_evaluations_ai_refresh_run_id",
                "ai_refresh_runs",
                ["ai_refresh_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                "ix_ai_evaluations_ai_refresh_run_id",
                ["ai_refresh_run_id"],
            )
    elif "ix_ai_evaluations_ai_refresh_run_id" not in eval_indexes:
        with op.batch_alter_table("ai_evaluations") as batch_op:
            batch_op.create_foreign_key(
                "fk_ai_evaluations_ai_refresh_run_id",
                "ai_refresh_runs",
                ["ai_refresh_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                "ix_ai_evaluations_ai_refresh_run_id",
                ["ai_refresh_run_id"],
            )

    _recreate_eval_dependent_views()


def downgrade() -> None:
    _drop_eval_dependent_views()

    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.drop_index("ix_ai_evaluations_ai_refresh_run_id")
        batch_op.drop_constraint(
            "fk_ai_evaluations_ai_refresh_run_id",
            type_="foreignkey",
        )
        batch_op.drop_column("ai_refresh_run_id")

    _recreate_eval_dependent_views()

    op.drop_table("ai_refresh_runs")
