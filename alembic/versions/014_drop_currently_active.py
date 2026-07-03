"""TD10 Task 4: drop job_observations.currently_active; rebuild read views.

Revision ID: 014_drop_currently_active
Revises: 013_run_trigger
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_drop_currently_active"
down_revision: Union[str, None] = "013_run_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JOB_OBSERVATION_STATS_VIEW = """
CREATE VIEW job_observation_stats_view AS
SELECT
    o.job_id AS job_id,
    MIN(o.observed_at) AS first_seen,
    MAX(o.observed_at) AS last_seen,
    MAX(o.times_seen) AS times_seen,
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


_VIEWS_TO_DROP_FOR_COLUMN = (
    "current_jobs_view",
    "historical_jobs_view",
    "latest_ai_evaluations_view",
    "current_export_cohort_view",
    "job_observation_stats_view",
)


def _drop_views_for_column_migration() -> None:
    for name in _VIEWS_TO_DROP_FOR_COLUMN:
        op.execute(f"DROP VIEW IF EXISTS {name}")


def _drop_eval_dependent_views() -> None:
    for name in _VIEWS_USING_LATEST_EVALS:
        op.execute(f"DROP VIEW IF EXISTS {name}")


def _recreate_eval_dependent_views() -> None:
    op.execute(_LATEST_AI_EVALUATIONS_VIEW)
    op.execute(_HISTORICAL_JOBS_VIEW)
    op.execute(_CURRENT_JOBS_VIEW)


def upgrade() -> None:
    _drop_views_for_column_migration()
    with op.batch_alter_table("job_observations") as batch_op:
        batch_op.drop_column("currently_active")
    op.execute(_JOB_OBSERVATION_STATS_VIEW)
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
    _recreate_eval_dependent_views()


def downgrade() -> None:
    _drop_views_for_column_migration()
    with op.batch_alter_table("job_observations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "currently_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
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
    )
    op.execute(_CURRENT_JOBS_VIEW)
