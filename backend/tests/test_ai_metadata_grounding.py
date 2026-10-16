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


def _claude(monkeypatch, text, stop_reason="end_turn"):
    sent: list[dict] = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": text}],
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 50, "output_tokens": 20},
            },
        )

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
