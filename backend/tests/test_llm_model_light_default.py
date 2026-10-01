"""Unit tests for the light model each provider uses without an override.

Regression guard: the light model (used by query_data SQL generation and AI
metadata) must default to a model the configured provider actually serves.
Previously it hardcoded "gpt-4o-mini" for any non-Anthropic provider, which
404s on Azure OpenAI / gateways / Ollama where the model name must match a
real deployment — silently breaking query_data while chat kept working.
"""

import pytest

from app.core.persistent_config import llm_model_default, settings


@pytest.fixture
def _restore_settings():
    """Snapshot + restore the three attrs the default reads."""
    saved = (
        settings.anthropic_api_key,
        settings.openai_model,
        settings.openai_model_light,
    )
    yield
    (
        settings.anthropic_api_key,
        settings.openai_model,
        settings.openai_model_light,
    ) = saved


def test_anthropic_provider_uses_haiku(_restore_settings):
    assert llm_model_default("anthropic", light=True) == "claude-haiku-4-5-20251001"


def test_openai_provider_falls_back_to_openai_model(_restore_settings):
    # The bug: an Azure deployment named gpt-4.1-mini works for chat, but the
    # light model hardcoded gpt-4o-mini (no deployment) -> 404. Now it reuses
    # the configured model, which the provider is known to serve.
    settings.openai_model = "gpt-4.1-mini"
    settings.openai_model_light = None
    assert llm_model_default("openai_compatible", light=True) == "gpt-4.1-mini"


def test_explicit_light_model_overrides_main(_restore_settings):
    settings.openai_model = "gpt-4o"
    settings.openai_model_light = "gpt-4o-mini"
    assert llm_model_default("openai_compatible", light=True) == "gpt-4o-mini"
