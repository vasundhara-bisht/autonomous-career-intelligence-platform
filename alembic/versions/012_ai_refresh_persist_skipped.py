"""Add persist_skipped_count to ai_refresh_runs.

Revision ID: 012_ai_refresh_persist_skipped
Revises: 011_ai_refresh_runs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_ai_refresh_persist_skipped"
down_revision: Union[str, None] = "011_ai_refresh_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_refresh_runs",
        sa.Column("persist_skipped_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ai_refresh_runs", "persist_skipped_count")
