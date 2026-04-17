"""Tests for the ai_send_sample_values feature flag.

Verifies that:
- _should_send_sample_values() respects the PersistentConfig toggle
- _execute_search_tool() omits sample_values when the flag is disabled
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete


@pytest.fixture(autouse=True)
async def _clean_settings(client: AsyncClient):
    """Clean up any DB settings overrides after each test."""
    yield
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.modules.settings.models import AppSetting

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

    async for db in app.dependency_overrides[get_db]():
        with patch(
            "app.processing.ai.service.search_datasets", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = ([fake_ds], 1)
            results = await _execute_search_tool(
                db,
                SimpleNamespace(id="user-1"),
                {"admin"},
                {"q": "test"},
                send_sample_values=True,
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

    async for db in app.dependency_overrides[get_db]():
        with patch(
            "app.processing.ai.service.search_datasets", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = ([fake_ds], 1)
            results = await _execute_search_tool(
                db,
                SimpleNamespace(id="user-1"),
                {"admin"},
                {"q": "test"},
                send_sample_values=False,
            )

    assert len(results) == 1
    assert results[0]["sample_values"] is None
