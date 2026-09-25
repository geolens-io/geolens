"""Backfill the dataset_assets rows of rasters uploaded before v1.3.0.

Raster ingest has written a ``data``, ``thumbnail`` and ``overview`` row for
every upload since v1.3.0. Older rasters have none, so STAC and OGC items
advertise no COG or quicklooks for them, and the storage quota counts their
bytes as zero. Their raster asset already keeps every value a row needs: the
COG key, both quicklook keys, and the COG's size measured at ingest. Nothing
here reads storage.

The rows copy what ``_build_dataset_asset_rows`` writes today. A row is
written only for a key under ``rasters/``, where GeoLens stores the rasters it
holds. That leaves out by-reference STAC imports, whose asset is the
publisher's URL: their refresh writes the row with the item's media type,
which the raster asset does not keep. VRTs get no rows, as a VRT built from
members gets none at ingest. ON CONFLICT DO NOTHING keeps any row that
already exists.

Revision ID: 0069_backfill_raster_dataset_assets
Revises: 0068_tileset_contents
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0069_backfill_raster_dataset_assets"
down_revision: Union[str, None] = "0068_tileset_contents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO catalog.dataset_assets
            (dataset_id, key, href, media_type, title, roles, size_bytes)
        SELECT ra.dataset_id, asset.key, asset.href, asset.media_type, asset.title,
               asset.roles, asset.size_bytes
        FROM catalog.raster_assets ra
        CROSS JOIN LATERAL (VALUES
            ('data', ra.asset_uri,
             'image/tiff; application=geotiff; profile=cloud-optimized',
             'Cloud-Optimized GeoTIFF', ARRAY['data'], ra.size_bytes),
            ('thumbnail', ra.quicklook_256_uri, 'image/png',
             'Quicklook (256px)', ARRAY['thumbnail'], NULL::bigint),
            ('overview', ra.quicklook_512_uri, 'image/png',
             'Quicklook (512px)', ARRAY['overview'], NULL::bigint)
        ) AS asset(key, href, media_type, title, roles, size_bytes)
        WHERE ra.driver IS DISTINCT FROM 'VRT'
          AND asset.href LIKE 'rasters/%'
        ON CONFLICT ON CONSTRAINT uq_dataset_assets_key DO NOTHING
        """
    )


def downgrade() -> None:
    # The rows match what the previous revision's ingest writes, and
    # backfilled rows cannot be told apart from those.
    pass
