from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.anyio
async def test_get_tile_config_exposes_resolved_public_urls():
    """The public tile-config payload should expose the resolved app/API URLs."""
    from app.settings import router as settings_router

    with (
        patch.object(
            settings_router,
            "app_settings",
            SimpleNamespace(cdn_base_url="https://cdn.example.com"),
        ),
        patch(
            "app.settings.router.get_public_app_url",
            AsyncMock(return_value="https://catalog.example.com"),
        ),
        patch(
            "app.settings.router.get_public_api_url",
            AsyncMock(return_value="https://catalog.example.com/api"),
        ),
    ):
        response = await settings_router.get_tile_config(
            request=SimpleNamespace(headers={}, url=SimpleNamespace(scheme="https"), scope={}),
            db=object(),
        )

    assert response.cdn_base_url == "https://cdn.example.com"
    assert response.public_app_url == "https://catalog.example.com"
    assert response.public_api_url == "https://catalog.example.com/api"
    assert response.public_base_url == "https://catalog.example.com/api"
