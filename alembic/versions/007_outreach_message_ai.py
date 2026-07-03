"""Outreach Intelligence: ai_recommended_message column on outreach_attempts.

Revision ID: 007_outreach_message_ai
Revises: 006_outreach_hiring_signal
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_outreach_message_ai"
down_revision: Union[str, None] = "006_outreach_hiring_signal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_attempts",
        sa.Column("ai_recommended_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_attempts", "ai_recommended_message")
