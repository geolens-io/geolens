"""Add datasets.tile_cache_version — URL-keyed tile cache-buster.

`Dataset.current_version` is coupled to DatasetVersion history rows and is
bumped on reupload only, yet it fed `MapLayerResponse.tile_version` (the
frontend's `_v=` tile-URL parameter). Content mutations that don't create a
version — single-feature edits, column DDL, tile_columns changes — purged the
Valkey tile cache but left the tile URL unchanged, so CDN/browser/nginx caches
kept serving stale tiles until max-age expiry (builder-audit 2026-07-15 T-01).

This dedicated counter is bumped by every tile-content mutation (including
reupload) and now feeds tile_version, leaving current_version's version-history
semantics untouched.

Revision ID: 0025_dataset_tile_cache_version
Revises: 0024_tenant_provisioning_reentry
Create Date: 2026-07-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_dataset_tile_cache_version"
down_revision: Union[str, None] = "0024_tenant_provisioning_reentry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "tile_cache_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("datasets", "tile_cache_version", schema="catalog")
