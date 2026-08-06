"""Drop the unused datasets.quality_score_numeric column.

fix(#1231): quality_score_numeric was written nowhere, read nowhere, and
absent from openapi.json — a scalar that would only ever be a derived
roll-up of quality_detail (JSONB, written at ingest in tasks_common.py).
Persisting a derived value separately is a second source of truth that
goes stale, so ADR-002 Decision 8 calls for dropping it rather than wiring
it up. This decision is not gated on the rest of ADR-002 / Milestone 5.

Revision ID: 0035_drop_quality_score_numeric
Revises: 0034_linearize_geom_4326
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_drop_quality_score_numeric"
down_revision: Union[str, None] = "0034_linearize_geom_4326"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "chk_quality_score_range", "datasets", schema="catalog", type_="check"
    )
    op.drop_column("datasets", "quality_score_numeric", schema="catalog")


def downgrade() -> None:
    # Column had no writers in production, so there is no data to restore.
    op.add_column(
        "datasets",
        sa.Column("quality_score_numeric", sa.Float(), nullable=True),
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_quality_score_range",
        "datasets",
        "quality_score_numeric IS NULL OR "
        "(quality_score_numeric >= 0 AND quality_score_numeric <= 1)",
        schema="catalog",
    )
