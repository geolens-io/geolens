"""Add 'fanned_out' to ingest_jobs status check constraint.

The fan-out endpoint (POST /ingest/commit-fan-out/{job_id}) converts a
single-layer pending IngestJob into N per-layer ingest tasks. After
dispatching, the original job is marked 'fanned_out' — a terminal state
distinct from 'complete' (which means a single dataset was committed).

The existing CHECK constraint only allows:
  pending | running | complete | failed | cancelled

This migration extends it to include 'fanned_out'.

Phase 1058-04: GPKG-03 fan-out endpoint.

Phase 1060 close-gate note: renumbered from 0017 → 0018 to resolve a
branching collision with 0017_map_basemap_config (both originally claimed
revision 0017 with the same down_revision). The original 0017_map_basemap_config
was the migration actually applied to the dev DB.
"""

from typing import Union

from alembic import op


revision: str = "0018_ingest_job_fanned_out_status"
down_revision: Union[str, None] = "0017_map_basemap_config"
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
    # WR-03 fix: reset any 'fanned_out' rows to 'complete' before recreating
    # the old constraint. Without this UPDATE, Postgres will fail the
    # ADD CONSTRAINT check on existing fanned_out rows and the downgrade will
    # abort with a confusing constraint-violation error in production.
    op.execute(
        "UPDATE catalog.ingest_jobs SET status = 'complete' WHERE status = 'fanned_out'"
    )
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
