"""Monitor provider state table and lifecycle run provider summary (OHM Phase 2).

Revision ID: 010_monitor_provider_state
Revises: 009_listing_status
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_monitor_provider_state"
down_revision: Union[str, None] = "009_listing_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_provider_state",
        sa.Column("source", sa.String(length=32), primary_key=True),
        sa.Column("health", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=True),
        sa.Column("backoff_until", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("lifecycle_monitor_runs") as batch_op:
        batch_op.add_column(sa.Column("provider_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("lifecycle_monitor_runs") as batch_op:
        batch_op.drop_column("provider_summary")
    op.drop_table("monitor_provider_state")
