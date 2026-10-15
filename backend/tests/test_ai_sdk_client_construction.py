"""The provider SDK clients build for real, with the granular call timeout.

The other AI tests replace the SDK clients, so they cannot see a constructor
that rejects its arguments. These tests build each cached client and stop at
the first network call, or answer it from an httpx2 mock so the SDK's own
response parsing runs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.platform.extensions.defaults import (
    DefaultAnthropicProvider,
    DefaultOpenAICompatibleProvider,
    DefaultOpenAIEmbeddingProvider,
)
from app.processing.ai.llm_loop import (
    get_anthropic_client,
    get_openai_client,
    noop_tool_executor,
)

_BASE_URL = "http://llm.internal:11434/v1"


class _StopBeforeNetwork(Exception):
    pass


async def _refuse(*args, **kwargs):
    raise _StopBeforeNetwork


@pytest.fixture
def ai_keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_base_url", _BASE_URL)
    monkeypatch.setattr(settings, "embedding_base_url", _BASE_URL)

    def clear() -> None:
        DefaultAnthropicProvider._client = None
        DefaultOpenAICompatibleProvider._clients.clear()
        DefaultOpenAIEmbeddingProvider._clients.clear()

    clear()
    yield
    clear()


def _assert_timeout(client, *, read: float, connect: float) -> None:
    assert client.timeout.read == read
    assert client.timeout.connect == connect


def test_shared_getters_build_clients(ai_keys: None) -> None:
    _assert_timeout(get_anthropic_client(), read=120.0, connect=10.0)
    _assert_timeout(get_openai_client(_BASE_URL), read=120.0, connect=10.0)


async def test_anthropic_tool_loop_builds_its_client(
    ai_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from anthropic.resources.messages import AsyncMessages

    monkeypatch.setattr(AsyncMessages, "create", _refuse)
    with pytest.raises(_StopBeforeNetwork):
        await DefaultAnthropicProvider().complete(
            model="claude-test",
            system_prompt="s",
            user_message="u",
            tools=[],
            tool_executor=noop_tool_executor,
            max_rounds=1,
        )
    _assert_timeout(DefaultAnthropicProvider._client, read=120.0, connect=10.0)


async def test_openai_tool_loop_builds_its_client(
    ai_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openai.resources.chat.completions import AsyncCompletions

    monkeypatch.setattr(AsyncCompletions, "create", _refuse)
    with pytest.raises(_StopBeforeNetwork):
        await DefaultOpenAICompatibleProvider().complete(
            model="gpt-test",
            system_prompt="s",
            user_message="u",
            tools=[],
            tool_executor=noop_tool_executor,
            max_rounds=1,
            base_url=_BASE_URL,
        )
    (client,) = DefaultOpenAICompatibleProvider._clients.values()
    _assert_timeout(client, read=120.0, connect=10.0)


async def test_embedding_provider_builds_its_client(
    ai_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openai.resources.embeddings import AsyncEmbeddings

    async def one_vector(*args, **kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.5])])

    monkeypatch.setattr(AsyncEmbeddings, "create", one_vector)
    vectors = await DefaultOpenAIEmbeddingProvider().embed(
        texts=["t"], model="embed-test", base_url=_BASE_URL
    )
    assert vectors == [[0.5]]
    (client,) = DefaultOpenAIEmbeddingProvider._clients.values()
    _assert_timeout(client, read=60.0, connect=10.0)


# --- Requests through the real SDK HTTP stack --------------------------------


def _sse(*events: tuple[str | None, dict | str]) -> bytes:
    lines = []
    for name, data in events:
        if name:
            lines.append(f"event: {name}")
        lines.append(f"data: {data if isinstance(data, str) else json.dumps(data)}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def _mocked(client, handler):
    return client.with_options(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )


async def test_anthropic_stream_parses_through_the_sdk(ai_keys: None) -> None:
    body = _sse(
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 2},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    client = _mocked(
        get_anthropic_client(),
        lambda request: httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=body
        ),
    )

    async with client.messages.stream(
        model="claude-test",
        max_tokens=16,
        messages=[{"role": "user", "content": "hi"}],
    ) as stream:
        deltas = [
            event.delta.text
            async for event in stream
            if event.type == "content_block_delta"
        ]
        final = await stream.get_final_message()

    assert deltas == ["hello"]
    assert final.stop_reason == "end_turn"
    assert (final.usage.input_tokens, final.usage.output_tokens) == (5, 2)


async def test_openai_rejection_is_parsed_and_the_request_adapts(
    ai_keys: None,
) -> None:
    from app.processing.ai.openai_request import create_chat_completion

    sent: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        if "max_tokens" in sent[-1]:
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "code": "unsupported_parameter",
                        "param": "max_tokens",
                        "message": "Unsupported parameter: 'max_tokens' is not "
                        "supported with this model.",
                    }
                },
            )
        chunks = [
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "gpt-test",
                "choices": [
                    {"index": 0, "delta": {"content": "hello"}, "finish_reason": None}
                ],
            },
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "gpt-test",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "gpt-test",
                "choices": [],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            },
        ]
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(*((None, chunk) for chunk in chunks), (None, "[DONE]")),
        )

    client = _mocked(get_openai_client(_BASE_URL), handler).with_options(max_retries=0)
    stream = await create_chat_completion(
        client.chat.completions.create,
        base_url=_BASE_URL,
        model="gpt-test",
        max_tokens=16,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    chunks = [chunk async for chunk in stream]

    assert [
        ("max_tokens" in body, "max_completion_tokens" in body) for body in sent
    ] == [
        (True, False),
        (False, True),
    ]
    assert chunks[0].choices[0].delta.content == "hello"
    assert chunks[-1].usage.completion_tokens == 2
