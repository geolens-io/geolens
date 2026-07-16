"""Allow 'parquet' (and other accepted upload suffixes) in chk_datasets_source_format.

fix(#541 review): GeoParquet ingest derives ``source_format = 'parquet'`` from
the upload suffix (tasks_vector.py), but ``chk_datasets_source_format`` did not
include it, so every parquet upload would have failed with a check-constraint
violation at dataset creation — the last step of the ingest pipeline.

While extending the list, also add ``json``, ``xlsx``, and ``xls``: all three
are accepted upload extensions whose suffix-derived source_format values were
likewise missing from the constraint (latent since the constraint was
introduced; simply never hit in deployments that upload .geojson/.csv instead).

Revision ID: 0027_source_format_parquet
Revises: 0026_db_audit_naming_cleanup
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0027_source_format_parquet"
down_revision: Union[str, None] = "0026_db_audit_naming_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BASE_FORMATS = (
    "'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml', "
    "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff', "
    "'ogcapi_features', 'stac'"
)
_NEW_FORMATS = "'parquet', 'json', 'xlsx', 'xls'"


def upgrade() -> None:
    op.drop_constraint(
        "chk_datasets_source_format", "datasets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_datasets_source_format",
        "datasets",
        f"source_format IS NULL OR source_format IN ({_BASE_FORMATS}, {_NEW_FORMATS})",
        schema="catalog",
    )


def downgrade() -> None:
    # Fails loudly if rows with the new formats exist — remove or remap them
    # before downgrading rather than silently orphaning constraint-violating rows.
    op.drop_constraint(
        "chk_datasets_source_format", "datasets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_datasets_source_format",
        "datasets",
        f"source_format IS NULL OR source_format IN ({_BASE_FORMATS})",
        schema="catalog",
    )
