"""Action-execution helpers for chat-edit (label, query_data, tool dispatch).

Phase 276 CODE-02 — extracted from chat_service.py.

Note on call-site indirection: ``validate_and_execute`` and ``generate_sql`` are
looked up via the ``chat_service`` facade module (not imported here directly).
This preserves the public test-patch path
``patch("app.processing.ai.chat_service.validate_and_execute")`` /
``patch("app.processing.ai.chat_service.generate_sql")`` so existing tests
keep working unchanged when the patch replaces the attribute on the facade.
"""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.sandbox import SandboxError
from app.processing.ai.chat_constants import _EDIT_TOOLS, ERROR_MESSAGES
from app.processing.ai.chat_geojson import _extract_geojson
from app.processing.ai.colors import is_css_colorish
from app.processing.ai.chat_styles import _build_data_driven_style
from app.processing.ai.schemas import (
    ChatMapLayer,
    validate_paint_property_names_with_feedback,
    validate_paint_with_feedback,
)
from app.processing.ai.service import _execute_search_tool, _should_send_sample_values
from app.processing.ai.sql_generator import build_sql_schema_context

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)


_DEFAULT_LABEL_TEXT_COLOR = "#333333"


def _safe_label_text_color(value: object) -> str:
    # fix(#394) CH-02: hex / real CSS named color / numeric-arg functional form
    # only (see colors.py) — anything else falls back to the default so an
    # unparseable value never reaches map.setPaintProperty.
    if isinstance(value, str) and is_css_colorish(value):
        return value.strip()
    return _DEFAULT_LABEL_TEXT_COLOR


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
                # fix(#394) CH-02: sanitized — see _safe_label_text_color.
                "textColor": _safe_label_text_color(
                    tool_input.get("text_color", _DEFAULT_LABEL_TEXT_COLOR)
                ),
                "haloColor": "#ffffff",
                "haloWidth": 1.5,
            },
        }
    return {
        "type": "set_label",
        "layer_id": tool_input.get("layer_id"),
        "label_config": None,
    }


async def _handle_query_data(
    tool_input: dict,
    session: AsyncSession,
    user: Identity,
    layers: list[ChatMapLayer],
    stage_callback: Callable[[str], None] | None = None,
    *,
    map_id: str | None = None,
) -> dict:
    """Handle query_data tool: generate SQL, validate, execute via sandbox.

    map_id is threaded through so the schema-context cache key partitions
    per-map (PERF-04 / Phase 274), preventing cross-map prompt pollution.

    NB: ``generate_sql`` and ``validate_and_execute`` are looked up via the
    ``chat_service`` facade module so test patches on
    ``app.processing.ai.chat_service.generate_sql`` /
    ``app.processing.ai.chat_service.validate_and_execute`` keep working.
    """
    # Lazy import: avoid a hard cycle (chat_service imports from this module).
    from app.processing.ai import chat_service

    question = tool_input["question"]
    schema_context = build_sql_schema_context(layers, map_id=map_id)

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

    sql = await chat_service.generate_sql(
        session,
        question,
        schema_context,
        layer_descriptions=layer_descriptions,
        user_id=user.id if user is not None else None,
    )

    # Surface LLM error messages directly instead of letting the sandbox reject them
    if sql.strip().startswith("-- ERROR:"):
        error_msg = sql.strip().removeprefix("-- ERROR:").strip()
        return {"error": error_msg, "category": "llm_cannot_answer"}

    if stage_callback:
        stage_callback("Running query...")

    result = await chat_service.validate_and_execute(sql, session, user)
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
    *,
    port: "ProcessingPort",
    map_id: str | None = None,
) -> dict:
    """Execute a chat tool and return the result.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map (PERF-04 / Phase 274).
    """
    if tool_name == "search_datasets":
        send_samples = await _should_send_sample_values(session)
        results = await _execute_search_tool(
            session,
            user,
            user_roles,
            tool_input,
            send_sample_values=send_samples,
            port=port,
        )
        return {"results": results}

    if tool_name == "query_data":
        # Look up _handle_query_data via the facade module so existing
        # tests that patch ``app.processing.ai.chat_service._handle_query_data``
        # are honored by this dispatcher (the test asserts the SandboxError
        # raised by the patched mock is caught + mapped to a friendly message).
        from app.processing.ai import chat_service

        try:
            return await chat_service._handle_query_data(
                tool_input,
                session,
                user,
                layers,
                stage_callback=stage_callback,
                map_id=map_id,
            )
        except SandboxError as e:
            return {
                "error": ERROR_MESSAGES.get(
                    e.category, "Something went wrong. Try rephrasing your question."
                ),
                "category": e.category,
            }
        except Exception as e:  # broad: query/sandbox layer can throw varied SDK/SQL errors; map to user-facing fallback
            logger.warning(
                "query_data.failed", error=str(e), error_type=type(e).__name__
            )
            return {"error": "Could not generate or execute query"}

    if tool_name == "set_data_driven_style":
        return await _build_data_driven_style(tool_input, session, layers, port=port)

    # Validate set_style paint and explicit clear lists against geometry type.
    if tool_name == "set_style" and (
        tool_input.get("paint") or tool_input.get("clear_paint")
    ):
        target = next(
            (lyr for lyr in layers if lyr.id == tool_input.get("layer_id")), None
        )
        if target:
            # fix(#392): thread the layer's own render_mode through so
            # heatmap-radius/heatmap-opacity/heatmap-intensity survive validation on
            # an already-heatmap-rendered layer — set_style is the only AI tool that
            # can tune those. Mirrors ChatPanel.tsx's validateChatPaint. (audit WR-01)
            render_mode = (
                (target.style_config or {}).get("render_mode")
                if target.style_config
                else None
            )
            warnings: list[str] = []
            next_input = {**tool_input}
            if tool_input.get("paint"):
                validated_paint, paint_warnings = validate_paint_with_feedback(
                    tool_input["paint"], target.geometry_type, render_mode
                )
                next_input["paint"] = validated_paint or {}
                warnings.extend(paint_warnings)
            if tool_input.get("clear_paint"):
                validated_clear, clear_warnings = (
                    validate_paint_property_names_with_feedback(
                        tool_input.get("clear_paint"),
                        target.geometry_type,
                        render_mode,
                    )
                )
                next_input["clear_paint"] = validated_clear
                warnings.extend(clear_warnings)
            tool_input = next_input
            if warnings:
                return {"status": "ok", "warnings": warnings, **tool_input}

    # fix(#394) CH-02: validate the set_label column against the target layer's
    # schema before the action reaches the client — a hallucinated column
    # previously flowed straight through to a text-field ["get", col] that
    # renders empty labels. Returning an error lets the model retry with a real
    # column (mirrors the set_style validation feedback pattern above).
    if tool_name == "set_label" and tool_input.get("column"):
        target = next(
            (lyr for lyr in layers if lyr.id == tool_input.get("layer_id")), None
        )
        if target is not None and target.column_info:
            valid_columns = {
                col.get("name")
                for col in target.column_info
                if isinstance(col, dict) and col.get("name")
            }
            if valid_columns and tool_input["column"] not in valid_columns:
                return {
                    "error": (
                        f"Column '{tool_input['column']}' does not exist on "
                        "this layer — pick one of the layer's real columns."
                    )
                }

    # add_layer: resolve the dataset's display title server-side so the staging
    # chip can show a human name instead of the raw UUID (builder-audit #338 B-002).
    # Name resolution is best-effort — a lookup miss/error must not block the
    # add, so we degrade silently to the dataset_id fallback on the frontend.
    if tool_name == "add_layer":
        result = {"status": "ok", **tool_input}
        raw_id = tool_input.get("dataset_id")
        if raw_id:
            try:
                dataset = await port.get_dataset(session, UUID(str(raw_id)))
                title = getattr(getattr(dataset, "record", None), "title", None)
                if title:
                    result["dataset_name"] = title
            except Exception:  # noqa: BLE001 — name lookup is best-effort; never block the add
                logger.debug(
                    "add_layer.dataset_name_lookup_failed", dataset_id=str(raw_id)
                )
        return result

    # For all other edit tools, return tool_input as-is
    if tool_name in _EDIT_TOOLS:
        return {"status": "ok", **tool_input}

    return {"error": f"Unknown tool: {tool_name}"}


def _collect_chat_action(tool_name: str, tool_input: dict, result: dict) -> dict | None:
    """Build an action dict from a chat tool call.

    Used as the action_collector callback for provider_ext.complete().
    """
    if tool_name not in _EDIT_TOOLS:
        # query_data emits show_query_result for both spatial (geojson+bbox) and
        # non-spatial (columns+rows) results so the frontend inline data-analysis
        # card can render either case. Phase 1135 AI-08 carry-forward fix.
        if tool_name == "query_data" and "error" not in result and "columns" in result:
            action: dict = {
                "type": "show_query_result",
                "columns": result["columns"],
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "truncated": result.get("truncated", False),
            }
            # fix(#392): guard both keys — geojson and bbox are set together
            # by _extract_geojson's tuple unpack today, but that pairing is an unenforced
            # invariant on this plain dict; a future caller emitting geojson without bbox
            # must not raise an uncaught KeyError inside the action-collector callback. (audit WR-03)
            if "geojson" in result and "bbox" in result:
                action["geojson"] = result["geojson"]
                action["bbox"] = result["bbox"]
            return action
        return None

    if tool_name == "set_data_driven_style":
        if "error" not in result:
            return result
        return None

    if tool_name == "set_label":
        # fix(#394) CH-02: a validation error from _execute_chat_tool (unknown
        # column) must not still emit a label action built from the raw input.
        if "error" in result:
            return None
        return _build_label_action(tool_input)

    # fix(#392): set_style must emit the backend-validated/clamped paint computed in
    # _execute_chat_tool (it lives on `result` because `tool_input` was
    # reassigned to `next_input` and returned there), not the raw fn_args. When
    # validation was skipped (no paint/clear_paint on the call), `result`
    # equals the raw tool_input, so behavior is unchanged. (audit CH-02)
    if tool_name == "set_style":
        action = {"type": "set_style", **tool_input}
        if "paint" in result:
            action["paint"] = result["paint"]
        if "clear_paint" in result:
            action["clear_paint"] = result["clear_paint"]
        return action

    # add_layer: carry the server-resolved dataset_name (builder-audit #338 B-002) so
    # the staging chip shows a human name instead of the raw UUID. The name is
    # resolved during _execute_chat_tool and arrives on `result`, not tool_input.
    if tool_name == "add_layer":
        action = {"type": "add_layer", **tool_input}
        if result.get("dataset_name"):
            action["dataset_name"] = result["dataset_name"]
        return action

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
