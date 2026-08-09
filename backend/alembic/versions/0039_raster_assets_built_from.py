"""Record what a VRT was actually built from.

fix(#1290 review). VRT member staleness was decided by comparing timestamps —
the member's ``ingested_at`` against the parent's ``last_regenerated_at`` — and
three rounds of fixing that comparison each left a residual window, because the
question is not a time question.

The decisive case: a replacement assigns ``ingested_at`` inside its transaction
and commits later. A regenerate whose snapshot falls between those two instants
cannot see the uncommitted swap (read committed), so it builds from the OLD
URI, and afterwards the member's stamp PRECEDES the parent's. Healthy, and
wrong. PostgreSQL cannot stamp commit time from inside a transaction — ``now()``
is transaction start and ``clock_timestamp()`` is statement time, both before
commit — so no wall-clock scheme can express "committed after my snapshot".

``built_from`` stores the answer directly: the member asset URIs the published
VRT was assembled from, as ``{dataset_id: asset_uri}``. Staleness becomes a
state comparison — what a member IS versus what the artifact was built FROM —
which is exact under every interleaving and has no window to narrow.

Nullable with no backfill, deliberately. NULL means "built before this column
existed" and the health endpoint falls back to the legacy timestamp comparison
for those rows, which is what every pre-existing VRT needs. Rows written from
here on carry the state and never consult a clock.

Revision ID: 0039_raster_assets_built_from
Revises: 0038_dataset_assets_archived_original
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_raster_assets_built_from"
down_revision: Union[str, None] = "0038_dataset_assets_archived_original"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raster_assets",
        sa.Column("built_from", postgresql.JSONB(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("raster_assets", "built_from", schema="catalog")
