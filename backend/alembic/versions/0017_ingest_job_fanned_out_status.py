"""Add 'fanned_out' to ingest_jobs status check constraint.

The fan-out endpoint (POST /ingest/commit-fan-out/{job_id}) converts a
single-layer pending IngestJob into N per-layer ingest tasks. After
dispatching, the original job is marked 'fanned_out' — a terminal state
distinct from 'complete' (which means a single dataset was committed).

The existing CHECK constraint only allows:
  pending | running | complete | failed | cancelled

This migration extends it to include 'fanned_out'.

Phase 1058-04: GPKG-03 fan-out endpoint.
"""

from typing import Union

from alembic import op


revision: str = "0017_ingest_job_fanned_out_status"
down_revision: Union[str, None] = "0016_drop_redundant_data_gid_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # Drop the old constraint and recreate with 'fanned_out' added.
    # Two separate op.execute() calls are required: asyncpg does not allow
    # multiple DDL statements in a single prepared statement.
    op.execute(
        "ALTER TABLE catalog.ingest_jobs "
        "DROP CONSTRAINT IF EXISTS chk_ingest_jobs_status"
    )
    op.execute(
        "ALTER TABLE catalog.ingest_jobs "
        "ADD CONSTRAINT chk_ingest_jobs_status CHECK ("
        "  status IN ('pending', 'running', 'complete', 'failed', 'cancelled', 'fanned_out')"
        ")"
    )


def downgrade() -> None:
    # Revert to original constraint. Any rows with status='fanned_out'
    # must be manually updated before downgrade or they will violate the
    # constraint.
    op.execute(
        "ALTER TABLE catalog.ingest_jobs "
        "DROP CONSTRAINT IF EXISTS chk_ingest_jobs_status"
    )
    op.execute(
        "ALTER TABLE catalog.ingest_jobs "
        "ADD CONSTRAINT chk_ingest_jobs_status CHECK ("
        "  status IN ('pending', 'running', 'complete', 'failed', 'cancelled')"
        ")"
    )
