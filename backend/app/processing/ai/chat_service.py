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
    _MAX_COLUMNS_PER_LAYER,
    _MAX_SAMPLE_COLS,
    _MAX_SYSTEM_PROMPT_LAYERS,
    ERROR_MESSAGES,
    QUERY_RESULT_SANITY_PROMPT,
    RAMP_COLORS,
    _get_ramp_colors,
    _sanitize_layer_name,
    fence_untrusted_content,
    lang_name,
    sanitize_dataset_value,
)
from app.processing.ai.chat_dataset import (
    build_dataset_chat_system_prompt,
)  # re-exported (facade contract — router imports via this module)
from app.processing.ai.chat_geojson import (
    _detect_geom_column,
    _extract_geojson,
    _is_geom_value,
    _safe_value,
    ensure_geometry_selected,
    strip_geometry_columns,
)
from app.processing.ai.chat_styles import (
    _build_categorical_style,
    _build_data_driven_style,
    _build_graduated_style,
    _get_color_property,
)
from app.processing.ai.chat_validation import (
    _build_chat_actions,
    _extract_get_refs,
    _validate_actions,
    _validate_filter_columns,
)
from app.processing.ai.llm_loop import resolve_provider
from app.processing.ai.schemas import (
    ChatHistoryMessage,
    ChatMapLayer,
    ChatResponse,
    history_to_dicts,
)
from app.processing.ai.sql_generator import (
    generate_sql,
)  # re-exported (test patch target)
from app.processing.ai.token_usage import (
    record_token_usage,
    record_token_usage_from_error,
)
from app.processing.ai.tools import select_chat_tools

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)

__all__ = [
    # Public orchestrator + prompt builders
    "chat_edit_map",
    "build_chat_system_prompt",
    "build_dataset_chat_system_prompt",
    # Constants / language utilities (used by service.py + metadata_service.py)
    "ERROR_MESSAGES",
    "RAMP_COLORS",
    "lang_name",
    # Tool-call entry points (used by streaming.py + tests)
    "_execute_chat_tool",
    "_handle_query_data",
    "_collect_chat_action",
    # Validation (used by streaming.py)
    "_build_chat_actions",
    "_validate_actions",
    "_validate_filter_columns",
    "_extract_get_refs",
    # GeoJSON helpers (used by tests)
    "_is_geom_value",
    "_detect_geom_column",
    "_safe_value",
    "_extract_geojson",
    "ensure_geometry_selected",
    "strip_geometry_columns",
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


def build_chat_system_prompt(
    layers: list[ChatMapLayer],
    language: str | None = None,
    basemap_style: str | None = None,
    can_edit: bool = True,
) -> str:
    """Build a system prompt that describes the user's current map state.

    When ``can_edit`` is False the caller may view but not edit the map (the AI
    is given read-only tools — see ``select_chat_tools``); a read-only directive
    is injected so the model declines edit requests instead of silently failing.
    ``can_edit`` also gates the query_data filter-offer note (#1242): only an
    editor has set_filter available to fulfil it.
    """
    # Cap layers to prevent unbounded prompt growth
    display_layers = layers[:_MAX_SYSTEM_PROMPT_LAYERS]
    truncated_count = len(layers) - len(display_layers)

    layers_desc = []
    for layer in display_layers:
        # Limit column info to first N columns to avoid token bloat
        cols_raw = layer.column_info or []
        cols_limited = cols_raw[:_MAX_COLUMNS_PER_LAYER]
        # fix(#1778): column names reach here from the client for a map layer
        # and from an upstream service schema for an ArcGIS/STAC ingest, so
        # they carry the same injection risk as the layer name sanitized below.
        cols_str = ", ".join(
            f"{sanitize_dataset_value(c.get('name', '?'))} "
            f"({sanitize_dataset_value(c.get('type', '?'))})"
            for c in cols_limited
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
                # fix(#1778): raw row content — the one field on this layer
                # that an attacker controls end to end via a public dataset.
                safe_col = sanitize_dataset_value(col_name)
                safe_vals = [sanitize_dataset_value(v) for v in vals]
                sample_parts.append(f"{safe_col}: {safe_vals}")
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

    readonly_note = (
        ""
        if can_edit
        else (
            "\n\n## Read-Only Access\n"
            "You do NOT have edit access to this map — the current user can view it "
            "but does not own it. You may ONLY answer questions about the map's data "
            "using the query_data and run_analysis tools (both are read-only; "
            "run_analysis draws a temporary preview and saves nothing). "
            "You cannot change styles, filters, labels, "
            "visibility, opacity, or add or remove layers; those tools are unavailable "
            "to you. If the user asks you to modify the map, briefly explain that only "
            "the map's owner can edit it, then offer to answer questions about the data."
        )
    )

    # feat(#1242): companion to the query_data/set_filter split above, not a
    # rewrite of it — this fires AFTER query_data has already answered a
    # QUESTION, so it never decides which tool a request reaches. A persisted
    # set_filter beats an ephemeral query_data result for the shape it covers
    # (a plain row predicate), so the model is told to name that option, once,
    # as an offer the user can decline. It must stay an offer: #549 is the
    # record of "show me the ..." silently landing on a persistent filter, and
    # that was reverted specifically because a read-shaped question must never
    # mutate saved map state on its own. Gated on can_edit — a read-only
    # caller never has set_filter in its tool set (select_chat_tools), so
    # promising it here would be a broken offer the readonly_note above
    # already tells the model to avoid making.
    filter_offer_note = (
        (
            "\n- If the question was a simple row predicate on a layer "
            "already on the map"
            ' ("earthquakes above magnitude 5", "parcels zoned commercial" -- '
            "not a count, aggregate, top-N/ranked list, multi-layer join, or "
            '"most recent" style question), offer -- after answering -- to '
            "apply it as a persistent filter on that layer instead: "
            'something like "Want this as a filter on the layer instead? It '
            'persists when you save the map." This is an offer, not an '
            "action -- call set_filter only if the user accepts."
        )
        if can_edit
        else ""
    )

    # fix(#1778 round 1): the fence is assembled by one helper that also strips
    # any forged marker out of the block. Interpolating the tags here would
    # have left the id, the serialized filter and the paint dict able to close
    # the region early, since none of those pass through a sanitizer.
    fenced_layers = fence_untrusted_content(
        f"{chr(10).join(layers_desc)}{truncation_note}"
    )

    return f"""\
You are a map editing assistant. The user has a map with these layers:

{fenced_layers}{readonly_note}

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
- For filter expressions, use MapLibre expression syntax and ALWAYS reference columns with ["get", "column"] -- never bare field names like [">", "column", value].
  Example filters: ["==", ["get", "status"], "active"], ["all", [">", ["get", "population"], 50000], ["==", ["get", "state"], "CA"]]
- For compound requests that include both a question and a map change, use both query_data and editing tools in a single response.
- To add a new layer, first use search_datasets to find the dataset, then use add_layer with the dataset_id.
- Tool selection is decided HERE, by the verb the user used. The tool
  descriptions say what each tool does; they do not decide which phrasing
  wins.
  Read the OBJECT of the request first, then the verb. The object decides
  which family; the verb decides which tool inside it.
  - The object is the CATALOG (a dataset, not something already on the map)
    -- "find datasets about flood zones", "is there a layer for parcels",
    "search for census data". Use search_datasets. query_data can only reach
    layers already on the map, so a catalog lookup sent there fails.
  - The object is a LAYER -- "show the layer", "show @Parks", "hide @Roads",
    "show only @Parks" when @Parks is a LAYER among several. Use
    toggle_visibility. set_filter cannot hide a sibling layer; it only
    filters features inside one.
  - The object is a layer's LABELS -- "hide the labels", "turn the labels
    off", "label them by name". Use set_label, with column null to turn
    labels off. toggle_visibility would hide the layer's features too.
  - The object is the DATA in a layer, and the request asks for something
    ANSWERED from it (counts, statistics, spatial relationships, distances,
    finding features). QUESTION verbs -- show, find, list, which, what,
    where, how many, how much. Use query_data.
    "Show me the ADA accessible stations served by the A line" is a QUESTION.
  - The object is the MAP's appearance -- colors, filters, labels,
    visibility, adding or removing layers. CHANGE verbs -- filter, style,
    color, label, hide, change, set, make. Use the map editing tools.
    "Filter to ADA accessible stations on the A line" is a CHANGE.
  - "show" is a QUESTION verb by default: "show me the ADA accessible
    stations" asks for a list, not a map change. Three exceptions, all
    CHANGE, and all of them have the MAP as the object rather than the data:
    - a LAYER, per the rule above -- use toggle_visibility; its LABELS --
      use set_label.
    - NARROWING to a feature PREDICATE -- "show only the accessible ones",
      "just the ones on the A line" -- use set_filter.
    - BROADENING an existing filter -- "show all", "show everything again",
      "show all the features" -- use set_filter with a null expression to
      CLEAR the filter. Answering that one as a question leaves the
      persistent filter in place, which is not what was asked.
  - A request that names a geometry OPERATION is a TRANSFORM whichever verb
    introduces it, and outranks both lists above.
- query_data takes a natural language question -- the server generates and
  executes the SQL safely.
- When the user asks to TRANSFORM a layer's geometry -- buffer ("within 500 m
  of the schools"), centroid ("the centre point of each parcel") -- use
  run_analysis, NOT query_data. It draws a temporary preview on the map and
  saves nothing.
- Keep your explanations concise (1-3 sentences).
- Respond in PLAIN TEXT only. The chat panel does not render markdown: never
  use **bold**, headers, backticks, or [links](...). Simple "- " bullet lines
  are fine.
- For raster layers (marked "[raster layer]"), only use set_opacity (with layer_id and opacity 0.0-1.0) or toggle_visibility. Do not use set_style, set_filter, set_label, or set_data_driven_style on raster layers.
- To add a raster dataset as a layer, use search_datasets then add_layer — same as vector.
- The current basemap is: {basemap_style or "unknown"}.{" This is a dark basemap — use light colors for labels (#e5e7eb) and outlines (#d1d5db)." if basemap_style and "dark" in basemap_style.lower() else " Use dark colors for labels (#333333) and outlines (#374151)."}

## Query Data Responses
When reporting query results back to the user:
- Lead with the key finding, then add context.
- Keep answers concise (2-4 sentences for simple questions, up to a paragraph for complex ones).
- If results were truncated, mention it naturally (e.g., "showing the first 50 of 1,200 results").
- Never show raw SQL, table structures, or row counts as bare numbers -- interpret them meaningfully.
- If no results were found, tell the user and suggest trying different criteria.{filter_offer_note}

{QUERY_RESULT_SANITY_PROMPT}
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
    can_edit: bool = True,
) -> ChatResponse:
    """Main orchestrator: run LLM tool-calling loop for chat map editing.

    Provider selection: Anthropic if key is set, else OpenAI-compatible.
    Returns ChatResponse with explanation and validated actions.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map (PERF-04 / Phase 274).

    can_edit gates the tool set: an owner gets the full editing toolbox; a
    view-only caller gets read-only tools (query_data) so the AI can answer
    questions but cannot emit edit actions.
    """
    system_prompt = build_chat_system_prompt(
        layers, language=language, basemap_style=basemap_style, can_edit=can_edit
    )
    provider, model, runtime_config = await resolve_provider(session)
    provider_ext = get_ai_provider(provider)

    history_dicts = history_to_dicts(history)

    selected_tools = select_chat_tools(can_edit)
    allowed_tool_names = {t["name"] for t in selected_tools}

    # Build tool executor bound to this session/user/layers. The non-streaming
    # complete() loop is advertised-tool constrained and has no XML fallback, but
    # we still reject tool names outside the selected set at execution AND
    # collection so a view-only caller can never run or receive a mutating action
    # (defense-in-depth, uniform with the streaming path).
    async def tool_executor(tool_name: str, tool_input: dict) -> dict:
        if tool_name not in allowed_tool_names:
            logger.warning(
                "Dropped disallowed chat tool call (read-only caller)",
                tool=tool_name,
            )
            return {"error": "Tool not permitted for this map."}
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

    def collect_allowed_action(
        tool_name: str, tool_input: dict, tool_result: dict
    ) -> dict | None:
        if tool_name not in allowed_tool_names:
            return None
        return _collect_chat_action(tool_name, tool_input, tool_result)

    try:
        result = await provider_ext.complete(
            model=model,
            system_prompt=system_prompt,
            user_message=message,
            tools=selected_tools,
            tool_executor=tool_executor,
            action_collector=collect_allowed_action,
            history=history_dicts,
            base_url=runtime_config.get("base_url"),
            temperature=0.3,
        )
    except Exception as exc:  # broad: any provider failure may still have spent tokens
        # fix(#1778): the tokens are spent the moment the provider answers, so
        # a loop that exhausts must still be billed to the daily cap. No-op
        # when the failure carries no counts (it never reached the provider).
        await record_token_usage_from_error(
            session, exc, user_id=user.id, subsystem="chat", model=model
        )
        raise

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

    # Parse actions into ChatAction models (per-item; invalid ones drop with a
    # note instead of failing the whole turn — fix(#525 B-037))
    actions, invalid = _build_chat_actions(result.actions)

    # Validate layer_id references + add_layer dataset RBAC
    actions, dropped = await _validate_actions(
        actions, layers, session=session, user=user, port=port
    )
    dropped = invalid + dropped

    explanation = result.text
    if dropped:
        explanation += "\n\nNote: some actions were skipped: " + "; ".join(dropped)

    return ChatResponse(
        explanation=explanation,
        actions=actions,
    )
