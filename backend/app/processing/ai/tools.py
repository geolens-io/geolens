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
            "Set or clear a filter on a map layer. Pass a MapLibre filter "
            "expression array to filter features, or null to clear the filter. "
            'Example: ["all", [">", "population", 1000000]]'
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
            "Change the paint properties of a layer (e.g., color, opacity, "
            "width). Use the correct paint property for the geometry type: "
            "fill-color for polygons, line-color for lines, circle-color for "
            "points. Do NOT use this for data-driven coloring -- use "
            "set_data_driven_style instead."
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
                    "description": "MapLibre paint properties to set/override",
                },
            },
            "required": ["layer_id", "paint"],
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
            "Query the user's map data using SQL. Use this when the user asks "
            "a question about their data (counts, statistics, spatial analysis, "
            "finding features, distances, areas, etc.). Do NOT use this for map "
            "styling or layer management -- use the other tools for that."
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
]
