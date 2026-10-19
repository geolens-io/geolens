"""Shared constants for AI modules."""

MAX_TOOL_ROUNDS = 8
MAX_STREAMING_WALL_CLOCK_SECONDS = 90

# Cumulative input+output token budget per chat request. Round count
# (MAX_TOOL_ROUNDS), wall clock (MAX_STREAMING_WALL_CLOCK_SECONDS) and the
# 10/min rate limit don't cap total provider token spend: a looping model can
# still drive ~8 rounds x 4096 output plus growing input history per request.
# Past this ceiling the loop stops gracefully (as at max rounds). Sized well
# above legitimate multi-round usage so it only trips on runaways.
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
    "set_render_as": "Changing render type...",
    "query_data": "Querying data...",
    "run_analysis": "Running analysis...",
    "get_dataset_details": "Fetching dataset details...",
}


def tool_label(tool_name: str) -> str:
    return TOOL_LABELS.get(tool_name, f"Running {tool_name}...")
