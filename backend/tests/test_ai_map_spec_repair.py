"""fix(#642): schema-invalid LLM map specs get one bounded repair round.

Parse failures already had _retry_parse_map_spec; these tests cover the
sibling path for valid-JSON-wrong-shape output (the failure mode observed
live on the demo: 'Field required' for name/layers).
"""

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.processing.ai import service as ai_service
from app.processing.ai.schemas import LLMMapSpec

pytestmark = pytest.mark.anyio

GOOD_SPEC = '<map_spec>{"name": "Fixed", "layers": [{"dataset_id": "d1"}]}</map_spec>'
STILL_BAD_SPEC = '<map_spec>{"title": "still wrong"}</map_spec>'

USER_ID = uuid.uuid4()


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
        return SimpleNamespace(text=self.text, input_tokens=7, output_tokens=11)


@pytest.fixture
def usage_records(monkeypatch):
    records: list[dict] = []

    async def _record(_db, **kwargs):
        records.append(kwargs)

    monkeypatch.setattr(ai_service, "record_token_usage", _record)
    return records


async def _run_repair(fake, monkeypatch):
    monkeypatch.setattr(ai_service, "get_ai_provider", lambda name: fake)
    return await ai_service._repair_map_spec(
        {"title": "wrong-key"},
        _validation_error(),
        "anthropic",
        "m",
        {},
        session=None,
        user_id=USER_ID,
    )


async def test_repair_round_fixes_invalid_spec(monkeypatch, usage_records):
    fake = _FakeProvider(GOOD_SPEC)

    spec = await _run_repair(fake, monkeypatch)

    assert spec.name == "Fixed"
    assert spec.layers[0].dataset_id == "d1"
    # The repair prompt carries the pydantic errors and the original spec
    assert "Field required" in fake.prompts[0]
    assert "wrong-key" in fake.prompts[0]


async def test_repair_round_records_token_usage(monkeypatch, usage_records):
    """codex P2 on #648: repair tokens must count toward the daily AI budget."""
    await _run_repair(_FakeProvider(GOOD_SPEC), monkeypatch)

    assert usage_records == [
        {
            "user_id": USER_ID,
            "subsystem": "map_generation",
            "model": "m",
            "input_tokens": 7,
            "output_tokens": 11,
        }
    ]


async def test_second_failure_raises_friendly_error(monkeypatch, usage_records):
    fake = _FakeProvider(STILL_BAD_SPEC)

    with pytest.raises(ValueError, match="try rephrasing"):
        await _run_repair(fake, monkeypatch)
    # Tokens were spent even though the repair failed — still recorded.
    assert len(usage_records) == 1


async def test_unparseable_repair_output_raises_friendly_error(
    monkeypatch, usage_records
):
    with pytest.raises(ValueError, match="try rephrasing"):
        await _run_repair(_FakeProvider("no map_spec block here"), monkeypatch)


async def test_parse_retry_records_token_usage(monkeypatch, usage_records):
    """The pre-existing parse retry had the same accounting gap — closed too."""
    fake = _FakeProvider(GOOD_SPEC)
    monkeypatch.setattr(ai_service, "get_ai_provider", lambda name: fake)

    spec_dict = await ai_service._retry_parse_map_spec(
        "garbled", "anthropic", "m", {}, session=None, user_id=USER_ID
    )

    assert spec_dict["name"] == "Fixed"
    assert len(usage_records) == 1
    assert usage_records[0]["input_tokens"] == 7
