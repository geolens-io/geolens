"""Allow 'GEOMETRY' in chk_datasets_geometry_type.

fix(#430 codex r5, P1): create_empty_dataset stores geometry_type='GEOMETRY'
(fix #430 BA-32 — the created table's column is generic geometry(Geometry,
4326), and storing 'POINT' made feature validation reject the Polygon/
LineString inserts the column accepts), but the constraint allow-list only
permitted concrete subtypes, so every empty-dataset create failed at flush.
Admit the generic sentinel.

Revision ID: 0011_allow_generic_geometry_type
Revises: 0010_oauth_github_provider_type
Create Date: 2026-07-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011_allow_generic_geometry_type"
down_revision: Union[str, None] = "0010_oauth_github_provider_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_LIST = (
    "'POINT', 'LINESTRING', 'POLYGON', "
    "'MULTIPOINT', 'MULTILINESTRING', 'MULTIPOLYGON', "
    "'GEOMETRYCOLLECTION'"
)
_NEW_LIST = _OLD_LIST + ", 'GEOMETRY'"


def upgrade() -> None:
    op.drop_constraint(
        "chk_datasets_geometry_type", "datasets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_datasets_geometry_type",
        "datasets",
        f"geometry_type IS NULL OR UPPER(geometry_type) IN ({_NEW_LIST})",
        schema="catalog",
    )


def downgrade() -> None:
    # Generic-typed rows would violate the old constraint — degrade them to
    # NULL (the column is nullable and NULL passes both constraint versions).
    op.execute(
        "UPDATE catalog.datasets SET geometry_type = NULL "
        "WHERE UPPER(geometry_type) = 'GEOMETRY'"
    )
    op.drop_constraint(
        "chk_datasets_geometry_type", "datasets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_datasets_geometry_type",
        "datasets",
        f"geometry_type IS NULL OR UPPER(geometry_type) IN ({_OLD_LIST})",
        schema="catalog",
    )
