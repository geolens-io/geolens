"""Data-driven / categorical / graduated style builders for chat-edit."""

import math
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csv_safety import numeric_column_names
from app.processing.ai.chat_constants import _get_ramp_colors
from app.processing.ai.chat_style_guards import (
    finish_data_driven_result,
    outline_only_error,
)
from app.processing.ai.schemas import ChatMapLayer

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort


def _get_color_property(
    geometry_type: str | None, layer_type: str | None = None
) -> str:
    """Determine the correct MapLibre color paint property for the layer.

    Heatmap layers share the source's Point geometry but need heatmap-color,
    not circle-color, so layer_type is checked first.
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
    class_count = max(2, min(class_count, 9))

    target_layer = next((layer for layer in layers if layer.id == layer_id), None)

    if not target_layer:
        return {"error": f"Layer {layer_id} not found"}
    render_mode = (target_layer.style_config or {}).get("render_mode")
    if render_mode == "heatmap":
        return {
            "error": "A heatmap's colour follows point density, not a column. "
            "To weight it by a column, use set_style with a heatmap-weight expression."
        }
    if render_mode == "symbol":
        return {
            "error": "Symbol layers draw icons, so a column can't colour them. "
            "Switch the layer to point first to colour it by a column."
        }
    if render_mode == "cluster":
        return {
            "error": "Cluster bubbles aggregate many features, so a column can't "
            "colour them. Switch the layer to point first to colour it by a column."
        }

    color_prop = _get_color_property(
        target_layer.geometry_type, layer_type=target_layer.layer_type
    )
    if error := outline_only_error(target_layer, color_prop):
        return {"error": error}

    table_name = target_layer.dataset_table_name

    if target_layer.column_info:
        col_names = {c.get("name") for c in target_layer.column_info if c.get("name")}
        if column not in col_names:
            return {
                "error": f"Column '{column}' not found in layer. Available columns: {', '.join(sorted(col_names)[:10])}"
            }

    # Defense in depth: queries stay within the validated layer set.
    allowed_tables = {layer.dataset_table_name for layer in layers}

    if mode == "categorical":
        result = await _build_categorical_style(
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
        result = await _build_graduated_style(
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
    return finish_data_driven_result(result, layers)


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

    # ["match", ["get", column], val1, color1, ..., fallback]. MapLibre rejects
    # boolean match labels, so a boolean column is matched on its "true"/"false"
    # string form. Other types keep native labels.
    match_input: list = ["get", column]
    if any(isinstance(v, bool) for v in values):
        match_input = ["to-string", match_input]
        values = [str(v).lower() if isinstance(v, bool) else str(v) for v in values]
    match_expr: list = ["match", match_input]
    categories = []
    for i, val in enumerate(values):
        match_expr.append(val)
        match_expr.append(colors[i])
        categories.append({"value": val, "color": colors[i]})

    match_expr.append("#cccccc")

    paint: dict = {color_prop: match_expr}
    # Keep polygon fills visible under data-driven color.
    if color_prop == "fill-color":
        paint["fill-opacity"] = 0.7
        paint["_outline-color"] = "#374151"

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
    min_val = stats["min"]
    max_val = stats["max"]

    if min_val is None or max_val is None:
        return {"error": f"No numeric data for column {column}"}

    if method == "equal_interval":
        if max_val == min_val:
            breaks = [min_val]
        else:
            breaks = [
                min_val + (max_val - min_val) * i / class_count
                for i in range(1, class_count)
            ]
    else:
        # quantile
        breaks = stats.get("quantiles", [])

    # MapLibre requires strictly increasing finite stops. Deduplicate quantiles
    # here because frontend validation cannot repair generated expressions, and
    # drop non-finite values to keep JSON valid. Colours are resampled below to
    # match the remaining stops.
    breaks = sorted(
        {
            float(b)
            for b in breaks
            if isinstance(b, (int, float))
            and not isinstance(b, bool)
            and math.isfinite(b)
        }
    )

    if not breaks:
        return {"error": f"Cannot compute class breaks for column '{column}'"}

    colors = _get_ramp_colors(ramp, len(breaks) + 1)

    # ["step", ["get", column], color0, break1, color1, ...]
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
    # Keep polygon fills visible under data-driven color.
    if color_prop == "fill-color":
        paint["fill-opacity"] = 0.7
        paint["_outline-color"] = "#374151"

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


# Mirrors RENDERER_CAPABILITIES in frontend components/builder/renderAs.ts.
_RENDER_AS_BY_FAMILY = {
    "point": ("point", "symbol", "heatmap", "cluster"),
    "line": ("line", "arrow"),
    "polygon": ("fill", "stroke", "fill-stroke", "extrusion-3d"),
}
_RENDER_AS_STORED_AS_RENDER_MODE = {"symbol", "heatmap", "cluster", "arrow"}


def apply_render_as(tool_input: dict, layers: list[ChatMapLayer]) -> dict:
    """Validate a set_render_as call and record the new mode on its layer.

    The layer's style_config is updated in place so set_style later in the
    same turn validates paint against the new render mode.
    """
    target = next((lyr for lyr in layers if lyr.id == tool_input.get("layer_id")), None)
    if target is None:
        return {"error": "That layer is not on this map."}
    if target.layer_type == "raster_geolens":
        return {"error": "Raster layers have one render type and cannot be switched."}
    gt = (target.geometry_type or "").upper()
    family = next((f for f in ("point", "line", "polygon") if f.upper() in gt), None)
    allowed = _RENDER_AS_BY_FAMILY.get(family or "", ())
    render_as = tool_input.get("render_as")
    if render_as not in allowed:
        return {
            "error": f"'{render_as}' is not available for this layer. "
            f"Choose one of: {', '.join(allowed) or 'none'}."
        }
    # Mirrors canUseClusterSource in frontend components/builder/cluster-source.ts.
    if render_as == "cluster" and target.layer_type not in (
        None,
        "vector_geolens",
        "geojson",
    ):
        return {"error": "Only vector layers can be clustered."}
    if render_as == "cluster" and target.feature_count is None:
        return {"error": "Cluster needs the layer's feature count, which is unknown."}
    if render_as == "extrusion-3d":
        numeric = numeric_column_names(target.column_info)
        height_column = tool_input.get("height_column")
        builder = (target.style_config or {}).get("builder") or {}
        current = builder.get("heightColumn") or (target.paint or {}).get(
            "_height_column"
        )
        if height_column is None and current not in numeric:
            # Name the column here: the client's fallback type check is looser.
            height_column = next(
                (
                    c["name"]
                    for c in target.column_info or []
                    if isinstance(c, dict) and c.get("name") in numeric
                ),
                None,
            )
            if height_column is None:
                return {
                    "error": "This layer has no numeric column to take 3D heights from."
                }
            tool_input = {**tool_input, "height_column": height_column}
        elif height_column is not None and height_column not in numeric:
            return {
                "error": f"'{height_column}' is not a numeric column on this layer."
            }
    style = dict(target.style_config or {})
    if family == "polygon":
        builder = dict(style.get("builder") or {})
        builder["fillDisabled"] = render_as == "stroke"
        builder["strokeDisabled"] = render_as == "fill"
        style["builder"] = builder
    if render_as in _RENDER_AS_STORED_AS_RENDER_MODE:
        style["render_mode"] = render_as
    else:
        style.pop("render_mode", None)
    target.style_config = style
    return {"type": "set_render_as", **tool_input}
