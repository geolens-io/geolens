"""Community-edition Anthropic AI provider default (Phase 226 D-17).

Split from the former single-module ``defaults.py`` (#836): this sub-module
owns ``DefaultAnthropicProvider``. Import it via the
``app.platform.extensions.defaults`` facade, never from this sub-module.
"""

from __future__ import annotations

from app.platform.ai_tool_payloads import tool_result_content


async def _run_tool_use_blocks(
    content,  # type: ignore[no-untyped-def]
    *,
    tool_executor,
    action_collector,
    collected_actions: list[dict],
    log,
) -> list[dict]:
    """Execute one round's tool_use blocks and build the tool_result payload.

    Split out of ``complete`` in fix(#1778 round 1): wrapping the loop so every
    exit stamps its token usage pushed that function over the complexity gate,
    and this block is self-contained. ``collected_actions`` is appended in
    place, matching what the caller did inline.
    """
    tool_results: list[dict] = []
    for block in content:
        if block.type != "tool_use":
            continue
        log.info("Tool call", tool=block.name, input=block.input)
        result = await tool_executor(block.name, block.input)
        if action_collector:
            action = action_collector(block.name, block.input, result)
            if action:
                collected_actions.append(action)
        tool_results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                # fix(#1778 round 2): fenced, not bare JSON. See
                # tool_result_content for why every result and not a subset.
                "content": tool_result_content(result),
            }
        )
    return tool_results


class DefaultAnthropicProvider:
    """Community-edition default: Anthropic native tool-calling loop (Phase 226 D-17).

    ``complete()`` body is ``_loop_anthropic`` from
    ``app.processing.ai.llm_loop`` (lines 179-277) moved verbatim — same
    request/response shape, same exit conditions, same token accounting.
    ``stream()`` raises NotImplementedError (D-03 — true LLM-token streaming
    is deferred; ``service.py:stream_generate_map`` is "semi-streaming"
    around ``complete()``, not real token streams).

    Class-level ``_client`` cache survives test registry resets (RESEARCH.md
    §Client Cache Lifetime) and is process-scoped in production (the
    accessor calls ``providers.setdefault(...)`` so the instance lives for
    the FastAPI process lifetime).

    Deferred imports (Phase 214 / Phase 222 / Phase 225 discipline): all
    SDK and modules-level imports happen INSIDE ``complete()``, never at
    defaults.py module load.
    """

    _client = None  # class-level cache (AsyncAnthropic | None)

    async def complete(  # type: ignore[no-untyped-def]
        self,
        *,
        model,
        system_prompt,
        user_message,
        tools,
        tool_executor,
        action_collector=None,
        history=None,
        max_rounds=None,
        max_tokens=4096,
        base_url=None,
        temperature=0.5,
    ):
        del temperature  # rejected by Claude 4.6+; kept in signature for callers
        # Deferred imports (Phase 214 discipline)
        import time

        import structlog
        from anthropic import AsyncAnthropic

        from app.core.config import reveal, settings
        from app.processing.ai.constants import (
            MAX_REQUEST_TOKEN_BUDGET,
            MAX_STREAMING_WALL_CLOCK_SECONDS,
            MAX_TOOL_ROUNDS,
        )
        from app.processing.ai.llm_loop import (
            ToolLoopExhaustedError,
            attach_token_usage,
            ToolLoopResult,
            _LLM_TIMEOUT,
            add_tool_cache_control,
            build_history_messages,
        )

        log = structlog.stdlib.get_logger(__name__)

        if max_rounds is None:
            max_rounds = MAX_TOOL_ROUNDS

        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")

        # Lazy class-level client cache
        if DefaultAnthropicProvider._client is None:
            DefaultAnthropicProvider._client = AsyncAnthropic(
                api_key=reveal(settings.anthropic_api_key),
                timeout=_LLM_TIMEOUT,
                max_retries=2,
            )
        client = DefaultAnthropicProvider._client

        messages = build_history_messages(history)
        messages.append({"role": "user", "content": user_message})

        # Enable prompt caching for system prompt and tools
        cached_system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        cached_tools = add_tool_cache_control(tools)

        collected_actions: list[dict] = []
        total_input = 0
        total_output = 0
        # fix(#448): mirror the streaming path's PERF-009 runaway guards — the
        # blocking tool loop (map-gen and friends) previously had neither a
        # wall-clock deadline nor a cumulative token cap, so a pathological
        # tool loop could burn budget until max_rounds.
        deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS

        # fix(#1778 round 1): EVERY exit from this loop carries the tokens it
        # has already spent, not just the exhaustion raises. After round one
        # the provider has been billed, so a later request failure, a tool
        # executor that raises, or a cancellation must still reach the daily
        # quota. One helper decides; nothing here enumerates exception types.
        try:
            for round_num in range(max_rounds):
                if time.monotonic() > deadline:
                    raise ToolLoopExhaustedError(
                        "LLM tool loop exceeded wall-clock budget",
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )
                if total_input + total_output > MAX_REQUEST_TOKEN_BUDGET:
                    raise ToolLoopExhaustedError(
                        "LLM tool loop exceeded request token budget",
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )
                # Anthropic API rejects `tools=[]` with 400 BadRequestError
                # ("tools: must have at least 1 item"). Omit the kwarg entirely
                # for no-tools paths (sql_generator.generate_sql,
                # _retry_parse_map_spec). REVIEW.md CR-01.
                # Claude 4.6+ models reject a non-default `temperature` with a
                # 400; omit it on the Anthropic path (steering is prompt-based).
                create_kwargs: dict[str, object] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": cached_system,
                    "messages": messages,
                }
                if cached_tools:
                    create_kwargs["tools"] = cached_tools
                response = await client.messages.create(**create_kwargs)

                # Track token usage
                if hasattr(response, "usage") and response.usage:
                    total_input += response.usage.input_tokens
                    total_output += response.usage.output_tokens

                log.info(
                    "LLM round",
                    provider="anthropic",
                    round=round_num + 1,
                    stop_reason=response.stop_reason,
                    input_tokens=response.usage.input_tokens if response.usage else 0,
                    output_tokens=response.usage.output_tokens if response.usage else 0,
                )

                if response.stop_reason == "end_turn":
                    text = "".join(
                        block.text for block in response.content if block.type == "text"
                    )
                    return ToolLoopResult(
                        text=text,
                        actions=collected_actions,
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )

                if response.stop_reason == "tool_use":
                    tool_results = await _run_tool_use_blocks(
                        response.content,
                        tool_executor=tool_executor,
                        action_collector=action_collector,
                        collected_actions=collected_actions,
                        log=log,
                    )
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})
                    continue

                # Unexpected stop reason — return whatever text we have
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                return ToolLoopResult(
                    text=text,
                    actions=collected_actions,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            raise ToolLoopExhaustedError(
                "Max tool rounds exceeded without final response",
                input_tokens=total_input,
                output_tokens=total_output,
            )
        except BaseException as exc:
            # BaseException, not Exception: asyncio.CancelledError is the shape
            # a client disconnect and the caller's wait_for timeout both take,
            # and wait_for re-raises TimeoutError *from* it, so the stamp
            # survives on __cause__ for token_usage_from_error to find.
            attach_token_usage(exc, total_input, total_output)
            raise

    # fix(#1590): explicit keyword-only signature instead of a bare
    # **kwargs shim, matching AIProviderExtension.stream exactly.
    async def stream(  # type: ignore[no-untyped-def]
        self,
        *,
        model,
        system_prompt,
        user_message,
        tools,
        tool_executor,
        action_collector=None,
        history=None,
        max_rounds=None,
        max_tokens=4096,
        base_url=None,
        temperature=0.5,
    ):
        raise NotImplementedError(
            "DefaultAnthropicProvider.stream() not implemented in community "
            "edition; use complete() (Phase 226 D-03 — true LLM-token "
            "streaming is deferred to a follow-up phase)."
        )

    # fix(#1590): explicit keyword-only signature instead of a bare
    # **kwargs shim, matching AIProviderExtension.stream_chat_events
    # exactly. `base_url` is accepted (the Protocol declares it) but unused
    # here — Anthropic's streaming client resolves its own endpoint, same as
    # `del temperature` in `complete()` above for a different unused keyword.
    async def stream_chat_events(  # type: ignore[no-untyped-def]
        self,
        *,
        message,
        system_prompt,
        session,
        user,
        user_roles,
        layers,
        model,
        base_url=None,
        history=None,
        port,
        map_id=None,
        tools=None,
        restrict_tables=None,
    ):
        del base_url
        from app.processing.ai.llm_loop import get_anthropic_client
        from app.processing.ai.streaming import _stream_anthropic_chat

        async for event in _stream_anthropic_chat(
            message=message,
            system_prompt=system_prompt,
            session=session,
            user=user,
            user_roles=user_roles,
            layers=layers,
            model=model,
            history=history,
            client=get_anthropic_client(),
            port=port,
            map_id=map_id,
            tools=tools,
            restrict_tables=restrict_tables,
        ):
            yield event

    async def structured_complete(  # type: ignore[no-untyped-def]
        self,
        *,
        model,
        system_prompt,
        user_message,
        response_model,
        base_url=None,
        max_tokens=1024,
        temperature=0.3,
    ):
        del base_url
        import structlog

        from app.processing.ai.llm_loop import get_anthropic_client

        client = get_anthropic_client()
        model_schema = response_model.model_json_schema()
        model_schema.pop("title", None)
        model_schema.pop("description", None)

        tool = {
            "name": "output",
            "description": "Output the structured result",
            "input_schema": model_schema,
        }

        structlog.stdlib.get_logger(__name__).info(
            "AI metadata request",
            provider="anthropic",
            model=model,
            response_model=response_model.__name__,
        )

        # Claude 4.6+ models reject a non-default `temperature` with a 400;
        # omit it on the Anthropic path (steering is prompt-based).
        del temperature
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "output"},
        )

        for block in response.content:
            if block.type == "tool_use":
                return (
                    response_model.model_validate(block.input),
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )

        raise ValueError("No tool_use block in Anthropic response")

    async def resolve_runtime_config(self, db) -> dict[str, object]:  # type: ignore[no-untyped-def]
        from app.core.persistent_config import LLM_MODEL

        model = await LLM_MODEL.get(db)
        return {"base_url": None, "default_model": model}
