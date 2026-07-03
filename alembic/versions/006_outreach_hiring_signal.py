"""Outreach Intelligence V1.1: hiring signal columns on outreach_attempts.

Revision ID: 006_outreach_hiring_signal
Revises: 005_outreach_attempts
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_outreach_hiring_signal"
down_revision: Union[str, None] = "005_outreach_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_attempts",
        sa.Column("hiring_signal_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "outreach_attempts",
        sa.Column("hiring_signal_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_attempts", "hiring_signal_url")
    op.drop_column("outreach_attempts", "hiring_signal_type")
