"""Chat-based map editing service: LLM orchestration with tool calling."""

import json
import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import shapely
from shapely.geometry import shape as shapely_shape
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ai.llm_loop import resolve_provider, run_tool_loop
from app.processing.ai.schemas import (
    ChatAction,
    ChatHistoryMessage,
    ChatMapLayer,
    ChatResponse,
    history_to_dicts,
    validate_paint_with_feedback,
)
from app.processing.ai.sql_generator import build_sql_schema_context, generate_sql
from app.processing.ai.token_usage import record_token_usage
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC, CHAT_TOOLS_OPENAI
from app.processing.ai.service import _execute_search_tool, _should_send_sample_values
from app.core.identity import Identity
from app.modules.catalog.datasets.domain.column_stats import (
    get_column_stats,
    get_distinct_values,
)
from app.platform.sandbox import validate_and_execute, SandboxError

logger = structlog.stdlib.get_logger(__name__)

ERROR_MESSAGES = {
    "query_timeout": "Query took too long. Try narrowing your question to fewer features or a smaller area.",
    "table_not_accessible": "You don't have access to one of the referenced datasets.",
    "invalid_query": "I couldn't generate a valid query for that. Try rephrasing your question.",
    "query_failed": "Something went wrong. Try rephrasing your question.",
}

# Edit action tool names (everything except search_datasets)
_EDIT_TOOLS = {
    "set_filter",
    "set_style",
    "set_data_driven_style",
    "set_label",
    "toggle_visibility",
    "remove_layer",
    "add_layer",
    "set_opacity",
}

# Pre-computed color ramp palettes (no external dependency).
# NOTE: Frontend has a parallel copy in frontend/src/lib/color-ramps.ts.
# Keep both in sync when adding or correcting ramps.
RAMP_COLORS: dict[str, dict[str, list[str]]] = {
    "YlOrRd": {
        "5": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
        "8": [
            "#ffffcc",
            "#ffeda0",
            "#fed976",
            "#feb24c",
            "#fd8d3c",
            "#fc4e2a",
            "#e31a1c",
            "#b10026",
        ],
    },
    "Viridis": {
        "5": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
        "8": [
            "#440154",
            "#46327e",
            "#365c8d",
            "#277f8e",
            "#1fa187",
            "#4ac16d",
            "#9fda3a",
            "#fde725",
        ],
    },
    "Blues": {
        "5": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
        "8": [
            "#f7fbff",
            "#deebf7",
            "#c6dbef",
            "#9ecae1",
            "#6baed6",
            "#4292c6",
            "#2171b5",
            "#084594",
        ],
    },
    "Greens": {
        "5": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
        "8": [
            "#f7fcf5",
            "#e5f5e0",
            "#c7e9c0",
            "#a1d99b",
            "#74c476",
            "#41ab5d",
            "#238b45",
            "#005a32",
        ],
    },
    "RdYlBu": {
        "5": ["#d73027", "#fc8d59", "#ffffbf", "#91bfdb", "#4575b4"],
        "8": [
            "#d73027",
            "#f46d43",
            "#fdae61",
            "#fee090",
            "#e0f3f8",
            "#abd9e9",
            "#74add1",
            "#4575b4",
        ],
    },
    "Set2": {
        "5": ["#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854"],
        "8": [
            "#66c2a5",
            "#fc8d62",
            "#8da0cb",
            "#e78ac3",
            "#a6d854",
            "#ffd92f",
            "#e5c494",
            "#b3b3b3",
        ],
    },
    # Colorblind-safe ramps
    "Cividis": {
        "5": ["#002051", "#3b4f6b", "#6d7e53", "#b4a436", "#fdca26"],
        "8": [
            "#002051",
            "#253d5d",
            "#445e6e",
            "#5d7a6b",
            "#7b955a",
            "#9fb045",
            "#c8ca33",
            "#fdca26",
        ],
    },
    "PuOr": {
        "5": ["#e66101", "#fdb863", "#f7f7f7", "#b2abd2", "#5e3c99"],
        "8": [
            "#b35806",
            "#e08214",
            "#fdb863",
            "#fee0b6",
            "#d8daeb",
            "#b2abd2",
            "#8073ac",
            "#542788",
        ],
    },
}


def _get_ramp_colors(ramp: str, count: int) -> list[str]:
    """Get a list of colors from a named ramp, cycling if needed."""
    palette = RAMP_COLORS.get(ramp, RAMP_COLORS["YlOrRd"])
    # Use the closest pre-computed palette size
    if count <= 5:
        colors = palette["5"]
    else:
        colors = palette["8"]

    # If count matches, return as-is; if fewer, slice; if more, cycle
    if count <= len(colors):
        return colors[:count]
    return [colors[i % len(colors)] for i in range(count)]


def _get_color_property(geometry_type: str | None) -> str:
    """Determine the correct MapLibre color paint property for a geometry type."""
    if not geometry_type:
        return "circle-color"
    gt = geometry_type.lower()
    if "polygon" in gt:
        return "fill-color"
    if "line" in gt:
        return "line-color"
    return "circle-color"


def _build_label_action(tool_input: dict) -> dict:
    """Restructure set_label tool output into the ChatAction label_config shape."""
    column = tool_input.get("column")
    if column:
        return {
            "type": "set_label",
            "layer_id": tool_input.get("layer_id"),
            "label_config": {
                "column": column,
                "fontSize": tool_input.get("font_size", 12),
                "textColor": tool_input.get("text_color", "#333333"),
                "haloColor": "#ffffff",
                "haloWidth": 1.5,
            },
        }
    return {
        "type": "set_label",
        "layer_id": tool_input.get("layer_id"),
        "label_config": None,
    }


_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}


def lang_name(code: str | None) -> str:
    """Map an ISO 639-1 code to a human-readable language name."""
    if not code:
        return "English"
    # Handle codes like "en-US" → "en"
    base = code.split("-")[0].lower()
    return _LANGUAGE_NAMES.get(base, "English")


# Maximum tokens to budget for the system prompt (cap layer context to fit)
_MAX_SYSTEM_PROMPT_LAYERS = 15
_MAX_COLUMNS_PER_LAYER = 30
_MAX_SAMPLE_COLS = 3


def build_chat_system_prompt(
    layers: list[ChatMapLayer],
    language: str | None = None,
    basemap_style: str | None = None,
) -> str:
    """Build a system prompt that describes the user's current map state."""
    # Cap layers to prevent unbounded prompt growth
    display_layers = layers[:_MAX_SYSTEM_PROMPT_LAYERS]
    truncated_count = len(layers) - len(display_layers)

    layers_desc = []
    for layer in display_layers:
        # Limit column info to first N columns to avoid token bloat
        cols_raw = layer.column_info or []
        cols_limited = cols_raw[:_MAX_COLUMNS_PER_LAYER]
        cols_str = ", ".join(
            f"{c.get('name', '?')} ({c.get('type', '?')})" for c in cols_limited
        )
        if len(cols_raw) > _MAX_COLUMNS_PER_LAYER:
            cols_str += f" ... and {len(cols_raw) - _MAX_COLUMNS_PER_LAYER} more"

        summary_parts = [f"Visible: {layer.visible}"]
        if layer.filter:
            summary_parts.append(f"Filter: {json.dumps(layer.filter)}")
        if layer.label_config:
            summary_parts.append(f"Labels: {json.dumps(layer.label_config)}")
        if layer.style_config:
            summary_parts.append(f"Data-driven style: {json.dumps(layer.style_config)}")
        if layer.paint:
            summary_parts.append(f"Paint: {json.dumps(layer.paint)}")

        # Dataset metadata lines
        title_str = f"\n  Title: {layer.dataset_title}" if layer.dataset_title else ""
        feat_count_str = (
            f"\n  Features: {layer.feature_count}" if layer.feature_count else ""
        )

        # Sample values (limit to first N columns, 5 values each)
        sample_str = ""
        if layer.sample_values:
            sample_parts = []
            for col_name, values in list(layer.sample_values.items())[
                :_MAX_SAMPLE_COLS
            ]:
                vals = values[:5] if isinstance(values, list) else [values]
                sample_parts.append(f"{col_name}: {vals}")
            if sample_parts:
                sample_str = "\n  Sample values: " + "; ".join(sample_parts)

        is_raster = layer.layer_type == "raster_geolens"
        raster_note = (
            " [raster layer - opacity only, no style/filter/label]" if is_raster else ""
        )
        layers_desc.append(
            f'- Layer "{layer.name}" (id: {layer.id}, '
            f"geometry: {layer.geometry_type}, "
            f"dataset_id: {layer.dataset_id}, "
            f"table: {layer.dataset_table_name})"
            f"{raster_note}"
            f"{title_str}"
            f"{feat_count_str}\n"
            f"  Columns: {cols_str}"
            f"{sample_str}\n"
            f"  {', '.join(summary_parts)}"
        )

    truncation_note = ""
    if truncated_count > 0:
        truncation_note = f"\n\n(... and {truncated_count} more layers not shown. If the user references a layer not listed above, tell them you cannot see that layer.)"

    return f"""\
You are a map editing assistant. The user has a map with these layers:

{chr(10).join(layers_desc)}{truncation_note}

## Instructions
- Modify the map based on the user's instructions using the available tools.
- Always reference layers by their id (UUID).
- Users may reference layers by name using @LayerName or @[Layer Name] syntax. Match the name to the layers listed above to find the correct layer id.
  Example: If the user says "make @Parks green" and there is a layer named "Parks" with id "abc-1234", call set_style with layer_id "abc-1234".
  If no layer matches the name, tell the user which layers are available.
- For style changes, use the correct paint property for the geometry type:
  - fill-color for Polygon/MultiPolygon
  - line-color for LineString/MultiLineString
  - circle-color for Point/MultiPoint
- For data-driven coloring (e.g., "color by population"), use set_data_driven_style, NOT set_style.
- For simple flat color changes (e.g., "make it red"), use set_style.
  Example paint: {{"fill-color": "#ef4444", "fill-opacity": 0.7, "_outline-color": "#dc2626"}}
- For filter expressions, use MapLibre expression syntax: ["all", [">", "column", value]]
  Example filters: ["==", ["get", "status"], "active"], ["all", [">", ["get", "population"], 50000], ["==", ["get", "state"], "CA"]]
- For compound requests that include both a question and a map change, use both query_data and editing tools in a single response.
- To add a new layer, first use search_datasets to find the dataset, then use add_layer with the dataset_id.
- When the user asks a QUESTION about their data (counts, statistics, spatial
  relationships, distances, finding features), use the query_data tool.
- When the user asks to CHANGE the map (colors, filters, labels, visibility,
  add/remove layers), use the map editing tools.
- query_data takes a natural language question -- the server generates and
  executes the SQL safely.
- Keep your explanations concise (1-3 sentences).
- For raster layers (marked "[raster layer]"), only use set_opacity (with layer_id and opacity 0.0-1.0) or toggle_visibility. Do not use set_style, set_filter, set_label, or set_data_driven_style on raster layers.
- To add a raster dataset as a layer, use search_datasets then add_layer — same as vector.
- The current basemap is: {basemap_style or "unknown"}.{" This is a dark basemap — use light colors for labels (#e5e7eb) and outlines (#d1d5db)." if basemap_style and "dark" in basemap_style.lower() else " Use dark colors for labels (#333333) and outlines (#374151)."}

## Query Data Responses
When reporting query results back to the user:
- Lead with the key finding, then add context.
- Keep answers concise (2-4 sentences for simple questions, up to a paragraph for complex ones).
- If results were truncated, mention it naturally (e.g., "showing the first 50 of 1,200 results").
- Never show raw SQL, table structures, or row counts as bare numbers -- interpret them meaningfully.
- If no results were found, tell the user and suggest trying different criteria.

## Uncertainty
- If you are uncertain about a column name or data interpretation, say so in your explanation.
- Do not guess column names that are not listed in the layer info above.
- If a user's request cannot be fulfilled with the available tools, explain what is not supported.

## Error Handling
- If a layer cannot be found by the user's name, say so and list available layer names.
- If a column doesn't exist in a layer, say so and mention similar available columns.
- If a user requests an unsupported operation on a raster layer, explain: "Raster layers only support opacity and visibility changes."

## Language
Always respond in {lang_name(language)}. Never switch to another language.
"""


def _extract_get_refs(expr: list | None) -> set[str]:
    """Recursively extract column names from ["get", "col"] expression nodes."""
    if not isinstance(expr, list) or len(expr) == 0:
        return set()
    refs: set[str] = set()
    if len(expr) >= 2 and expr[0] == "get" and isinstance(expr[1], str):
        refs.add(expr[1])
    for item in expr:
        if isinstance(item, list):
            refs.update(_extract_get_refs(item))
    return refs


def _validate_filter_columns(
    expression: list | None, layer: ChatMapLayer | None
) -> list | None:
    """Validate column refs in a filter expression against layer column_info.

    Returns the expression unchanged if valid, or None if invalid refs found.
    """
    if expression is None or layer is None:
        return expression
    col_names = {c.get("name") for c in (layer.column_info or []) if c.get("name")}
    if not col_names:
        return expression  # no column_info to validate against
    refs = _extract_get_refs(expression)
    invalid = refs - col_names
    if invalid:
        logger.warning(
            "Filter references non-existent columns, clearing filter",
            invalid_columns=list(invalid),
            layer_id=layer.id,
        )
        return None
    return expression


def _validate_actions(
    actions: list[ChatAction], layers: list[ChatMapLayer]
) -> tuple[list[ChatAction], list[str]]:
    """Validate layer_id references in actions. Filter out invalid ones."""
    valid_layer_ids = {layer.id for layer in layers}
    layer_map = {layer.id: layer for layer in layers}
    validated = []
    dropped: list[str] = []
    for action in actions:
        # add_layer: validate dataset_id is present (actual RBAC check happens on the frontend add)
        if action.type == "add_layer":
            if not action.dataset_id:
                dropped.append("add_layer (missing dataset_id)")
                continue
            try:
                UUID(action.dataset_id)
            except (ValueError, AttributeError):
                dropped.append(f"add_layer (invalid dataset_id: {action.dataset_id})")
                continue
            validated.append(action)
            continue
        if action.layer_id and action.layer_id not in valid_layer_ids:
            logger.warning(
                "Invalid layer_id in chat action, skipping",
                action_type=action.type,
                layer_id=action.layer_id,
            )
            dropped.append(f"{action.type} (invalid layer_id: {action.layer_id})")
            continue
        # Validate column refs in filter expressions
        if action.type == "set_filter" and action.expression is not None:
            target_layer = layer_map.get(action.layer_id) if action.layer_id else None
            validated_expr = _validate_filter_columns(action.expression, target_layer)
            if validated_expr is None:
                dropped.append(
                    f"{action.type} (invalid column refs in filter expression)"
                )
                continue  # skip action with invalid column refs
            action.expression = validated_expr
        validated.append(action)
    return validated, dropped


# ---------------------------------------------------------------------------
# Geometry detection & GeoJSON helpers (ephemeral result layers)
# ---------------------------------------------------------------------------

_GEOM_NAMES = {"geom_4326", "geom", "geometry", "the_geom", "wkb_geometry"}
_HEX_RE = re.compile(r"^[0-9a-fA-F]{10,}$")


def _is_geom_value(val: object) -> bool:
    """Check if a value looks like WKB hex or ST_AsGeoJSON output."""
    if not isinstance(val, str):
        return False
    # WKB hex: long even-length hex string
    if len(val) >= 10 and len(val) % 2 == 0 and _HEX_RE.match(val):
        return True
    # ST_AsGeoJSON: JSON string containing geometry type
    if val.startswith("{") and '"type"' in val:
        return True
    return False


def _detect_geom_column(columns: list[str], first_row: list) -> int | None:
    """Find the index of a geometry column by name + value check."""
    for i, col in enumerate(columns):
        name = col.lower()
        if name in _GEOM_NAMES or name.startswith("st_"):
            if i < len(first_row) and _is_geom_value(first_row[i]):
                return i
    return None


def _safe_value(v: object) -> object:
    """Convert non-JSON-serializable types to str; pass through primitives."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date, Decimal, bytes, memoryview, UUID)):
        return str(v)
    return str(v)


def _extract_geojson(
    columns: list[str], rows: list[list]
) -> tuple[dict, list[float]] | None:
    """Build a GeoJSON FeatureCollection + bbox from query rows."""
    if not rows:
        return None

    geom_idx = _detect_geom_column(columns, rows[0])
    if geom_idx is None:
        return None

    prop_indices = [(i, col) for i, col in enumerate(columns) if i != geom_idx]
    features: list[dict] = []
    min_x, min_y, max_x, max_y = (
        float("inf"),
        float("inf"),
        float("-inf"),
        float("-inf"),
    )

    for row in rows:
        raw = row[geom_idx] if geom_idx < len(row) else None
        if raw is None:
            continue

        # Parse geometry
        try:
            if isinstance(raw, str) and raw.startswith("{"):
                geom_dict = json.loads(raw)
                shape = shapely_shape(geom_dict)
                geometry = geom_dict
            else:
                shape = shapely.from_wkb(bytes.fromhex(raw))
                geometry = json.loads(shapely.to_geojson(shape))
        except Exception:
            continue

        # Build properties
        props = {}
        for idx, col_name in prop_indices:
            props[col_name] = _safe_value(row[idx] if idx < len(row) else None)

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            }
        )

        # Update bbox
        bx = shape.bounds  # (minx, miny, maxx, maxy)
        if bx[0] < min_x:
            min_x = bx[0]
        if bx[1] < min_y:
            min_y = bx[1]
        if bx[2] > max_x:
            max_x = bx[2]
        if bx[3] > max_y:
            max_y = bx[3]

    if not features:
        return None

    fc = {"type": "FeatureCollection", "features": features}
    bbox = [min_x, min_y, max_x, max_y]
    return fc, bbox


async def _handle_query_data(
    tool_input: dict,
    session: AsyncSession,
    user: Identity,
    layers: list[ChatMapLayer],
    stage_callback: Callable[[str], None] | None = None,
) -> dict:
    """Handle query_data tool: generate SQL, validate, execute via sandbox."""
    question = tool_input["question"]
    schema_context = build_sql_schema_context(layers)

    # Build brief layer descriptions for SQL context
    layer_desc_parts = []
    for layer in layers:
        desc = f"- {layer.dataset_table_name}"
        if layer.dataset_title:
            desc += f" ({layer.dataset_title})"
        if layer.feature_count:
            desc += f" [{layer.feature_count} features]"
        layer_desc_parts.append(desc)
    layer_descriptions = "\n".join(layer_desc_parts) if layer_desc_parts else None

    if stage_callback:
        stage_callback("Generating SQL...")

    sql = await generate_sql(
        session, question, schema_context, layer_descriptions=layer_descriptions
    )

    # Surface LLM error messages directly instead of letting the sandbox reject them
    if sql.strip().startswith("-- ERROR:"):
        error_msg = sql.strip().removeprefix("-- ERROR:").strip()
        return {"error": error_msg, "category": "llm_cannot_answer"}

    if stage_callback:
        stage_callback("Running query...")

    result = await validate_and_execute(sql, session, user)
    # Limit rows in tool result for token economy
    # Note: raw SQL intentionally excluded to prevent info disclosure via LLM leakage
    out: dict = {
        "columns": result.columns,
        "rows": result.rows[:50],
        "row_count": result.row_count,
        "truncated": result.truncated,
    }
    if result.row_count == 0:
        out["note"] = (
            "No matching results found. The user may want to try different criteria."
        )

    # Extract GeoJSON for ephemeral result layers
    geojson_result = _extract_geojson(result.columns, result.rows[:50])
    if geojson_result is not None:
        out["geojson"] = geojson_result[0]
        out["bbox"] = geojson_result[1]

    return out


async def _execute_chat_tool(
    tool_name: str,
    tool_input: dict,
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    layers: list[ChatMapLayer],
    stage_callback: Callable[[str], None] | None = None,
) -> dict:
    """Execute a chat tool and return the result."""
    if tool_name == "search_datasets":
        send_samples = await _should_send_sample_values(session)
        results = await _execute_search_tool(
            session,
            user,
            user_roles,
            tool_input,
            send_sample_values=send_samples,
        )
        return {"results": results}

    if tool_name == "query_data":
        try:
            return await _handle_query_data(
                tool_input, session, user, layers, stage_callback=stage_callback
            )
        except SandboxError as e:
            return {
                "error": ERROR_MESSAGES.get(
                    e.category, "Something went wrong. Try rephrasing your question."
                ),
                "category": e.category,
            }
        except Exception as e:
            logger.warning(
                "query_data.failed", error=str(e), error_type=type(e).__name__
            )
            return {"error": "Could not generate or execute query"}

    if tool_name == "set_data_driven_style":
        return await _build_data_driven_style(tool_input, session, layers)

    # Validate paint properties for set_style against geometry type
    if tool_name == "set_style" and tool_input.get("paint"):
        target = next(
            (lyr for lyr in layers if lyr.id == tool_input.get("layer_id")), None
        )
        if target:
            validated_paint, warnings = validate_paint_with_feedback(
                tool_input["paint"], target.geometry_type
            )
            tool_input = {**tool_input, "paint": validated_paint or {}}
            if warnings:
                return {"status": "ok", "warnings": warnings, **tool_input}

    # For all other edit tools, return tool_input as-is
    if tool_name in _EDIT_TOOLS:
        return {"status": "ok", **tool_input}

    return {"error": f"Unknown tool: {tool_name}"}


async def _build_data_driven_style(
    tool_input: dict,
    session: AsyncSession,
    layers: list[ChatMapLayer],
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

    color_prop = _get_color_property(target_layer.geometry_type)

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
) -> dict:
    """Build categorical style with match expression."""
    values = await get_distinct_values(
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
) -> dict:
    """Build graduated style with step expression."""
    stats = await get_column_stats(
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


def _collect_chat_action(tool_name: str, tool_input: dict, result: dict) -> dict | None:
    """Build an action dict from a chat tool call.

    Used as the action_collector callback for run_tool_loop.
    """
    if tool_name not in _EDIT_TOOLS:
        # Check for query_data with geometry
        if tool_name == "query_data" and "geojson" in result:
            return {
                "type": "show_query_result",
                "geojson": result["geojson"],
                "bbox": result["bbox"],
            }
        return None

    if tool_name == "set_data_driven_style":
        if "error" not in result:
            return result
        return None

    if tool_name == "set_label":
        return _build_label_action(tool_input)

    # Some models pass expression as a JSON string instead of an array
    if tool_name == "set_filter" and isinstance(tool_input.get("expression"), str):
        try:
            tool_input = {
                **tool_input,
                "expression": json.loads(tool_input["expression"]),
            }
        except (json.JSONDecodeError, ValueError):
            pass

    return {"type": tool_name, **tool_input}


async def chat_edit_map(
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    message: str,
    layers: list[ChatMapLayer],
    language: str | None = None,
    history: list[ChatHistoryMessage] | None = None,
    basemap_style: str | None = None,
) -> ChatResponse:
    """Main orchestrator: run LLM tool-calling loop for chat map editing.

    Provider selection: Anthropic if key is set, else OpenAI-compatible.
    Returns ChatResponse with explanation and validated actions.
    """
    system_prompt = build_chat_system_prompt(
        layers, language=language, basemap_style=basemap_style
    )
    provider, model, base_url = await resolve_provider(session)

    history_dicts = history_to_dicts(history)

    # Build tool executor bound to this session/user/layers
    async def tool_executor(tool_name: str, tool_input: dict) -> dict:
        return await _execute_chat_tool(
            tool_name, tool_input, session, user, user_roles, layers
        )

    result = await run_tool_loop(
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_message=message,
        tools_anthropic=CHAT_TOOLS_ANTHROPIC,
        tools_openai=CHAT_TOOLS_OPENAI,
        tool_executor=tool_executor,
        action_collector=_collect_chat_action,
        history=history_dicts,
        base_url=base_url,
        temperature=0.3,
    )

    logger.info(
        "Chat edit complete",
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )

    await record_token_usage(
        session,
        user_id=user.id,
        subsystem="chat",
        model=model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )

    # Parse actions into ChatAction models
    actions = [ChatAction(**a) for a in result.actions]

    # Validate layer_id references
    actions, dropped = _validate_actions(actions, layers)

    explanation = result.text
    if dropped:
        explanation += "\n\nNote: some actions were skipped: " + "; ".join(dropped)

    return ChatResponse(
        explanation=explanation,
        actions=actions,
    )
