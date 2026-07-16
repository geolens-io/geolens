"""Dataset-scoped chat system prompt (dataset-chat v1).

Sub-module of the chat_service facade (Phase 276 CODE-02 pattern): external
callers import ``build_dataset_chat_system_prompt`` via
``app.processing.ai.chat_service``, never from here.
"""

from app.processing.ai.chat_constants import (
    _MAX_COLUMNS_PER_LAYER,
    _MAX_SAMPLE_COLS,
    _sanitize_layer_name,
    lang_name,
)
from app.processing.ai.schemas import ChatMapLayer


def build_dataset_chat_system_prompt(
    layer: ChatMapLayer,
    language: str | None = None,
) -> str:
    """Build the system prompt for dataset-scoped chat (no map context).

    Dataset chat is read-only by construction — the router selects the
    read-only tool set (``query_data`` only) — so the prompt frames the
    assistant as a data analyst for a single dataset rather than a map editor.
    The layer is server-built from authoritative DB values (see
    ``_validate_chat_dataset`` in router.py); the title is still sanitized
    because record titles are user-controlled text.
    """
    cols_raw = layer.column_info or []
    cols_limited = cols_raw[:_MAX_COLUMNS_PER_LAYER]
    cols_str = ", ".join(
        f"{c.get('name', '?')} ({c.get('type', '?')})" for c in cols_limited
    )
    if len(cols_raw) > _MAX_COLUMNS_PER_LAYER:
        cols_str += f" ... and {len(cols_raw) - _MAX_COLUMNS_PER_LAYER} more"

    sample_str = ""
    if layer.sample_values:
        sample_parts = []
        for col_name, values in list(layer.sample_values.items())[:_MAX_SAMPLE_COLS]:
            vals = values[:5] if isinstance(values, list) else [values]
            sample_parts.append(f"{col_name}: {vals}")
        if sample_parts:
            sample_str = "\nSample values: " + "; ".join(sample_parts)

    feat_str = f"\nFeatures: {layer.feature_count}" if layer.feature_count else ""
    geom_str = (
        f"\nGeometry: {layer.geometry_type}"
        if layer.geometry_type
        else "\nGeometry: none (attribute table)"
    )
    safe_title = _sanitize_layer_name(layer.dataset_title or layer.name)

    return f"""\
You are a data analysis assistant. The user is exploring this dataset:

Dataset "{safe_title}" (table: {layer.dataset_table_name}){geom_str}{feat_str}
Columns: {cols_str}{sample_str}

## Instructions
- When the user asks a question about the data (counts, statistics, spatial
  relationships, distances, areas, finding features), use the query_data tool.
- query_data takes a natural language question -- the server generates and
  executes the SQL safely.
- You have NO map-editing tools here. If the user asks to style, filter, or
  visualize this data on a map, suggest opening the dataset in the map builder.
- Keep your explanations concise (1-3 sentences).
- Respond in PLAIN TEXT only. The chat panel does not render markdown: never
  use **bold**, headers, backticks, or [links](...). Simple "- " bullet lines
  are fine.

## Query Data Responses
When reporting query results back to the user:
- Lead with the key finding, then add context.
- Keep answers concise (2-4 sentences for simple questions, up to a paragraph for complex ones).
- If results were truncated, mention it naturally (e.g., "showing the first 50 of 1,200 results").
- Never show raw SQL, table structures, or row counts as bare numbers -- interpret them meaningfully.
- If no results were found, tell the user and suggest trying different criteria.

## Uncertainty
- If you are uncertain about a column name or data interpretation, say so in your explanation.
- Do not guess column names that are not listed above.
- If a user's request cannot be fulfilled with the available tools, explain what is not supported.

## Language
Always respond in {lang_name(language)}. Never switch to another language.
"""
