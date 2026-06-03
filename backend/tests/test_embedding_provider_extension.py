"""Tests for EmbeddingProviderExtension Protocol, registry seeding, and entry-points dispatch.

Phase 231 D-18 (entry-points overlay test) + D-19 (default smoke test) +
D-20 (ValueError on unknown provider name).

Maps to EMBPROV-01 (Protocol exists), EMBPROV-02 (default registered via accessor),
EMBPROV-05 (overlay-registered providers dispatch correctly via importlib.metadata
entry_points). The architecture-guard test in test_layering.py covers EMBPROV-03
and EMBPROV-04.
"""

from unittest.mock import MagicMock, patch

import pytest


def _reset_registry():
    """Reset extension registry state between tests (RESEARCH.md Pitfall 2).

    Mirrors test_extensions.py:10-15 verbatim. Replicated inline rather than
    imported to avoid inter-test-file import coupling (Phase 226 RESEARCH.md
    Pitfall 6).
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
    points via ``with patch(...)`` (Phase 226 RESEARCH.md Pitfall 6,
    Phase 231 RESEARCH.md Pitfall 2).
    """
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


def test_default_embedding_provider_registered():
    """D-19 / EMBPROV-02 smoke: get_embedding_provider returns DefaultOpenAIEmbeddingProvider."""
    from app.platform.extensions import get_embedding_provider
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider
    from app.platform.extensions.protocols import EmbeddingProviderExtension

    provider = get_embedding_provider("openai_compatible")
    assert isinstance(provider, DefaultOpenAIEmbeddingProvider)

    # Verify Protocol satisfaction (runtime_checkable per D-05)
    assert isinstance(provider, EmbeddingProviderExtension)

    # Singleton stability — two calls return the SAME instance (registry singleton)
    assert get_embedding_provider("openai_compatible") is provider


def test_unknown_embedding_provider_raises_value_error():
    """D-20 / D-11: unknown name raises ValueError with exact message."""
    from app.platform.extensions import get_embedding_provider

    with pytest.raises(ValueError, match=r"^Unknown embedding provider: bedrock$"):
        get_embedding_provider("bedrock")

    with pytest.raises(ValueError, match=r"^Unknown embedding provider: $"):
        get_embedding_provider("")


@pytest.mark.asyncio
async def test_overlay_embedding_provider_is_dispatched():
    """D-18 / SC#5 / EMBPROV-05 binding: overlay registered via
    importlib.metadata entry_points is dispatched correctly without
    modifying any core file.

    Exercises the FULL chain: ``entry_points()`` discovery →
    ``register_extensions(registry)`` callback → ``get_embedding_provider(name)``
    accessor → ``provider.embed(...)`` async dispatch → returned vectors.
    """
    from app.platform.extensions import get_embedding_provider, load_extensions
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider

    captured_kwargs: dict = {}

    class TestEmbeddingProvider:
        async def embed(
            self,
            *,
            texts,
            model,
            dimensions=None,
            base_url=None,
            timeout=None,
        ):
            captured_kwargs.update(
                {
                    "texts": texts,
                    "model": model,
                    "dimensions": dimensions,
                    "base_url": base_url,
                    "timeout": timeout,
                }
            )
            return [[0.1] * (dimensions or 1536) for _ in texts]

        async def resolve_runtime_config(self, db):
            return {
                "base_url": None,
                "default_model": "test-emb-model",
                "default_dims": 1536,
            }

    def register(registry: dict) -> None:
        providers = registry.setdefault("embedding_providers", {})
        providers["test_embedding_provider"] = TestEmbeddingProvider()

    mock_ep = MagicMock()
    mock_ep.name = "geolens.embedding-providers.test"
    mock_ep.load.return_value = register

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        provider_ext = get_embedding_provider("test_embedding_provider")
        vectors = await provider_ext.embed(
            texts=["hello"],
            model="test-emb-model",
            dimensions=1536,
        )
        assert len(vectors) == 1
        assert len(vectors[0]) == 1536
        assert captured_kwargs["model"] == "test-emb-model"
        assert captured_kwargs["dimensions"] == 1536
        assert captured_kwargs["texts"] == ["hello"]

        # Verify community default still resolves correctly even though we
        # added an overlay (registry coexistence — D-10 setdefault discipline).
        assert isinstance(
            get_embedding_provider("openai_compatible"),
            DefaultOpenAIEmbeddingProvider,
        )
