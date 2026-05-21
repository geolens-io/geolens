"""Add progress/current_step/rows_processed columns to catalog.ingest_jobs.

REMED-02 / ingest-audit P2-07: the polling UI (BulkTrackingList, ReuploadDialog)
hits ``/jobs/{id}`` every 2s, but the response only ever toggled between
``pending|running|complete|failed|cancelled|fanned_out``. During multi-minute
ingests (10-min raster COG conversion, large VRT mosaics) users saw a dead
spinner with no progress signal. The audit confirmed ``IngestJob.started_at``
and discrete step boundaries already existed in code — the contract gap was
purely UX-shaped.

This migration adds the three nullable columns the worker writes at natural
step boundaries:

- ``progress`` (Float, 0.0-1.0): coarse-grained fraction-complete signal.
- ``current_step`` (String(32)): the name of the step currently executing.
  No CHECK constraint at the DB level — the Pydantic ``Literal`` allowlist
  on ``JobStatusResponse.current_step`` is the contract boundary, so future
  step additions only require touching the schema (single-source-of-truth
  per project KNOWN-04).
- ``rows_processed`` (Integer): row count surfaced for vector ingests; left
  NULL for raster ingests (no rows).

Upgrade: adds the three columns to ``catalog.ingest_jobs`` as nullable.
Downgrade: drops the three columns in reverse order.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_ingest_jobs_progress_columns"
down_revision: Union[str, None] = "0021_drop_ingest_job_last_heartbeat_at"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("progress", sa.Float(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "ingest_jobs",
        sa.Column("current_step", sa.String(length=32), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "ingest_jobs",
        sa.Column("rows_processed", sa.Integer(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("ingest_jobs", "rows_processed", schema="catalog")
    op.drop_column("ingest_jobs", "current_step", schema="catalog")
    op.drop_column("ingest_jobs", "progress", schema="catalog")
