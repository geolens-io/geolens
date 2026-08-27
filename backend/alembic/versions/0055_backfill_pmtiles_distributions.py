"""Backfill PMTiles download distributions for existing spatial datasets.

_DISTRIBUTION_TEMPLATES now generates a PMTiles download distribution at
dataset creation (records/service.py), but those rows are materialized --
existing spatial datasets created before this deploy would never advertise
the pmtiles download in DCAT feeds until an unrelated geometry-mode flip
happened to run reconcile. This backfills one row per spatial dataset that
lacks it, so DCAT distributions match what a fresh ingest produces. Mirrors
0013_backfill_geoparquet_distributions.py and
0054_backfill_flatgeobuf_distributions.py, the precedent for adding a
format to this materialized list.

The NOT EXISTS guard reads only auto_generated rows (0054's codex-review
fix, applied here from the start): a user-authored download/pmtiles
distribution must not suppress the platform's own export row -- both are
meant to coexist, matching generate_distributions' own existence probe. The
INSERT carries ON CONFLICT DO NOTHING for the same reason 0054 needs it: a
user row at the exact guessable template URL
(`/datasets/{id}/export?format=pmtiles`) collides on
uq_record_distribution once the existence check no longer treats it as
"the pair is taken".

Idempotent: the NOT EXISTS guard plus ON CONFLICT DO NOTHING make re-running
a no-op. Downgrade removes only the auto-generated pmtiles download rows.

Non-spatial datasets are excluded (geometry_type IS NULL) -- PMTiles
requires geometry, matching generate_distributions' spatial-only filter.

Revision ID: 0055_backfill_pmtiles_distributions
Revises: 0054_backfill_flatgeobuf_distributions
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0055_backfill_pmtiles_distributions"
down_revision: Union[str, None] = "0054_backfill_flatgeobuf_distributions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO catalog.record_distributions
            (record_id, distribution_type, format, url, title, protocol,
             media_type, is_primary, auto_generated)
        SELECT d.record_id, 'download', 'pmtiles',
               '/datasets/' || d.id::text || '/export?format=pmtiles',
               'PMTiles Download', 'HTTP',
               'application/vnd.pmtiles', false, true
        FROM catalog.datasets d
        WHERE d.geometry_type IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM catalog.record_distributions rd
              WHERE rd.record_id = d.record_id
                AND rd.distribution_type = 'download'
                AND rd.format = 'pmtiles'
                AND rd.auto_generated = true
          )
        ON CONFLICT ON CONSTRAINT uq_record_distribution DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM catalog.record_distributions
        WHERE distribution_type = 'download'
          AND format = 'pmtiles'
          AND auto_generated = true
        """
    )
