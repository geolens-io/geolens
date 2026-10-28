"""Streaming chat service: SSE event generators for Anthropic and OpenAI providers."""

import json
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import MAX_AI_TOKENS_PER_USER_PER_DAY
from app.platform.ai_tool_payloads import tool_result_content

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
    stream_error_event,
)
from app.processing.ai.openai_conversation import Round, ToolCall, open_conversation
from app.processing.ai.schemas import ChatHistoryMessage, history_to_dicts
from app.processing.ai.token_usage import AITokenUsage, record_token_usage
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC, select_chat_tools
from typing import TYPE_CHECKING

from app.core.db import release_connection
from app.core.identity import Identity
from app.platform.extensions import get_ai_provider

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)


async def _daily_token_budget(session: AsyncSession, user: Identity) -> tuple[int, int]:
    """Snapshot the per-user daily AI token cap and 24h usage.

    The cap is enforced at request entry (enforce_ai_token_budget), so a caller
    near the cap could still run a full multi-round tool loop over it. Returns
    ``(cap, used_in_last_24h)``; ``cap <= 0`` means unlimited. Callers add this
    request's in-memory accumulator and check it after each round, so the round
    that crosses the cap is billed and no further round starts. It costs one
    query per request, not per round.
    """
    # Fail-open: the entry gate already checked the cap and each request stays
    # under MAX_REQUEST_TOKEN_BUDGET, so a DB error disables only this backstop
    # rather than crashing the stream.
    cap: int | None = None
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
    except Exception as exc:  # broad: never let the backstop crash the stream
        logger.warning(
            "Daily AI token budget unreadable; mid-loop cap off for this request",
            user_id=str(user.id),
            daily_cap=cap,
            error=str(exc),
            error_type=type(exc).__name__,
        )
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

    If *results_out* is provided, each raw tool result dict is appended so
    callers can build conversation-history messages without re-executing.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map.

    allowed_tools, when provided, restricts which tool names may run: a call
    outside the set is dropped before execution AND collection, enforcing the
    read-only tool set even for a call arriving via the XML fallback, which
    bypasses the advertised tool schema. A dropped call still appends a refusal
    entry to results_out so the OpenAI-native path's calls/ids ↔ results_out
    zip stays aligned; the model receives an explicit "not permitted" result.
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
            # Balances the tool_start already emitted for this call.
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
    messages = build_history_messages(history)
    messages.append({"role": "user", "content": message})

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
    daily_cap, daily_used = await _daily_token_budget(session, user)

    for round_num in range(MAX_TOOL_ROUNDS):
        if time.monotonic() > deadline:
            yield {
                "type": "error",
                "message": "Response took too long. Please try a simpler request.",
            }
            break

        # Stop gracefully once the request's cumulative input+output token
        # budget is exceeded. Usage accumulates at the end of each round, so
        # this check catches a runaway before the next provider call.
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

        # Stop once usage has reached the daily cap (snapshot + this request's
        # accumulator; no per-round query). The round that crosses it bills.
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
            # Return, not break: falling through would emit a second "No
            # response generated" error. Usage is recorded per round, so
            # nothing post-loop is skipped.
            return

        buffered_tokens: list[str] = []
        has_tool_use = False
        # tool_start is buffered, not yielded mid-stream: usage is only
        # available from get_final_message() below, and a yield before that
        # would let a disconnect skip this round's accounting. It is flushed
        # AFTER record_token_usage. (A disconnect DURING the provider stream
        # itself is inherently unaccountable.)
        pending_tool_starts: list[dict] = []

        await release_connection(session)
        # Claude 4.6+ models reject a non-default `temperature` with a 400, so
        # it is omitted on the Anthropic path.
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

        if hasattr(final_message, "usage") and final_message.usage:
            total_input += final_message.usage.input_tokens
            total_output += final_message.usage.output_tokens
            # Record THIS round's usage before the token/tool-event yields
            # below: a client disconnect raises GeneratorExit at a yield,
            # skipping end-of-function accounting, so the daily cap would be
            # bypassable by aborting streaming chats. record_token_usage
            # self-commits, so completed rounds always count.
            await record_token_usage(
                user_id=user.id,
                subsystem="chat_stream",
                model=model,
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
            )

        # Flushed after accounting, so the per-round record precedes every
        # yield in the round (disconnect-safe).
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
                            # Fenced, not bare JSON.
                            "content": tool_result_content(
                                raw_results[0] if raw_results else {}
                            ),
                        }
                    )

            messages.append({"role": "assistant", "content": final_message.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason.
        break

    logger.info(
        "Chat stream complete",
        provider="anthropic",
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
    # Usage is recorded per round above; an end-of-stream record would
    # double-count and be skipped on disconnect.

    if final_message is None:
        yield {"type": "error", "message": "No response generated. Please try again."}
        return

    explanation = "".join(
        block.text for block in final_message.content if block.type == "text"
    )

    # Per-item build: one invalid action drops with a note instead of raising
    # through the broad except and discarding the whole turn.
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
    base_url: str | None = None,
    port: "ProcessingPort",
    map_id: str | None = None,
    tools: list | None = None,
    restrict_tables: frozenset[str] | None = None,
) -> AsyncGenerator[dict, None]:
    selected_tools = CHAT_TOOLS_ANTHROPIC if tools is None else tools
    conversation = open_conversation(
        client,
        base_url=base_url,
        model=model,
        system_prompt=system_prompt,
        history=history,
        user_message=message,
        tools=selected_tools,
        max_tokens=4096,
        temperature=0.3,
    )

    collected_actions: list[dict] = []
    deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS
    total_input = 0
    total_output = 0
    daily_cap, daily_used = await _daily_token_budget(session, user)
    # Read-only enforcement backstop: the XML fallback (parse_xml_tool_calls)
    # extracts tool calls from model text, bypassing the advertised schema, so
    # execution and collection are restricted to the selected tool set. A
    # view-only caller then cannot get a mutating action even from an
    # XML-emitting model.
    allowed_tool_names = {t["name"] for t in selected_tools}

    for round_num in range(MAX_TOOL_ROUNDS):
        if time.monotonic() > deadline:
            yield {
                "type": "error",
                "message": "Response took too long. Please try a simpler request.",
            }
            break

        # Stop gracefully once the request's cumulative input+output token
        # budget is exceeded. Usage accumulates per round, so this check
        # catches a runaway before the next provider call.
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

        # Stop once usage has reached the daily cap (snapshot + this request's
        # accumulator; no per-round query). The round that crosses it bills.
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
            # Return, not break: falling through would yield empty actions/done
            # and let clients treat the capped request as a success. Usage is
            # recorded per round, so nothing post-loop is skipped.
            return

        await release_connection(session)

        content_parts: list[str] = []
        has_tool_use = False
        buffered_tokens: list[str] = []
        # Buffered and flushed after the per-round record, so a mid-stream
        # tool_start yield can't let a disconnect skip this round's accounting.
        pending_tool_starts: list[dict] = []
        round_ = None

        async for delta in conversation.stream():
            if isinstance(delta, Round):
                round_ = delta
            elif delta.usage is not None:
                _round_in, _round_out = delta.usage
                total_input += _round_in
                total_output += _round_out
                # Recorded as learned, before the post-round token/tool yields:
                # a client disconnect raises GeneratorExit at a yield and
                # skips end-of-function accounting, so aborted streaming chats
                # would otherwise bypass the daily cap.
                await record_token_usage(
                    user_id=user.id,
                    subsystem="chat_stream",
                    model=model,
                    input_tokens=_round_in,
                    output_tokens=_round_out,
                )
            elif delta.text:
                content_parts.append(delta.text)
                # Emitted after the stream if no tool calls follow.
                if not has_tool_use:
                    buffered_tokens.append(delta.text)
            elif delta.tool_name:
                has_tool_use = True
                pending_tool_starts.append(
                    {
                        "type": "tool_start",
                        "tool": delta.tool_name,
                        "label": tool_label(delta.tool_name),
                    }
                )
        finish_reason = round_.finish_reason if round_ else None

        # Flushed after the per-round record above (disconnect-safe).
        for _tool_start in pending_tool_starts:
            yield _tool_start

        logger.info(
            "Chat stream round",
            provider="openai",
            round=round_num + 1,
            finish_reason=finish_reason,
        )

        if finish_reason == "tool_calls":
            # Pre-tool "thinking" text stays out of the done event.
            content_parts.clear()

            parsed_native: list[tuple[str, dict]] = []
            parsed_native_calls: list[ToolCall] = []
            for call in round_.tool_calls:
                fn_name = call.name
                try:
                    fn_args = json.loads(call.arguments)
                except json.JSONDecodeError:
                    # Some models emit malformed JSON; take the first valid object.
                    try:
                        fn_args, _ = json.JSONDecoder().raw_decode(call.arguments)
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(
                            "Unparseable tool arguments",
                            tool=fn_name,
                            args=call.arguments,
                        )
                        continue
                parsed_native.append((fn_name, fn_args))
                parsed_native_calls.append(call)

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

            conversation.add_tool_results(
                round_, list(zip(parsed_native_calls, native_results))
            )
            continue

        # A round that stopped early can still hold a complete-looking XML
        # call; only a finished round runs one.
        full_text = "".join(content_parts)
        parsed_calls, cleaned_text = (
            parse_xml_tool_calls(full_text)
            if finish_reason == "stop"
            else ([], full_text)
        )

        if parsed_calls:
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

            if cleaned_text:
                yield {"type": "token", "text": cleaned_text}
            content_parts.clear()
            content_parts.append(cleaned_text)
        else:
            for token in buffered_tokens:
                yield {"type": "token", "text": token}
        break

    # Usage is recorded per usage chunk above; an end-of-stream record would
    # double-count and be skipped on disconnect.

    # Per-item build: one invalid action drops with a note instead of raising
    # through the broad except and discarding the whole turn.
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
    has_map: bool = True,
) -> AsyncGenerator[dict, None]:
    """Main streaming orchestrator. Yields typed event dicts.

    map_id is forwarded so the schema-context cache partitions per-map.

    can_edit gates the tool set: a view-only caller gets read-only tools
    (see select_chat_tools).

    system_prompt_override replaces the map-framed system prompt for
    non-map surfaces (dataset chat builds its own); tool selection still
    follows can_edit.

    restrict_tables narrows query_data's sandbox allowlist to the calling
    surface's table scope (dataset chat passes its single table); None keeps
    the user-wide RBAC allowlist.

    has_map=False withholds map-only tools (run_analysis) from surfaces
    with no map to render an overlay on.
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
            tools=select_chat_tools(can_edit, has_map),
            restrict_tables=restrict_tables,
        ):
            yield event
    except Exception as e:  # broad: SSE stream generator — any unhandled SDK/runtime error must yield a graceful error event
        # Same positive allowlist as the map-generation generator: passing
        # every ValueError/KeyError through would leak internals, since a
        # KeyError names an internal dict key and
        # OpenAICredentialDestinationError is a ValueError naming the
        # configured provider endpoint.
        logger.exception("Chat streaming error")
        yield stream_error_event(e)
    finally:
        # Runs even if the consumer cancels mid-stream. The caller owns the db
        # session; the structlog contextvar is unbound so context doesn't leak
        # across requests when the same task is reused.
        try:
            structlog.contextvars.unbind_contextvars("chat_stream_id")
        except Exception:  # broad: structlog contextvar cleanup is best-effort; never block stream finalization
            pass
