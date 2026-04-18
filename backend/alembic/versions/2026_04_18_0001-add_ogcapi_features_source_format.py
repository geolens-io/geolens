"""Add ogcapi_features to catalog.datasets source_format CHECK constraint.

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-04-18 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.datasets "
        "DROP CONSTRAINT IF EXISTS chk_datasets_source_format"
    )
    op.execute(
        "ALTER TABLE catalog.datasets ADD CONSTRAINT chk_datasets_source_format "
        "CHECK (source_format IS NULL OR source_format IN ("
        "'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml', "
        "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff', "
        "'ogcapi_features'"
        "))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.datasets "
        "DROP CONSTRAINT IF EXISTS chk_datasets_source_format"
    )
    op.execute(
        "ALTER TABLE catalog.datasets ADD CONSTRAINT chk_datasets_source_format "
        "CHECK (source_format IS NULL OR source_format IN ("
        "'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml', "
        "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff'"
        "))"
    )
