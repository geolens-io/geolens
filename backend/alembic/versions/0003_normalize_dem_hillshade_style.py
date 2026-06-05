"""Normalize persisted DEM hillshade render modes.

Revision ID: 0003_normalize_dem_hillshade_style
Revises: 0002_procrastinate
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_normalize_dem_hillshade_style"
down_revision: Union[str, None] = "0002_procrastinate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE catalog.map_layers AS ml
        SET style_config =
            (
                CASE
                    WHEN jsonb_typeof(ml.style_config) = 'object' THEN ml.style_config
                    ELSE '{}'::jsonb
                END
            )
            || jsonb_build_object('render_mode', 'hillshade')
        FROM catalog.raster_assets AS ra
        WHERE ra.dataset_id = ml.dataset_id
          AND ra.is_dem IS TRUE
          AND (
              ml.style_config IS NULL
              OR jsonb_typeof(ml.style_config) <> 'object'
              OR ml.style_config->>'render_mode' IS NULL
              OR ml.style_config->>'render_mode' = 'image'
          )
        """
    )


def downgrade() -> None:
    # Data-only normalization; intentionally not reversible.
    pass
