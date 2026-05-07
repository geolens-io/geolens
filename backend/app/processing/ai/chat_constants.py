"""Constants and lookup tables for chat-edit (Phase 276 CODE-02).

Holds the chat-edit error catalogue, edit-tool name set, color-ramp palettes,
and ISO-639-1 language-name lookup. No external imports beyond stdlib so this
module can be safely imported by every other ``chat_*`` sibling.
"""

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
