"""Tool definitions for chat-based map editing LLM interactions.

This module declares the **JSON schemas** that the LLM sees as tool definitions
when generating maps or editing them via chat. Each tool corresponds to one
action the LLM can take (search the catalog, add/remove a layer, set a filter,
change a paint property, generate a data-driven style, etc.). The actual
execution of each tool happens in `app.ai.service` and `app.ai.chat_service` —
this file is the **contract** the LLM is shown.

# Editing guidelines
# ------------------
# - Anthropic and OpenAI tool schemas are produced by the helper functions at
#   the bottom of this file (`get_anthropic_tools`, `get_openai_tools`). Add
#   new tools by extending the underlying schema constants and re-exporting
#   from those helpers — do NOT inline tool definitions in service.py.
# - Schemas must stay valid JSON Schema. The LLM will reject malformed tool
#   definitions silently (the request will succeed but no tool calls happen).
# - Tool descriptions are visible to the model — keep them prescriptive and
#   short. Long descriptions waste tokens on every request.
"""

# --- Shared search_datasets schema (reused from service.py) ---

_SEARCH_DATASETS_SCHEMA = {
    "type": "object",
    "properties": {
        "q": {
            "type": "string",
            "description": "Full-text search query",
        },
        "geometry_type": {
            "type": "string",
            "description": (
                "Filter by geometry type: POINT, LINESTRING, POLYGON, "
                "MULTIPOINT, MULTILINESTRING, MULTIPOLYGON"
            ),
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Filter by keywords",
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return (default 10, max 25)",
            "default": 10,
        },
        "bbox": {
            "type": "array",
            "items": {"type": "number"},
            "description": (
                "Spatial bounding box filter [west, south, east, north] in "
                "WGS84 coordinates. Use this to find datasets in a specific area."
            ),
        },
    },
}

_SEARCH_DATASETS_DESC = (
    "Search the dataset catalog. Returns matching datasets with id, "
    "title, summary, geometry_type, keywords, extent_bbox, feature_count, "
    "column_info (up to 20 columns with name/type), and sample_values "
    "(up to 5 columns). Use this to find datasets before adding them as layers."
)

# --- get_dataset_details tool schema ---

_GET_DATASET_DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "dataset_id": {
            "type": "string",
            "description": "Dataset UUID to get details for",
        },
    },
    "required": ["dataset_id"],
}

_GET_DATASET_DETAILS_DESC = (
    "Get full column info, sample values, and feature count for a specific "
    "dataset. Use after search_datasets to understand a dataset's columns "
    "before applying data-driven styling."
)


# --- Anthropic tool format ---

CHAT_TOOLS_ANTHROPIC = [
    {
        "name": "search_datasets",
        "description": _SEARCH_DATASETS_DESC,
        "input_schema": _SEARCH_DATASETS_SCHEMA,
    },
    {
        "name": "set_filter",
        "description": (
            # fix(#549): a pointer, not a second copy of the rule. This tool
            # carried no routing guidance at all while run_analysis carried
            # some, which is how "show me the ..." landed on a persistent
            # layer filter instead of a query result.
            "Set or clear a filter on a map layer. This is the map-edit path: "
            "it changes what the map shows and persists on save. The system "
            "prompt's verb classes decide when a request routes here. "
            "Pass a MapLibre filter "
            "expression array to filter features, or null to clear the filter. "
            "Always reference columns with the expression form "
            '["get", "column"] -- never bare field names. '
            'Example: ["all", [">", ["get", "population"], 1000000], '
            '["==", ["get", "state"], "CA"]]'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
                "expression": {
                    "description": (
                        "MapLibre filter expression array, or null to clear"
                    ),
                    "oneOf": [{"type": "array"}, {"type": "null"}],
                },
            },
            "required": ["layer_id"],
        },
    },
    {
        "name": "set_style",
        "description": (
            "Patch paint properties of a layer (e.g., color, opacity, width). "
            "Unspecified paint properties are preserved. Use clear_paint to "
            "remove stale properties such as line-gradient or line-dasharray. "
            "Set replace_paint=true only when paint contains the complete "
            "desired paint object. Use the correct paint property for the "
            "geometry type: fill-color for polygons, line-color for lines, "
            "circle-color for points. Data-driven coloring (a colour that "
            # fix(#549 codex r1): reworded from "Do NOT use this for ... use
            # set_data_driven_style instead". The pointer is a CAPABILITY
            # difference and stays, but the old phrasing read as
            # request-classification prose, which is the shape the routing
            # guard now rejects.
            "varies by column value) belongs to set_data_driven_style."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
                "paint": {
                    "type": "object",
                    "description": (
                        "MapLibre paint properties to patch into the current "
                        "layer style. Omitted properties are preserved."
                    ),
                },
                "clear_paint": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "MapLibre paint property names to clear/unset. Use for "
                        "transitions like gradient to solid color."
                    ),
                },
                "replace_paint": {
                    "type": "boolean",
                    "description": (
                        "When true, replace the whole paint object with paint "
                        "after applying clear_paint. Defaults to false."
                    ),
                },
            },
            "required": ["layer_id"],
        },
    },
    {
        "name": "set_data_driven_style",
        "description": (
            "Apply data-driven coloring (categorical or graduated) to a layer "
            "based on a column. Use 'categorical' for text/string columns "
            "(e.g., land use type) and 'graduated' for numeric columns "
            "(e.g., population). The server fetches actual column values/stats "
            "and builds the full paint expression."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["categorical", "graduated"],
                    "description": "Styling mode",
                },
                "column": {
                    "type": "string",
                    "description": "Column name to style by",
                },
                "ramp": {
                    "type": "string",
                    "description": (
                        "Color ramp name: YlOrRd, Viridis, Blues, Greens, "
                        "RdYlBu, Set2, Cividis (colorblind-safe), "
                        "PuOr (colorblind-safe diverging). Default: YlOrRd"
                    ),
                },
                "method": {
                    "type": "string",
                    "enum": ["equal_interval", "quantile"],
                    "description": (
                        "Classification method for graduated mode (default: quantile)"
                    ),
                },
                "class_count": {
                    "type": "integer",
                    "description": "Number of classes (default 5)",
                },
            },
            "required": ["layer_id", "mode", "column"],
        },
    },
    {
        "name": "set_label",
        "description": (
            "Enable or configure labels on a layer. Set column to null to "
            "disable labels. Choose a text or name column for best results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
                "column": {
                    "type": ["string", "null"],
                    "description": "Column to label by, or null to disable",
                },
                "font_size": {
                    "type": "number",
                    "description": "Font size in pixels (default 12)",
                },
                "text_color": {
                    "type": "string",
                    "description": "Text color hex string (default #333333)",
                },
            },
            "required": ["layer_id", "column"],
        },
    },
    {
        "name": "toggle_visibility",
        "description": "Show or hide a layer on the map.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
                "visible": {
                    "type": "boolean",
                    "description": "True to show, false to hide",
                },
            },
            "required": ["layer_id", "visible"],
        },
    },
    {
        "name": "set_opacity",
        "description": (
            "Set the opacity of a layer. Works for both vector and raster layers. "
            "Use values from 0.0 (fully transparent) to 1.0 (fully opaque)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
                "opacity": {
                    "type": "number",
                    "description": "Opacity value from 0.0 (transparent) to 1.0 (opaque)",
                },
            },
            "required": ["layer_id", "opacity"],
        },
    },
    {
        "name": "remove_layer",
        "description": "Remove a layer from the map entirely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID)",
                },
            },
            "required": ["layer_id"],
        },
    },
    {
        "name": "add_layer",
        "description": (
            "Add a new layer to the map from a dataset. Use search_datasets "
            "first to find the dataset_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "Dataset ID (UUID) to add as a layer",
                },
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "query_data",
        "description": (
            # fix(#549 codex r1): behavioural only. This description used to
            # classify user phrasing too ("use this when the user asks a
            # question", "do NOT use this for map styling"), competing with
            # the system prompt's verb classes from a second site without
            # naming any sibling tool.
            "Query the user's map data using SQL. The server generates the "
            "SQL from a natural language question and executes it safely, so "
            "the result is a table of values plus an optional highlight "
            "overlay -- never a persistent map change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's natural language question about their data",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "run_analysis",
        "description": (
            # fix(#549): behavioural only. This description used to classify
            # user phrasing -- it cited "show the centre point of each parcel"
            # as a transform request while the system prompt left "show"
            # unclassified, so the model read verb classes from two competing
            # sites. The system prompt is now the single owner of verb
            # classification; nothing here may re-litigate which phrasing wins.
            "Run a parameterized PostGIS geometry operation on a layer and "
            "draw the result on the map as a temporary preview. buffer grows "
            "each feature by a distance; centroid replaces each feature with "
            "its centre point. The preview is temporary and is not saved. "
            "Do NOT tell the user where to save it -- the tool result says "
            "what they need to know, and the surfaces differ."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {
                    "type": "string",
                    "description": "Layer ID (UUID) to run the operation on",
                },
                "operation": {
                    "type": "string",
                    # feat(#683): `clip` joined the enum once #682 shipped the
                    # layer-sourced mask. The old narrowing said clip needed a
                    # drawn polygon only the Analysis rail could supply, which
                    # stopped being true then. `dissolve` stays out on its own
                    # merits: it is materialize-only, an aggregate with no
                    # preview shape.
                    "enum": ["buffer", "centroid", "clip"],
                    "description": (
                        "buffer = grow each feature by a distance; "
                        "centroid = replace each feature with its centre "
                        "point; clip = keep only the parts of each feature "
                        "that fall inside another layer"
                    ),
                },
                "distance_meters": {
                    "type": "number",
                    "description": (
                        "Buffer distance in metres, 0 < d <= 100000 "
                        "(required for buffer, ignored otherwise)"
                    ),
                },
                "mask_layer_id": {
                    "type": "string",
                    "description": (
                        "Layer ID (UUID) of the POLYGON layer to clip against "
                        "(required for clip, ignored otherwise). Must be a "
                        "different layer from layer_id."
                    ),
                },
            },
            "required": ["layer_id", "operation"],
        },
    },
]


# Read-only chat tools: a user who can VIEW a map but not edit it (non-owner /
# non-admin) may ask the AI questions about the map's data but must not be able
# to change it. We enforce this by withholding every mutating tool from the
# model — the read-only set can answer questions (sandboxed, RBAC-scoped
# SELECTs) and draw a temporary analysis preview, but has no tool to emit a
# style / filter / label / visibility / opacity / add- or remove-layer edit.
# ``run_analysis`` qualifies: it only SELECTs through the same sandbox rails and
# its result is an ephemeral overlay, never a persisted map change. Edit
# *persistence* is separately owner-gated at Save, so this is defense-in-depth,
# not the only gate.
_READONLY_TOOL_NAMES = {"query_data", "run_analysis"}
CHAT_TOOLS_READONLY = [
    t for t in CHAT_TOOLS_ANTHROPIC if t["name"] in _READONLY_TOOL_NAMES
]

# Tools whose entire output is a map overlay — withheld from map-less surfaces
# (dataset-scoped chat) by select_chat_tools(has_map=False).
_MAP_ONLY_TOOL_NAMES = {"run_analysis"}


def select_chat_tools(can_edit: bool, has_map: bool = True) -> list:
    """Return the chat tool set for a caller.

    Full tool set when the caller may edit the map; read-only (``query_data``
    + ``run_analysis``) when they may only view it.

    has_map=False drops the map-only tools for surfaces with no map to draw on
    (dataset-scoped chat): ``run_analysis``'s whole output is an ephemeral map
    overlay, so offering it there would let the model promise a preview the
    surface cannot render.
    """
    tools = CHAT_TOOLS_ANTHROPIC if can_edit else CHAT_TOOLS_READONLY
    if not has_map:
        tools = [t for t in tools if t["name"] not in _MAP_ONLY_TOOL_NAMES]
    return tools
