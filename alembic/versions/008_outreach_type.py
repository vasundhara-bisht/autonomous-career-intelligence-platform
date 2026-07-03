"""Outreach Intelligence: outreach_type column on outreach_attempts.

Revision ID: 008_outreach_type
Revises: 007_outreach_message_ai
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_outreach_type"
down_revision: Union[str, None] = "007_outreach_message_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_attempts",
        sa.Column("outreach_type", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_attempts", "outreach_type")
