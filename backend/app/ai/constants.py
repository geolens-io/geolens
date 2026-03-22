"""Shared constants for AI modules."""

MAX_TOOL_ROUNDS = 15

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
