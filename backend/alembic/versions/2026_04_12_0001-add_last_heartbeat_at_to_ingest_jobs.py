"""Add last_heartbeat_at to ingest_jobs for stale-job detection.

Adds a nullable timestamp column that workers can periodically update to
signal that a job is still actively processing. The recover_stale_jobs()
function uses this column to distinguish between jobs that were killed
mid-run (no recent heartbeat) and jobs that are actively running on
another worker instance (recent heartbeat).

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-04-12
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("ingest_jobs", "last_heartbeat_at", schema="catalog")
