"""Community-edition OpenAI-compatible AI provider defaults.

Import ``DefaultOpenAICompatibleProvider`` and
``DefaultOpenAIEmbeddingProvider`` via the ``app.platform.extensions.defaults``
facade, never from this sub-module.
"""

from __future__ import annotations

from collections.abc import Mapping


class DefaultOpenAICompatibleProvider:
    """Community-edition default: OpenAI-compatible tool-calling loop.

    Callers pass tools in the canonical Anthropic shape;
    ``open_conversation`` converts them.

    All SDK and app-module imports happen INSIDE the methods, never at
    module load.
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
        import json
        import time

        import structlog
        from openai import AsyncOpenAI, Timeout

        from app.core.ai_credentials import bind_openai_credential_base_url
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
            _LLM_CONNECT_TIMEOUT_SECONDS,
            _LLM_TIMEOUT_SECONDS,
        )
        from app.processing.ai.openai_conversation import (
            ResponsesError,
            open_conversation,
        )
        from app.processing.ai.tool_call_parser import parse_xml_tool_calls

        log = structlog.stdlib.get_logger(__name__)

        if max_rounds is None:
            max_rounds = MAX_TOOL_ROUNDS

        if not settings.openai_api_key:
            raise ValueError("OpenAI-compatible API key not configured")

        effective_base_url = bind_openai_credential_base_url(
            base_url or settings.openai_base_url,
            purpose="chat",
        )

        if effective_base_url not in DefaultOpenAICompatibleProvider._clients:
            DefaultOpenAICompatibleProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=Timeout(
                    _LLM_TIMEOUT_SECONDS, connect=_LLM_CONNECT_TIMEOUT_SECONDS
                ),
                max_retries=2,
            )
        client = DefaultOpenAICompatibleProvider._clients[effective_base_url]

        conversation = open_conversation(
            client,
            base_url=effective_base_url,
            model=model,
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        collected_actions: list[dict] = []
        total_input = 0
        total_output = 0
        # Same runaway guards as the Anthropic complete() loop.
        deadline = time.monotonic() + MAX_STREAMING_WALL_CLOCK_SECONDS

        # EVERY exit from this loop carries the tokens already spent: after
        # round one the provider has billed, so a later failure must still
        # reach the daily quota.
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
                try:
                    round_ = await conversation.complete()
                except ResponsesError as exc:
                    total_input += exc.input_tokens
                    total_output += exc.output_tokens
                    raise
                total_input += round_.input_tokens
                total_output += round_.output_tokens

                log.info(
                    "LLM round",
                    provider="openai",
                    round=round_num + 1,
                    finish_reason=round_.finish_reason,
                    input_tokens=round_.input_tokens,
                    output_tokens=round_.output_tokens,
                )

                if round_.finish_reason == "stop":
                    text = round_.text
                    parsed_calls, cleaned_text = parse_xml_tool_calls(text)

                    if parsed_calls:
                        for fn_name, fn_args in parsed_calls:
                            log.info(
                                "Parsed XML tool call", tool=fn_name, input=fn_args
                            )
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

                if round_.finish_reason == "tool_calls":
                    results = []
                    for tool_call in round_.tool_calls:
                        fn_name = tool_call.name
                        try:
                            fn_args = json.loads(tool_call.arguments)
                        except json.JSONDecodeError:
                            try:
                                fn_args, _ = json.JSONDecoder().raw_decode(
                                    tool_call.arguments
                                )
                            except (json.JSONDecodeError, ValueError):
                                log.warning(
                                    "Unparseable tool arguments",
                                    tool=fn_name,
                                    args=tool_call.arguments,
                                )
                                continue
                        log.info("Tool call", tool=fn_name, input=fn_args)

                        result = await tool_executor(fn_name, fn_args)

                        if action_collector:
                            action = action_collector(fn_name, fn_args, result)
                            if action:
                                collected_actions.append(action)

                        results.append((tool_call, result))
                    conversation.add_tool_results(round_, results)
                    continue

                return ToolLoopResult(
                    text=round_.text,
                    truncated=True,
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
            # BaseException, not Exception: a client disconnect and the
            # caller's wait_for timeout both surface as asyncio.CancelledError,
            # and wait_for re-raises TimeoutError *from* it, so the stamp
            # survives on __cause__ for token_usage_from_error to find.
            attach_token_usage(exc, total_input, total_output)
            raise

    # Explicit keyword-only signature matching AIProviderExtension.stream.
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
            "community edition; use complete()."
        )

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
            base_url=resolved_base_url,
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
        from app.processing.ai.openai_conversation import structured_completion

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

        return await structured_completion(
            client,
            base_url=effective_base_url,
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=response_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def resolve_runtime_config(  # type: ignore[no-untyped-def]
        self, db, settings: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        from app.core.ai_credentials import bind_openai_credential_base_url
        from app.core.persistent_config import OPENAI_BASE_URL, llm_model_default

        # The default without the admin override, which callers apply.
        model = llm_model_default("openai_compatible")
        configured = (
            settings[OPENAI_BASE_URL.key]
            if settings is not None and OPENAI_BASE_URL.key in settings
            else await OPENAI_BASE_URL.get(db)
        )
        base_url = bind_openai_credential_base_url(configured, purpose="chat")
        return {"base_url": base_url, "default_model": model}


class DefaultOpenAIEmbeddingProvider:
    """Community-edition default: OpenAI-compatible embeddings.

    Class-level ``_clients`` dict cache keyed by ``base_url``, process-scoped.

    All SDK and app-module imports happen INSIDE ``embed()`` /
    ``resolve_runtime_config()``, never at module load.
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
        import asyncio
        import random

        import structlog
        from openai import AsyncOpenAI, Timeout

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

        if effective_base_url not in DefaultOpenAIEmbeddingProvider._clients:
            DefaultOpenAIEmbeddingProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=Timeout(60.0, connect=10.0),
                max_retries=2,
            )
        client = DefaultOpenAIEmbeddingProvider._clients[effective_base_url]

        max_attempts = 2
        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                # dimensions=None must NOT be passed to the SDK.
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

        # Fallback chain: EMBEDDING_BASE_URL -> OPENAI_BASE_URL -> default.
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
