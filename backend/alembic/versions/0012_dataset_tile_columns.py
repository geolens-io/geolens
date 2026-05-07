"""Add `tile_columns` allowlist to datasets for vector-tile column projection.

Phase 269 H-23: tile SQL was projecting every non-geometry column into MVT
properties. The 137-column `populated_places_10m` reference dataset
produced 824 KB decompressed tiles. With no admin-controllable column
allowlist, wide-table datasets blow up tile size and bandwidth.

This migration adds an optional `tile_columns text[]` column to
`catalog.datasets`. Semantics:

* `NULL` (default) — fall back to per-zoom defaults: at z<10, project no
  attribute columns (geometry-only tiles); at z>=10, project all columns.
* Empty array `[]` — never project any attribute columns regardless of
  zoom (admin opt-in for label-free tiles).
* Non-empty array — admin-curated allowlist; only the listed columns
  flow into MVT properties at any zoom.

The column is admin-configurable. Phase 269 ships the schema + tile-SQL
filter; the admin UI surface is deferred to a follow-up backlog item.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_dataset_tile_columns"
down_revision: Union[str, None] = "0011_record_embeddings_hnsw_idx"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "tile_columns",
            sa.ARRAY(sa.String()),
            nullable=True,
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("datasets", "tile_columns", schema="catalog")
