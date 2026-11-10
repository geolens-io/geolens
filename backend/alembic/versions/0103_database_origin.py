"""Allow the ``database`` source format and refresh-run origin kind.

A dataset imported from an operator-configured database connection stores
``source_format = 'database'``, and its refresh runs record
``origin_kind = 'database'``. Both checks only widen.

The downgrade refuses while any dataset or refresh run uses the new value, so
no row is left violating the narrower check.

Revision ID: 0103_database_origin
Revises: 0102_dataset_assets_vrt_overview
Create Date: 2026-11-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0103_database_origin"
down_revision: Union[str, None] = "0102_dataset_assets_vrt_overview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"

_OLD_FORMATS = (
    "'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml', "
    "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff', "
    "'ogcapi_features', 'stac', 'parquet', 'json', 'xlsx', 'xls', 'fgb', "
    "'3dtiles', 'copc'"
)
_NEW_FORMATS = f"{_OLD_FORMATS}, 'database'"
_OLD_RUN_KINDS = "'upload', 'postgis', 'service', 'stac', 'raster', 'restore'"
_NEW_RUN_KINDS = f"{_OLD_RUN_KINDS}, 'database'"


def _replace_checks_sql(formats: str, run_kinds: str, *, suffix: str) -> str:
    return f"""
      ALTER TABLE catalog.datasets
        DROP CONSTRAINT IF EXISTS chk_datasets_source_format,
        ADD CONSTRAINT chk_datasets_source_format CHECK (
          source_format IS NULL OR source_format IN ({formats})
        ){suffix};
      ALTER TABLE catalog.dataset_refresh_runs
        DROP CONSTRAINT IF EXISTS chk_refresh_runs_origin_kind,
        ADD CONSTRAINT chk_refresh_runs_origin_kind CHECK (
          origin_kind IN ({run_kinds})
        ){suffix};
    """


def upgrade() -> None:
    # Dropped and re-added in one statement block so writes are never
    # unconstrained; NOT VALID skips the scan under ACCESS EXCLUSIVE, and
    # every statement can be repeated after an interrupted run.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "DO $$ BEGIN PERFORM set_config('lock_timeout', '5s', true);"
                + _replace_checks_sql(_NEW_FORMATS, _NEW_RUN_KINDS, suffix=" NOT VALID")
                + "END $$;"
            )
        )
    # VALIDATE takes SHARE UPDATE EXCLUSIVE, so reads and writes continue.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                  PERFORM set_config('lock_timeout', '5s', true);
                  ALTER TABLE catalog.datasets
                    VALIDATE CONSTRAINT chk_datasets_source_format;
                  ALTER TABLE catalog.dataset_refresh_runs
                    VALIDATE CONSTRAINT chk_refresh_runs_origin_kind;
                END $$;
                """
            )
        )


def downgrade() -> None:
    # One transaction: a later revision in the same downgrade can refuse, and a
    # committed narrower check would then outlive the rollback here.
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              -- Held from the check through the replacement, so no database
              -- row can land between them.
              LOCK TABLE catalog.datasets, catalog.dataset_refresh_runs
                IN ACCESS EXCLUSIVE MODE;
              IF EXISTS (
                SELECT 1 FROM catalog.datasets WHERE source_format = 'database'
              ) OR EXISTS (
                SELECT 1 FROM catalog.dataset_refresh_runs
                WHERE origin_kind = 'database'
              ) THEN
                RAISE EXCEPTION 'Datasets or refresh runs with the database '
                  'origin exist; delete them before downgrading.';
              END IF;
            """
            + _replace_checks_sql(_OLD_FORMATS, _OLD_RUN_KINDS, suffix="")
            + "END $$;"
        )
    )
