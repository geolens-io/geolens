"""Move legacy map builder paint metadata into style_config.

Revision ID: 0004_style_config_paint_cleanup
Revises: 0003_workflow_status_extension
Create Date: 2026-05-05
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_style_config_paint_cleanup"
down_revision: Union[str, None] = "0003_workflow_status_extension"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_BUILDER_PAINT_KEYS = {
    "_outline-width": "outline_width",
    "outline-width": "outline_width",
    "_outline-color": "outline_color",
    "outline-color": "outline_color",
    "_fill-disabled": "fill_disabled",
    "_stroke-disabled": "stroke_disabled",
    "_fill-opacity-saved": "fill_opacity_saved",
    "_outline-width-saved": "outline_width_saved",
    "_heatmap-ramp": "heatmap_ramp",
    "_heatmap-weight-column": "heatmap_weight_column",
    "_height_column": "height_column",
}

DOWNGRADE_PAINT_KEYS = {
    "outline_width": "_outline-width",
    "outline_color": "_outline-color",
    "fill_disabled": "_fill-disabled",
    "stroke_disabled": "_stroke-disabled",
    "fill_opacity_saved": "_fill-opacity-saved",
    "outline_width_saved": "_outline-width-saved",
    "heatmap_ramp": "_heatmap-ramp",
    "heatmap_weight_column": "_heatmap-weight-column",
    "height_column": "_height_column",
}


def _merge_builder_config(
    style_config: dict | None,
    builder_values: dict,
) -> dict | None:
    if not builder_values:
        return style_config

    merged = dict(style_config or {})
    existing_builder = merged.get("builder")
    builder = dict(existing_builder) if isinstance(existing_builder, dict) else {}
    for key, value in builder_values.items():
        if value is not None and builder.get(key) is None:
            builder[key] = value
    if builder:
        merged["builder"] = builder
    return merged


def clean_legacy_paint_row(
    paint: dict | None,
    style_config: dict | None,
) -> tuple[dict, dict | None]:
    """Strip legacy builder keys from paint and preserve them in style_config."""
    clean_paint = dict(paint or {})
    builder_values = {}
    for legacy_key, builder_key in LEGACY_BUILDER_PAINT_KEYS.items():
        if legacy_key in clean_paint:
            builder_values[builder_key] = clean_paint.pop(legacy_key)
    return clean_paint, _merge_builder_config(style_config, builder_values)


def rehydrate_legacy_paint_row(
    paint: dict | None,
    style_config: dict | None,
) -> tuple[dict, dict | None]:
    """Best-effort downgrade: copy known builder values back into paint.

    Unrelated style_config fields are preserved. The builder block is also
    preserved because later app versions may have written additional fields that
    this downgrade must not destroy.
    """
    restored_paint = dict(paint or {})
    if isinstance(style_config, dict):
        builder = style_config.get("builder")
        if isinstance(builder, dict):
            for builder_key, paint_key in DOWNGRADE_PAINT_KEYS.items():
                value = builder.get(builder_key)
                if value is not None and restored_paint.get(paint_key) is None:
                    restored_paint[paint_key] = value
    return restored_paint, style_config


def _rewrite_map_layers(transform) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, paint, style_config FROM catalog.map_layers")
    ).mappings()
    update_stmt = sa.text(
        "UPDATE catalog.map_layers "
        "SET paint = CAST(:paint AS jsonb), style_config = CAST(:style_config AS jsonb) "
        "WHERE id = :id"
    )
    for row in rows:
        paint, style_config = transform(row["paint"], row["style_config"])
        if paint != row["paint"] or style_config != row["style_config"]:
            bind.execute(
                update_stmt,
                {
                    "id": row["id"],
                    "paint": None if paint is None else json.dumps(paint),
                    "style_config": None
                    if style_config is None
                    else json.dumps(style_config),
                },
            )


def upgrade() -> None:
    _rewrite_map_layers(clean_legacy_paint_row)


def downgrade() -> None:
    _rewrite_map_layers(rehydrate_legacy_paint_row)
