"""Streaming chat service: SSE event generators for Anthropic and OpenAI providers."""

import json
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import MAX_AI_TOKENS_PER_USER_PER_DAY

from app.processing.ai.chat_service import (
    _build_chat_actions,
    _collect_chat_action,
    _execute_chat_tool,
    _validate_actions,
    build_chat_system_prompt,
)
from app.processing.ai.constants import (
    MAX_REQUEST_TOKEN_BUDGET,
    MAX_STREAMING_WALL_CLOCK_SECONDS,
    MAX_TOOL_ROUNDS,
    tool_label,
)
from app.processing.ai.tool_call_parser import parse_xml_tool_calls
from app.processing.ai.llm_loop import (
    add_tool_cache_control,
    build_history_messages,
    resolve_provider,
)
from app.processing.ai.schemas import ChatHistoryMessage, history_to_dicts
from app.processing.ai.token_usage import AITokenUsage, record_token_usage
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC, select_chat_tools
from typing import TYPE_CHECKING

from app.core.identity import Identity
from app.platform.extensions import get_ai_provider

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)


async def _daily_token_budget(session: AsyncSession, user: Identity) -> tuple[int, int]:
    """Snapshot the per-user daily AI token cap and 24h usage.

    fix(#430 BA-10): the cap is enforced once at request entry (enforce_ai_token_budget),
    so a caller near the cap could still run a full multi-round tool loop over it.
    Returns ``(cap, used_in_last_24h)``; ``cap <= 0`` means unlimited. Callers add
    this request's in-memory token accumulator and stop the loop before crossing —
    one query per request, not per round.
    """
    # Fail-open: this is a best-effort mid-loop backstop; the authoritative cap
    # is enforced at request entry (enforce_ai_token_budget). A transient DB error
    # must never crash the user's stream, so any failure disables mid-loop
    # enforcement rather than raising.
    try:
        cap = await MAX_AI_TOKENS_PER_USER_PER_DAY.get(session)
        if cap <= 0:
            return 0, 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        used = await session.scalar(
            select(
                func.coalesce(
                    func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens), 0
                )
            ).where(AITokenUsage.user_id == user.id, AITokenUsage.created_at >= cutoff)
        )
        return cap, int(used or 0)
    except Exception:  # broad: never let the backstop crash the stream
        return 0, 0


def _make_stage_callback(tool_name: str, stage_events: list[dict]):
    """Build a stage callback for query_data sub-stages, or None for other tools."""
    if tool_name != "query_data":
        return None
    return lambda label: stage_events.append(
        {"type": "tool_start", "tool": "query_data", "label": label}
    )


async def _execute_and_yield_tools(
    tool_calls: list[tuple[str, dict]],
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    layers: list,
    collected_actions: list[dict],
    results_out: list[dict] | None = None,
    *,
    port: "ProcessingPort",
    map_id: str | None = None,
    allowed_tools: set[str] | None = None,
    restrict_tables: frozenset[str] | None = None,
) -> AsyncGenerator[dict, None]:
    """Execute a list of (name, args) tool calls and yield SSE events for each.

    If *results_out* is provided, each raw tool result dict is appended to it
    so callers can build conversation-history messages without re-executing.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map (PERF-04 / Phase 274).

    allowed_tools, when provided, restricts which tool names may run: a call
    whose name is outside the set is dropped before execution AND collection,
    enforcing the read-only tool set for view-only callers even when a call
    arrives via the XML fallback (parse_xml_tool_calls), which bypasses the
    advertised tool schema. A dropped call still appends a refusal entry to
    results_out (when provided) so the caller's results_out↔tool_calls zip stays
    aligned — the OpenAI-native path zips the original calls/ids with results_out
    to build the next round's tool messages, so a missing entry would misalign
    tool_call ids or emit an unmatched call. The model receives an explicit
    "not permitted" result instead.
    """
    for fn_name, fn_args in tool_calls:
        if allowed_tools is not None and fn_name not in allowed_tools:
            logger.warning(
                "Dropped disallowed chat tool call (read-only caller)",
                tool=fn_name,
                allowed=sorted(allowed_tools),
            )
            if results_out is not None:
                results_out.append({"error": "Tool not permitted for this map."})
            # Balance the tool_start the streaming loop already emitted for this call.
            yield {"type": "tool_result", "tool": fn_name, "success": False}
            continue
        stage_events: list[dict] = []
        stage_cb = _make_stage_callback(fn_name, stage_events)

        result = await _execute_chat_tool(
            fn_name,
            fn_args,
            session,
            user,
            user_roles,
            layers,
            stage_callback=stage_cb,
            port=port,
            map_id=map_id,
            restrict_tables=restrict_tables,
        )

        if results_out is not None:
            results_out.append(result)

        action = _collect_chat_action(fn_name, fn_args, result)
        if action:
            collected_actions.append(action)

        for evt in stage_events:
            yield evt

        yield {
            "type": "tool_result",
            "tool": fn_name,
            "success": "error" not in result,
        }


async def _stream_anthropic_chat(
    message: str,
    system_prompt: str,
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    layers: list,
    *,
    model: str,
    history: list[dict] | None = None,
    client,
    port: "ProcessingPort",
    map_id: str | None = None,
    tools: list | None = None,
    restrict_tables: frozenset[str] | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream Anthropic chat with tool-calling loop."""
    messages = build_history_messages(history)
    messages.append({"role": "user", "content": message})

    # Enable prompt caching for system prompt and tools
    cached_system = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
    ]
    _raw_tools = CHAT_TOOLS_ANTHROPIC if tools is None else tools
    cached_tools = add_tool_cache_control(_raw_tools)
    allowed_tool_names = {t["name"] for t in _raw_tools}

    collected_actions: list[dict] = []
    total_input = 0
    total_output = 0
    deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS
    final_message = None
    daily_cap, daily_used = await _daily_token_budget(session, user)  # fix(#430 BA-10)

    for round_num in range(MAX_TOOL_ROUNDS):
        if time.monotonic() > deadline:
            yield {
                "type": "error",
                "message": "Response took too long. Please try a simpler request.",
            }
            break

        # PERF-009: stop gracefully once the cumulative input+output token budget
        # for this request is exceeded. Usage is accumulated at the end of each
        # round below, so this top-of-loop check catches a runaway before the next
        # provider call — same shape as the deadline guard above.
        if total_input + total_output > MAX_REQUEST_TOKEN_BUDGET:
            logger.info(
                "Chat stream token budget exceeded",
                provider="anthropic",
                round=round_num,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                budget=MAX_REQUEST_TOKEN_BUDGET,
            )
            break

        # fix(#430 BA-10): stop before the next round would push the user over their
        # daily token cap (snapshot + this request's accumulator; no per-round query).
        if daily_cap > 0 and daily_used + total_input + total_output >= daily_cap:
            logger.info(
                "Chat stream daily token budget exceeded",
                provider="anthropic",
                round=round_num,
                daily_cap=daily_cap,
            )
            yield {
                "type": "error",
                "message": "Daily AI token budget exceeded. Try again later.",
            }
            # fix(#430 codex): return, not break — falling through emitted a
            # second "No response generated" error after the budget error.
            # Usage is recorded per-round, so nothing post-loop is skipped.
            return

        buffered_tokens: list[str] = []
        has_tool_use = False
        # fix(#402) codex P1 (round 5): tool_start is buffered, not yielded
        # mid-stream. Usage is only retrievable from get_final_message() below,
        # so a yield before that point would let a disconnect skip this round's
        # accounting. Flushed AFTER record_token_usage so the record precedes
        # every yield in the round. (Residual: a disconnect DURING the provider
        # stream, before get_final_message returns, is inherently unaccountable —
        # the token count does not exist client-side yet.)
        pending_tool_starts: list[dict] = []

        # Claude 4.6+ models reject a non-default `temperature` with a 400;
        # omit it on the Anthropic path (steering is prompt-based there).
        async with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=cached_system,
            tools=cached_tools,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if (
                        hasattr(event.content_block, "type")
                        and event.content_block.type == "tool_use"
                    ):
                        has_tool_use = True
                        pending_tool_starts.append(
                            {
                                "type": "tool_start",
                                "tool": event.content_block.name,
                                "label": tool_label(event.content_block.name),
                            }
                        )
                elif event.type == "content_block_delta":
                    if (
                        hasattr(event.delta, "type")
                        and event.delta.type == "text_delta"
                    ):
                        buffered_tokens.append(event.delta.text)

            final_message = await stream.get_final_message()

        # Track token usage
        if hasattr(final_message, "usage") and final_message.usage:
            total_input += final_message.usage.input_tokens
            total_output += final_message.usage.output_tokens
            # fix(#402) codex P1: record THIS round's usage now, before the
            # token/tool-event yields below. A client disconnect mid-stream
            # raises GeneratorExit at a yield and skips any end-of-function
            # accounting, so usage must land per-round as it is learned — else
            # the daily cap is bypassable by aborting streaming chats. Each row
            # is durable (record_token_usage self-commits), so completed rounds
            # always count.
            await record_token_usage(
                session,
                user_id=user.id,
                subsystem="chat_stream",
                model=model,
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
            )

        # Flush buffered tool_start events now — after accounting, so the
        # per-round record precedes every yield in the round (disconnect-safe).
        for _tool_start in pending_tool_starts:
            yield _tool_start

        # Only emit buffered text tokens if the round did NOT end with tool use.
        if not has_tool_use:
            for token in buffered_tokens:
                yield {"type": "token", "text": token}

        logger.info(
            "Chat stream round",
            provider="anthropic",
            round=round_num + 1,
            stop_reason=final_message.stop_reason,
            input_tokens=final_message.usage.input_tokens if final_message.usage else 0,
            output_tokens=final_message.usage.output_tokens
            if final_message.usage
            else 0,
        )

        if final_message.stop_reason == "end_turn":
            break

        if final_message.stop_reason == "tool_use":
            tool_results = []
            for block in final_message.content:
                if block.type == "tool_use":
                    raw_results: list[dict] = []
                    async for evt in _execute_and_yield_tools(
                        [(block.name, block.input)],
                        session,
                        user,
                        user_roles,
                        layers,
                        collected_actions,
                        results_out=raw_results,
                        port=port,
                        map_id=map_id,
                        allowed_tools=allowed_tool_names,
                        restrict_tables=restrict_tables,
                    ):
                        yield evt

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            # default=str: query_data rows can carry Decimal /
                            # datetime values straight from PostGIS.
                            "content": json.dumps(
                                raw_results[0] if raw_results else {},
                                default=str,
                            ),
                        }
                    )

            messages.append({"role": "assistant", "content": final_message.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason -- break
        break

    logger.info(
        "Chat stream complete",
        provider="anthropic",
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
    # Usage is recorded per-round above (disconnect-safe); no end-of-stream
    # record here — that would double-count and would be skipped on disconnect.

    if final_message is None:
        yield {"type": "error", "message": "No response generated. Please try again."}
        return

    explanation = "".join(
        block.text for block in final_message.content if block.type == "text"
    )

    # Validate actions before yielding (mirrors non-streaming path).
    # Per-item build: one invalid action drops with a note instead of raising
    # through the broad except and discarding the whole turn (fix(#525 B-037)).
    actions, invalid = _build_chat_actions(collected_actions)
    actions, dropped = await _validate_actions(
        actions, layers, session=session, user=user, port=port
    )
    dropped = invalid + dropped
    if dropped:
        explanation += "\n\nNote: some actions were skipped: " + "; ".join(dropped)

    yield {
        "type": "actions",
        "actions": [a.model_dump(exclude_none=True) for a in actions],
    }
    yield {"type": "done", "explanation": explanation}


async def _stream_openai_chat(
    message: str,
    system_prompt: str,
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    layers: list,
    *,
    model: str,
    history: list[dict] | None = None,
    client,
    port: "ProcessingPort",
    map_id: str | None = None,
    tools: list | None = None,
    restrict_tables: frozenset[str] | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream OpenAI-compatible chat with tool-calling loop."""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history_messages(history))
    messages.append({"role": "user", "content": message})

    collected_actions: list[dict] = []
    deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS
    total_input = 0
    total_output = 0
    daily_cap, daily_used = await _daily_token_budget(session, user)  # fix(#430 BA-10)
    # Read-only enforcement backstop: the XML fallback (parse_xml_tool_calls)
    # below extracts tool calls from model text, bypassing the advertised schema.
    # Restrict execution/collection to the selected tool set so a view-only caller
    # cannot get a mutating action even from an XML-emitting model.
    allowed_tool_names = {
        t["name"] for t in (CHAT_TOOLS_ANTHROPIC if tools is None else tools)
    }

    for round_num in range(MAX_TOOL_ROUNDS):
        if time.monotonic() > deadline:
            yield {
                "type": "error",
                "message": "Response took too long. Please try a simpler request.",
            }
            break

        # PERF-009: stop gracefully once the cumulative input+output token budget
        # for this request is exceeded. Usage is accumulated per round below, so
        # this top-of-loop check catches a runaway before the next provider call —
        # same shape as the deadline guard above.
        if total_input + total_output > MAX_REQUEST_TOKEN_BUDGET:
            logger.info(
                "Chat stream token budget exceeded",
                provider="openai",
                round=round_num,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                budget=MAX_REQUEST_TOKEN_BUDGET,
            )
            break

        # fix(#430 BA-10): stop before the next round would push the user over their
        # daily token cap (snapshot + this request's accumulator; no per-round query).
        if daily_cap > 0 and daily_used + total_input + total_output >= daily_cap:
            logger.info(
                "Chat stream daily token budget exceeded",
                provider="openai",
                round=round_num,
                daily_cap=daily_cap,
            )
            yield {
                "type": "error",
                "message": "Daily AI token budget exceeded. Try again later.",
            }
            # fix(#430 codex): return, not break — falling through yielded empty
            # actions/done, letting clients treat the capped request as success.
            # Usage is recorded per-round, so nothing post-loop is skipped.
            return

        # Phase 226 D-08: CHAT_TOOLS_OPENAI removed; convert from canonical Anthropic shape.
        _tools_openai = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in (CHAT_TOOLS_ANTHROPIC if tools is None else tools)
        ]
        response_stream = await client.chat.completions.create(
            model=model,
            max_tokens=4096,
            temperature=0.3,
            tools=_tools_openai,
            messages=messages,
            stream=True,
            # OpenAI streaming omits the usage block by default; opt in so
            # per-round input/output token counts arrive on the FINAL chunk
            # (the one with empty choices[]).
            stream_options={"include_usage": True},
        )

        # Accumulate tool calls and content across chunks
        content_parts: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        finish_reason = None
        seen_tool_indices: set[int] = set()
        has_tool_use = False
        buffered_tokens: list[str] = []
        # fix(#402) codex P1 (round 5): buffer tool_start (flushed after the
        # per-round record below), so a disconnect can't skip this round's
        # accounting via a mid-stream tool_start yield.
        pending_tool_starts: list[dict] = []

        async for chunk in response_stream:
            # Usage-only chunks arrive after the last content chunk with
            # empty choices[]; accumulate token counts and continue.
            if getattr(chunk, "usage", None) is not None:
                _round_in = getattr(chunk.usage, "prompt_tokens", 0) or 0
                _round_out = getattr(chunk.usage, "completion_tokens", 0) or 0
                total_input += _round_in
                total_output += _round_out
                # fix(#402) codex P1: record usage as it is learned, before the
                # post-round token/tool yields. A client disconnect raises
                # GeneratorExit at a yield and skips any end-of-function
                # accounting, so recording here (durable, self-committing) keeps
                # aborted streaming chats from bypassing the daily cap.
                await record_token_usage(
                    session,
                    user_id=user.id,
                    subsystem="chat_stream",
                    model=model,
                    input_tokens=_round_in,
                    output_tokens=_round_out,
                )
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta
            if delta and delta.content:
                content_parts.append(delta.content)
                # Buffer tokens — emit after stream if no tool calls
                if not has_tool_use:
                    buffered_tokens.append(delta.content)

            if delta and delta.tool_calls:
                has_tool_use = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = tool_calls_by_index[idx]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function and tc.function.name:
                        entry["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        entry["arguments"] += tc.function.arguments

                    # Buffer tool_start on first appearance (flushed post-record)
                    if idx not in seen_tool_indices and entry["name"]:
                        seen_tool_indices.add(idx)
                        pending_tool_starts.append(
                            {
                                "type": "tool_start",
                                "tool": entry["name"],
                                "label": tool_label(entry["name"]),
                            }
                        )

            if choice.finish_reason:
                finish_reason = choice.finish_reason

        # Flush buffered tool_start events — after the per-round record above, so
        # the record precedes every yield in the round (disconnect-safe).
        for _tool_start in pending_tool_starts:
            yield _tool_start

        logger.info(
            "Chat stream round",
            provider="openai",
            round=round_num + 1,
            finish_reason=finish_reason,
        )

        if finish_reason == "tool_calls":
            # Discard pre-tool "thinking" text from content_parts for the done event
            pre_tool_text = "".join(content_parts)
            content_parts.clear()

            # Build assistant message with tool_calls for conversation history
            assistant_tool_calls = []
            for idx in sorted(tool_calls_by_index.keys()):
                tc_data = tool_calls_by_index[idx]
                assistant_tool_calls.append(
                    {
                        "id": tc_data["id"],
                        "type": "function",
                        "function": {
                            "name": tc_data["name"],
                            "arguments": tc_data["arguments"],
                        },
                    }
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": pre_tool_text or None,
                    "tool_calls": assistant_tool_calls,
                }
            )

            parsed_native: list[tuple[str, dict]] = []
            parsed_native_ids: list[str] = []
            for idx in sorted(tool_calls_by_index.keys()):
                tc_data = tool_calls_by_index[idx]
                fn_name = tc_data["name"]
                try:
                    fn_args = json.loads(tc_data["arguments"])
                except json.JSONDecodeError:
                    # Some models produce malformed JSON; extract first valid object
                    try:
                        fn_args, _ = json.JSONDecoder().raw_decode(tc_data["arguments"])
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(
                            "Unparseable tool arguments",
                            tool=fn_name,
                            args=tc_data["arguments"],
                        )
                        continue
                parsed_native.append((fn_name, fn_args))
                parsed_native_ids.append(tc_data["id"])

            native_results: list[dict] = []
            async for evt in _execute_and_yield_tools(
                parsed_native,
                session,
                user,
                user_roles,
                layers,
                collected_actions,
                results_out=native_results,
                port=port,
                map_id=map_id,
                allowed_tools=allowed_tool_names,
                restrict_tables=restrict_tables,
            ):
                yield evt

            for (fn_name, _), call_id, result in zip(
                parsed_native, parsed_native_ids, native_results
            ):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        # default=str: see the Anthropic tool_result path above.
                        "content": json.dumps(result, default=str),
                    }
                )
            continue

        # finish_reason == "stop" or anything else — check for XML tool calls first
        full_text = "".join(content_parts)
        parsed_calls, cleaned_text = parse_xml_tool_calls(full_text)

        if parsed_calls:
            # Execute parsed XML tool calls through existing pipeline
            for fn_name, fn_args in parsed_calls:
                logger.info("Parsed XML tool call", tool=fn_name, input=fn_args)
                yield {
                    "type": "tool_start",
                    "tool": fn_name,
                    "label": tool_label(fn_name),
                }
            async for evt in _execute_and_yield_tools(
                parsed_calls,
                session,
                user,
                user_roles,
                layers,
                collected_actions,
                port=port,
                map_id=map_id,
                allowed_tools=allowed_tool_names,
                restrict_tables=restrict_tables,
            ):
                yield evt

            # Emit cleaned text (without XML blocks) as tokens
            if cleaned_text:
                yield {"type": "token", "text": cleaned_text}
            # Update content_parts for the done event
            content_parts.clear()
            content_parts.append(cleaned_text)
        else:
            # No XML tool calls — emit buffered tokens incrementally
            for token in buffered_tokens:
                yield {"type": "token", "text": token}
        break

    # Usage is recorded per usage-chunk above (disconnect-safe); no
    # end-of-stream record here — that would double-count and be skipped on
    # disconnect.

    # Validate actions before yielding (mirrors non-streaming path).
    # Per-item build: one invalid action drops with a note instead of raising
    # through the broad except and discarding the whole turn (fix(#525 B-037)).
    actions, invalid = _build_chat_actions(collected_actions)
    actions, dropped = await _validate_actions(
        actions, layers, session=session, user=user, port=port
    )
    dropped = invalid + dropped
    explanation_text = "".join(content_parts)
    if dropped:
        explanation_text += "\n\nNote: some actions were skipped: " + "; ".join(dropped)

    yield {
        "type": "actions",
        "actions": [a.model_dump(exclude_none=True) for a in actions],
    }
    yield {"type": "done", "explanation": explanation_text}


async def stream_chat_edit(
    db: AsyncSession,
    user: Identity,
    user_roles: set[str],
    message: str,
    layers: list,
    language: str | None = None,
    history: list[ChatHistoryMessage] | None = None,
    basemap_style: str | None = None,
    *,
    port: "ProcessingPort",
    map_id: str | None = None,
    can_edit: bool = True,
    system_prompt_override: str | None = None,
    restrict_tables: frozenset[str] | None = None,
) -> AsyncGenerator[dict, None]:
    """Main streaming orchestrator. Yields typed event dicts.

    map_id is forwarded so the schema-context cache partitions per-map
    (PERF-04 / Phase 274).

    can_edit gates the tool set: a view-only caller gets read-only tools so the
    AI answers questions but cannot emit edit actions (see select_chat_tools).

    system_prompt_override replaces the map-framed system prompt for non-map
    surfaces (dataset-scoped chat builds its own via
    build_dataset_chat_system_prompt); tool selection still follows can_edit.

    restrict_tables narrows query_data's sandbox allowlist to the calling
    surface's table scope (dataset chat passes its single table — PR #531
    review); None preserves the user-wide RBAC allowlist.
    """
    try:
        provider, model, runtime_config = await resolve_provider(db)
        system_prompt = system_prompt_override or build_chat_system_prompt(
            layers, language=language, basemap_style=basemap_style, can_edit=can_edit
        )

        history_dicts = history_to_dicts(history)
        provider_ext = get_ai_provider(provider)
        async for event in provider_ext.stream_chat_events(
            message=message,
            system_prompt=system_prompt,
            session=db,
            user=user,
            user_roles=user_roles,
            layers=layers,
            model=model,
            base_url=runtime_config.get("base_url"),
            history=history_dicts,
            port=port,
            map_id=map_id,
            tools=select_chat_tools(can_edit),
            restrict_tables=restrict_tables,
        ):
            yield event
    except Exception as e:  # broad: SSE stream generator — any unhandled SDK/runtime error must yield a graceful error event
        error_msg = "An unexpected error occurred. Please try again."
        if isinstance(e, (ValueError, KeyError)):
            error_msg = str(e)
        logger.exception("Chat streaming error")
        yield {"type": "error", "message": error_msg}
    finally:
        # Guarantee cleanup even if the consumer cancels mid-stream. The
        # caller owns the db session (we don't close it), but we flush any
        # structlog contextvars we may have bound so context doesn't leak
        # across requests when the same task is reused.
        try:
            structlog.contextvars.unbind_contextvars("chat_stream_id")
        except Exception:  # broad: structlog contextvar cleanup is best-effort; never block stream finalization
            pass
