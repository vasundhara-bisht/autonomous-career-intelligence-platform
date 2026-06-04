"""D6 dashboard CRM: active_recruiters_view for SQLite CRM reads.

Revision ID: 004_active_recruiters_view
Revises: 003_query_metadata
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004_active_recruiters_view"
down_revision: Union[str, None] = "003_query_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW active_recruiters_view AS
        SELECT
            r.recruiter_key AS RECRUITER_KEY,
            r.recruiter_name AS recruiter_name,
            r.current_company AS current_company,
            r.source AS source,
            r.first_seen AS first_seen,
            r.last_seen AS last_seen,
            COALESCE(link_agg.jobs_connected, 0) AS jobs_connected,
            r.recruiter_stage AS recruiter_stage,
            r.outreach_sent AS outreach_sent,
            r.recruiter_replied AS recruiter_replied,
            r.notes AS notes,
            r.last_outreach_date AS last_outreach_date,
            r.last_response_date AS last_response_date,
            r.touchpoint_count AS touchpoint_count,
            r.last_interaction_note AS last_interaction_note,
            r.currently_active AS currently_active,
            r.recruiter_title AS recruiter_title,
            r.recruiter_company AS recruiter_company
        FROM recruiters r
        LEFT JOIN (
            SELECT recruiter_id, COUNT(DISTINCT job_id) AS jobs_connected
            FROM recruiter_job_links
            GROUP BY recruiter_id
        ) link_agg ON link_agg.recruiter_id = r.id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS active_recruiters_view")
