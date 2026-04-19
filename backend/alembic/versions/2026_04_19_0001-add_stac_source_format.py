"""Add stac to catalog.datasets source_format CHECK constraint.

Revision ID: i6j7k8l9m0n1
Revises: h5i6j7k8l9m0
Create Date: 2026-04-19 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "i6j7k8l9m0n1"
down_revision = "h5i6j7k8l9m0"
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
        "'ogcapi_features', 'stac'"
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
        "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff', "
        "'ogcapi_features'"
        "))"
    )
