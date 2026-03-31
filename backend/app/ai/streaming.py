"""Streaming chat service: SSE event generators for Anthropic and OpenAI providers."""

import json
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_service import (
    _collect_chat_action,
    _execute_chat_tool,
    build_chat_system_prompt,
)
from app.ai.constants import MAX_TOOL_ROUNDS, tool_label
from app.ai.tool_call_parser import parse_xml_tool_calls
from app.ai.llm_loop import (
    add_tool_cache_control,
    get_anthropic_client,
    get_openai_client,
    build_history_messages,
    resolve_provider,
)
from app.ai.schemas import ChatHistoryMessage
from app.ai.tools import CHAT_TOOLS_ANTHROPIC, CHAT_TOOLS_OPENAI
from app.auth.models import User
from app.config import settings

logger = structlog.stdlib.get_logger(__name__)


async def _stream_anthropic_chat(
    message: str,
    system_prompt: str,
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    layers: list,
    *,
    model: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream Anthropic chat with tool-calling loop."""
    client = get_anthropic_client()

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

    for round_num in range(MAX_TOOL_ROUNDS):
        buffered_tokens: list[str] = []
        has_tool_use = False

        async with client.messages.stream(
            model=model,
            max_tokens=4096,
            temperature=0.5,
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
                    stage_events: list[dict] = []
                    stage_cb = (
                        (
                            lambda label: stage_events.append(
                                {
                                    "type": "tool_start",
                                    "tool": "query_data",
                                    "label": label,
                                }
                            )
                        )
                        if block.name == "query_data"
                        else None
                    )

                    result = await _execute_chat_tool(
                        block.name,
                        block.input,
                        session,
                        user,
                        user_roles,
                        layers,
                        stage_callback=stage_cb,
                    )

                    action = _collect_chat_action(block.name, block.input, result)
                    if action:
                        collected_actions.append(action)

                    # Yield sub-stage events before tool_result
                    for evt in stage_events:
                        yield evt

                    yield {
                        "type": "tool_result",
                        "tool": block.name,
                        "success": "error" not in result,
                    }

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
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

    explanation = "".join(
        block.text for block in final_message.content if block.type == "text"
    )
    yield {"type": "actions", "actions": collected_actions}
    yield {"type": "done", "explanation": explanation}


async def _stream_openai_chat(
    message: str,
    system_prompt: str,
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    layers: list,
    *,
    model: str,
    base_url: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream OpenAI-compatible chat with tool-calling loop."""
    client = get_openai_client(base_url)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history_messages(history))
    messages.append({"role": "user", "content": message})

    collected_actions: list[dict] = []

    for round_num in range(MAX_TOOL_ROUNDS):
        response_stream = await client.chat.completions.create(
            model=model,
            max_tokens=4096,
            temperature=0.5,
            tools=CHAT_TOOLS_OPENAI,
            messages=messages,
            stream=True,
        )

        # Accumulate tool calls and content across chunks
        content_parts: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        finish_reason = None
        seen_tool_indices: set[int] = set()

        async for chunk in response_stream:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta
            if delta and delta.content:
                content_parts.append(delta.content)

            if delta and delta.tool_calls:
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

                stage_events: list[dict] = []
                stage_cb = (
                    (
                        lambda label: stage_events.append(
                            {"type": "tool_start", "tool": "query_data", "label": label}
                        )
                    )
                    if fn_name == "query_data"
                    else None
                )

                result = await _execute_chat_tool(
                    fn_name,
                    fn_args,
                    session,
                    user,
                    user_roles,
                    layers,
                    stage_callback=stage_cb,
                )

                action = _collect_chat_action(fn_name, fn_args, result)
                if action:
                    collected_actions.append(action)

                # Yield sub-stage events before tool_result
                for evt in stage_events:
                    yield evt

                yield {
                    "type": "tool_result",
                    "tool": fn_name,
                    "success": "error" not in result,
                }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_data["id"],
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

                stage_events: list[dict] = []
                stage_cb = (
                    (
                        lambda label: stage_events.append(
                            {"type": "tool_start", "tool": "query_data", "label": label}
                        )
                    )
                    if fn_name == "query_data"
                    else None
                )

                result = await _execute_chat_tool(
                    fn_name,
                    fn_args,
                    session,
                    user,
                    user_roles,
                    layers,
                    stage_callback=stage_cb,
                )

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

            # Emit cleaned text (without XML blocks) as tokens
            if cleaned_text:
                yield {"type": "token", "text": cleaned_text}
            # Update content_parts for the done event
            content_parts.clear()
            content_parts.append(cleaned_text)
        else:
            # No XML tool calls — emit text as-is
            for part in content_parts:
                yield {"type": "token", "text": part}
        break

    yield {"type": "actions", "actions": collected_actions}
    yield {"type": "done", "explanation": "".join(content_parts)}


async def stream_chat_edit(
    db: AsyncSession,
    user: User,
    user_roles: set[str],
    message: str,
    layers: list,
    language: str | None = None,
    history: list[ChatHistoryMessage] | None = None,
) -> AsyncGenerator[dict, None]:
    """Main streaming orchestrator. Yields typed event dicts."""
    try:
        provider, model, _ = await resolve_provider(db)
        system_prompt = build_chat_system_prompt(layers, language=language)

        # Convert history to generic dicts
        history_dicts = None
        if history:
            history_dicts = [{"role": h.role, "content": h.content} for h in history]

        if provider == "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError("Anthropic API key not configured")
            async for event in _stream_anthropic_chat(
                message,
                system_prompt,
                db,
                user,
                user_roles,
                layers,
                model=model,
                history=history_dicts,
            ):
                yield event
        elif provider == "openai_compatible":
            if not settings.openai_api_key:
                raise ValueError("OpenAI-compatible API key not configured")
            from app.persistent_config import OPENAI_BASE_URL

            oai_base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
            async for event in _stream_openai_chat(
                message,
                system_prompt,
                db,
                user,
                user_roles,
                layers,
                model=model,
                base_url=oai_base_url,
                history=history_dicts,
            ):
                yield event
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
    except Exception as e:
        logger.exception("Stream chat error")
        yield {"type": "error", "message": str(e)}
