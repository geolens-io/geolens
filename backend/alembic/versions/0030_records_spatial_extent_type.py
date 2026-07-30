"""Widen catalog.records.spatial_extent to generic geometry + a type CHECK.

fix(#892): ``records.spatial_extent`` was ``geometry(Polygon, 4326)``. RFC 7946
§5.2 and STAC express an antimeridian-crossing extent as a bbox with
west > east, and a single planar 4326 ring cannot encode that -- so a dataset
that genuinely straddles the seam could only register a globe-spanning
-180..180 extent. The honest representation is two rings (``west..180`` and
``-180..east``), which needs a column that accepts MULTIPOLYGON.

The typmod becomes plain ``geometry(Geometry, 4326)`` rather than
``geometry(MultiPolygon, 4326)`` on purpose: every existing non-crossing extent
stays a POLYGON, byte-identical, with no blanket ``ST_Multi`` promotion.
``chk_records_spatial_extent_type`` preserves the DB-level type guard the
typmod used to provide -- it once caught a real bug where an extent-write path
tried to store a POINT and 500'd.

The GiST index ``idx_records_spatial_extent`` is rebuilt automatically by the
ALTER COLUMN TYPE rewrite; it is not dropped or recreated here.

Revision ID: 0030_records_spatial_extent_type
Revises: 0029_api_key_hardening
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0030_records_spatial_extent_type"
down_revision: Union[str, None] = "0029_api_key_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COUNT_MULTIPOLYGON = (
    "SELECT count(*) FROM catalog.records "
    "WHERE spatial_extent IS NOT NULL "
    "AND GeometryType(spatial_extent) = 'MULTIPOLYGON'"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.records "
        "ALTER COLUMN spatial_extent TYPE geometry(Geometry, 4326) "
        "USING spatial_extent::geometry(Geometry, 4326)"
    )
    op.create_check_constraint(
        "chk_records_spatial_extent_type",
        "records",
        "spatial_extent IS NULL OR "
        "GeometryType(spatial_extent) IN ('POLYGON', 'MULTIPOLYGON')",
        schema="catalog",
    )


def downgrade() -> None:
    # Refuse rather than coerce. Narrowing the typmod back to POLYGON has no
    # lossless answer for a two-ring seam extent: the only POLYGON that contains
    # it is -180..180, which silently re-registers the globe-spanning extent this
    # migration exists to eliminate. An operator downgrading the schema is told
    # the data cannot round-trip instead of having it quietly widened.
    bind = op.get_bind()
    crossing = bind.execute(text(_COUNT_MULTIPOLYGON)).scalar_one()
    if crossing:
        raise RuntimeError(
            f"{crossing} catalog.records row(s) hold a MULTIPOLYGON "
            "spatial_extent, which geometry(Polygon, 4326) cannot store. "
            "Downgrading would have to replace each one with its -180..180 "
            "envelope, losing the antimeridian-crossing extent. Inspect them "
            "with:\n"
            "  SELECT id, title, ST_AsText(spatial_extent) FROM catalog.records "
            "WHERE GeometryType(spatial_extent) = 'MULTIPOLYGON';\n"
            "If that loss is acceptable, run this first, then re-run the "
            "downgrade:\n"
            "  UPDATE catalog.records SET spatial_extent = "
            "ST_Envelope(spatial_extent) "
            "WHERE GeometryType(spatial_extent) = 'MULTIPOLYGON';"
        )

    op.drop_constraint(
        "chk_records_spatial_extent_type",
        "records",
        schema="catalog",
        type_="check",
    )
    op.execute(
        "ALTER TABLE catalog.records "
        "ALTER COLUMN spatial_extent TYPE geometry(Polygon, 4326) "
        "USING spatial_extent::geometry(Polygon, 4326)"
    )
