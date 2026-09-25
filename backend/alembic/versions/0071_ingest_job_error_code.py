"""Add the stable code of a fixed failure reason to catalog.ingest_jobs.

The job ledger writes it beside ``error_message`` when the reason is one the
server wrote as a fixed sentence, so a client can show that reason in the
reader's language while ``error_message`` keeps its English text. Nullable with
no default and no backfill: NULL means free text, and an older row reads as it
always has.

Revision ID: 0071_ingest_job_error_code
Revises: 0070_pointcloud_record_type
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071_ingest_job_error_code"
down_revision: Union[str, None] = "0070_pointcloud_record_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("error_code", sa.String(64), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("ingest_jobs", "error_code", schema="catalog")
