"""AI metadata prompts ask only for grounded claims, and Claude returns them.

The live evals in ``tests/evals/test_metadata_grounding_evals.py`` score real
drafts; these check the prompts' own worked examples against the same scorer,
the scorer itself, and the Claude structured-output request.
"""

import json

import httpx2
import pytest
from anthropic import AsyncAnthropic
from pydantic import BaseModel, SecretStr

import app.processing.ai.metadata_service as metadata_service
from app.core.config import settings
from app.platform.extensions.defaults import DefaultAnthropicProvider
from app.processing.ai.llm_loop import token_usage_from_error
from tests.ai_metadata_grounding import ungrounded_keywords, unsupported_claims

_SUMMARY_KINDS = ("time", "audience", "use", "publisher")


def _example_output(prompt: str) -> str:
    return prompt.rsplit("Output: ", 1)[1]


def test_the_summary_prompt_example_marks_its_inferred_uses():
    example = _example_output(metadata_service.SUMMARY_SYSTEM)

    assert unsupported_claims(example, _SUMMARY_KINDS) == []
    assert "(inferred)" in example


def test_the_summary_prompt_no_longer_asks_for_ungrounded_claims():
    prompt = metadata_service.SUMMARY_SYSTEM.lower()

    assert "intended audience, and potential uses" not in prompt
    assert "temporal scope if apparent" not in prompt


def test_the_keyword_prompt_example_invents_no_period():
    example = json.loads(_example_output(metadata_service.KEYWORD_SYSTEM))

    assert ungrounded_keywords(example) == []


def test_the_scorer_flags_an_unmarked_use_and_accepts_a_marked_one():
    unmarked = "Park polygons in New York City. It is suitable for urban planning."
    marked = "Park polygons in New York City. Likely uses include planning (inferred)."

    assert unsupported_claims(unmarked, _SUMMARY_KINDS) == [
        ("use", "It is suitable for urban planning.")
    ]
    assert unsupported_claims(marked, _SUMMARY_KINDS) == []


def test_the_scorer_accepts_combined_grounded_places_only():
    assert (
        ungrounded_keywords(
            [{"keyword": "bronx and staten island", "keyword_type": "place"}]
        )
        == []
    )
    assert ungrounded_keywords(
        [{"keyword": "new jersey", "keyword_type": "place"}]
    ) == [{"keyword": "new jersey", "keyword_type": "place"}]


class _Draft(BaseModel):
    draft: str


def _message(content, stop_reason):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 50, "output_tokens": 20},
    }


def _text_reply(text, stop_reason="end_turn"):
    return httpx2.Response(
        200, json=_message([{"type": "text", "text": text}], stop_reason)
    )


def _tool_reply(arguments, stop_reason="tool_use"):
    block = {"type": "tool_use", "id": "toolu_1", "name": "output", "input": arguments}
    return httpx2.Response(200, json=_message([block], stop_reason))


def _rejection(body):
    return httpx2.Response(400, json=body)


STRUCTURED_REJECTED = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "output_config.format: structured outputs are not supported "
        "for this model.",
    },
}
# Bedrock's InvokeModel validation for a key an older model does not take.
STRUCTURED_REJECTED_ON_BEDROCK = {
    "message": "extraneous key [output_config] is not permitted"
}
FORCED_TOOL_REJECTED = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": 'tool_choice: type "tool" and "any" are not supported for this '
        "model.",
    },
}
UNRELATED = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "messages: text content blocks must be non-empty",
    },
}


@pytest.fixture(autouse=True)
def _fresh_request_choices(monkeypatch):
    import app.processing.ai.claude_structured as claude_structured

    monkeypatch.setattr(claude_structured, "_requests", {})


def _claude_replies(monkeypatch, *replies):
    """A real SDK client that answers each request with the next reply."""
    sent: list[dict] = []
    pending = list(replies)

    def handler(request):
        sent.append(json.loads(request.content))
        return pending.pop(0)

    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("synthetic-test-key"))
    client = AsyncAnthropic(
        api_key="synthetic-test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_anthropic_client", lambda: client
    )
    return sent


def _claude(monkeypatch, text, stop_reason="end_turn"):
    return _claude_replies(monkeypatch, _text_reply(text, stop_reason))


async def _structured():
    return await DefaultAnthropicProvider().structured_complete(
        model="claude-sonnet-5-5",
        system_prompt="sys",
        user_message="describe",
        response_model=_Draft,
    )


@pytest.mark.anyio
async def test_claude_metadata_uses_structured_outputs_not_a_forced_tool(monkeypatch):
    sent = _claude(monkeypatch, '{"draft": "Park polygons."}')

    result = await _structured()

    assert result == (_Draft(draft="Park polygons."), 50, 20)
    # Sonnet 5.5, Opus 5.5 and Fable 5.1 reject a forced tool_choice.
    assert "tool_choice" not in sent[0] and "tools" not in sent[0]
    schema = sent[0]["output_config"]["format"]
    assert schema["type"] == "json_schema"
    assert schema["schema"]["required"] == ["draft"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("text", "stop_reason"),
    [('{"draft": "Park', "max_tokens"), ("not json", "end_turn"), ("", "refusal")],
)
async def test_a_billed_claude_reply_that_does_not_parse_carries_its_usage(
    monkeypatch, text, stop_reason
):
    _claude(monkeypatch, text, stop_reason)

    with pytest.raises(Exception) as caught:
        await _structured()

    assert token_usage_from_error(caught.value) == (50, 20)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "rejection", [STRUCTURED_REJECTED, STRUCTURED_REJECTED_ON_BEDROCK]
)
async def test_a_model_without_structured_outputs_falls_back_to_a_forced_tool(
    monkeypatch, rejection
):
    sent = _claude_replies(
        monkeypatch,
        _rejection(rejection),
        _tool_reply({"draft": "Park polygons."}),
        _tool_reply({"draft": "Second."}),
    )

    first = await _structured()
    second = await _structured()

    assert first == (_Draft(draft="Park polygons."), 50, 20)
    assert second[0] == _Draft(draft="Second.")
    assert "output_config" in sent[0]
    assert sent[1]["tool_choice"] == {"type": "tool", "name": "output"}
    # The choice is remembered: the second call goes straight to the tool.
    assert len(sent) == 3 and "output_config" not in sent[2]


@pytest.mark.anyio
async def test_a_model_without_forced_tools_switches_to_structured_outputs(
    monkeypatch,
):
    import app.processing.ai.claude_structured as claude_structured

    monkeypatch.setitem(
        claude_structured._requests,
        (settings.anthropic_platform, "claude-sonnet-5-5"),
        "forced_tool",
    )
    sent = _claude_replies(
        monkeypatch,
        _rejection(FORCED_TOOL_REJECTED),
        _text_reply('{"draft": "Park polygons."}'),
    )

    result = await _structured()

    assert result[0] == _Draft(draft="Park polygons.")
    assert "tool_choice" in sent[0] and "output_config" in sent[1]


@pytest.mark.anyio
async def test_an_unrelated_rejection_does_not_switch_requests(monkeypatch):
    import anthropic

    sent = _claude_replies(monkeypatch, _rejection(UNRELATED))

    with pytest.raises(anthropic.BadRequestError):
        await _structured()

    assert len(sent) == 1


@pytest.mark.anyio
async def test_a_model_rejecting_both_requests_raises_after_one_switch(monkeypatch):
    import anthropic

    sent = _claude_replies(
        monkeypatch, _rejection(STRUCTURED_REJECTED), _rejection(FORCED_TOOL_REJECTED)
    )

    with pytest.raises(anthropic.BadRequestError):
        await _structured()

    assert len(sent) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reply",
    [
        _tool_reply({"draft": "Park"}, stop_reason="max_tokens"),
        _tool_reply({"name": "Parks"}),
    ],
)
async def test_a_billed_forced_tool_reply_that_does_not_parse_carries_its_usage(
    monkeypatch, reply
):
    _claude_replies(monkeypatch, _rejection(STRUCTURED_REJECTED), reply)

    with pytest.raises(Exception) as caught:
        await _structured()

    assert token_usage_from_error(caught.value) == (50, 20)
