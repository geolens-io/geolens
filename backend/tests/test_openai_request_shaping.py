"""OpenAI-compatible chat requests adapt to the parameters a server rejects.

The rejection bodies are the ones Azure OpenAI returned for GeoLens's request
shape.
"""

from types import SimpleNamespace

import httpx2
import openai
import pytest
from pydantic import SecretStr

import app.processing.ai.openai_request as openai_request
import app.processing.ai.streaming as streaming
from app.core.config import settings
from app.processing.ai.openai_request import (
    ResponsesAPIRequiredError,
    create_chat_completion,
)

pytestmark = pytest.mark.anyio

_URL = "http://llm.internal:11434/v1"

MAX_TOKENS_REJECTED = {
    "code": "unsupported_parameter",
    "param": "max_tokens",
    "message": "Unsupported parameter: 'max_tokens' is not supported with this "
    "model. Use 'max_completion_tokens' instead.",
}
MAX_COMPLETION_TOKENS_REJECTED = {
    "code": "unsupported_parameter",
    "param": "max_completion_tokens",
    "message": "Unsupported parameter: 'max_completion_tokens' is not supported "
    "with this model. Use 'max_tokens' instead.",
}
TEMPERATURE_REJECTED = {
    "code": "unsupported_value",
    "param": "temperature",
    "message": "Unsupported value: 'temperature' does not support 0.5 with this "
    "model. Only the default (1) value is supported.",
}
REASONING_UNRECOGNIZED = {
    "code": None,
    "param": None,
    "message": "Unrecognized request argument supplied: reasoning_effort",
}
TOOLS_NEED_NO_REASONING = {
    "code": None,
    "param": "reasoning_effort",
    "message": "Function tools with reasoning_effort are not supported for "
    "eval-gpt-6-luna in /v1/chat/completions. To use function tools, use "
    "/v1/responses or set reasoning_effort to 'none'.",
}
NONE_REJECTED = {
    "code": "unsupported_value",
    "param": "reasoning_effort",
    "message": "Unsupported value: 'reasoning_effort' does not support 'none' "
    "with this model. Supported values are: 'low', 'medium', 'high', and 'xhigh'.",
}
CONTEXT_TOO_LONG = {
    "code": "context_length_exceeded",
    "param": "messages",
    "message": "This model's maximum context length is 128000 tokens.",
}

_TOOLS = [{"type": "function", "function": {"name": "query_data"}}]


def _rejection(body: dict, status: int = 400) -> openai.APIStatusError:
    response = httpx2.Response(status, request=httpx2.Request("POST", _URL))
    error = openai.BadRequestError if status == 400 else openai.InternalServerError
    return error(f"Error code: {status} - {body}", response=response, body=body)


def _response(prompt_tokens: int = 7, completion_tokens: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="ok", tool_calls=None),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


class _Server:
    """A fake ``create`` that rejects each request a rule names."""

    def __init__(self, *rules, result=None):
        self.rules = rules
        self.calls: list[dict] = []
        self.result = result if result is not None else _response()

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        for rule in self.rules:
            body = rule(kwargs)
            if body is not None:
                raise _rejection(body)
        return self.result


def _rejects_max_tokens(kwargs):
    return MAX_TOKENS_REJECTED if "max_tokens" in kwargs else None


def _rejects_max_completion_tokens(kwargs):
    return MAX_COMPLETION_TOKENS_REJECTED if "max_completion_tokens" in kwargs else None


def _rejects_temperature(kwargs):
    return TEMPERATURE_REJECTED if "temperature" in kwargs else None


def _rejects_reasoning_effort(kwargs):
    return REASONING_UNRECOGNIZED if "reasoning_effort" in kwargs else None


def _tools_need_no_reasoning(kwargs):
    if kwargs.get("tools") and kwargs.get("reasoning_effort") != "none":
        return TOOLS_NEED_NO_REASONING
    return None


def _rejects_none(kwargs):
    return NONE_REJECTED if kwargs.get("reasoning_effort") == "none" else None


@pytest.fixture(autouse=True)
def _fresh_shapes(monkeypatch):
    monkeypatch.setattr(openai_request, "_shapes", {})
    monkeypatch.setattr(settings, "openai_reasoning_effort", None)


async def _call(server: _Server, model: str = "m", **extra):
    return await create_chat_completion(
        server.create,
        base_url=_URL,
        model=model,
        max_tokens=4096,
        temperature=0.5,
        messages=[{"role": "user", "content": "hi"}],
        **extra,
    )


async def test_current_request_is_sent_first_and_unchanged():
    server = _Server()
    await _call(server)
    assert len(server.calls) == 1
    assert server.calls[0]["max_tokens"] == 4096
    assert server.calls[0]["temperature"] == 0.5
    assert "reasoning_effort" not in server.calls[0]


async def test_blank_reasoning_effort_setting_is_not_sent(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "")
    server = _Server()
    await _call(server)
    assert "reasoning_effort" not in server.calls[0]


async def test_rejected_max_tokens_is_sent_as_max_completion_tokens():
    server = _Server(_rejects_max_tokens)
    await _call(server)
    retry = server.calls[-1]
    assert len(server.calls) == 2
    assert "max_tokens" not in retry
    assert retry["max_completion_tokens"] == 4096
    assert retry["temperature"] == 0.5


async def test_rejected_max_completion_tokens_switches_back():
    await _call(_Server(_rejects_max_tokens))
    server = _Server(_rejects_max_completion_tokens)
    await _call(server)
    assert [("max_tokens" in c) for c in server.calls] == [False, True]


async def test_rejected_temperature_is_omitted():
    server = _Server(_rejects_temperature)
    await _call(server)
    assert len(server.calls) == 2
    assert "temperature" not in server.calls[-1]


async def test_unrecognized_reasoning_effort_is_omitted(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    server = _Server(_rejects_reasoning_effort)
    await _call(server)
    assert server.calls[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in server.calls[-1]
    assert len(server.calls) == 2


async def test_configured_reasoning_effort_is_sent_from_the_first_request(
    monkeypatch,
):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")
    server = _Server()
    await _call(server)
    assert server.calls == [
        {
            "model": "m",
            "max_tokens": 4096,
            "temperature": 0.5,
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    ]


async def test_function_tools_get_reasoning_effort_none():
    server = _Server(_tools_need_no_reasoning)
    await _call(server, tools=_TOOLS)
    assert "reasoning_effort" not in server.calls[0]
    assert server.calls[-1]["reasoning_effort"] == "none"
    assert len(server.calls) == 2


async def test_model_rejecting_none_needs_the_responses_api():
    server = _Server(
        _rejects_max_tokens,
        _rejects_temperature,
        _tools_need_no_reasoning,
        _rejects_none,
    )
    with pytest.raises(ResponsesAPIRequiredError) as caught:
        await _call(server, model="eval-gpt-6.1-sol", tools=_TOOLS)
    assert "Responses API" in str(caught.value)
    # Sanitized: no model name or provider body reaches the viewer.
    assert "eval-gpt-6.1-sol" not in str(caught.value)
    assert isinstance(caught.value.__cause__, openai.BadRequestError)
    assert len(server.calls) == 4


@pytest.mark.parametrize("tools", [None, _TOOLS])
async def test_configured_none_the_model_rejects_is_dropped(monkeypatch, tools):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    server = _Server(_rejects_none)
    await _call(server, **({"tools": tools} if tools else {}))
    assert server.calls[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in server.calls[-1]
    assert len(server.calls) == 2


async def test_configured_none_on_a_responses_only_model_needs_the_responses_api(
    monkeypatch,
):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    server = _Server(_tools_need_no_reasoning, _rejects_none)
    with pytest.raises(ResponsesAPIRequiredError):
        await _call(server, tools=_TOOLS)
    assert [c.get("reasoning_effort") for c in server.calls] == ["none", None]


async def test_learned_shape_skips_the_rejected_attempts_on_the_next_call():
    rules = (_rejects_max_tokens, _rejects_temperature, _tools_need_no_reasoning)
    first = _Server(*rules)
    await _call(first, model="eval-gpt-6-luna", tools=_TOOLS)
    assert len(first.calls) == 4

    second = _Server(*rules)
    await _call(second, model="eval-gpt-6-luna", tools=_TOOLS)
    assert len(second.calls) == 1
    assert second.calls[0] == {
        "model": "eval-gpt-6-luna",
        "max_completion_tokens": 4096,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": _TOOLS,
        "reasoning_effort": "none",
    }


async def test_learned_shape_is_per_base_url_and_model():
    await _call(_Server(_rejects_max_tokens), model="a")
    other_model = _Server()
    await _call(other_model, model="b")
    assert "max_tokens" in other_model.calls[0]

    other_url = _Server()
    await create_chat_completion(
        other_url.create, base_url="http://other:8000/v1", model="a", max_tokens=1
    )
    assert "max_tokens" in other_url.calls[0]


async def test_tool_only_reasoning_shape_stays_off_requests_without_tools(
    monkeypatch,
):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")
    rules = (_tools_need_no_reasoning,)
    await _call(_Server(*rules), model="eval-gpt-6-luna", tools=_TOOLS)

    without_tools = _Server(*rules)
    await _call(without_tools, model="eval-gpt-6-luna")
    assert without_tools.calls[0]["reasoning_effort"] == "low"


async def test_unsupported_reasoning_parameter_is_dropped_even_with_tools(
    monkeypatch,
):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    body = {
        "code": "unsupported_parameter",
        "param": "reasoning_effort",
        "message": "Unsupported parameter: 'reasoning_effort' is not supported "
        "with this model.",
    }
    server = _Server(lambda kwargs: body if "reasoning_effort" in kwargs else None)
    await _call(server, tools=_TOOLS)
    assert len(server.calls) == 2
    assert "reasoning_effort" not in server.calls[-1]


def test_stream_error_event_carries_a_code_only_for_coded_errors():
    from app.processing.ai.llm_loop import stream_error_event

    assert stream_error_event(ResponsesAPIRequiredError()) == {
        "type": "error",
        "message": str(ResponsesAPIRequiredError()),
        "code": "model_requires_responses_api",
    }
    assert stream_error_event(ValueError("http://llm.internal names the host")) == {
        "type": "error",
        "message": "An unexpected error occurred. Please try again.",
    }


async def test_unrecognized_rejection_is_not_retried():
    server = _Server(lambda _kwargs: CONTEXT_TOO_LONG)
    with pytest.raises(openai.BadRequestError) as caught:
        await _call(server)
    assert caught.value.code == "context_length_exceeded"
    assert len(server.calls) == 1


async def test_server_error_is_not_retried():
    calls: list[dict] = []

    async def create(**kwargs):
        calls.append(kwargs)
        raise _rejection(MAX_TOKENS_REJECTED, status=500)

    with pytest.raises(openai.InternalServerError):
        await create_chat_completion(create, base_url=_URL, model="m", max_tokens=1)
    assert len(calls) == 1


async def test_each_parameter_is_adjusted_at_most_once_per_call():
    server = _Server(_rejects_max_tokens, _rejects_max_completion_tokens)
    with pytest.raises(openai.BadRequestError) as caught:
        await _call(server)
    assert caught.value.param == "max_completion_tokens"
    assert len(server.calls) == 2


async def test_rejected_attempts_bill_nothing_in_the_tool_loop(monkeypatch):
    """The probe's call shape: only the accepted response's usage is counted."""
    from app.core.ai_credentials import bind_openai_credential_base_url
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider
    from app.processing.ai.llm_loop import noop_tool_executor

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_base_url", _URL)
    server = _Server(
        _rejects_max_tokens,
        _rejects_temperature,
        result=_response(prompt_tokens=11, completion_tokens=1),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=server.create))
    )
    monkeypatch.setitem(
        DefaultOpenAICompatibleProvider._clients,
        bind_openai_credential_base_url(None, purpose="chat"),
        client,
    )

    result = await DefaultOpenAICompatibleProvider().complete(
        model="eval-gpt-6.1-sol",
        system_prompt="Connectivity probe.",
        user_message="ping",
        tools=[],
        tool_executor=noop_tool_executor,
        max_rounds=1,
        max_tokens=1,
        temperature=0.0,
    )

    assert (result.input_tokens, result.output_tokens) == (11, 1)
    assert len(server.calls) == 3
    assert server.calls[-1]["max_completion_tokens"] == 1
    assert "temperature" not in server.calls[-1]
    assert "tools" not in server.calls[-1]


async def test_admin_probe_passes_on_a_reasoning_model(monkeypatch):
    from app.core.ai_credentials import bind_openai_credential_base_url
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider
    from app.processing.ai.probe import _probe_chat

    def _rejects_tiny_limit(kwargs):
        if kwargs.get("max_completion_tokens", 0) < 4:
            return {
                "code": None,
                "param": None,
                "message": "Could not finish the message because max_tokens or "
                "model output limit was reached.",
            }
        return None

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_base_url", _URL)
    server = _Server(_rejects_max_tokens, _rejects_temperature, _rejects_tiny_limit)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=server.create))
    )
    monkeypatch.setitem(
        DefaultOpenAICompatibleProvider._clients,
        bind_openai_credential_base_url(None, purpose="chat"),
        client,
    )

    async def resolve_provider(_db):
        return "openai_compatible", "eval-gpt-6-luna", {"base_url": None}

    monkeypatch.setattr("app.processing.ai.llm_loop.resolve_provider", resolve_provider)
    monkeypatch.setattr(
        "app.platform.extensions.get_ai_provider",
        lambda _name: DefaultOpenAICompatibleProvider(),
    )

    check = await _probe_chat(None)

    assert check.ok is True
    assert len(server.calls) == 3


async def test_structured_metadata_request_is_adapted(monkeypatch):
    import json

    import httpx2
    from openai import AsyncOpenAI
    from pydantic import BaseModel

    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider

    class _Answer(BaseModel):
        title: str

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_base_url", _URL)
    sent: list[dict] = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        for rule in (_rejects_max_tokens, _rejects_temperature):
            error = rule(body)
            if error is not None:
                return httpx2.Response(400, json={"error": error})
        return httpx2.Response(
            200,
            json={
                "id": "c",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"title": "Parks"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 4,
                    "total_tokens": 9,
                },
            },
        )

    client = AsyncOpenAI(
        api_key="synthetic-test-key",
        base_url=_URL,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_openai_client", lambda _url: client
    )

    result = await DefaultOpenAICompatibleProvider().structured_complete(
        model="eval-gpt-5.6-luna",
        system_prompt="sys",
        user_message="describe",
        response_model=_Answer,
    )

    assert result == (_Answer(title="Parks"), 5, 4)
    assert len(sent) == 3
    assert sent[-1]["max_completion_tokens"] == 1024
    assert "temperature" not in sent[-1]
    assert sent[-1]["response_format"]["type"] == "json_schema"


class _Stream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


async def _async_return(value):
    return value


async def test_streamed_chat_retries_before_the_first_chunk(monkeypatch):
    recorded: list[tuple[int, int]] = []

    async def record_token_usage(**kwargs):
        recorded.append((kwargs["input_tokens"], kwargs["output_tokens"]))

    async def release_connection(_session):
        return None

    monkeypatch.setattr(
        streaming, "_daily_token_budget", lambda *_a: _async_return((0, 0))
    )
    monkeypatch.setattr(streaming, "record_token_usage", record_token_usage)
    monkeypatch.setattr(streaming, "release_connection", release_connection)

    chunks = [
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hello", tool_calls=None),
                    finish_reason="stop",
                )
            ],
        ),
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=2), choices=[]
        ),
    ]
    server = _Server(
        _rejects_max_tokens,
        _rejects_temperature,
        _tools_need_no_reasoning,
        result=_Stream(chunks),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=server.create))
    )

    events = [
        event
        async for event in streaming._stream_openai_chat(
            "hi",
            "sys",
            SimpleNamespace(),
            SimpleNamespace(id="user-1"),
            set(),
            [],
            model="eval-gpt-6-luna",
            client=client,
            base_url=_URL,
            port=SimpleNamespace(),
        )
    ]

    assert len(server.calls) == 4
    final = server.calls[-1]
    assert final["stream"] is True
    assert final["stream_options"] == {"include_usage": True}
    assert final["max_completion_tokens"] == 4096
    assert final["reasoning_effort"] == "none"
    assert "temperature" not in final
    assert recorded == [(20, 2)]
    assert {"type": "token", "text": "Hello"} in events
