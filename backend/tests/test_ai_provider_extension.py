"""Tests for AIProviderExtension Protocol, registry seeding, and entry-points dispatch.

Phase 226 D-15 (entry-points overlay test) + D-16 (default smoke test) +
D-06 (ValueError on unknown provider name).

Maps to AIEXT-01 (Protocol exists), AIEXT-02 (defaults registered via accessor),
AIEXT-04 (overlay-registered providers dispatch correctly via importlib.metadata
entry_points). The architecture-guard test in test_layering.py covers AIEXT-03
and AIEXT-05.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _reset_registry():
    """Reset extension registry state between tests (RESEARCH.md Pitfall 6).

    Mirrors test_extensions.py:10-15 verbatim. Replicated inline rather than
    imported to avoid inter-test-file import coupling.
    """
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate registry from environment-discovered entry points.

    The enterprise overlay is editable-installable in the backend test venv;
    that install adds ``geolens.extensions`` entry points which would
    otherwise pollute the registry whenever a test calls ``load_extensions()``.
    Patch ``entry_points`` to default-empty so each test starts from a
    known-empty discovery surface and can opt in to its own mock entry
    points via ``with patch(...)`` (Phase 226 RESEARCH.md Pitfall 6).
    """
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


def test_default_providers_registered():
    """D-16 / AIEXT-02 smoke: get_ai_provider returns the right community-default class for each name.

    Verifies SC#2 ("DefaultAIProviderExtension resolves the two community
    providers -- Anthropic native, OpenAI-compatible -- via the same accessor
    pattern as get_billing_extension() / get_audit_sink()").
    """
    from app.platform.extensions import get_ai_provider
    from app.platform.extensions.defaults import (
        DefaultAnthropicProvider,
        DefaultOpenAICompatibleProvider,
    )

    anthropic = get_ai_provider("anthropic")
    openai_compatible = get_ai_provider("openai_compatible")

    assert isinstance(anthropic, DefaultAnthropicProvider)
    assert isinstance(openai_compatible, DefaultOpenAICompatibleProvider)

    # Verify Protocol satisfaction (runtime_checkable per D-07)
    from app.platform.extensions.protocols import AIProviderExtension

    assert isinstance(anthropic, AIProviderExtension)
    assert isinstance(openai_compatible, AIProviderExtension)

    # Singleton stability (Nyquist Dimension #6 -- state management):
    # Two calls to get_ai_provider("anthropic") return the SAME instance
    # (registry singleton, not re-seeded per call).
    assert get_ai_provider("anthropic") is anthropic
    assert get_ai_provider("openai_compatible") is openai_compatible


def test_unknown_provider_raises_value_error():
    """D-06 / Nyquist Dimension #7: unknown name raises ValueError with the
    EXACT message from llm_loop.py:149's pre-Phase-226 behavior.

    Phase 226 D-06: preserves today's exception type and message format so
    existing tests that catch ``ValueError`` from the dispatch path continue
    to pass.
    """
    from app.platform.extensions import get_ai_provider

    with pytest.raises(ValueError, match=r"^Unknown LLM provider: bedrock$"):
        get_ai_provider("bedrock")

    with pytest.raises(ValueError, match=r"^Unknown LLM provider: $"):
        get_ai_provider("")


@pytest.mark.asyncio
async def test_overlay_provider_is_dispatched():
    """D-15 / SC#5 / AIEXT-04 binding: overlay registered via
    importlib.metadata entry_points is dispatched correctly without
    modifying any core file.

    Exercises the FULL chain: ``entry_points()`` discovery ->
    ``register_extensions(registry)`` callback -> ``get_ai_provider(name)``
    accessor -> ``provider.complete(...)`` async dispatch -> returned
    ToolLoopResult. The fake provider's ``complete()`` returns a known
    sentinel value to prove dispatch reached the overlay's class (not the
    community defaults).
    """
    from app.platform.extensions import get_ai_provider, load_extensions
    from app.processing.ai.llm_loop import ToolLoopResult

    # Track whether complete() was called with the expected kwargs.
    captured_kwargs: dict = {}

    class TestProvider:
        async def complete(self, **kwargs):
            captured_kwargs.update(kwargs)
            return ToolLoopResult(
                text="from-test-provider",
                actions=[],
                input_tokens=0,
                output_tokens=0,
            )

        async def stream(self, **kwargs):
            raise NotImplementedError

        async def resolve_runtime_config(self, db):
            return {"base_url": None, "default_model": "test-model-1"}

    def register(registry: dict) -> None:
        providers = registry.setdefault("ai_providers", {})
        providers["test_provider"] = TestProvider()

    mock_ep = MagicMock()
    mock_ep.name = "geolens.ai-providers.test"
    mock_ep.load.return_value = register

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        provider_ext = get_ai_provider("test_provider")

        # Sentinel executor -- never invoked because tools=[] + max_rounds=1.
        async def _noop_executor(name: str, args: dict) -> dict:
            return {}

        result = await provider_ext.complete(
            model="test-model-1",
            system_prompt="",
            user_message="hello",
            tools=[],
            tool_executor=_noop_executor,
            max_rounds=1,
            max_tokens=128,
        )

        assert result.text == "from-test-provider"
        assert captured_kwargs.get("model") == "test-model-1"
        assert captured_kwargs.get("user_message") == "hello"
        assert captured_kwargs.get("max_rounds") == 1

    # Verify the community defaults still resolve correctly even though we
    # added a third provider -- registry coexistence (D-05 setdefault discipline).
    from app.platform.extensions.defaults import (
        DefaultAnthropicProvider,
        DefaultOpenAICompatibleProvider,
    )

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        assert isinstance(get_ai_provider("anthropic"), DefaultAnthropicProvider)
        assert isinstance(
            get_ai_provider("openai_compatible"), DefaultOpenAICompatibleProvider
        )
