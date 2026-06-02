"""Add catalog.maps.og_image_uri column for SHARE-08 OG-image pipeline (Path A).

Upgrade: adds a nullable TEXT column ``og_image_uri`` to ``catalog.maps``.
This column stores the storage key (e.g. ``maps/og-images/{id}.jpg``) for
the 1200x630 OG social-card image. It is separate from ``thumbnail_uri``
because the OG image exceeds the 100KB thumbnail payload cap.

Downgrade: drops ``og_image_uri`` from ``catalog.maps``. Any uploaded OG
images are orphaned in storage on downgrade (same behaviour as
``thumbnail_uri`` on a column drop — storage GC is a separate operation).
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# NOTE (C-2): revision id is intentionally the bare "0024" (not
# "0024_maps_og_image_uri"). This id shipped in the public v2.0.0 release;
# renaming it would break `alembic upgrade` for any deployed DB whose
# alembic_version.version_num='0024'. Frozen for release-compat -- do not rename.
revision: str = "0024"
down_revision: Union[str, None] = "0023_geolens_readonly_role"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column("og_image_uri", sa.Text(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "og_image_uri", schema="catalog")
