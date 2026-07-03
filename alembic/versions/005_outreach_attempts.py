"""Outreach Intelligence V1: outreach_attempts table.

Revision ID: 005_outreach_attempts
Revises: 004_active_recruiters_view
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_outreach_attempts"
down_revision: Union[str, None] = "004_active_recruiters_view"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("person_name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=512), nullable=False),
        sa.Column("designation", sa.String(length=255), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("outreach_channel", sa.String(length=64), nullable=False),
        sa.Column("outreach_message", sa.Text(), nullable=True),
        sa.Column("date_contacted", sa.String(length=32), nullable=False),
        sa.Column("follow_up_date", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("opportunity_id", sa.String(length=255), nullable=True),
        sa.Column("opportunity_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_attempts_status", "outreach_attempts", ["status"])
    op.create_index(
        "ix_outreach_attempts_follow_up_date", "outreach_attempts", ["follow_up_date"]
    )
    op.create_index(
        "ix_outreach_attempts_date_contacted", "outreach_attempts", ["date_contacted"]
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_attempts_date_contacted", table_name="outreach_attempts")
    op.drop_index("ix_outreach_attempts_follow_up_date", table_name="outreach_attempts")
    op.drop_index("ix_outreach_attempts_status", table_name="outreach_attempts")
    op.drop_table("outreach_attempts")
