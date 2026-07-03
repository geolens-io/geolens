"""Tests for AI chat style mutation validation."""

from app.processing.ai.schemas import (
    validate_paint_property_names_with_feedback,
    validate_paint_with_feedback,
)


def test_validate_clear_paint_filters_invalid_geometry_keys():
    cleaned, warnings = validate_paint_property_names_with_feedback(
        ["line-gradient", "fill-color", "line-gradient", 123],
        "LineString",
    )

    assert cleaned == ["line-gradient"]
    assert "Removed 'fill-color': not valid for line layers" in warnings
    assert "Removed non-string paint clear entry" in warnings


def test_validate_set_style_keeps_line_gradient_for_line_layers():
    gradient = ["interpolate", ["linear"], ["line-progress"], 0, "#00f", 1, "#0f0"]

    cleaned, warnings = validate_paint_with_feedback(
        {"line-color": "#f97316", "line-gradient": gradient},
        "LineString",
    )

    assert warnings == []
    assert cleaned == {"line-color": "#f97316", "line-gradient": gradient}


def test_validate_paint_with_feedback_heatmap_render_mode_keeps_heatmap_props():
    """fix(#392): a heatmap-rendered layer's dataset_geometry_type is
    virtually always Point, so without render_mode awareness heatmap-radius/
    heatmap-opacity/heatmap-intensity would be stripped as invalid-for-circle.
    set_style is the only AI tool that can tune those three properties. (audit WR-01)"""
    cleaned, warnings = validate_paint_with_feedback(
        {"heatmap-radius": 999, "heatmap-opacity": 2.0, "circle-color": "#f00"},
        "Point",
        "heatmap",
    )

    assert "heatmap-radius" in cleaned
    assert "heatmap-opacity" in cleaned
    # circle-color is not a valid heatmap paint property, so it's dropped even
    # though the geometry-type filter itself was bypassed.
    assert "circle-color" not in cleaned
    assert "Removed 'circle-color': not valid for heatmap layers" in warnings
    # Out-of-bounds values are still clamped.
    assert cleaned["heatmap-radius"] == 200.0
    assert cleaned["heatmap-opacity"] == 1.0


def test_validate_paint_with_feedback_without_render_mode_strips_heatmap_props():
    """Regression guard: without render_mode, a Point-geometry layer's heatmap-*
    paint is stripped as invalid-for-circle (fix #392, audit WR-01)."""
    cleaned, warnings = validate_paint_with_feedback(
        {"heatmap-radius": 30},
        "Point",
    )

    assert cleaned is None
    assert any("not valid for circle layers" in w for w in warnings)


def test_validate_clear_paint_property_names_heatmap_render_mode():
    """Companion to the paint fix: clear_paint entries must also survive
    render-mode-aware validation for heatmap layers."""
    cleaned, warnings = validate_paint_property_names_with_feedback(
        ["heatmap-radius", "circle-color"],
        "Point",
        "heatmap",
    )

    assert cleaned == ["heatmap-radius"]
    assert any("not valid for heatmap layers" in w for w in warnings)
