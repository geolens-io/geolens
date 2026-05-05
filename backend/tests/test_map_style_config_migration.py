"""Tests for the 0004 map paint/style_config data migration."""

import importlib.util
from pathlib import Path


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0004_style_config_paint_cleanup.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0004_style_config_paint_cleanup",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def test_clean_legacy_paint_row_moves_builder_state_without_losing_visual_paint():
    paint = {
        "fill-color": "#ef4444",
        "fill-opacity": 0,
        "circle-stroke-width": 0,
        "_fill-disabled": True,
        "_outline-color": "#111827",
        "_outline-width": 2,
    }

    clean_paint, style_config = migration.clean_legacy_paint_row(paint, None)

    assert clean_paint == {
        "fill-color": "#ef4444",
        "fill-opacity": 0,
        "circle-stroke-width": 0,
    }
    assert style_config == {
        "builder": {
            "fill_disabled": True,
            "outline_color": "#111827",
            "outline_width": 2,
        }
    }


def test_clean_legacy_paint_row_preserves_existing_non_null_builder_values():
    paint = {
        "outline-color": "#334155",
        "outline-width": 4,
        "_outline-width-saved": 1.5,
        "_heatmap-ramp": "viridis",
        "_heatmap-weight-column": "density",
        "_height_column": "height_m",
    }
    existing_style_config = {
        "mode": "heatmap",
        "builder": {
            "outline_color": "#000000",
            "outline_width": None,
            "heatmap_ramp": "magma",
        },
    }

    clean_paint, style_config = migration.clean_legacy_paint_row(
        paint,
        existing_style_config,
    )

    assert clean_paint == {}
    assert style_config == {
        "mode": "heatmap",
        "builder": {
            "outline_color": "#000000",
            "outline_width": 4,
            "outline_width_saved": 1.5,
            "heatmap_ramp": "magma",
            "heatmap_weight_column": "density",
            "height_column": "height_m",
        },
    }


def test_rehydrate_legacy_paint_row_is_best_effort_and_preserves_style_config():
    paint = {"fill-color": "#3b82f6"}
    style_config = {
        "mode": "3d",
        "builder": {
            "outline_color": "#1d4ed8",
            "outline_width": 1,
            "height_column": "height_m",
        },
    }

    restored_paint, restored_style_config = migration.rehydrate_legacy_paint_row(
        paint,
        style_config,
    )

    assert restored_paint == {
        "fill-color": "#3b82f6",
        "_outline-color": "#1d4ed8",
        "_outline-width": 1,
        "_height_column": "height_m",
    }
    assert restored_style_config == style_config
