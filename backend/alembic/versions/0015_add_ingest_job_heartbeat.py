"""Add worker heartbeat leases for long-running ingest jobs.

Revision ID: 0015_add_ingest_job_heartbeat
Revises: 0014_record_translations
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_add_ingest_job_heartbeat"
down_revision: Union[str, None] = "0014_record_translations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "ingest_jobs",
        sa.Column(
            "attempt_id",
            sa.Uuid(),
            nullable=True,
        ),
        schema="catalog",
    )
    # Existing rows must remain NULL so already-enqueued tokenless deliveries
    # are distinguishable and can be adopted exactly once. Only future inserts
    # receive a token from the database default.
    op.alter_column(
        "ingest_jobs",
        "attempt_id",
        schema="catalog",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.add_column(
        "vrt_generations",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("vrt_generations", "heartbeat_at", schema="catalog")
    op.drop_column("ingest_jobs", "attempt_id", schema="catalog")
    op.drop_column("ingest_jobs", "heartbeat_at", schema="catalog")
