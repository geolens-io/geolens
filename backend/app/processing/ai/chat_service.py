"""Chat-based map editing service: facade re-exporting from chat_* sub-modules.

Phase 276 CODE-02 — Phase-226 facade pattern. This module preserves the stable
public import path used by router.py, streaming.py, metadata_service.py,
service.py, and tests:

    from app.processing.ai.chat_service import chat_edit_map
    from app.processing.ai.chat_service import build_chat_system_prompt
    from app.processing.ai.chat_service import (
        _validate_actions,
        _execute_chat_tool,
        _handle_query_data,
        _collect_chat_action,
        _is_geom_value,
        _detect_geom_column,
        _safe_value,
        _extract_geojson,
        ERROR_MESSAGES,
        lang_name,
    )

The body of this file is split between (a) the orchestrator ``chat_edit_map``
and the system-prompt builder ``build_chat_system_prompt`` that own the public
chat-edit contract, and (b) a re-export wall pulling private helpers out of
sibling modules. ``generate_sql`` and ``validate_and_execute`` are imported
here AT module level so existing tests can patch
``app.processing.ai.chat_service.generate_sql`` /
``app.processing.ai.chat_service.validate_and_execute`` and the patch is
honored at every call site (chat_actions._handle_query_data does its lookup
via this module — see chat_actions.py for the rationale).
"""

import json
import re as _re
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.extensions import get_ai_provider
from app.platform.sandbox import validate_and_execute  # re-exported (test patch target)

# Re-exports — public names every external caller may import from this facade.
# Sub-module imports first; the facade-only orchestrator follows below.
from app.processing.ai.chat_actions import (
    _build_label_action,
    _collect_chat_action,
    _execute_chat_tool,
    _handle_query_data,
)
from app.processing.ai.chat_constants import (
    _EDIT_TOOLS,
    ERROR_MESSAGES,
    RAMP_COLORS,
    _get_ramp_colors,
    lang_name,
)
from app.processing.ai.chat_geojson import (
    _detect_geom_column,
    _extract_geojson,
    _is_geom_value,
    _safe_value,
)
from app.processing.ai.chat_styles import (
    _build_categorical_style,
    _build_data_driven_style,
    _build_graduated_style,
    _get_color_property,
)
from app.processing.ai.chat_validation import (
    _extract_get_refs,
    _validate_actions,
    _validate_filter_columns,
)
from app.processing.ai.llm_loop import resolve_provider
from app.processing.ai.schemas import (
    ChatAction,
    ChatHistoryMessage,
    ChatMapLayer,
    ChatResponse,
    history_to_dicts,
)
from app.processing.ai.sql_generator import (
    generate_sql,
)  # re-exported (test patch target)
from app.processing.ai.token_usage import record_token_usage
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)

__all__ = [
    # Public orchestrator + prompt builder
    "chat_edit_map",
    "build_chat_system_prompt",
    # Constants / language utilities (used by service.py + metadata_service.py)
    "ERROR_MESSAGES",
    "RAMP_COLORS",
    "lang_name",
    # Tool-call entry points (used by streaming.py + tests)
    "_execute_chat_tool",
    "_handle_query_data",
    "_collect_chat_action",
    # Validation (used by streaming.py)
    "_validate_actions",
    "_validate_filter_columns",
    "_extract_get_refs",
    # GeoJSON helpers (used by tests)
    "_is_geom_value",
    "_detect_geom_column",
    "_safe_value",
    "_extract_geojson",
    # Test patch targets (kept module-level so unittest.mock.patch resolves
    # ``app.processing.ai.chat_service.{generate_sql,validate_and_execute}``)
    "generate_sql",
    "validate_and_execute",
    # Style builders (kept available; not imported by external callers but
    # tests inspect the facade surface).
    "_build_data_driven_style",
    "_build_categorical_style",
    "_build_graduated_style",
    "_get_color_property",
    # Action helpers
    "_build_label_action",
    # Tool name set
    "_EDIT_TOOLS",
    "_get_ramp_colors",
]


# Maximum tokens to budget for the system prompt (cap layer context to fit)
_MAX_SYSTEM_PROMPT_LAYERS = 15
_MAX_COLUMNS_PER_LAYER = 30
_MAX_SAMPLE_COLS = 3

# Layer-name sanitization for prompt-injection defense: layer names are
# user-controlled and embedded verbatim in the chat system prompt. Strip
# control chars, role markers, and obvious prompt-injection seeds before
# inlining. 80-char cap is generous for human-readable names while bounding
# token cost.
_MAX_LAYER_NAME_LEN = 80

_PROMPT_INJECTION_PATTERNS = _re.compile(
    r"(?i)\b(system|assistant|user)\s*:\s*|"  # role markers
    r"<\|[^|>]*\|>|"  # special tokens like <|im_start|>
    r"```|"  # code-fence boundaries
    r"\bignore\s+(all\s+)?previous\b|"  # classic injection seed
    r"\bdisregard\s+(all\s+)?previous\b"
)
_CONTROL_CHARS = _re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_layer_name(name: str | None) -> str:
    """Sanitize a user-controlled layer name for embedding in a system prompt.

    Strips control characters, neutralizes role markers and injection seeds,
    and caps length. The result is wrapped in backticks at the call site so
    even after sanitization the LLM treats it as quoted text rather than
    instructions.
    """
    if not name:
        return "unnamed"
    s = _CONTROL_CHARS.sub("", name)
    s = _PROMPT_INJECTION_PATTERNS.sub("[redacted] ", s)
    s = s.strip()
    if len(s) > _MAX_LAYER_NAME_LEN:
        s = s[: _MAX_LAYER_NAME_LEN - 1] + "…"
    return s or "unnamed"


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

        # Dataset metadata lines — dataset_title is also user-controlled, sanitize it
        title_str = (
            f"\n  Title: {_sanitize_layer_name(layer.dataset_title)}"
            if layer.dataset_title
            else ""
        )
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
        safe_name = _sanitize_layer_name(layer.name)
        layers_desc.append(
            f'- Layer "{safe_name}" (id: {layer.id}, '
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
- For simple flat color changes (e.g., "make it red"), use set_style. set_style patches the current paint; omitted paint properties are preserved.
- To remove a stale style property, pass clear_paint with the property name (for example clear_paint: ["line-gradient"] when changing a line from gradient back to solid).
- Use replace_paint=true only when you are providing the full desired paint object.
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


async def chat_edit_map(
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    message: str,
    layers: list[ChatMapLayer],
    language: str | None = None,
    history: list[ChatHistoryMessage] | None = None,
    basemap_style: str | None = None,
    *,
    port: "ProcessingPort",
    map_id: str | None = None,
) -> ChatResponse:
    """Main orchestrator: run LLM tool-calling loop for chat map editing.

    Provider selection: Anthropic if key is set, else OpenAI-compatible.
    Returns ChatResponse with explanation and validated actions.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map (PERF-04 / Phase 274).
    """
    system_prompt = build_chat_system_prompt(
        layers, language=language, basemap_style=basemap_style
    )
    provider, model, runtime_config = await resolve_provider(session)
    provider_ext = get_ai_provider(provider)

    history_dicts = history_to_dicts(history)

    # Build tool executor bound to this session/user/layers
    async def tool_executor(tool_name: str, tool_input: dict) -> dict:
        return await _execute_chat_tool(
            tool_name,
            tool_input,
            session,
            user,
            user_roles,
            layers,
            port=port,
            map_id=map_id,
        )

    result = await provider_ext.complete(
        model=model,
        system_prompt=system_prompt,
        user_message=message,
        tools=CHAT_TOOLS_ANTHROPIC,
        tool_executor=tool_executor,
        action_collector=_collect_chat_action,
        history=history_dicts,
        base_url=runtime_config.get("base_url"),
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

    # Validate layer_id references + add_layer dataset RBAC
    actions, dropped = await _validate_actions(
        actions, layers, session=session, user=user, port=port
    )

    explanation = result.text
    if dropped:
        explanation += "\n\nNote: some actions were skipped: " + "; ".join(dropped)

    return ChatResponse(
        explanation=explanation,
        actions=actions,
    )
