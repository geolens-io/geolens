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
