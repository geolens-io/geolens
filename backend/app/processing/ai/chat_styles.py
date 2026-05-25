"""Data-driven / categorical / graduated style builders for chat-edit.

Phase 276 CODE-02 — extracted from chat_service.py.
"""

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ai.chat_constants import _get_ramp_colors
from app.processing.ai.schemas import ChatMapLayer

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort


def _get_color_property(
    geometry_type: str | None, layer_type: str | None = None
) -> str:
    """Determine the correct MapLibre color paint property for the layer.

    Heatmap layers share the source's Point geometry but require the
    heatmap-color paint property, not circle-color — check layer_type
    first so a heatmap-typed layer with Point geometry routes correctly.
    """
    if layer_type and "heatmap" in layer_type.lower():
        return "heatmap-color"
    if not geometry_type:
        return "circle-color"
    gt = geometry_type.lower()
    if "polygon" in gt:
        return "fill-color"
    if "line" in gt:
        return "line-color"
    if "heatmap" in gt:
        return "heatmap-color"
    return "circle-color"


async def _build_data_driven_style(
    tool_input: dict,
    session: AsyncSession,
    layers: list[ChatMapLayer],
    *,
    port: "ProcessingPort",
) -> dict:
    """Build a complete data-driven style from tool input + database lookups."""
    layer_id = tool_input["layer_id"]
    mode = tool_input["mode"]
    column = tool_input["column"]
    default_ramp = "Set2" if mode == "categorical" else "YlOrRd"
    ramp = tool_input.get("ramp", default_ramp)
    method = tool_input.get("method", "quantile")
    class_count = tool_input.get("class_count", 5)
    class_count = max(2, min(class_count, 9))  # Clamp to 2-9 classes

    # Find the layer to get table_name and geometry_type
    target_layer = None
    for layer in layers:
        if layer.id == layer_id:
            target_layer = layer
            break

    if not target_layer:
        return {"error": f"Layer {layer_id} not found"}

    table_name = target_layer.dataset_table_name

    # Validate column exists in layer
    if target_layer.column_info:
        col_names = {c.get("name") for c in target_layer.column_info if c.get("name")}
        if column not in col_names:
            return {
                "error": f"Column '{column}' not found in layer. Available columns: {', '.join(sorted(col_names)[:10])}"
            }

    color_prop = _get_color_property(
        target_layer.geometry_type, layer_type=target_layer.layer_type
    )

    # Build allowed_tables from the validated layer set for defense-in-depth
    allowed_tables = {layer.dataset_table_name for layer in layers}

    if mode == "categorical":
        return await _build_categorical_style(
            session,
            table_name,
            column,
            ramp,
            color_prop,
            layer_id,
            allowed_tables=allowed_tables,
            port=port,
        )
    else:
        return await _build_graduated_style(
            session,
            table_name,
            column,
            ramp,
            method,
            class_count,
            color_prop,
            layer_id,
            allowed_tables=allowed_tables,
            port=port,
        )


async def _build_categorical_style(
    session: AsyncSession,
    table_name: str,
    column: str,
    ramp: str,
    color_prop: str,
    layer_id: str,
    *,
    allowed_tables: set[str] | None = None,
    port: "ProcessingPort",
) -> dict:
    """Build categorical style with match expression."""
    values = await port.get_distinct_values(
        session,
        table_name,
        column,
        limit=50,
        allowed_tables=allowed_tables,
    )
    colors = _get_ramp_colors(ramp, len(values))

    # Build MapLibre match expression: ["match", ["get", column], val1, color1, ..., fallback]
    match_expr: list = ["match", ["get", column]]
    categories = []
    for i, val in enumerate(values):
        match_expr.append(val)
        match_expr.append(colors[i])
        categories.append({"value": val, "color": colors[i]})

    # Fallback color (gray)
    match_expr.append("#cccccc")

    paint: dict = {color_prop: match_expr}
    # Ensure fill is visible when applying data-driven color to polygons
    if color_prop == "fill-color":
        paint["fill-opacity"] = 0.7
        paint["_outline-color"] = "#374151"  # neutral dark gray outline

    return {
        "type": "set_data_driven_style",
        "layer_id": layer_id,
        "paint": paint,
        "style_config": {
            "mode": "categorical",
            "column": column,
            "ramp": ramp,
            "categories": categories,
        },
    }


async def _build_graduated_style(
    session: AsyncSession,
    table_name: str,
    column: str,
    ramp: str,
    method: str,
    class_count: int,
    color_prop: str,
    layer_id: str,
    *,
    allowed_tables: set[str] | None = None,
    port: "ProcessingPort",
) -> dict:
    """Build graduated style with step expression."""
    stats = await port.get_column_stats(
        session,
        table_name,
        column,
        class_count=class_count,
        allowed_tables=allowed_tables,
    )
    colors = _get_ramp_colors(ramp, class_count)

    min_val = stats["min"]
    max_val = stats["max"]

    if min_val is None or max_val is None:
        return {"error": f"No numeric data for column {column}"}

    # Compute breaks
    if method == "equal_interval":
        if max_val == min_val:
            breaks = [min_val]
        else:
            breaks = [
                min_val + (max_val - min_val) * i / class_count
                for i in range(1, class_count)
            ]
    else:
        # quantile: use the dynamically-computed quantiles from stats
        breaks = stats.get("quantiles", [])

    if not breaks:
        return {"error": f"Cannot compute class breaks for column '{column}'"}

    # Build MapLibre step expression: ["step", ["get", column], color0, break1, color1, ...]
    step_expr: list = ["step", ["get", column], colors[0]]
    break_entries = []
    for i, brk in enumerate(breaks):
        step_expr.append(brk)
        step_expr.append(colors[i + 1] if i + 1 < len(colors) else colors[-1])
        break_entries.append(
            {
                "value": brk,
                "color": colors[i + 1] if i + 1 < len(colors) else colors[-1],
            }
        )

    paint: dict = {color_prop: step_expr}
    # Ensure fill is visible when applying data-driven color to polygons
    if color_prop == "fill-color":
        paint["fill-opacity"] = 0.7
        paint["_outline-color"] = "#374151"  # neutral dark gray outline

    return {
        "type": "set_data_driven_style",
        "layer_id": layer_id,
        "paint": paint,
        "style_config": {
            "mode": "graduated",
            "column": column,
            "ramp": ramp,
            "method": method,
            "breaks": break_entries,
        },
    }
