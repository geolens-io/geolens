"""Tests for the ai_send_sample_values feature flag.

Verifies that:
- _should_send_sample_values() respects the PersistentConfig toggle
- _execute_search_tool() omits sample_values when the flag is disabled
- metadata drafts, map chat and dataset chat SQL context stop carrying samples
  once the flag is turned off, including context cached while it was on
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.persistent_config import AI_SEND_SAMPLE_VALUES
from app.modules.auth.models import User
from app.modules.catalog.maps.models import Map
from app.platform.extensions.defaults import DefaultProcessingPort
from app.processing.ai.metadata_schemas import (
    KeywordSuggestion,
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)
from app.processing.ai.router import _validate_chat_dataset, _validate_chat_layers
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.sql_generator import build_sql_schema_context

from tests.factories import create_dataset

_default_port = DefaultProcessingPort()

_DRAFT_URLS = (
    "/ai/metadata/summary/",
    "/ai/metadata/keywords/",
    "/ai/metadata/lineage/",
    "/ai/metadata/quality-statement/",
)

_DRAFT_RESPONSES = {
    SummaryDraftResponse: SummaryDraftResponse(draft="A summary."),
    KeywordSuggestionsResponse: KeywordSuggestionsResponse(
        keywords=[KeywordSuggestion(keyword="parks", keyword_type="theme")]
    ),
    LineageDraftResponse: LineageDraftResponse(draft="A lineage."),
    QualityStatementDraftResponse: QualityStatementDraftResponse(
        draft="A quality statement."
    ),
}


class _CapturingProvider:
    """Stands in for the configured AI provider and keeps every prompt it is sent."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def resolve_runtime_config(self, _db):
        return {}

    async def structured_complete(self, *, user_message, response_model, **_kw):
        self.prompts.append(user_message)
        return _DRAFT_RESPONSES[response_model], 0, 0


async def _admin(session) -> User:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one()


async def _dataset_with_sample(session, marker: str):
    admin = await _admin(session)
    dataset = await create_dataset(
        session,
        created_by=admin.id,
        record_type="vector_dataset",
        column_info=[{"name": "owner_name", "type": "text"}],
        sample_values={"owner_name": [marker]},
    )
    return admin, dataset


@pytest.fixture(autouse=True)
async def _clean_settings(client: AsyncClient):
    """Clean up any DB settings overrides after each test."""
    yield
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.db.models import AppSetting

    async for db in app.dependency_overrides[get_db]():
        await db.execute(delete(AppSetting))
        await db.commit()

    from app.platform.cache import get_cache

    try:
        cache = get_cache()
        from app.core.persistent_config import _registry

        for cfg in _registry:
            await cache.delete(f"config:{cfg.key}")
    except RuntimeError:
        pass


def _make_fake_dataset(*, with_samples: bool = True):
    """Build a lightweight namespace that looks like a Dataset to _execute_search_tool."""
    record = SimpleNamespace(
        title="Test Dataset",
        summary="A test dataset",
        keywords=[],
        spatial_extent=None,
    )
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        record=record,
        geometry_type="POINT",
        feature_count=100,
        column_info=[{"name": "name", "type": "text"}],
        sample_values={"name": ["Alice", "Bob", "Carol"]} if with_samples else None,
        extent=None,
    )


# ---------------------------------------------------------------------------
# _should_send_sample_values tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_should_send_sample_values_default_true(client: AsyncClient):
    """Default value for ai_send_sample_values is True."""
    from app.processing.ai.service import _should_send_sample_values
    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        result = await _should_send_sample_values(db)
        assert result is True


@pytest.mark.anyio
async def test_should_send_sample_values_respects_toggle(client: AsyncClient):
    """When ai_send_sample_values is set to False, the function returns False."""
    from app.processing.ai.service import _should_send_sample_values
    from app.core.persistent_config import AI_SEND_SAMPLE_VALUES
    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        await AI_SEND_SAMPLE_VALUES.set(db, False)
        result = await _should_send_sample_values(db)
        assert result is False


@pytest.mark.anyio
async def test_an_unreadable_sample_values_setting_withholds_samples(
    client: AsyncClient,
):
    from unittest.mock import AsyncMock, patch

    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import AI_SEND_SAMPLE_VALUES
    from app.processing.ai.service import _should_send_sample_values

    with patch.object(
        AI_SEND_SAMPLE_VALUES, "get", AsyncMock(side_effect=TimeoutError)
    ):
        async for db in app.dependency_overrides[get_db]():
            assert await _should_send_sample_values(db) is False


# ---------------------------------------------------------------------------
# _execute_search_tool integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_tool_includes_samples_when_enabled(client: AsyncClient):
    """_execute_search_tool includes sample_values when send_sample_values=True."""
    from app.processing.ai.service import _execute_search_tool
    from app.core.dependencies import get_db
    from app.api.main import app

    fake_ds = _make_fake_dataset(with_samples=True)

    port = DefaultProcessingPort()
    async for db in app.dependency_overrides[get_db]():
        port.search_datasets = AsyncMock(return_value=([fake_ds], 1))
        results = await _execute_search_tool(
            db,
            SimpleNamespace(id="user-1"),
            {"admin"},
            {"q": "test"},
            send_sample_values=True,
            port=port,
        )

    assert len(results) == 1
    assert results[0]["sample_values"] is not None
    assert "name" in results[0]["sample_values"]


@pytest.mark.anyio
async def test_search_tool_omits_samples_when_disabled(client: AsyncClient):
    """_execute_search_tool omits sample_values when send_sample_values=False."""
    from app.processing.ai.service import _execute_search_tool
    from app.core.dependencies import get_db
    from app.api.main import app

    fake_ds = _make_fake_dataset(with_samples=True)

    port = DefaultProcessingPort()
    async for db in app.dependency_overrides[get_db]():
        port.search_datasets = AsyncMock(return_value=([fake_ds], 1))
        results = await _execute_search_tool(
            db,
            SimpleNamespace(id="user-1"),
            {"admin"},
            {"q": "test"},
            send_sample_values=False,
            port=port,
        )

    assert len(results) == 1
    assert results[0]["sample_values"] is None


# ---------------------------------------------------------------------------
# Provider context built after the flag is turned off
# ---------------------------------------------------------------------------


async def _draft_prompts(
    client: AsyncClient, headers: dict, dataset_id, provider: _CapturingProvider
) -> list[str]:
    provider.prompts.clear()
    for url in _DRAFT_URLS:
        resp = await client.post(
            url, json={"dataset_id": str(dataset_id)}, headers=headers
        )
        assert resp.status_code == 200, f"{url}: {resp.status_code} {resp.text}"
    assert len(provider.prompts) == len(_DRAFT_URLS)
    return list(provider.prompts)


@pytest.mark.anyio
async def test_metadata_draft_prompts_omit_samples_when_disabled(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Every draft prompt drops samples once the flag is off, even right after
    a draft for the same dataset was built while it was on."""
    marker = f"sample-{uuid.uuid4().hex}"
    _admin_user, dataset = await _dataset_with_sample(test_db_session, marker)
    provider = _CapturingProvider()

    with (
        patch("app.processing.ai.router._check_ai_available", new=AsyncMock()),
        patch(
            "app.processing.ai.metadata_service.get_ai_provider",
            return_value=provider,
        ),
    ):
        enabled = await _draft_prompts(client, admin_auth_header, dataset.id, provider)
        await AI_SEND_SAMPLE_VALUES.set(test_db_session, False)
        disabled = await _draft_prompts(client, admin_auth_header, dataset.id, provider)

    assert all(marker in prompt for prompt in enabled)
    assert not any(marker in prompt for prompt in disabled)


@pytest.mark.anyio
async def test_dataset_chat_sql_context_omits_samples_after_disable(
    client: AsyncClient, test_db_session
):
    """The SQL schema context cached with samples is not reused once they are off."""
    marker = f"sample-{uuid.uuid4().hex}"
    admin, dataset = await _dataset_with_sample(test_db_session, marker)
    map_id = f"dataset:{dataset.id}"

    layer = await _validate_chat_dataset(
        test_db_session, admin, str(dataset.id), port=_default_port
    )
    assert marker in build_sql_schema_context([layer], map_id=map_id)

    await AI_SEND_SAMPLE_VALUES.set(test_db_session, False)
    layer = await _validate_chat_dataset(
        test_db_session, admin, str(dataset.id), port=_default_port
    )
    assert marker not in build_sql_schema_context([layer], map_id=map_id)


@pytest.mark.anyio
async def test_map_chat_layers_drop_client_samples_when_disabled(
    client: AsyncClient, test_db_session
):
    """Map chat layers arrive from the client with samples; the flag still applies."""
    marker = f"sample-{uuid.uuid4().hex}"
    admin, dataset = await _dataset_with_sample(test_db_session, marker)
    map_obj = Map(name="Sample policy map", created_by=admin.id, visibility="private")
    test_db_session.add(map_obj)
    await test_db_session.commit()

    def client_layer() -> ChatMapLayer:
        return ChatMapLayer(
            id=str(uuid.uuid4()),
            name="Layer",
            dataset_id=str(dataset.id),
            dataset_table_name=dataset.table_name,
            sample_values={"owner_name": [marker]},
        )

    validated, _basemap, _can_edit = await _validate_chat_layers(
        test_db_session, admin, str(map_obj.id), [client_layer()], port=_default_port
    )
    assert validated[0].sample_values == {"owner_name": [marker]}

    await AI_SEND_SAMPLE_VALUES.set(test_db_session, False)
    validated, _basemap, _can_edit = await _validate_chat_layers(
        test_db_session, admin, str(map_obj.id), [client_layer()], port=_default_port
    )
    assert validated[0].sample_values is None
