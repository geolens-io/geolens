"""Community-edition OpenAI-compatible AI provider defaults.

Split from the former single-module ``defaults.py`` (#836): this sub-module
owns ``DefaultOpenAICompatibleProvider`` (Phase 226 D-17) and
``DefaultOpenAIEmbeddingProvider`` (Phase 231 D-08). Import them via the
``app.platform.extensions.defaults`` facade, never from this sub-module.
"""

from __future__ import annotations

from app.platform.ai_tool_payloads import model_safe_tool_result


class DefaultOpenAICompatibleProvider:
    """Community-edition default: OpenAI-compatible tool-calling loop (Phase 226 D-17).

    ``complete()`` body is ``_loop_openai`` from
    ``app.processing.ai.llm_loop`` (lines 280-404) moved verbatim, with
    Anthropic→OpenAI tool format conversion applied INTERNALLY at the top
    of the method (D-08 — callers pass canonical Anthropic shape; the
    provider converts on the way in).

    Class-level ``_clients`` dict cache keyed by ``base_url`` matches
    today's module-level singleton at llm_loop.py:29.

    Deferred imports (Phase 214 / Phase 222 / Phase 225 discipline): all
    SDK and modules-level imports happen INSIDE ``complete()``, never at
    defaults.py module load.
    """

    _clients: dict = {}  # class-level cache: base_url -> AsyncOpenAI

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
        # Deferred imports (Phase 214 discipline)
        import json
        import time

        import structlog
        from openai import AsyncOpenAI

        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.config import reveal, settings
        from app.processing.ai.constants import (
            MAX_REQUEST_TOKEN_BUDGET,
            MAX_STREAMING_WALL_CLOCK_SECONDS,
            MAX_TOOL_ROUNDS,
        )
        from app.processing.ai.llm_loop import (
            ToolLoopExhaustedError,
            ToolLoopResult,
            _LLM_TIMEOUT,
            build_history_messages,
        )
        from app.processing.ai.tool_call_parser import parse_xml_tool_calls

        log = structlog.stdlib.get_logger(__name__)

        if max_rounds is None:
            max_rounds = MAX_TOOL_ROUNDS

        if not settings.openai_api_key:
            raise ValueError("OpenAI-compatible API key not configured")

        # D-08: Anthropic-shape tools -> OpenAI function-format tools.
        # Mirrors tools.py:313-323 algorithmic conversion.
        tools_openai = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

        effective_base_url = bind_openai_credential_base_url(
            base_url or settings.openai_base_url,
            purpose="chat",
        )

        # Lazy class-level keyed-client cache
        if effective_base_url not in DefaultOpenAICompatibleProvider._clients:
            DefaultOpenAICompatibleProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=_LLM_TIMEOUT,
                max_retries=2,
            )
        client = DefaultOpenAICompatibleProvider._clients[effective_base_url]

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(build_history_messages(history))
        messages.append({"role": "user", "content": user_message})

        collected_actions: list[dict] = []
        total_input = 0
        total_output = 0
        # fix(#448): same PERF-009 runaway guards as the Anthropic complete()
        # loop above — see that comment.
        deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS

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
            # OpenAI API rejects `tools=[]` similarly. Omit when empty so
            # no-tools paths (sql_generator.generate_sql, _retry_parse_map_spec)
            # work for OpenAI-compatible providers too. REVIEW.md CR-01.
            create_kwargs: dict[str, object] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if tools_openai:
                create_kwargs["tools"] = tools_openai
            response = await client.chat.completions.create(**create_kwargs)

            choice = response.choices[0]

            # Track token usage
            if response.usage:
                total_input += response.usage.prompt_tokens
                total_output += response.usage.completion_tokens

            log.info(
                "LLM round",
                provider="openai",
                round=round_num + 1,
                finish_reason=choice.finish_reason,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            )

            if choice.finish_reason == "stop":
                text = choice.message.content or ""
                parsed_calls, cleaned_text = parse_xml_tool_calls(text)

                if parsed_calls:
                    # Execute parsed XML tool calls
                    for fn_name, fn_args in parsed_calls:
                        log.info("Parsed XML tool call", tool=fn_name, input=fn_args)
                        result = await tool_executor(fn_name, fn_args)
                        if action_collector:
                            action = action_collector(fn_name, fn_args, result)
                            if action:
                                collected_actions.append(action)

                    return ToolLoopResult(
                        text=cleaned_text,
                        actions=collected_actions,
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )

                return ToolLoopResult(
                    text=text,
                    actions=collected_actions,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            if choice.finish_reason == "tool_calls":
                messages.append(choice.message)

                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        try:
                            fn_args, _ = json.JSONDecoder().raw_decode(
                                tool_call.function.arguments
                            )
                        except (json.JSONDecodeError, ValueError):
                            log.warning(
                                "Unparseable tool arguments",
                                tool=fn_name,
                                args=tool_call.function.arguments,
                            )
                            continue
                    log.info("Tool call", tool=fn_name, input=fn_args)

                    result = await tool_executor(fn_name, fn_args)

                    if action_collector:
                        action = action_collector(fn_name, fn_args, result)
                        if action:
                            collected_actions.append(action)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            # default=str: see the Anthropic tool_result path above.
                            "content": json.dumps(
                                model_safe_tool_result(result), default=str
                            ),
                        }
                    )
                continue

            # Unexpected finish reason
            return ToolLoopResult(
                text=choice.message.content or "",
                actions=collected_actions,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        raise ToolLoopExhaustedError(
            "Max tool rounds exceeded without final response",
            input_tokens=total_input,
            output_tokens=total_output,
        )

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
            "DefaultOpenAICompatibleProvider.stream() not implemented in "
            "community edition; use complete() (Phase 226 D-03)."
        )

    # fix(#1590): explicit keyword-only signature instead of a bare
    # **kwargs shim, matching AIProviderExtension.stream_chat_events
    # exactly.
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
        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.config import settings
        from app.processing.ai.llm_loop import get_openai_client
        from app.processing.ai.streaming import _stream_openai_chat

        resolved_base_url = bind_openai_credential_base_url(
            base_url or settings.openai_base_url,
            purpose="chat",
        )
        async for event in _stream_openai_chat(
            message=message,
            system_prompt=system_prompt,
            session=session,
            user=user,
            user_roles=user_roles,
            layers=layers,
            model=model,
            history=history,
            client=get_openai_client(resolved_base_url),
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
        import structlog

        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.config import settings
        from app.processing.ai.llm_loop import get_openai_client

        effective_base_url = bind_openai_credential_base_url(
            base_url or settings.openai_base_url,
            purpose="chat",
        )
        client = get_openai_client(effective_base_url)

        structlog.stdlib.get_logger(__name__).info(
            "AI metadata request",
            provider="openai",
            model=model,
            response_model=response_model.__name__,
        )

        response = await client.beta.chat.completions.parse(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format=response_model,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI returned no parsed response")
        usage = response.usage
        return (
            parsed,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )

    async def resolve_runtime_config(self, db) -> dict[str, object]:  # type: ignore[no-untyped-def]
        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.persistent_config import LLM_MODEL, OPENAI_BASE_URL

        model = await LLM_MODEL.get(db)
        base_url = bind_openai_credential_base_url(
            await OPENAI_BASE_URL.get(db),
            purpose="chat",
        )
        return {"base_url": base_url, "default_model": model}


class DefaultOpenAIEmbeddingProvider:
    """Community-edition default: OpenAI-compatible embeddings (Phase 231 D-08).

    Replaces helpers.py:8 (``from openai import OpenAI``) with a Protocol-typed
    provider class. ``embed()`` body absorbs:
      - helpers.py:100-109 ``build_openai_client()`` — AsyncOpenAI client + httpx.Timeout
      - helpers.py:90-97 ``resolve_embedding_base_url()`` — folded into ``resolve_runtime_config()``
      - service.py:70-110 retry/backoff loop (D-22, max_attempts=2, backoff=2.0+jitter)

    Class-level ``_clients`` dict cache keyed by ``base_url`` mirrors
    ``DefaultOpenAICompatibleProvider._clients`` (defaults.py:625) verbatim.
    Lifetime is process-scoped (provider instance is registered as a
    singleton in ``_extensions["embedding_providers"]["openai_compatible"]``).

    ``AsyncOpenAI`` replaces today's sync ``OpenAI`` + ``asyncio.to_thread``
    (D-25). The eliminated to_thread overhead matches Phase 226's
    ``DefaultOpenAICompatibleProvider`` which already uses AsyncOpenAI for
    the chat-completions path.

    Deferred imports (Phase 214 / Phase 222 / Phase 225 / Phase 226 discipline):
    all SDK and modules-level imports happen INSIDE ``embed()`` /
    ``resolve_runtime_config()``, never at defaults.py module load.
    """

    _clients: dict = {}  # class-level cache: base_url -> AsyncOpenAI

    async def embed(
        self,
        *,
        texts: list[str],
        model: str,
        dimensions: int | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> list[list[float]]:
        # Deferred imports (Phase 214 discipline)
        import asyncio
        import random

        import httpx
        import structlog
        from openai import AsyncOpenAI

        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.config import reveal, settings
        from app.processing.embeddings.service import EmbeddingUnavailableError

        log = structlog.stdlib.get_logger(__name__)

        if not settings.openai_api_key:
            raise EmbeddingUnavailableError(
                "Embedding generation requires an OpenAI-compatible API key."
            )

        effective_base_url = bind_openai_credential_base_url(
            base_url or settings.embedding_base_url or settings.openai_base_url,
            purpose="embedding",
        )

        # Lazy class-level keyed-client cache (mirrors defaults.py:684-692)
        if effective_base_url not in DefaultOpenAIEmbeddingProvider._clients:
            DefaultOpenAIEmbeddingProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                max_retries=2,
            )
        client = DefaultOpenAIEmbeddingProvider._clients[effective_base_url]

        # Retry loop moved from service.py:70-110 (D-22) — max 2 attempts,
        # 2.0s backoff with up to 30% jitter, asyncio.wait_for per call.
        max_attempts = 2
        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                # RESEARCH.md Pitfall 3: dimensions=None must NOT be passed
                # to the SDK — build kwargs conditionally.
                kwargs: dict[str, object] = {"model": model, "input": texts}
                if dimensions is not None:
                    kwargs["dimensions"] = dimensions
                response = await asyncio.wait_for(
                    client.embeddings.create(**kwargs),
                    timeout=timeout if timeout is not None else 130.0,
                )
                return [item.embedding for item in response.data]
            except Exception as exc:  # broad: network/API/timeout
                last_exc = exc
                if attempt < max_attempts:
                    log.debug(
                        "Embedding API call failed, retrying",
                        attempt=attempt,
                        backoff=backoff,
                        error=str(exc),
                        model=model,
                    )
                    await asyncio.sleep(backoff * (1 + random.random() * 0.3))
                else:
                    log.error(
                        "Embedding API call failed after retries",
                        error=str(exc),
                        model=model,
                        attempts=max_attempts,
                        exc_info=True,
                    )
        raise EmbeddingUnavailableError(
            f"Embedding API call failed: {last_exc}"
        ) from last_exc

    async def resolve_runtime_config(self, db) -> dict[str, object]:  # type: ignore[no-untyped-def]
        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.persistent_config import (
            EMBEDDING_BASE_URL,
            EMBEDDING_DIMS,
            EMBEDDING_MODEL,
            OPENAI_BASE_URL,
        )

        # Fallback chain mirrors helpers.py:90-97 byte-for-byte (D-04 / D-24):
        # EMBEDDING_BASE_URL -> OPENAI_BASE_URL -> hardcoded default
        embedding_url = await EMBEDDING_BASE_URL.get(db)
        base_url = bind_openai_credential_base_url(
            embedding_url or await OPENAI_BASE_URL.get(db) or None,
            purpose="embedding",
        )
        return {
            "base_url": base_url,
            "default_model": await EMBEDDING_MODEL.get(db),
            "default_dims": await EMBEDDING_DIMS.get(db),
        }
