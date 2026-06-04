"""Phase D0 read views for CSV-shaped SQLite queries (no production read switch).

Revision ID: 002_read_views
Revises: 001_mvp_schema
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002_read_views"
down_revision: Union[str, None] = "001_mvp_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VIEW_DROPS = (
    "current_jobs_view",
    "historical_jobs_view",
    "current_export_cohort_view",
    "latest_acquisition_run_view",
    "job_observation_stats_view",
    "latest_ai_evaluations_view",
)


def upgrade() -> None:
    op.execute(
        """
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
    )

    op.execute(
        """
        CREATE VIEW job_observation_stats_view AS
        SELECT
            o.job_id AS job_id,
            MIN(o.observed_at) AS first_seen,
            MAX(o.observed_at) AS last_seen,
            MAX(o.times_seen) AS times_seen,
            (
                SELECT o2.currently_active
                FROM job_observations o2
                WHERE o2.job_id = o.job_id
                ORDER BY o2.observed_at DESC, o2.id DESC
                LIMIT 1
            ) AS currently_active,
            (
                SELECT o2.run_id
                FROM job_observations o2
                WHERE o2.job_id = o.job_id
                ORDER BY o2.observed_at DESC, o2.id DESC
                LIMIT 1
            ) AS last_run_id
        FROM job_observations o
        GROUP BY o.job_id
        """
    )

    op.execute(
        """
        CREATE VIEW latest_acquisition_run_view AS
        SELECT
            ar.id AS run_id,
            ar.started_at AS started_at,
            ar.completed_at AS completed_at,
            ar.status AS status,
            ar.notes AS notes
        FROM acquisition_runs ar
        WHERE ar.status = 'completed'
        ORDER BY ar.completed_at DESC, ar.id DESC
        LIMIT 1
        """
    )

    op.execute(
        """
        CREATE VIEW current_export_cohort_view AS
        SELECT DISTINCT
            j.job_key_v2 AS job_key_v2,
            j.id AS job_id,
            obs.run_id AS run_id
        FROM job_observations obs
        INNER JOIN jobs j ON j.id = obs.job_id
        WHERE obs.run_id = (SELECT run_id FROM latest_acquisition_run_view)
        """
    )

    op.execute(
        """
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
    )

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


def downgrade() -> None:
    for name in _VIEW_DROPS:
        op.execute(f"DROP VIEW IF EXISTS {name}")
