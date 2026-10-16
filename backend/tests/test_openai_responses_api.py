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


async def test_structured_metadata_uses_responses_parse(monkeypatch):
    class _Answer(BaseModel):
        title: str

    parsed = _Answer(title="Parks")
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=5, output_tokens=4),
        )

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_openai_client", lambda _url: client
    )

    result = await DefaultOpenAICompatibleProvider().structured_complete(
        model="eval-gpt-6.1-sol",
        system_prompt="sys",
        user_message="describe",
        response_model=_Answer,
    )

    assert result == (parsed, 5, 4)
    assert calls[0]["text_format"] is _Answer
    assert calls[0]["instructions"] == "sys"
    assert calls[0]["max_output_tokens"] == 1024
    assert calls[0]["store"] is False


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
    async def record_token_usage(_session, **kwargs):
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

    def _choice(finish_reason, content=None, tool_calls=None):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content, tool_calls=tool_calls),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    def _tc(call_id, args):
        return SimpleNamespace(
            id=call_id, function=SimpleNamespace(name="query_data", arguments=args)
        )

    replies = [
        _choice(
            "tool_calls", tool_calls=[_tc("a", '{"sql": "SELECT 1"}'), _tc("b", "{")]
        ),
        _choice("stop", content="done"),
    ]
    sent = []

    async def create(**kwargs):
        sent.append(list(kwargs["messages"]))
        return replies.pop(0)

    _install(
        monkeypatch,
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    executed: list = []
    result = await DefaultOpenAICompatibleProvider().complete(
        model="gpt-4.1-mini",
        system_prompt="sys",
        user_message="hi",
        tools=_TOOLS,
        tool_executor=await _executing(executed),
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
