"""Streaming chat service: SSE event generators for Anthropic and OpenAI providers."""

import json
import time
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ai.chat_service import (
    _collect_chat_action,
    _execute_chat_tool,
    _validate_actions,
    build_chat_system_prompt,
)
from app.processing.ai.constants import (
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
from app.processing.ai.schemas import ChatAction, ChatHistoryMessage, history_to_dicts
from app.processing.ai.token_usage import record_token_usage
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC
from typing import TYPE_CHECKING

from app.core.identity import Identity
from app.platform.extensions import get_ai_provider

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)


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
) -> AsyncGenerator[dict, None]:
    """Execute a list of (name, args) tool calls and yield SSE events for each.

    If *results_out* is provided, each raw tool result dict is appended to it
    so callers can build conversation-history messages without re-executing.

    map_id is forwarded to query_data so the schema-context cache partitions
    per-map (PERF-04 / Phase 274).
    """
    for fn_name, fn_args in tool_calls:
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
) -> AsyncGenerator[dict, None]:
    """Stream Anthropic chat with tool-calling loop."""
    messages = build_history_messages(history)
    messages.append({"role": "user", "content": message})

    # Enable prompt caching for system prompt and tools
    cached_system = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
    ]
    cached_tools = add_tool_cache_control(CHAT_TOOLS_ANTHROPIC)

    collected_actions: list[dict] = []
    total_input = 0
    total_output = 0
    deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS
    final_message = None

    for round_num in range(MAX_TOOL_ROUNDS):
        if time.monotonic() > deadline:
            yield {
                "type": "error",
                "message": "Response took too long. Please try a simpler request.",
            }
            break

        buffered_tokens: list[str] = []
        has_tool_use = False

        async with client.messages.stream(
            model=model,
            max_tokens=4096,
            temperature=0.3,
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
                        yield {
                            "type": "tool_start",
                            "tool": event.content_block.name,
                            "label": tool_label(event.content_block.name),
                        }
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
                    ):
                        yield evt

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(
                                raw_results[0] if raw_results else {}
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

    await record_token_usage(
        session,
        user_id=user.id,
        subsystem="chat_stream",
        model=model,
        input_tokens=total_input,
        output_tokens=total_output,
    )

    if final_message is None:
        yield {"type": "error", "message": "No response generated. Please try again."}
        return

    explanation = "".join(
        block.text for block in final_message.content if block.type == "text"
    )

    # Validate actions before yielding (mirrors non-streaming path)
    actions = [ChatAction(**a) for a in collected_actions]
    actions, dropped = await _validate_actions(
        actions, layers, session=session, user=user, port=port
    )
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
) -> AsyncGenerator[dict, None]:
    """Stream OpenAI-compatible chat with tool-calling loop."""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history_messages(history))
    messages.append({"role": "user", "content": message})

    collected_actions: list[dict] = []
    deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS
    total_input = 0
    total_output = 0

    for round_num in range(MAX_TOOL_ROUNDS):
        if time.monotonic() > deadline:
            yield {
                "type": "error",
                "message": "Response took too long. Please try a simpler request.",
            }
            break

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
            for t in CHAT_TOOLS_ANTHROPIC
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

        async for chunk in response_stream:
            # Usage-only chunks arrive after the last content chunk with
            # empty choices[]; accumulate token counts and continue.
            if getattr(chunk, "usage", None) is not None:
                total_input += getattr(chunk.usage, "prompt_tokens", 0) or 0
                total_output += getattr(chunk.usage, "completion_tokens", 0) or 0
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

                    # Emit tool_start on first appearance
                    if idx not in seen_tool_indices and entry["name"]:
                        seen_tool_indices.add(idx)
                        yield {
                            "type": "tool_start",
                            "tool": entry["name"],
                            "label": tool_label(entry["name"]),
                        }

            if choice.finish_reason:
                finish_reason = choice.finish_reason

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
            ):
                yield evt

            for (fn_name, _), call_id, result in zip(
                parsed_native, parsed_native_ids, native_results
            ):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result),
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

    await record_token_usage(
        session,
        user_id=user.id,
        subsystem="chat_stream",
        model=model,
        input_tokens=total_input,
        output_tokens=total_output,
    )

    # Validate actions before yielding (mirrors non-streaming path)
    actions = [ChatAction(**a) for a in collected_actions]
    actions, dropped = await _validate_actions(
        actions, layers, session=session, user=user, port=port
    )
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
) -> AsyncGenerator[dict, None]:
    """Main streaming orchestrator. Yields typed event dicts.

    map_id is forwarded so the schema-context cache partitions per-map
    (PERF-04 / Phase 274).
    """
    try:
        provider, model, runtime_config = await resolve_provider(db)
        system_prompt = build_chat_system_prompt(
            layers, language=language, basemap_style=basemap_style
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
