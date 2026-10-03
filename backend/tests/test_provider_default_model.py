"""An extension LLM provider's own default_model resolves when no override is set."""

import pytest

from app.core.persistent_config import LLM_MODEL, LLM_MODEL_LIGHT, llm_model_default


class _FakeProvider:
    def __init__(self, config: dict[str, object]) -> None:
        self._config = config

    async def resolve_runtime_config(self, db):
        return self._config


def _register(monkeypatch, config):
    monkeypatch.setattr(
        "app.platform.extensions.get_ai_provider",
        lambda name: _FakeProvider(config),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [LLM_MODEL, LLM_MODEL_LIGHT])
async def test_extension_provider_default_model_is_used(monkeypatch, cfg):
    _register(monkeypatch, {"default_model": "ext-model"})
    assert await cfg.default_for(None, "ext") == "ext-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"default_model": "  "}])
async def test_extension_provider_without_default_model_uses_community_default(
    monkeypatch, config
):
    _register(monkeypatch, config)
    assert await LLM_MODEL.default_for(None, "ext") == llm_model_default("ext")
