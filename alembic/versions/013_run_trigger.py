"""Add run_trigger to acquisition_runs and lifecycle_monitor_runs.

Revision ID: 013_run_trigger
Revises: 012_ai_refresh_persist_skipped
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_run_trigger"
down_revision: Union[str, None] = "012_ai_refresh_persist_skipped"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "acquisition_runs",
        sa.Column("run_trigger", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "lifecycle_monitor_runs",
        sa.Column("run_trigger", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lifecycle_monitor_runs", "run_trigger")
    op.drop_column("acquisition_runs", "run_trigger")
