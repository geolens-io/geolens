"""Both service-preview doors refuse an option-like layer name before ogrinfo runs."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_WFS_URL = "https://services.example.test/geoserver/wfs"
_OPTION_LIKE = "--debug"
_REFUSAL = "Invalid layer_name: must not start with '-'"


@pytest.fixture
def no_ogrinfo(monkeypatch: pytest.MonkeyPatch) -> list:
    spawned: list = []

    async def _fake_exec(*cmd, **kwargs):
        spawned.append(cmd)
        raise AssertionError("ogrinfo must not run for a refused layer name")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return spawned


@pytest.mark.parametrize("service_type", ["WFS 2.0.0", "OGC API Features"])
async def test_the_import_preview_refuses_an_option_like_layer_name(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch: pytest.MonkeyPatch,
    no_ogrinfo: list,
    service_type: str,
) -> None:
    monkeypatch.setattr(
        "app.modules.catalog.sources.router.validate_url_for_ssrf", AsyncMock()
    )

    resp = await client.post(
        "/services/preview",
        json={
            "url": _WFS_URL,
            "service_type": service_type,
            "layer_name": _OPTION_LIKE,
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == _REFUSAL
    assert no_ogrinfo == []


async def test_the_reupload_preview_refuses_an_option_like_layer_name(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch: pytest.MonkeyPatch,
    no_ogrinfo: list,
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, name="Option-like layer"
    )
    monkeypatch.setattr(
        "app.modules.catalog.datasets.api.router_reupload.validate_url_for_ssrf",
        AsyncMock(),
    )

    resp = await client.post(
        f"/datasets/{dataset.id}/reupload/service/preview",
        json={
            "url": _WFS_URL,
            "service_type": "WFS 2.0.0",
            "layer_name": _OPTION_LIKE,
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == _REFUSAL
    assert no_ogrinfo == []
