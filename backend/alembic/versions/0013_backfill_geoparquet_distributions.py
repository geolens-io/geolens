"""Backfill GeoParquet download distributions for existing spatial datasets.

fix(#462 follow-up): _DISTRIBUTION_TEMPLATES now generates a GeoParquet download
distribution at dataset creation (records/service.py), but those rows are
materialized — existing spatial datasets created before this deploy would never
advertise the parquet download in DCAT feeds. This backfills one row per spatial
dataset that lacks it, so DCAT distributions match what a fresh ingest produces.

Idempotent: the NOT EXISTS guard (plus the uq_record_distribution unique
constraint on record_id/distribution_type/format/url) makes re-running a no-op.
Downgrade removes only the auto-generated parquet download rows.

Non-spatial datasets are excluded (geometry_type IS NULL) — GeoParquet requires
geometry, matching generate_distributions' spatial-only filter.

Revision ID: 0013_backfill_geoparquet_distributions
Revises: 0012_type_embedding_vector
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013_backfill_geoparquet_distributions"
down_revision: Union[str, None] = "0012_type_embedding_vector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO catalog.record_distributions
            (record_id, distribution_type, format, url, title, protocol,
             media_type, is_primary, auto_generated)
        SELECT d.record_id, 'download', 'parquet',
               '/datasets/' || d.id::text || '/export?format=parquet',
               'GeoParquet Download', 'HTTP',
               'application/vnd.apache.parquet', false, true
        FROM catalog.datasets d
        WHERE d.geometry_type IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM catalog.record_distributions rd
              WHERE rd.record_id = d.record_id
                AND rd.distribution_type = 'download'
                AND rd.format = 'parquet'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM catalog.record_distributions
        WHERE distribution_type = 'download'
          AND format = 'parquet'
          AND auto_generated = true
        """
    )
