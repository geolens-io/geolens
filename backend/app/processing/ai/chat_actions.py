"""Action-execution helpers for chat-edit (label, query_data, tool dispatch).

``validate_and_execute`` and ``generate_sql`` are looked up via the
``chat_service`` facade module, not imported directly here, so the public
test-patch path (``patch("app.processing.ai.chat_service.validate_and_execute")``
/ ``.generate_sql``) keeps working.
"""

import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.sandbox import SandboxError
from app.processing.ai.chat_analysis import (
    collect_run_analysis_action,
    handle_run_analysis,
)
from app.processing.ai.chat_constants import _EDIT_TOOLS, ERROR_MESSAGES
from app.processing.ai.chat_geojson import (
    _extract_geojson,
    safe_rows,
    ensure_geometry_selected,
    strip_geometry_columns,
)
from app.processing.ai.colors import is_css_colorish, label_halo_color
from app.processing.ai import sandbox_bounds
from app.processing.ai.chat_styles import _build_data_driven_style, apply_render_as
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

# Overlay/table render budget: only this many rows reach the chat result
# table and the ephemeral map overlay. When geom_4326 is appended to an
# attribute-only query, the fetch is capped here so a large polygon/line layer
# doesn't transfer up to 1000 full geometries to discard all but these.
_OVERLAY_ROW_BUDGET = 50

# query_data reaches the same validator and executor as POST /api/query/,
# behind the SAME `use_ai_chat` permission, so it must carry the same sandbox
# bounds. These protect a shared resource or cost nothing in answer quality,
# and apply at all three call sites below:
#
#   capacity_semaphore   the ONE pool-derived slot pool shared with the raw
#                        endpoint; chat had only a per-user advisory lock,
#                        useless against N distinct users.
#   max_table_repeats    self-join fan-out cap (`foo a, foo b, foo c` is a
#                        cardinality bomb the outer LIMIT can't bound).
#   max_values_rows      a large inline VALUES relation cross-joined.
#   max_output_columns   repeated projections widening a row.
#   require_reader_role  fail closed when `SET LOCAL ROLE geolens_reader`
#                        can't bind, instead of running LLM-authored SQL
#                        under the application login.
#
# NOT applied: the 5 s statement timeout (half chat's — a spatial join
# worth an 8 s wait is a normal chat answer) and `extra_blocked_functions`
# (model-written SQL uses replace/regexp_replace/format for string
# cleanup). Both stay bounded regardless: advisory lock, shared semaphore,
# row limit, statement timeout.
_SANDBOX_BOUNDS: dict = {
    "capacity_semaphore": sandbox_bounds.query_slots,
    "max_table_repeats": sandbox_bounds.MAX_TABLE_REPEATS,
    "max_values_rows": sandbox_bounds.MAX_VALUES_ROWS,
    "max_output_columns": sandbox_bounds.MAX_OUTPUT_COLUMNS,
    "require_reader_role": True,
}

# Matches Postgres's undefined-column clause. Unqualified misses are quoted
# (`column "geom_4326" does not exist`); aliased misses are not
# (`column a.geom_4326 does not exist`), and overlay/intersect queries alias, so
# both forms must match. Anchored on the clause so a different missing column
# is not a false positive.
_UNDEFINED_COLUMN_RE = re.compile(
    r"column\s+([\w\".]+)\s+does not exist", re.IGNORECASE
)


def _geom_4326_missing_note(err: SandboxError) -> dict | None:
    """Clean degrade note when ``err`` was caused by a missing ``geom_4326`` column.

    The SQL prompt always names the geometry column ``geom_4326``, often
    qualified (``a.geom_4326``). A legacy dataset ingested before that
    convention fails with ``column ["<alias>".]geom_4326 does not exist``; the
    Postgres text lives on ``__cause__``, not ``SandboxError.category``
    (generic ``query_failed``). Compares the missing column's final segment so
    aliased/quoted forms match while a *different* missing column (whose SQL
    echo merely mentions geom_4326) does not; returns None for any other error
    so it propagates unmasked.
    """
    m = _UNDEFINED_COLUMN_RE.search(f"{err} {err.__cause__}")
    if m is None or m.group(1).replace('"', "").split(".")[-1].lower() != "geom_4326":
        return None
    logger.info("query_data.geom_4326_missing")
    return {
        "error": (
            "This dataset's geometry can't be used in spatial queries. "
            "I can still answer questions about its attribute columns."
        ),
        "category": "llm_cannot_answer",
    }


def _safe_label_text_color(value: object) -> str:
    # Hex / CSS named color / numeric functional form only (see colors.py);
    # anything else falls back so an unparseable value never reaches
    # map.setPaintProperty.
    if isinstance(value, str) and is_css_colorish(value):
        return value.strip()
    return _DEFAULT_LABEL_TEXT_COLOR


def _build_label_action(tool_input: dict) -> dict:
    """Restructure set_label tool output into the ChatAction label_config shape."""
    column = tool_input.get("column")
    if column:
        text_color = _safe_label_text_color(
            tool_input.get("text_color", _DEFAULT_LABEL_TEXT_COLOR)
        )
        return {
            "type": "set_label",
            "layer_id": tool_input.get("layer_id"),
            "label_config": {
                "column": column,
                "fontSize": tool_input.get("font_size", 12),
                "textColor": text_color,
                # Halo contrasts the text so the label reads on any basemap.
                "haloColor": label_halo_color(text_color),
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
    restrict_tables: frozenset[str] | None = None,
) -> dict:
    """Handle query_data tool: generate SQL, validate, execute via sandbox.

    map_id threads through so the schema-context cache partitions per-map.
    restrict_tables narrows the sandbox allowlist to a surface-level table
    scope (dataset chat passes its single table).
    """
    # Lazy import: avoid a hard cycle (chat_service imports from this module).
    from app.processing.ai import chat_service

    question = tool_input["question"]
    schema_context = build_sql_schema_context(layers, map_id=map_id)

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

    # Geometry must reach _extract_geojson regardless of which columns the model
    # chose, or every map surface silently loses its overlay.
    original_sql = sql
    sql = ensure_geometry_selected(original_sql, layers)
    geom_appended = sql != original_sql

    if stage_callback:
        stage_callback("Running query...")

    # When geometry was appended, cap the fetch to the overlay render budget:
    # only _OVERLAY_ROW_BUDGET rows reach the table and overlay, so holding up
    # to 1000 full geometries is wasted transfer and memory. row_count then
    # reflects the budget, with `truncated` signalling more rows exist. Queries
    # where the model selected geometry itself keep the default limit.
    exec_kwargs: dict = {"restrict_tables": restrict_tables, **_SANDBOX_BOUNDS}
    if geom_appended:
        exec_kwargs["row_limit"] = _OVERLAY_ROW_BUDGET
    try:
        result = await chat_service.validate_and_execute(
            sql, session, user, **exec_kwargs
        )
    except SandboxError as err:
        # The appended geom_4326 may not exist (a SRID-less ingest keeps
        # geometry_type but exposes only native `geom`), or the append otherwise
        # broke a valid model query. Fall back to the original SQL so attribute
        # rows still return and only the overlay is dropped. If the original
        # also fails, its error propagates.
        if not geom_appended:
            # The model wrote geom_4326 itself, so there is no attribute-only
            # fallback. If the column is absent (a legacy geom-only table),
            # degrade to a clean note; any other error propagates.
            note = _geom_4326_missing_note(err)
            if note is not None:
                return note
            raise
        logger.info("query_data.geometry_append_fallback")
        geom_appended = False
        sql = original_sql
        try:
            result = await chat_service.validate_and_execute(
                sql, session, user, restrict_tables=restrict_tables, **_SANDBOX_BOUNDS
            )
        except SandboxError as retry_err:
            # The original query also references geom_4326 (e.g. in WHERE or
            # ORDER BY), so the retry misses it too; degrade the same way.
            note = _geom_4326_missing_note(retry_err)
            if note is not None:
                return note
            raise

    # The transfer cap bounds the sandbox row_count to the render budget, but
    # show_query_result.row_count is the documented TOTAL matched rows (the
    # model narrates it, the UI displays it). When the cap truncated the result,
    # recover the total with a geometry-free COUNT wrapping the same validated
    # SQL (still bounded by the query's own LIMIT). A failure keeps the capped
    # count.
    if geom_appended and result.truncated:
        try:
            count_res = await chat_service.validate_and_execute(
                f"SELECT COUNT(*) AS n FROM ({sql}) AS _geolens_total",
                session,
                user,
                row_limit=1,
                restrict_tables=restrict_tables,
                **_SANDBOX_BOUNDS,
            )
            result = result.model_copy(update={"row_count": int(count_res.rows[0][0])})
        except Exception:  # broad: count recovery is best-effort, never fail the query
            logger.warning("query_data.total_count_recovery_failed")

    columns, rows = result.columns, result.rows[:_OVERLAY_ROW_BUDGET]
    geojson_result = _extract_geojson(columns, rows)
    if geojson_result is not None:
        # Geometry travels via geojson only; raw WKB in the tabular payload is
        # token noise for the model and renders as hex in the result tables.
        columns, rows = strip_geometry_columns(columns, rows)

    # Raw SQL is intentionally excluded to prevent info disclosure via the LLM.
    # Rows are normalized here, after _extract_geojson, which detects the
    # geometry column by value: stringifying a cell earlier would hide it.
    # The collector re-reads this dict rather than touching result.rows again.
    out: dict = {
        "columns": columns,
        "rows": safe_rows(rows),
        "row_count": result.row_count,
        "truncated": result.truncated,
    }
    if len(out["rows"]) < len(rows):
        # `truncated` describes the overlay when there is one, and the overlay
        # still carries every row this table dropped.
        out["rows_truncated"] = True
        out["truncated"] = out["truncated"] or geojson_result is None
    if result.row_count == 0:
        out["note"] = (
            "No matching results found. The user may want to try different criteria."
        )
    if geojson_result is not None:
        out["geojson"] = geojson_result[0]
        # The bbox is None when no row contributed finite bounds (all-EMPTY
        # geometries); omitting the key lets the collector drop the overlay.
        if geojson_result[1] is not None:
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
    restrict_tables: frozenset[str] | None = None,
) -> dict:
    """Execute a chat tool and return the result.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map. restrict_tables narrows query_data's sandbox allowlist to the
    calling surface's table scope.
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
        # Looked up via the facade module so patches on
        # ``app.processing.ai.chat_service._handle_query_data`` are honored.
        from app.processing.ai import chat_service

        try:
            return await chat_service._handle_query_data(
                tool_input,
                session,
                user,
                layers,
                stage_callback=stage_callback,
                map_id=map_id,
                restrict_tables=restrict_tables,
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

    if tool_name == "run_analysis":
        # handle_run_analysis owns its own error mapping (including the broad
        # catch-all) so every failure returns a tool result, never an exception.
        return await handle_run_analysis(
            tool_input, session, user, user_roles, layers, port=port
        )

    if tool_name == "set_data_driven_style":
        return await _build_data_driven_style(tool_input, session, layers, port=port)

    if tool_name == "set_render_as":
        return apply_render_as(tool_input, layers)

    # Validate set_style paint and explicit clear lists against geometry type.
    if tool_name == "set_style" and (
        tool_input.get("paint") or tool_input.get("clear_paint")
    ):
        target = next(
            (lyr for lyr in layers if lyr.id == tool_input.get("layer_id")), None
        )
        if target:
            # The layer's own render_mode keeps the heatmap radius, opacity and
            # intensity properties valid on an already-heatmap layer; set_style
            # is the only AI tool that tunes those. Mirrors ChatPanel.tsx's
            # validateChatPaint.
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

    # A hallucinated set_label column renders empty labels via a text-field
    # ["get", col]; returning an error lets the model retry with a real one.
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
    # chip shows a name instead of the raw UUID. Best-effort: a lookup miss or
    # error must not block the add (the frontend falls back to dataset_id). A
    # dataset the caller can't read fails the access check and gets the same
    # result as a missing one.
    if tool_name == "add_layer":
        result = {"status": "ok", **tool_input}
        raw_id = tool_input.get("dataset_id")
        if raw_id:
            try:
                dataset_id = UUID(str(raw_id))
                dataset = await port.get_dataset(session, dataset_id)
                if dataset is not None:
                    await port.check_dataset_access(
                        session, dataset, dataset_id, user, user_roles=user_roles
                    )
                    title = getattr(getattr(dataset, "record", None), "title", None)
                    if title:
                        result["dataset_name"] = title
            except Exception:  # broad: name lookup is best-effort; never block the add
                logger.debug(
                    "add_layer.dataset_name_lookup_failed", dataset_id=str(raw_id)
                )
        return result

    # For all other edit tools, return tool_input as-is
    if tool_name in _EDIT_TOOLS:
        return {"status": "ok", **tool_input}

    return {"error": f"Unknown tool: {tool_name}"}


def _collect_chat_action(tool_name: str, tool_input: dict, result: dict) -> dict | None:
    """Build an action dict from a chat tool call; None when it emits none."""
    if tool_name not in _EDIT_TOOLS:
        # query_data emits show_query_result for both spatial (geojson+bbox) and
        # non-spatial (columns+rows) results so the frontend inline data-analysis
        # card can render either case.
        if tool_name == "query_data" and "error" not in result and "columns" in result:
            action: dict = {
                "type": "show_query_result",
                "columns": result["columns"],
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "truncated": result.get("truncated", False),
            }
            # geojson and bbox are set together today, but that pairing is
            # unenforced on this plain dict; a missing bbox must not raise
            # inside the action collector.
            if "geojson" in result and "bbox" in result:
                action["geojson"] = result["geojson"]
                action["bbox"] = result["bbox"]
            return action
        if tool_name == "run_analysis":
            return collect_run_analysis_action(result)
        return None

    if tool_name in {"set_data_driven_style", "set_render_as"}:
        if "error" not in result:
            return result
        return None

    if tool_name == "set_label":
        # A validation error from _execute_chat_tool (unknown column) must not
        # still emit a label action built from the raw input.
        if "error" in result:
            return None
        return _build_label_action(tool_input)

    # set_style emits the validated/clamped paint from _execute_chat_tool,
    # which lives on `result`, not the raw fn_args. When validation was skipped
    # (no paint/clear_paint), `result` equals the raw tool_input.
    if tool_name == "set_style":
        action = {"type": "set_style", **tool_input}
        if "paint" in result:
            action["paint"] = result["paint"]
        if "clear_paint" in result:
            action["clear_paint"] = result["clear_paint"]
        return action

    # add_layer: the server-resolved dataset_name arrives on `result`, not
    # tool_input.
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

    # Clamp opacity server-side, like _PAINT_BOUNDS in set_style: models emit
    # percent values (opacity: 50), which fail ChatAction's ge=0/le=1 check.
    if tool_name == "set_opacity":
        raw_opacity = tool_input.get("opacity")
        if isinstance(raw_opacity, (int, float)) and not isinstance(raw_opacity, bool):
            tool_input = {
                **tool_input,
                "opacity": min(1.0, max(0.0, float(raw_opacity))),
            }

    return {"type": tool_name, **tool_input}
