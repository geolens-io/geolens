"""Add a raster's CRS facts beside its CRS text in catalog.raster_assets.

Requests read these instead of handing ``crs_wkt`` to PROJ. The columns start
NULL, which readers treat as unknown; the worker's CRS facts repair job fills
them for rows that already exist.

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


def upgrade() -> None:
    for name, type_ in _FACT_COLUMNS:
        op.add_column(
            "raster_assets", sa.Column(name, type_, nullable=True), schema="catalog"
        )


def downgrade() -> None:
    for name, _ in reversed(_FACT_COLUMNS):
        op.drop_column("raster_assets", name, schema="catalog")
