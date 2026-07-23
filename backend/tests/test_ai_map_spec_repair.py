"""fix(#642): schema-invalid LLM map specs get one bounded repair round.

Parse failures already had _retry_parse_map_spec; these tests cover the
sibling path for valid-JSON-wrong-shape output (the failure mode observed
live on the demo: 'Field required' for name/layers).
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.processing.ai import service as ai_service
from app.processing.ai.schemas import LLMMapSpec

pytestmark = pytest.mark.anyio

GOOD_SPEC = '<map_spec>{"name": "Fixed", "layers": [{"dataset_id": "d1"}]}</map_spec>'
STILL_BAD_SPEC = '<map_spec>{"title": "still wrong"}</map_spec>'


def _validation_error() -> ValidationError:
    try:
        LLMMapSpec(title="wrong-key")
    except ValidationError as e:
        return e
    raise AssertionError("expected ValidationError")


class _FakeProvider:
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    async def complete(self, **kwargs):
        self.prompts.append(kwargs["user_message"])
        return SimpleNamespace(text=self.text, input_tokens=1, output_tokens=1)


async def test_repair_round_fixes_invalid_spec(monkeypatch):
    fake = _FakeProvider(GOOD_SPEC)
    monkeypatch.setattr(ai_service, "get_ai_provider", lambda name: fake)

    spec = await ai_service._repair_map_spec(
        {"title": "wrong-key"}, _validation_error(), "anthropic", "m", {}
    )

    assert spec.name == "Fixed"
    assert spec.layers[0].dataset_id == "d1"
    # The repair prompt carries the pydantic errors and the original spec
    assert "Field required" in fake.prompts[0]
    assert "wrong-key" in fake.prompts[0]


async def test_second_failure_raises_friendly_error(monkeypatch):
    fake = _FakeProvider(STILL_BAD_SPEC)
    monkeypatch.setattr(ai_service, "get_ai_provider", lambda name: fake)

    with pytest.raises(ValueError, match="try rephrasing"):
        await ai_service._repair_map_spec(
            {"title": "wrong-key"}, _validation_error(), "anthropic", "m", {}
        )


async def test_unparseable_repair_output_raises_friendly_error(monkeypatch):
    fake = _FakeProvider("no map_spec block here")
    monkeypatch.setattr(ai_service, "get_ai_provider", lambda name: fake)

    with pytest.raises(ValueError, match="try rephrasing"):
        await ai_service._repair_map_spec(
            {"title": "wrong-key"}, _validation_error(), "anthropic", "m", {}
        )
