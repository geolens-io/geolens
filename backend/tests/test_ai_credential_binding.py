"""Security regression tests for environment AI credential destination binding."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_credentials import (
    OpenAICredentialDestinationError,
    bind_openai_credential_base_url,
    validate_persistent_openai_base_url,
)
from app.core.config import settings


@pytest.fixture
def operator_openai_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Bind the synthetic environment key to two explicit operator URLs."""
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(
        settings,
        "openai_base_url",
        "http://llm.internal:11434/v1/",
    )
    monkeypatch.setattr(
        settings,
        "embedding_base_url",
        "http://embeddings.internal:11434/v1/",
    )
    from app.platform.extensions.defaults import (
        DefaultOpenAICompatibleProvider,
        DefaultOpenAIEmbeddingProvider,
    )

    DefaultOpenAICompatibleProvider._clients.clear()
    DefaultOpenAIEmbeddingProvider._clients.clear()
    yield
    DefaultOpenAICompatibleProvider._clients.clear()
    DefaultOpenAIEmbeddingProvider._clients.clear()


def test_binding_preserves_explicit_operator_http_endpoints(
    operator_openai_config: None,
) -> None:
    """Private HTTP services remain valid when the operator explicitly chose them."""
    assert (
        bind_openai_credential_base_url(
            "http://LLM.internal:11434/v1",
            purpose="chat",
        )
        == "http://llm.internal:11434/v1"
    )
    assert (
        bind_openai_credential_base_url(
            "http://embeddings.internal:11434/v1",
            purpose="embedding",
        )
        == "http://embeddings.internal:11434/v1"
    )


def test_blank_persistent_override_preserves_operator_fallback(
    operator_openai_config: None,
) -> None:
    assert validate_persistent_openai_base_url("", purpose="chat") == ""
    assert validate_persistent_openai_base_url("  ", purpose="embedding") == ""
    assert (
        bind_openai_credential_base_url("", purpose="chat")
        == "http://llm.internal:11434/v1"
    )
    assert (
        bind_openai_credential_base_url(None, purpose="embedding")
        == "http://embeddings.internal:11434/v1"
    )


def test_binding_rejects_a_different_runtime_destination(
    operator_openai_config: None,
) -> None:
    with pytest.raises(OpenAICredentialDestinationError, match="operator-approved"):
        bind_openai_credential_base_url(
            "https://credential-capture.invalid/v1",
            purpose="chat",
        )


def test_endpoint_can_be_staged_before_operator_supplies_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-key deployments retain the existing configure-endpoint-first workflow."""
    monkeypatch.setattr(settings, "openai_api_key", None)
    assert (
        bind_openai_credential_base_url(
            "http://future-provider.internal:8000/v1/",
            purpose="chat",
        )
        == "http://future-provider.internal:8000/v1"
    )


@pytest.mark.anyio
async def test_manage_settings_cannot_rebind_environment_key(
    client: AsyncClient,
    admin_auth_header: dict,
    operator_openai_config: None,
) -> None:
    response = await client.put(
        "/settings/",
        json={"settings": {"openai_base_url": "https://credential-capture.invalid/v1"}},
        headers=admin_auth_header,
    )

    assert response.status_code == 422
    assert "operator-approved OPENAI_BASE_URL" in response.json()["detail"]


@pytest.mark.anyio
async def test_config_import_cannot_rebind_environment_key(
    operator_openai_config: None,
) -> None:
    from app.platform.config_ops.exceptions import ConfigValidationError
    from app.platform.config_ops.service import import_config

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.commit = AsyncMock()

    with pytest.raises(
        ConfigValidationError, match="operator-approved OPENAI_BASE_URL"
    ):
        await import_config(
            db=mock_db,
            data={
                "settings": {"openai_base_url": "https://credential-capture.invalid/v1"}
            },
            mode="merge",
            user_id=uuid.uuid4(),
            ip_address=None,
        )
    mock_db.commit.assert_not_called()


@pytest.mark.anyio
async def test_chat_runtime_resolver_rejects_stale_database_override(
    operator_openai_config: None,
) -> None:
    from app.core.persistent_config import LLM_MODEL, OPENAI_BASE_URL
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider

    provider = DefaultOpenAICompatibleProvider()
    with (
        patch.object(
            OPENAI_BASE_URL,
            "get",
            AsyncMock(return_value="https://credential-capture.invalid/v1"),
        ),
        patch.object(LLM_MODEL, "get", AsyncMock(return_value="test-model")),
        pytest.raises(OpenAICredentialDestinationError),
    ):
        await provider.resolve_runtime_config(MagicMock())


@pytest.mark.anyio
async def test_embedding_runtime_resolver_rejects_stale_database_override(
    operator_openai_config: None,
) -> None:
    from app.core.persistent_config import (
        EMBEDDING_BASE_URL,
        EMBEDDING_DIMS,
        EMBEDDING_MODEL,
    )
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider

    provider = DefaultOpenAIEmbeddingProvider()
    with (
        patch.object(
            EMBEDDING_BASE_URL,
            "get",
            AsyncMock(return_value="https://credential-capture.invalid/v1"),
        ),
        patch.object(EMBEDDING_MODEL, "get", AsyncMock(return_value="test-embedding")),
        patch.object(EMBEDDING_DIMS, "get", AsyncMock(return_value=3)),
        pytest.raises(OpenAICredentialDestinationError),
    ):
        await provider.resolve_runtime_config(MagicMock())


def test_chat_client_checks_binding_before_cache_lookup(
    operator_openai_config: None,
) -> None:
    """A stale client cache entry cannot bypass the new runtime invariant."""
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider
    from app.processing.ai.llm_loop import get_openai_client

    capture_url = "https://credential-capture.invalid/v1"
    stale_client = object()
    DefaultOpenAICompatibleProvider._clients[capture_url] = stale_client
    try:
        with pytest.raises(OpenAICredentialDestinationError):
            get_openai_client(capture_url)
    finally:
        DefaultOpenAICompatibleProvider._clients.pop(capture_url, None)


def test_chat_client_pairs_key_only_with_operator_destination(
    operator_openai_config: None,
) -> None:
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider
    from app.processing.ai.llm_loop import get_openai_client

    approved = "http://llm.internal:11434/v1"
    DefaultOpenAICompatibleProvider._clients.clear()
    constructed = MagicMock()
    with patch("openai.AsyncOpenAI", return_value=constructed) as client_factory:
        assert get_openai_client(approved) is constructed

    kwargs = client_factory.call_args.kwargs
    assert kwargs["api_key"] == "synthetic-test-key"
    assert kwargs["base_url"] == approved


@pytest.mark.anyio
async def test_embedding_client_pairs_key_only_with_operator_destination(
    operator_openai_config: None,
) -> None:
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider

    approved = "http://embeddings.internal:11434/v1"
    DefaultOpenAIEmbeddingProvider._clients.clear()
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])
    )

    provider = DefaultOpenAIEmbeddingProvider()
    with patch("openai.AsyncOpenAI", return_value=fake_client) as client_factory:
        vectors = await provider.embed(
            texts=["hello"],
            model="test-embedding",
            dimensions=3,
            base_url=approved,
        )

    assert vectors == [[0.1, 0.2, 0.3]]
    kwargs = client_factory.call_args.kwargs
    assert kwargs["api_key"] == "synthetic-test-key"
    assert kwargs["base_url"] == approved


@pytest.mark.anyio
async def test_embedding_client_rejects_rebinding_before_construction(
    operator_openai_config: None,
) -> None:
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider

    provider = DefaultOpenAIEmbeddingProvider()
    with (
        patch("openai.AsyncOpenAI") as client_factory,
        pytest.raises(OpenAICredentialDestinationError),
    ):
        await provider.embed(
            texts=["hello"],
            model="test-embedding",
            dimensions=3,
            base_url="https://credential-capture.invalid/v1",
        )
    client_factory.assert_not_called()
