"""D2.1 query/feed metadata: acquisition_query_runs columns + current_jobs_view join.

Revision ID: 003_query_metadata
Revises: 002_read_views
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_query_metadata"
down_revision: Union[str, None] = "002_read_views"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "acquisition_query_runs",
        sa.Column("query_group", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "acquisition_query_runs",
        sa.Column("filter_profile", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "acquisition_query_runs",
        sa.Column("run_ts", sa.Text(), nullable=True),
    )

    op.execute("DROP VIEW IF EXISTS current_jobs_view")
    op.execute(
        """
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
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS current_jobs_view")
    op.execute(
        """
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
            NULL AS linkedin_query_id,
            NULL AS linkedin_query_group,
            NULL AS linkedin_query_label,
            NULL AS linkedin_filter_profile,
            NULL AS linkedin_query_role,
            NULL AS linkedin_run_ts,
            NULL AS instahyre_feed_id,
            NULL AS instahyre_query_id,
            NULL AS instahyre_query_label,
            NULL AS instahyre_run_ts,
            c.run_id AS export_run_id
        FROM current_export_cohort_view c
        INNER JOIN jobs j ON j.id = c.job_id
        LEFT JOIN latest_ai_evaluations_view e ON e.job_id = j.id
        LEFT JOIN user_job_state u ON u.job_id = j.id
        """
    )
    op.drop_column("acquisition_query_runs", "run_ts")
    op.drop_column("acquisition_query_runs", "filter_profile")
    op.drop_column("acquisition_query_runs", "query_group")
