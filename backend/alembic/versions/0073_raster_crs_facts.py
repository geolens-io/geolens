"""Add a raster's CRS facts beside its CRS text in catalog.raster_assets.

Requests read these instead of handing ``crs_wkt`` to PROJ. The columns start
NULL, which readers treat as unknown; the worker's CRS facts repair job fills
them for rows that already exist.

A worker still on the previous image during a rolling deploy can write new
``crs_wkt`` and leave the old facts beside it. The trigger clears the facts
whenever the text changes and none of them do, so the repair job refills them
from the new text.

Revision ID: 0073_raster_crs_facts
Revises: 0072_ingest_job_error_code
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0073_raster_crs_facts"
down_revision: Union[str, None] = "0072_ingest_job_error_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FACT_COLUMNS = (
    ("crs_is_geographic", sa.Boolean()),
    ("crs_has_degree_unit", sa.Boolean()),
    ("crs_metres_per_unit", sa.Double()),
)
_FUNCTION_NAME = "catalog.clear_stale_raster_crs_facts"
_TRIGGER_NAME = "trg_clear_stale_raster_crs_facts"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    # ADD COLUMN and CREATE TRIGGER lock raster_assets. Fail fast on a busy
    # table rather than queue ahead of API traffic.
    op.execute(_LOCK_TIMEOUT)
    for name, type_ in _FACT_COLUMNS:
        op.add_column(
            "raster_assets", sa.Column(name, type_, nullable=True), schema="catalog"
        )
    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION_NAME}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        BEGIN
            NEW.crs_is_geographic := NULL;
            NEW.crs_has_degree_unit := NULL;
            NEW.crs_metres_per_unit := NULL;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER_NAME}
        BEFORE UPDATE OF crs_wkt ON catalog.raster_assets
        FOR EACH ROW
        WHEN (
            NEW.crs_wkt IS DISTINCT FROM OLD.crs_wkt
            AND NEW.crs_is_geographic IS NOT DISTINCT FROM OLD.crs_is_geographic
            AND NEW.crs_has_degree_unit IS NOT DISTINCT FROM OLD.crs_has_degree_unit
            AND NEW.crs_metres_per_unit IS NOT DISTINCT FROM OLD.crs_metres_per_unit
        )
        EXECUTE FUNCTION {_FUNCTION_NAME}()
        """
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON catalog.raster_assets")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}()")
    for name, _ in reversed(_FACT_COLUMNS):
        op.drop_column("raster_assets", name, schema="catalog")
