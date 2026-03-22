"""Tests for the embedding generation service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.embeddings.service import EmbeddingUnavailableError, generate_embedding


@pytest.mark.asyncio
async def test_generate_embedding_returns_float_vector():
    """generate_embedding returns a list of floats with length matching configured dims."""
    fake_vector = [0.1] * 1536
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=fake_vector)]

    mock_client_instance = MagicMock()
    mock_client_instance.embeddings.create.return_value = mock_response

    mock_session = AsyncMock()

    with (
        patch(
            "app.embeddings.service.build_openai_client",
            return_value=mock_client_instance,
        ),
        patch("app.embeddings.service.settings") as mock_settings,
        patch("app.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.embeddings.service.EMBEDDING_DIMS") as mock_dims,
        patch(
            "app.embeddings.service.resolve_embedding_base_url",
            new_callable=AsyncMock,
            return_value="",
        ),
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="text-embedding-3-small")
        mock_dims.get = AsyncMock(return_value=1536)

        result = await generate_embedding("test text", mock_session)

    assert isinstance(result, list)
    assert len(result) == 1536
    assert all(isinstance(x, float) for x in result)


@pytest.mark.asyncio
async def test_generate_embedding_raises_when_no_openai_key():
    """EmbeddingUnavailableError raised with clear message when only Anthropic key configured."""
    mock_session = AsyncMock()

    with patch("app.embeddings.service.settings") as mock_settings:
        mock_settings.openai_api_key = None

        with pytest.raises(EmbeddingUnavailableError) as exc_info:
            await generate_embedding("test text", mock_session)

        assert "OpenAI-compatible API key" in str(exc_info.value)
        assert "Anthropic" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_embedding_uses_persistent_config():
    """generate_embedding reads model and dims from PersistentConfig."""
    fake_vector = [0.5] * 768
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=fake_vector)]

    mock_client_instance = MagicMock()
    mock_client_instance.embeddings.create.return_value = mock_response

    mock_session = AsyncMock()

    with (
        patch(
            "app.embeddings.service.build_openai_client",
            return_value=mock_client_instance,
        ),
        patch("app.embeddings.service.settings") as mock_settings,
        patch("app.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.embeddings.service.EMBEDDING_DIMS") as mock_dims,
        patch(
            "app.embeddings.service.resolve_embedding_base_url",
            new_callable=AsyncMock,
            return_value="http://localhost:11434/v1",
        ),
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="custom-model")
        mock_dims.get = AsyncMock(return_value=768)

        await generate_embedding("test text", mock_session)

    mock_client_instance.embeddings.create.assert_called_once_with(
        model="custom-model",
        input="test text",
        dimensions=768,
    )


@pytest.mark.asyncio
async def test_generate_embedding_truncates_long_input():
    """generate_embedding handles very long input text."""
    fake_vector = [0.1] * 1536
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=fake_vector)]

    mock_client_instance = MagicMock()
    mock_client_instance.embeddings.create.return_value = mock_response

    mock_session = AsyncMock()

    long_text = "word " * 100_000  # very long input

    with (
        patch(
            "app.embeddings.service.build_openai_client",
            return_value=mock_client_instance,
        ),
        patch("app.embeddings.service.settings") as mock_settings,
        patch("app.embeddings.service.EMBEDDING_MODEL") as mock_model,
        patch("app.embeddings.service.EMBEDDING_DIMS") as mock_dims,
        patch(
            "app.embeddings.service.resolve_embedding_base_url",
            new_callable=AsyncMock,
            return_value="",
        ),
    ):
        mock_settings.openai_api_key = "test-key"
        mock_model.get = AsyncMock(return_value="text-embedding-3-small")
        mock_dims.get = AsyncMock(return_value=1536)

        result = await generate_embedding(long_text, mock_session)

    assert isinstance(result, list)
    # Verify the input was truncated
    call_args = mock_client_instance.embeddings.create.call_args
    actual_input = call_args.kwargs.get("input") or call_args[1].get("input")
    assert len(actual_input) <= 100_000  # should be truncated
