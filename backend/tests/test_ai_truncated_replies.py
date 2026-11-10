"""A reply that stopped early is never acted on.

A round cut off by the token limit or a content filter can still hold a
complete-looking XML tool call, ``<map_spec>`` block or SQL statement. Tools,
maps and queries run only from a finished round, on both OpenAI APIs.
"""

import uuid
from types import SimpleNamespace

import pytest
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseUsage,
)
from pydantic import SecretStr

import app.processing.ai.openai_request as openai_request
import app.processing.ai.service as ai_service
import app.processing.ai.sql_generator as sql_generator
import app.processing.ai.streaming as streaming
from app.core.ai_credentials import bind_openai_credential_base_url
from app.core.config import settings
from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider
from app.processing.ai.llm_loop import ToolLoopResult, UserFacingAIError

pytestmark = pytest.mark.anyio

_URL = "http://llm.internal:11434/v1"
_FUNCTION = (
    "<function=query_data><parameter=question>how many parks</parameter></function>"
)
_XML_CALL = f"Let me query that. <tool_call>{_FUNCTION}</tool_call>"
# Every wrapper the parser accepts, including an unclosed one.
_XML_SPELLINGS = [
    _FUNCTION,
    f"<tool_call>{_FUNCTION}</tool_call>",
    f"<tool-call>{_FUNCTION}</tool-call>",
    f"<|tool_call|>{_FUNCTION}<|/tool_call|>",
    f"<tool_call>{_FUNCTION}",
]
_TOOLS = [
    {
        "name": "query_data",
        "description": "Run SQL",
        "input_schema": {"type": "object", "properties": {}},
    }
]


@pytest.fixture(autouse=True)
def _openai(monkeypatch):
    monkeypatch.setattr(openai_request, "_shapes", {})
    monkeypatch.setattr(settings, "openai_reasoning_effort", None)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_base_url", _URL)


class _Events:
    def __init__(self, events):
        self._events = iter(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None


async def _async_return(value):
    return value


def _chat_chunks(text, finish_reason):
    return [
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=text, tool_calls=None),
                    finish_reason=finish_reason,
                )
            ],
        )
    ]


def _responses_events(text, status, reason=None, call_status=None):
    message = ResponseOutputMessage.model_validate(
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
    )
    output = [message]
    if call_status is not None:
        output.append(
            ResponseFunctionToolCall(
                type="function_call",
                id="fc_1",
                call_id="call_1",
                name="query_data",
                arguments='{"question": "how many parks"}',
                status=call_status,
            )
        )
    response = Response.model_construct(
        output=output,
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        usage=ResponseUsage.model_construct(input_tokens=5, output_tokens=5),
    )
    final = "response.completed" if status == "completed" else "response.incomplete"
    return [
        SimpleNamespace(type="response.output_text.delta", delta=text),
        SimpleNamespace(type=final, response=response),
    ]


async def _stream(monkeypatch, style, events):
    monkeypatch.setattr(settings, "openai_api_style", style)
    executed: list = []

    async def record_token_usage(**_kwargs):
        return None

    async def release_connection(_session):
        return None

    async def execute_and_yield_tools(calls, *args, **kwargs):
        executed.extend(calls)
        yield {"type": "tool_result", "tool": "query_data"}

    monkeypatch.setattr(
        streaming, "_daily_token_budget", lambda *_a: _async_return((0, 0))
    )
    monkeypatch.setattr(streaming, "record_token_usage", record_token_usage)
    monkeypatch.setattr(streaming, "release_connection", release_connection)
    monkeypatch.setattr(streaming, "_execute_and_yield_tools", execute_and_yield_tools)

    async def create(**kwargs):
        return _Events(events)

    api = SimpleNamespace(create=create)
    client = SimpleNamespace(chat=SimpleNamespace(completions=api), responses=api)
    out = [
        event
        async for event in streaming._stream_openai_chat(
            "how many parks?",
            "sys",
            SimpleNamespace(),
            SimpleNamespace(id="user-1"),
            set(),
            [],
            model="m",
            client=client,
            base_url=_URL,
            port=SimpleNamespace(),
            tools=_TOOLS,
        )
    ]
    return executed, out


_TRUNCATED_ROUNDS = {
    "chat-length": ("chat_completions", lambda text: _chat_chunks(text, "length")),
    "chat-content_filter": (
        "chat_completions",
        lambda text: _chat_chunks(text, "content_filter"),
    ),
    "responses-max_output_tokens": (
        "responses",
        lambda text: _responses_events(text, "incomplete", "max_output_tokens"),
    ),
    "responses-content_filter": (
        "responses",
        lambda text: _responses_events(text, "incomplete", "content_filter"),
    ),
    "responses-incomplete-no-details": (
        "responses",
        lambda text: _responses_events(text, "incomplete"),
    ),
    "responses-completed-call-in_progress": (
        "responses",
        lambda text: _responses_events(text, "completed", call_status="in_progress"),
    ),
    "responses-completed-call-incomplete": (
        "responses",
        lambda text: _responses_events(text, "completed", call_status="incomplete"),
    ),
}


@pytest.mark.parametrize("spelling", _XML_SPELLINGS)
@pytest.mark.parametrize("round_kind", list(_TRUNCATED_ROUNDS))
async def test_a_streamed_xml_call_in_a_truncated_round_never_runs(
    monkeypatch, round_kind, spelling
):
    style, events = _TRUNCATED_ROUNDS[round_kind]
    executed, out = await _stream(monkeypatch, style, events(f"Querying. {spelling}"))

    assert executed == []
    assert out[-1]["type"] == "done"


@pytest.mark.parametrize(
    ("status", "call_status"),
    [
        ("completed", "in_progress"),
        ("completed", "incomplete"),
        ("incomplete", "completed"),
    ],
)
async def test_a_streamed_native_call_in_a_truncated_round_never_runs(
    monkeypatch, status, call_status
):
    events = _responses_events("", status, "max_output_tokens", call_status)

    executed, out = await _stream(monkeypatch, "responses", events)

    assert executed == []
    assert out[-1]["type"] == "done"


@pytest.mark.parametrize("spelling", _XML_SPELLINGS)
@pytest.mark.parametrize(
    ("style", "events"),
    [
        ("chat_completions", lambda text: _chat_chunks(text, "stop")),
        ("responses", lambda text: _responses_events(text, "completed")),
    ],
)
async def test_a_streamed_xml_call_in_a_finished_round_still_runs(
    monkeypatch, style, events, spelling
):
    executed, _ = await _stream(monkeypatch, style, events(spelling))

    assert executed == [("query_data", {"question": "how many parks"})]


async def test_the_tool_loop_flags_a_truncated_reply_and_runs_nothing(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_style", "chat_completions")

    async def create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content=_XML_CALL, tool_calls=None),
                )
            ],
            usage=None,
        )

    monkeypatch.setitem(
        DefaultOpenAICompatibleProvider._clients,
        bind_openai_credential_base_url(None, purpose="chat"),
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    executed: list = []

    async def tool_executor(name, args):
        executed.append(name)
        return {}

    result = await DefaultOpenAICompatibleProvider().complete(
        model="m",
        system_prompt="sys",
        user_message="hi",
        tools=_TOOLS,
        tool_executor=tool_executor,
    )

    assert result.truncated is True
    assert executed == []


_SPEC = '<map_spec>{"name": "Parks", "layers": []}</map_spec>'


@pytest.fixture
def _map_generation(monkeypatch):
    """Map generation whose provider returns a complete spec, cut off after it."""
    parsed: list[str] = []

    async def complete(**_kwargs):
        return ToolLoopResult(text=_SPEC + " Extra", truncated=True)

    def parse_map_spec(text):
        parsed.append(text)
        return {"error": "stop here"}

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(
        ai_service, "resolve_provider", lambda _s: _async_return(("x", "m", {}))
    )
    monkeypatch.setattr(
        ai_service, "get_ai_provider", lambda _p: SimpleNamespace(complete=complete)
    )
    monkeypatch.setattr(ai_service, "_get_available_basemaps", nothing)
    monkeypatch.setattr(
        ai_service, "_should_send_sample_values", lambda _s: _async_return(False)
    )
    monkeypatch.setattr(ai_service, "release_connection", nothing)
    monkeypatch.setattr(ai_service, "record_token_usage", nothing)
    monkeypatch.setattr(ai_service, "_parse_map_spec", parse_map_spec)
    return parsed


def _user():
    return SimpleNamespace(id=uuid.uuid4())


async def test_map_generation_refuses_a_truncated_spec(_map_generation):
    with pytest.raises(UserFacingAIError, match="cut off"):
        await ai_service.generate_map_from_prompt(
            SimpleNamespace(), _user(), set(), "parks", port=SimpleNamespace()
        )
    assert _map_generation == []


async def test_streamed_map_generation_refuses_a_truncated_spec(_map_generation):
    events = [
        event
        async for event in ai_service.stream_generate_map(
            SimpleNamespace(), _user(), set(), "parks", port=SimpleNamespace()
        )
    ]

    assert events[-1]["type"] == "error"
    assert "cut off" in events[-1]["message"]
    assert _map_generation == []


async def test_sql_generation_refuses_a_truncated_query(monkeypatch):
    class _Setting:
        async def get(self, _db):
            return "openai_compatible"

        async def for_provider(self, *_a):
            return "m"

    async def complete(**_kwargs):
        # A cut-off "LIMIT 10" still parses as a different query.
        return ToolLoopResult(text="SELECT * FROM parks LIMIT 1", truncated=True)

    async def nothing(*_a, **_k):
        return None

    provider = SimpleNamespace(
        resolve_runtime_config=lambda _db: _async_return({}), complete=complete
    )
    monkeypatch.setattr(sql_generator, "LLM_PROVIDER", _Setting())
    monkeypatch.setattr(sql_generator, "LLM_MODEL_LIGHT", _Setting())
    monkeypatch.setattr(sql_generator, "get_ai_provider", lambda _p: provider)
    monkeypatch.setattr(sql_generator, "release_connection", nothing)

    sql = await sql_generator.generate_sql(SimpleNamespace(), "how many?", "-- ddl")

    assert sql.startswith("-- ERROR:")


def _claude_client(text, stop_reason):
    """A real Anthropic SDK client answering every request with one message."""
    import httpx2
    from anthropic import AsyncAnthropic

    body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }
    return AsyncAnthropic(
        api_key="synthetic-test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(200, json=body)
            )
        ),
    )


@pytest.fixture
def _claude(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("synthetic-test-key"))

    def install(text, stop_reason):
        client = _claude_client(text, stop_reason)
        monkeypatch.setattr(
            "app.processing.ai.llm_loop.get_anthropic_client", lambda: client
        )

    return install


@pytest.mark.parametrize(
    ("stop_reason", "truncated"),
    [
        ("max_tokens", True),
        ("refusal", True),
        ("model_context_window_exceeded", True),
        ("stop_sequence", False),
        ("pause_turn", False),
        ("end_turn", False),
    ],
)
async def test_a_claude_reply_is_flagged_truncated_only_when_cut_off(
    _claude, stop_reason, truncated
):
    from app.platform.extensions.defaults import DefaultAnthropicProvider

    _claude("partial", stop_reason)

    async def tool_executor(name, args):
        return {}

    result = await DefaultAnthropicProvider().complete(
        model="claude-test",
        system_prompt="sys",
        user_message="hi",
        tools=[],
        tool_executor=tool_executor,
        max_rounds=1,
    )

    assert result.truncated is truncated


async def test_map_generation_refuses_a_truncated_claude_spec(
    _claude, _map_generation, monkeypatch
):
    from app.platform.extensions.defaults import DefaultAnthropicProvider

    _claude(_SPEC + " Then", "max_tokens")
    monkeypatch.setattr(
        ai_service, "get_ai_provider", lambda _p: DefaultAnthropicProvider()
    )

    with pytest.raises(UserFacingAIError, match="cut off"):
        await ai_service.generate_map_from_prompt(
            SimpleNamespace(), _user(), set(), "parks", port=SimpleNamespace()
        )
    assert _map_generation == []


async def test_sql_generation_refuses_a_truncated_claude_query(_claude, monkeypatch):
    from app.platform.extensions.defaults import DefaultAnthropicProvider

    class _Setting:
        async def get(self, _db):
            return "anthropic"

        async def for_provider(self, *_a):
            return "claude-test"

    async def nothing(*_a, **_k):
        return None

    async def runtime_config(_db):
        return {}

    _claude("SELECT * FROM parks LIMIT 1", "max_tokens")
    provider = DefaultAnthropicProvider()
    monkeypatch.setattr(provider, "resolve_runtime_config", runtime_config)
    monkeypatch.setattr(sql_generator, "LLM_PROVIDER", _Setting())
    monkeypatch.setattr(sql_generator, "LLM_MODEL_LIGHT", _Setting())
    monkeypatch.setattr(sql_generator, "get_ai_provider", lambda _p: provider)
    monkeypatch.setattr(sql_generator, "release_connection", nothing)

    sql = await sql_generator.generate_sql(SimpleNamespace(), "how many?", "-- ddl")

    assert sql.startswith("-- ERROR:")
