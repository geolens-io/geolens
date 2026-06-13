"""Shared constants for AI modules."""

MAX_TOOL_ROUNDS = 8
MAX_STREAMING_WALL_CLOCK_SECONDS = 90

# PERF-009: cumulative input+output token budget per chat request. The tool loop
# is otherwise bounded only by round count (MAX_TOOL_ROUNDS), wall clock
# (MAX_STREAMING_WALL_CLOCK_SECONDS), and the 10/min rate limit — none of which
# cap total provider token spend. A runaway/looping model can still drive ~8
# rounds x 4096 output plus growing input history per request. This ceiling stops
# the loop gracefully (same as hitting max rounds) once cumulative tokens exceed
# it. Sized well above legitimate multi-round usage so it only trips on runaways.
MAX_REQUEST_TOKEN_BUDGET = 200_000

TOOL_LABELS = {
    "search_datasets": "Searching datasets...",
    "set_filter": "Applying filter...",
    "set_style": "Changing style...",
    "set_data_driven_style": "Building data-driven style...",
    "set_label": "Configuring labels...",
    "toggle_visibility": "Toggling visibility...",
    "remove_layer": "Removing layer...",
    "add_layer": "Adding layer...",
    "set_opacity": "Adjusting opacity...",
    "query_data": "Querying data...",
    "get_dataset_details": "Fetching dataset details...",
}


def tool_label(tool_name: str) -> str:
    return TOOL_LABELS.get(tool_name, f"Running {tool_name}...")
