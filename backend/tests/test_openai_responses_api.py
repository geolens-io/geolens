"""OPENAI_API_STYLE=responses runs OpenAI-compatible chat on the Responses API.

The rejection bodies are the ones Azure OpenAI returned for Responses
requests from gpt-6.1-sol and gpt-4.1-mini.
"""

import json
from types import SimpleNamespace

import httpx
import openai
import pytest
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseUsage,
)
from pydantic import BaseModel, SecretStr, ValidationError

import app.processing.ai.openai_request as openai_request
import app.processing.ai.streaming as streaming
from app.core.ai_credentials import bind_openai_credential_base_url
from app.core.config import settings
from app.core.config_ai import OpenAISettings
from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider
from app.processing.ai.openai_conversation import ResponsesError
from app.processing.ai.openai_request import ResponsesAPIRequiredError

pytestmark = pytest.mark.anyio

_URL = "http://llm.internal:11434/v1"

TEMPERATURE_REJECTED = {
    "code": None,
    "param": "temperature",
    "message": "Unsupported parameter: 'temperature' is not supported with this model.",
}
EFFORT_UNSUPPORTED = {
    "code": "unsupported_parameter",
    "param": "reasoning.effort",
    "message": "Unsupported parameter: 'reasoning.effort' is not supported with "
    "this model.",
}
INCLUDE_UNSUPPORTED = {
    "code": "unsupported_parameter",
    "param": "include",
    "message": "Unsupported parameter: 'include' is not supported.",
}

_TOOLS = [
    {
        "name": "query_data",
        "description": "Run SQL",
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}},
    }
]


def _rejection(body: dict) -> openai.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", _URL))
    return openai.BadRequestError(
        f"Error code: 400 - {body}", response=response, body=body
    )


def _call_item(
    call_id: str = "call_1",
    args: str = '{"sql": "SELECT 1"}',
    status: str = "completed",
):
    return ResponseFunctionToolCall(
        type="function_call",
        id="fc_1",
        call_id=call_id,
        name="query_data",
        arguments=args,
        status=status,
    )


def _message_item(text: str):
    return ResponseOutputMessage.model_validate(
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
    )


def _response(
    output, *, input_tokens=10, output_tokens=5, status="completed", reason=None
):
    return Response.model_construct(
        output=output,
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        usage=ResponseUsage.model_construct(
            input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )


class _Server:
    """A fake ``responses.create`` that replays results and rejects by rule."""

    def __init__(self, *results, rules=()):
        self.results = list(results)
        self.rules = rules
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        # The loop mutates its input list later; keep what was sent.
        self.calls.append({**kwargs, "input": list(kwargs.get("input", []))})
        for rule in self.rules:
            body = rule(kwargs)
            if body is not None:
                raise _rejection(body)
        return self.results.pop(0)


@pytest.fixture(autouse=True)
def _responses_style(monkeypatch):
    monkeypatch.setattr(openai_request, "_shapes", {})
    monkeypatch.setattr(settings, "openai_api_style", "responses")
    monkeypatch.setattr(settings, "openai_reasoning_effort", None)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "openai_base_url", _URL)


def _install(monkeypatch, client):
    monkeypatch.setitem(
        DefaultOpenAICompatibleProvider._clients,
        bind_openai_credential_base_url(None, purpose="chat"),
        client,
    )


def test_api_style_defaults_to_chat_completions():
    assert OpenAISettings().openai_api_style == "chat_completions"
    assert OpenAISettings(openai_api_style="").openai_api_style == "chat_completions"
    assert OpenAISettings(openai_api_style="responses").openai_api_style == (
        "responses"
    )
    with pytest.raises(ValidationError):
        OpenAISettings(openai_api_style="assistants")


def test_responses_required_error_names_the_setting():
    assert "OPENAI_API_STYLE=responses" in str(ResponsesAPIRequiredError())


async def test_tool_loop_runs_function_calls_through_the_responses_api(monkeypatch):
    server = _Server(
        _response([_call_item()], input_tokens=100, output_tokens=20),
        _response(
            [_message_item("There are 42 parks.")], input_tokens=150, output_tokens=10
        ),
    )
    _install(
        monkeypatch, SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )
    executed = []

    async def tool_executor(name, args):
        executed.append((name, args))
        return {"count": 42}

    result = await DefaultOpenAICompatibleProvider().complete(
        model="eval-gpt-6.1-sol",
        system_prompt="You answer questions about parks.",
        user_message="How many parks?",
        tools=_TOOLS,
        tool_executor=tool_executor,
        history=[{"role": "user", "content": "Earlier question"}],
    )

    assert result.text == "There are 42 parks."
    assert (result.input_tokens, result.output_tokens) == (250, 30)
    assert executed == [("query_data", {"sql": "SELECT 1"})]

    first, second = server.calls
    assert first["instructions"] == "You answer questions about parks."
    assert first["input"] == [
        {"role": "user", "content": "Earlier question"},
        {"role": "user", "content": "How many parks?"},
    ]
    assert first["tools"] == [
        {
            "type": "function",
            "name": "query_data",
            "description": "Run SQL",
            "parameters": _TOOLS[0]["input_schema"],
            "strict": False,
        }
    ]
    assert first["max_output_tokens"] == 4096
    assert first["store"] is False
    assert "max_tokens" not in first and "messages" not in first

    replay, output = second["input"][2:]
    assert replay["type"] == "function_call" and replay["call_id"] == "call_1"
    assert output["type"] == "function_call_output"
    assert output["call_id"] == "call_1"
    # Fenced like every other tool result, not bare JSON.
    assert output["output"] != json.dumps({"count": 42})
    assert "42" in output["output"]


async def test_rejected_responses_parameters_are_left_out(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    server = _Server(
        _response([_message_item("ok")]),
        rules=(
            lambda kw: TEMPERATURE_REJECTED if "temperature" in kw else None,
            lambda kw: EFFORT_UNSUPPORTED if "reasoning" in kw else None,
            lambda kw: INCLUDE_UNSUPPORTED if "include" in kw else None,
        ),
    )
    _install(
        monkeypatch, SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )

    async def tool_executor(name, args):
        return {}

    result = await DefaultOpenAICompatibleProvider().complete(
        model="gpt-4.1-mini",
        system_prompt="sys",
        user_message="hi",
        tools=[],
        tool_executor=tool_executor,
        max_rounds=1,
    )

    assert result.text == "ok"
    assert server.calls[0]["reasoning"] == {"effort": "none"}
    assert server.calls[0]["include"] == ["reasoning.encrypted_content"]
    final = server.calls[-1]
    assert len(server.calls) == 4
    assert not {"temperature", "reasoning", "include", "tools"} & set(final)


def _sdk_client(handler):
    """A real SDK client whose HTTP calls ``handler`` answers."""
    import httpx2
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key="synthetic-test-key",
        base_url=_URL,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )


def _responses_body(text, *, status="completed", reason=None):
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "m",
        "status": status,
        "incomplete_details": {"reason": reason} if reason else None,
        "error": None,
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 50,
            "output_tokens": 1024,
            "total_tokens": 1074,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _chat_body(content, *, finish_reason="stop"):
    return {
        "id": "c",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 1024, "total_tokens": 1074},
    }


async def test_structured_metadata_uses_responses_parse(monkeypatch):
    import httpx2

    class _Answer(BaseModel):
        title: str

    sent: list[dict] = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=_responses_body('{"title": "Parks"}'))

    client = _sdk_client(handler)
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_openai_client", lambda _url: client
    )

    result = await DefaultOpenAICompatibleProvider().structured_complete(
        model="eval-gpt-6.1-sol",
        system_prompt="sys",
        user_message="describe",
        response_model=_Answer,
    )

    assert result == (_Answer(title="Parks"), 50, 1024)
    assert sent[0]["instructions"] == "sys"
    assert sent[0]["max_output_tokens"] == 1024
    assert sent[0]["store"] is False
    assert sent[0]["text"]["format"]["type"] == "json_schema"


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


def _event(type_, **fields):
    return SimpleNamespace(type=type_, **fields)


async def _async_return(value):
    return value


def _patch_stream_io(monkeypatch, recorded):
    async def record_token_usage(**kwargs):
        recorded.append((kwargs["input_tokens"], kwargs["output_tokens"]))

    async def release_connection(_session):
        return None

    monkeypatch.setattr(
        streaming, "_daily_token_budget", lambda *_a: _async_return((0, 0))
    )
    monkeypatch.setattr(streaming, "record_token_usage", record_token_usage)
    monkeypatch.setattr(streaming, "release_connection", release_connection)


async def _stream_chat(client):
    return [
        event
        async for event in streaming._stream_openai_chat(
            "how many parks?",
            "sys",
            SimpleNamespace(),
            SimpleNamespace(id="user-1"),
            set(),
            [],
            model="eval-gpt-6.1-sol",
            client=client,
            base_url=_URL,
            port=SimpleNamespace(),
            tools=_TOOLS,
        )
    ]


async def test_streamed_chat_runs_a_tool_call_over_responses_events(monkeypatch):
    recorded: list[tuple[int, int]] = []
    _patch_stream_io(monkeypatch, recorded)
    executed = []

    async def execute_and_yield_tools(calls, *args, results_out=None, **kwargs):
        executed.extend(calls)
        results_out.extend({"count": 42} for _ in calls)
        yield {"type": "tool_result", "tool": "query_data"}

    monkeypatch.setattr(streaming, "_execute_and_yield_tools", execute_and_yield_tools)

    call = _call_item()
    first = _Events(
        [
            _event("response.output_item.added", item=call),
            _event("response.function_call_arguments.delta", delta='{"sql"'),
            _event("response.output_item.done", item=call),
            _event(
                "response.completed",
                response=_response([call], input_tokens=100, output_tokens=20),
            ),
        ]
    )
    answer = _message_item("There are 42 parks.")
    second = _Events(
        [
            _event("response.output_text.delta", delta="There are "),
            _event("response.output_text.delta", delta="42 parks."),
            _event(
                "response.completed",
                response=_response([answer], input_tokens=150, output_tokens=10),
            ),
        ]
    )
    server = _Server(first, second)
    events = await _stream_chat(
        SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )

    assert [c["stream"] for c in server.calls] == [True, True]
    assert executed == [("query_data", {"sql": "SELECT 1"})]
    assert recorded == [(100, 20), (150, 10)]
    assert server.calls[1]["input"][-1]["type"] == "function_call_output"
    assert [e["tool"] for e in events if e["type"] == "tool_start"] == ["query_data"]
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "There are 42 parks."
    assert events[-1] == {"type": "done", "explanation": "There are 42 parks."}


@pytest.mark.parametrize(
    "events",
    [
        [_event("response.failed", response=_response([], status="failed"))],
        [_event("error", message="server error")],
        [_event("response.output_text.delta", delta="partial")],
    ],
)
async def test_a_failed_or_truncated_responses_stream_raises(monkeypatch, events):
    recorded: list[tuple[int, int]] = []
    _patch_stream_io(monkeypatch, recorded)
    server = _Server(_Events(events))

    with pytest.raises(ResponsesError):
        await _stream_chat(
            SimpleNamespace(responses=SimpleNamespace(create=server.create))
        )


def _refusal_item(text: str):
    return ResponseOutputMessage.model_validate(
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "refusal", "refusal": text}],
        }
    )


async def _executing(executed):
    async def tool_executor(name, args):
        executed.append((name, args))
        return {"count": 42}

    return tool_executor


async def test_a_malformed_function_call_still_gets_an_output(monkeypatch):
    server = _Server(
        _response([_call_item("call_1"), _call_item("call_2", args="{not json")]),
        _response([_message_item("There are 42 parks.")]),
    )
    _install(
        monkeypatch, SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )
    executed: list = []

    result = await DefaultOpenAICompatibleProvider().complete(
        model="eval-gpt-6.1-sol",
        system_prompt="sys",
        user_message="How many parks?",
        tools=_TOOLS,
        tool_executor=await _executing(executed),
    )

    assert result.text == "There are 42 parks."
    assert executed == [("query_data", {"sql": "SELECT 1"})]
    outputs = {
        item["call_id"]: item["output"]
        for item in server.calls[1]["input"]
        if item.get("type") == "function_call_output"
    }
    assert set(outputs) == {"call_1", "call_2"}
    assert "42" in outputs["call_1"]
    assert "not valid JSON" in outputs["call_2"]


async def test_a_malformed_chat_completions_call_still_gets_a_tool_message(
    monkeypatch,
):
    monkeypatch.setattr(settings, "openai_api_style", "chat_completions")

    sent, result = await _chat_completions_tool_round(
        monkeypatch,
        _cc_reply("tool_calls", tool_calls=[_cc_call("a"), _cc_call("b", args="{")]),
    )

    assert result.text == "done"
    tool_messages = [m for m in sent[1] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["a", "b"]
    assert "not valid JSON" in tool_messages[1]["content"]


async def test_a_completed_refusal_is_the_answer(monkeypatch):
    server = _Server(_response([_refusal_item("I can't help with that.")]))
    _install(
        monkeypatch, SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )

    result = await DefaultOpenAICompatibleProvider().complete(
        model="eval-gpt-6.1-sol",
        system_prompt="sys",
        user_message="hi",
        tools=[],
        tool_executor=await _executing([]),
        max_rounds=1,
    )

    assert result.text == "I can't help with that."


async def test_a_chat_completions_refusal_is_the_answer(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_style", "chat_completions")

    async def create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=None, refusal="I can't help with that.", tool_calls=None
                    ),
                )
            ],
            usage=None,
        )

    _install(
        monkeypatch,
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    result = await DefaultOpenAICompatibleProvider().complete(
        model="gpt-4.1-mini",
        system_prompt="sys",
        user_message="hi",
        tools=[],
        tool_executor=await _executing([]),
        max_rounds=1,
    )

    assert result.text == "I can't help with that."


async def test_a_streamed_refusal_reaches_the_user(monkeypatch):
    _patch_stream_io(monkeypatch, [])
    refusal = _refusal_item("I can't help with that.")
    server = _Server(
        _Events(
            [
                _event("response.refusal.delta", delta="I can't "),
                _event("response.refusal.delta", delta="help with that."),
                _event("response.completed", response=_response([refusal])),
            ]
        )
    )

    events = await _stream_chat(
        SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )

    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "I can't help with that."
    assert events[-1] == {"type": "done", "explanation": "I can't help with that."}


async def test_a_streamed_chat_completions_refusal_reaches_the_user(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_style", "chat_completions")
    _patch_stream_io(monkeypatch, [])

    def _chunk(**delta):
        return SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=None, **delta),
                    finish_reason="stop" if not delta else None,
                )
            ],
        )

    async def create(**kwargs):
        return _Events([_chunk(refusal="I can't help with that."), _chunk()])

    events = await _stream_chat(
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    assert events[-1] == {"type": "done", "explanation": "I can't help with that."}


async def _complete(monkeypatch, server, executed):
    _install(
        monkeypatch, SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )
    return await DefaultOpenAICompatibleProvider().complete(
        model="eval-gpt-6.1-sol",
        system_prompt="sys",
        user_message="How many parks?",
        tools=_TOOLS,
        tool_executor=await _executing(executed),
    )


@pytest.mark.parametrize("reason", ["max_output_tokens", "content_filter"])
async def test_a_response_that_stopped_early_returns_its_partial_text(
    monkeypatch, reason
):
    server = _Server(
        _response([_message_item("There are")], status="incomplete", reason=reason)
    )
    executed: list = []

    result = await _complete(monkeypatch, server, executed)

    assert result.text == "There are"
    assert len(server.calls) == 1


@pytest.mark.parametrize(
    ("response_status", "item_status"),
    [
        ("incomplete", "incomplete"),
        ("incomplete", "completed"),
        ("completed", "in_progress"),
    ],
)
async def test_an_unfinished_function_call_or_response_runs_no_tool(
    monkeypatch, response_status, item_status
):
    # Truncated arguments can still parse as JSON.
    call = _call_item(args='{"sql": "DELETE"}', status=item_status)
    server = _Server(
        _response([call], status=response_status, reason="max_output_tokens")
    )
    executed: list = []

    result = await _complete(monkeypatch, server, executed)

    assert executed == []
    assert result.text == ""
    assert len(server.calls) == 1


@pytest.mark.parametrize("status", ["failed", "cancelled", "in_progress", "queued"])
async def test_a_response_without_a_final_answer_raises(monkeypatch, status):
    server = _Server(_response([_message_item("partial")], status=status))

    with pytest.raises(ResponsesError):
        await _complete(monkeypatch, server, [])


async def test_a_streamed_response_that_stopped_early_returns_its_partial_text(
    monkeypatch,
):
    _patch_stream_io(monkeypatch, [])
    call = _call_item(args='{"sql": "DELETE"}', status="incomplete")
    partial = _message_item("There are")
    server = _Server(
        _Events(
            [
                _event("response.output_text.delta", delta="There are"),
                _event("response.output_item.added", item=call),
                _event(
                    "response.incomplete",
                    response=_response(
                        [partial, call], status="incomplete", reason="max_output_tokens"
                    ),
                ),
            ]
        )
    )
    executed: list = []

    async def execute_and_yield_tools(calls, *args, **kwargs):
        executed.extend(calls)
        yield {"type": "tool_result"}

    monkeypatch.setattr(streaming, "_execute_and_yield_tools", execute_and_yield_tools)

    events = await _stream_chat(
        SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )

    assert executed == []
    assert len(server.calls) == 1
    assert events[-1] == {"type": "done", "explanation": "There are"}


async def test_a_streamed_completed_event_without_a_final_answer_raises(monkeypatch):
    _patch_stream_io(monkeypatch, [])
    server = _Server(
        _Events(
            [_event("response.completed", response=_response([], status="cancelled"))]
        )
    )

    with pytest.raises(ResponsesError):
        await _stream_chat(
            SimpleNamespace(responses=SimpleNamespace(create=server.create))
        )


def _capture_error_usage(monkeypatch):
    import app.processing.ai.token_usage as token_usage

    recorded: list[tuple[int, int]] = []

    async def record_token_usage(**kwargs):
        recorded.append((kwargs["input_tokens"], kwargs["output_tokens"]))

    monkeypatch.setattr(token_usage, "record_token_usage", record_token_usage)
    return recorded


async def test_a_failed_round_counts_toward_the_daily_quota(monkeypatch):
    from app.processing.ai.token_usage import usage_accounting

    recorded = _capture_error_usage(monkeypatch)
    server = _Server(
        _response([_call_item()], input_tokens=100, output_tokens=20),
        _response([], status="failed", input_tokens=30, output_tokens=7),
    )

    with pytest.raises(ResponsesError):
        async with usage_accounting(None, user_id=None, subsystem="chat", model="m"):
            await _complete(monkeypatch, server, [])

    assert recorded == [(130, 27)]


@pytest.mark.parametrize(
    ("style", "body"),
    [
        # Truncated JSON in a reply the server marked completed.
        ("responses", _responses_body('{"title": "Par')),
        (
            "responses",
            _responses_body(
                '{"title": "Par', status="incomplete", reason="max_output_tokens"
            ),
        ),
        ("responses", _responses_body("", status="failed")),
        # Valid JSON that does not match the schema.
        ("responses", _responses_body('{"name": "Parks"}')),
        ("chat_completions", _chat_body('{"title": "Par', finish_reason="length")),
        ("chat_completions", _chat_body("", finish_reason="content_filter")),
        ("chat_completions", _chat_body('{"title": "Par')),
        ("chat_completions", _chat_body('{"name": "Parks"}')),
    ],
)
async def test_a_billed_metadata_reply_that_does_not_parse_still_counts(
    monkeypatch, style, body
):
    import httpx2

    import app.processing.ai.metadata_service as metadata_service

    class _Answer(BaseModel):
        title: str

    monkeypatch.setattr(settings, "openai_api_style", style)
    monkeypatch.setattr(metadata_service, "anthropic_configured", lambda: False)
    recorded = _capture_error_usage(monkeypatch)
    client = _sdk_client(lambda request: httpx2.Response(200, json=body))
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_openai_client", lambda _url: client
    )

    # The SDK's own parser raises a different error for each case.
    with pytest.raises(Exception):
        await metadata_service._generate_structured("sys", "describe", _Answer)

    assert recorded == [(50, 1024)]


def _cc_call(call_id: str, args: str = '{"sql": "SELECT 1"}') -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "query_data", "arguments": args},
    }


def _cc_reply(finish_reason, content=None, tool_calls=None, **extra):
    from openai.types.chat import ChatCompletionMessage

    message = ChatCompletionMessage.model_validate(
        {"role": "assistant", "content": content, "tool_calls": tool_calls, **extra}
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=message)],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


async def _chat_completions_tool_round(monkeypatch, first_reply):
    """Run a tool round then a final answer over Chat Completions."""
    monkeypatch.setattr(settings, "openai_api_style", "chat_completions")
    replies = [first_reply, _cc_reply("stop", content="done")]
    sent: list[list] = []

    async def create(**kwargs):
        sent.append(list(kwargs["messages"]))
        return replies.pop(0)

    _install(
        monkeypatch,
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    result = await DefaultOpenAICompatibleProvider().complete(
        model="deepseek-reasoner",
        system_prompt="sys",
        user_message="hi",
        tools=_TOOLS,
        tool_executor=await _executing([]),
    )
    return sent, result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reasoning_content", "First count the parks."),
        ("reasoning", "First count the parks."),
        ("reasoning_details", [{"type": "reasoning.text", "text": "Count."}]),
        ("provider_specific_state", {"opaque": 1}),
    ],
)
async def test_a_chat_completions_tool_follow_up_replays_provider_fields(
    monkeypatch, field, value
):
    sent, result = await _chat_completions_tool_round(
        monkeypatch,
        _cc_reply("tool_calls", tool_calls=[_cc_call("a")], **{field: value}),
    )

    assert result.text == "done"
    assistant = next(m for m in sent[1] if m.get("role") == "assistant")
    assert assistant[field] == value
    assert assistant["tool_calls"][0]["id"] == "a"
    tool = next(m for m in sent[1] if m.get("role") == "tool")
    assert tool["content"] != json.dumps({"count": 42})


async def test_a_streamed_tool_follow_up_keeps_streamed_reasoning(monkeypatch):
    from app.processing.ai.openai_conversation import (
        ChatCompletionsConversation,
        Round,
    )

    def _chunk(finish_reason=None, **delta):
        fields = {"content": None, "tool_calls": None, **delta}
        return SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(**fields), finish_reason=finish_reason
                )
            ],
        )

    tool_call = SimpleNamespace(
        index=0,
        id="a",
        function=SimpleNamespace(name="query_data", arguments='{"sql": "SELECT 1"}'),
    )
    chunks = [
        _chunk(reasoning_content="First "),
        _chunk(reasoning_content="count."),
        _chunk(tool_calls=[tool_call]),
        _chunk(finish_reason="tool_calls"),
    ]

    async def create(**kwargs):
        return _Events(chunks)

    conversation = ChatCompletionsConversation(
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
        base_url=_URL,
        model="deepseek-reasoner",
        system_prompt="sys",
        history=None,
        user_message="hi",
        tools=_TOOLS,
        max_tokens=64,
        temperature=0.3,
    )
    round_ = [d async for d in conversation.stream() if isinstance(d, Round)][0]
    conversation.add_tool_results(round_, [(round_.tool_calls[0], {"count": 42})])

    assistant = conversation._messages[-2]
    assert assistant["reasoning_content"] == "First count."
    assert assistant["tool_calls"][0]["id"] == "a"


async def test_responses_tools_are_sent_non_strict(monkeypatch):
    from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC

    server = _Server(_response([_message_item("ok")]))
    _install(
        monkeypatch, SimpleNamespace(responses=SimpleNamespace(create=server.create))
    )

    await DefaultOpenAICompatibleProvider().complete(
        model="eval-gpt-6.1-sol",
        system_prompt="sys",
        user_message="hi",
        tools=CHAT_TOOLS_ANTHROPIC,
        tool_executor=await _executing([]),
        max_rounds=1,
    )

    sent = server.calls[0]["tools"]
    assert len(sent) == len(CHAT_TOOLS_ANTHROPIC)
    assert all(tool["strict"] is False for tool in sent)
    # The schemas go out unchanged, optional properties still optional.
    assert [tool["parameters"] for tool in sent] == [
        tool["input_schema"] for tool in CHAT_TOOLS_ANTHROPIC
    ]


async def test_an_optional_argument_search_reaches_the_executor_unchanged(
    monkeypatch,
):
    args = '{"query": "parks"}'
    call = ResponseFunctionToolCall(
        type="function_call",
        id="fc_1",
        call_id="call_1",
        name="search_datasets",
        arguments=args,
        status="completed",
    )
    server = _Server(_response([call]), _response([_message_item("Found it.")]))
    executed: list = []

    await _complete(monkeypatch, server, executed)

    assert executed == [("search_datasets", {"query": "parks"})]
