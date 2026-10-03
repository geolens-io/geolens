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


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [LLM_MODEL, LLM_MODEL_LIGHT])
@pytest.mark.parametrize("base", ["anthropic", "openai"])
async def test_subclass_of_a_built_in_provider_supplies_its_default_model(
    monkeypatch, cfg, base
):
    from app.platform.extensions.defaults import (
        DefaultAnthropicProvider,
        DefaultOpenAICompatibleProvider,
    )

    parent = {
        "anthropic": DefaultAnthropicProvider,
        "openai": DefaultOpenAICompatibleProvider,
    }[base]

    class _Sub(parent):
        async def resolve_runtime_config(self, db):
            return {"default_model": "sub-deployment"}

    monkeypatch.setattr("app.platform.extensions.get_ai_provider", lambda n: _Sub())
    assert await cfg.default_for(None, "anthropic") == "sub-deployment"


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [LLM_MODEL, LLM_MODEL_LIGHT])
async def test_invalid_endpoint_does_not_break_default_model_lookup(monkeypatch, cfg):
    from app.core.ai_credentials import OpenAICredentialDestinationError

    class _Stale:
        async def resolve_runtime_config(self, db):
            raise OpenAICredentialDestinationError("stale endpoint")

    monkeypatch.setattr("app.platform.extensions.get_ai_provider", lambda n: _Stale())
    assert await cfg.default_for(None, "ext") == llm_model_default(
        "ext", light=cfg.light
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [LLM_MODEL, LLM_MODEL_LIGHT])
@pytest.mark.parametrize("base", ["anthropic", "openai"])
async def test_subclass_inheriting_the_resolver_keeps_community_defaults(
    monkeypatch, cfg, base
):
    from app.platform.extensions.defaults import (
        DefaultAnthropicProvider,
        DefaultOpenAICompatibleProvider,
    )

    parent, name = {
        "anthropic": (DefaultAnthropicProvider, "anthropic"),
        "openai": (DefaultOpenAICompatibleProvider, "openai_compatible"),
    }[base]

    class _Sub(parent):
        pass

    monkeypatch.setattr("app.platform.extensions.get_ai_provider", lambda n: _Sub())
    assert await cfg.default_for(None, name) == llm_model_default(name, light=cfg.light)


@pytest.mark.asyncio
async def test_resolve_provider_pairs_model_and_endpoint_from_one_resolution(
    monkeypatch,
):
    from app.core.persistent_config import LLM_PROVIDER
    from app.processing.ai.llm_loop import resolve_provider

    calls = []

    class _Moving:
        async def resolve_runtime_config(self, db):
            calls.append(1)
            n = len(calls)
            return {"base_url": f"https://ep{n}.example", "default_model": f"m{n}"}

    async def _provider(db):
        return "ext"

    async def _no_override(db):
        return ""

    monkeypatch.setattr(LLM_PROVIDER, "get", _provider)
    monkeypatch.setattr(LLM_MODEL, "override", _no_override)
    monkeypatch.setattr("app.platform.extensions.get_ai_provider", lambda n: _Moving())

    _, model, runtime_config = await resolve_provider(None)

    assert len(calls) == 1
    assert (model, runtime_config["base_url"]) == ("m1", "https://ep1.example")
