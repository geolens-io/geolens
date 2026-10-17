"""Tests for EmbeddingProviderExtension Protocol, registry seeding, and entry-points dispatch.

Covers the Protocol, the default registered via accessor, entry-points overlay
dispatch via importlib.metadata, and ValueError on an unknown provider name.
The architecture-guard test in test_layering.py covers the remaining registry
invariants.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.usefixtures("_clean_registry")


def test_default_embedding_provider_registered():
    """Smoke: get_embedding_provider returns DefaultOpenAIEmbeddingProvider."""
    from app.platform.extensions import get_embedding_provider
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider
    from app.platform.extensions.protocols import EmbeddingProviderExtension

    provider = get_embedding_provider("openai_compatible")
    assert isinstance(provider, DefaultOpenAIEmbeddingProvider)

    # Verify Protocol satisfaction (runtime_checkable)
    assert isinstance(provider, EmbeddingProviderExtension)

    # Singleton stability — two calls return the SAME instance (registry singleton)
    assert get_embedding_provider("openai_compatible") is provider


def test_unknown_embedding_provider_raises_value_error():
    """Unknown name raises ValueError with exact message."""
    from app.platform.extensions import get_embedding_provider

    with pytest.raises(ValueError, match=r"^Unknown embedding provider: bedrock$"):
        get_embedding_provider("bedrock")

    with pytest.raises(ValueError, match=r"^Unknown embedding provider: $"):
        get_embedding_provider("")


@pytest.mark.asyncio
async def test_overlay_embedding_provider_is_dispatched():
    """/ SC#5 / binding: overlay registered via
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
        # added an overlay (registry coexistence — setdefault discipline).
        assert isinstance(
            get_embedding_provider("openai_compatible"),
            DefaultOpenAIEmbeddingProvider,
        )
