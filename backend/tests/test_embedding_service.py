"""Tests for the embedding generation service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.processing.embeddings.service import (
    EmbeddingUnavailableError,
    generate_embedding,
)


def _make_mock_provider(
    *,
    embed_return,
    runtime_base_url="",
    runtime_default_model="text-embedding-3-small",
    runtime_default_dims=1536,
):
    """Build a MagicMock with AsyncMock embed/resolve_runtime_config (Phase 231 D-27)."""
    mock_provider = MagicMock()
    mock_provider.embed = AsyncMock(return_value=embed_return)
    mock_provider.resolve_runtime_config = AsyncMock(
        return_value={
            "base_url": runtime_base_url,
            "default_model": runtime_default_model,
            "default_dims": runtime_default_dims,
        }
    )
    return mock_provider


@pytest.mark.asyncio
async def test_generate_embedding_returns_float_vector():
    """generate_embedding returns a list of floats with length matching configured dims."""
    fake_vector = [0.1] * 1536
    mock_provider = _make_mock_provider(embed_return=[fake_vector])
    mock_session = AsyncMock()

    with (
        patch(
            "app.processing.embeddings.service.get_embedding_provider",
            return_value=mock_provider,
        ),
        patch("app.processing.embeddings.service.settings") as mock_settings,
        patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.processing.embeddings.service.EMBEDDING_DIMS") as mock_dims,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="text-embedding-3-small")
        mock_dims.get = AsyncMock(return_value=1536)

        result = await generate_embedding("test text", mock_session)

    assert isinstance(result, list)
    assert len(result) == 1536
    assert all(isinstance(x, float) for x in result)
    # Provider-boundary call shape (D-27)
    mock_provider.embed.assert_called_once_with(
        texts=["test text"],
        model="text-embedding-3-small",
        dimensions=1536,
        base_url="",
        timeout=130.0,
    )


@pytest.mark.asyncio
async def test_generate_embedding_raises_when_no_openai_key():
    """EmbeddingUnavailableError raised with clear message when only Anthropic key configured.

    UNCHANGED post-Phase-231 — the API-key check stays at service.py:47-53
    (defense in depth per RESEARCH.md Open Question 2 / D-22 fallback).
    """
    mock_session = AsyncMock()

    with patch("app.processing.embeddings.service.settings") as mock_settings:
        mock_settings.openai_api_key = None

        with pytest.raises(EmbeddingUnavailableError) as exc_info:
            await generate_embedding("test text", mock_session)

        assert "OpenAI-compatible API key" in str(exc_info.value)
        assert "Anthropic" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_embedding_uses_persistent_config():
    """generate_embedding reads model and dims from PersistentConfig."""
    fake_vector = [0.5] * 768
    mock_provider = _make_mock_provider(embed_return=[fake_vector])
    mock_session = AsyncMock()

    with (
        patch(
            "app.processing.embeddings.service.get_embedding_provider",
            return_value=mock_provider,
        ),
        patch("app.processing.embeddings.service.settings") as mock_settings,
        patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.processing.embeddings.service.EMBEDDING_DIMS") as mock_dims,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="custom-model")
        mock_dims.get = AsyncMock(return_value=768)

        result = await generate_embedding("test text", mock_session)

    assert len(result) == 768
    # PersistentConfig values flow through to provider_ext.embed kwargs (D-27)
    mock_provider.embed.assert_called_once_with(
        texts=["test text"],
        model="custom-model",
        dimensions=768,
        base_url="",
        timeout=130.0,
    )


@pytest.mark.asyncio
async def test_generate_embedding_truncates_long_input():
    """Long input (> _MAX_INPUT_CHARS) is truncated before being sent to the provider."""
    from app.processing.embeddings.service import _MAX_INPUT_CHARS

    long_text = "x" * (_MAX_INPUT_CHARS + 1000)
    fake_vector = [0.0] * 1536
    mock_provider = _make_mock_provider(embed_return=[fake_vector])
    mock_session = AsyncMock()

    with (
        patch(
            "app.processing.embeddings.service.get_embedding_provider",
            return_value=mock_provider,
        ),
        patch("app.processing.embeddings.service.settings") as mock_settings,
        patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.processing.embeddings.service.EMBEDDING_DIMS") as mock_dims,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="text-embedding-3-small")
        mock_dims.get = AsyncMock(return_value=1536)

        await generate_embedding(long_text, mock_session)

    # Truncation happens in service.py BEFORE the provider call (D-27).
    call_kwargs = mock_provider.embed.call_args.kwargs
    passed_text = call_kwargs["texts"][0]
    assert len(passed_text) == _MAX_INPUT_CHARS


@pytest.mark.asyncio
async def test_generate_embedding_dimension_mismatch():
    """Service passes through whatever the provider returns, even if length differs from configured dims."""
    # Provider returns 768-dim vector despite request for 1536
    returned_vector = [0.2] * 768
    mock_provider = _make_mock_provider(embed_return=[returned_vector])
    mock_session = AsyncMock()

    with (
        patch(
            "app.processing.embeddings.service.get_embedding_provider",
            return_value=mock_provider,
        ),
        patch("app.processing.embeddings.service.settings") as mock_settings,
        patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.processing.embeddings.service.EMBEDDING_DIMS") as mock_dims,
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="text-embedding-3-small")
        mock_dims.get = AsyncMock(return_value=1536)

        result = await generate_embedding("test text", mock_session)

    # Service does NOT enforce dimension match — that's a downstream pgvector concern.
    assert len(result) == 768
    # The REQUESTED dims value is what the service sent to the provider.
    call_kwargs = mock_provider.embed.call_args.kwargs
    assert call_kwargs["dimensions"] == 1536
