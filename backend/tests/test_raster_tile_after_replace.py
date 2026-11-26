"""A raster tile whose cached snapshot names a replaced file is rendered from the new one."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import text

from app.processing.tiles import router as tile_router

from tests.factories import get_user_id
from tests.test_perf002_raster_meta_cache import (
    _create_public_raster,
    _swap_raster_pointer,
)

_OLD_TILE = b"\x89PNG old"
_NEW_TILE = b"\x89PNG new"


def _opened(call) -> str:
    return httpx.URL(call.args[0]).params["url"]


class _Titiler:
    """Serves tiles for the files in ``present``; any other file is missing."""

    def __init__(self, present: dict[str, bytes]):
        self.present = present
        self.client = AsyncMock()
        self.client.get.side_effect = self._get

    async def _get(self, url: str) -> httpx.Response:
        source = httpx.URL(url).params["url"]
        for key, body in self.present.items():
            if source.endswith(key):
                return httpx.Response(
                    200, content=body, headers={"content-type": "image/png"}
                )
        return httpx.Response(
            500, json={"detail": f"{source}: No such file or directory"}
        )

    def opened(self) -> list[str]:
        return [_opened(call) for call in self.client.get.call_args_list]


async def _raster(session):
    dataset = await _create_public_raster(
        session, created_by=await get_user_id(session, "admin")
    )
    (old_uri,) = (
        await session.execute(
            text("SELECT asset_uri FROM catalog.raster_assets WHERE dataset_id = :id"),
            {"id": dataset.id},
        )
    ).one()
    return dataset, old_uri


async def _tile(client, dataset_id: uuid.UUID, **params):
    return await client.get(
        f"/tiles/raster-proxy/{dataset_id}/8/75/96.png", params=params
    )


async def test_a_tile_after_a_replace_is_rendered_from_the_new_file(
    client, test_db_session
):
    dataset, old_uri = await _raster(test_db_session)
    titiler = _Titiler({old_uri: _OLD_TILE})
    with patch.object(tile_router, "_titiler_client", titiler.client):
        warm = await _tile(client, dataset.id)
        new_uri = await _swap_raster_pointer(test_db_session, dataset.id)
        titiler.present = {new_uri: _NEW_TILE}

        unversioned = await _tile(client, dataset.id)
        old_version = await _tile(client, dataset.id, v="1")

    assert warm.content == _OLD_TILE
    assert unversioned.status_code == 200
    assert unversioned.content == _NEW_TILE
    assert old_version.status_code == 200
    assert old_version.content == _NEW_TILE
    # A `v` behind the row is served, but never into the shared cache.
    assert "no-store" in old_version.headers["cache-control"]
    assert titiler.opened()[-1].endswith(new_uri)


async def test_a_failure_with_the_file_unchanged_surfaces_after_one_render(
    client, test_db_session
):
    dataset, old_uri = await _raster(test_db_session)
    titiler = _Titiler({})
    with patch.object(tile_router, "_titiler_client", titiler.client):
        response = await _tile(client, dataset.id)

    assert response.status_code == 500
    # The transport retry loop's three attempts, and no second render.
    opened = titiler.opened()
    assert len(opened) == 3
    assert all(path.endswith(old_uri) for path in opened)


async def test_the_render_after_a_replace_is_authorized_from_the_fresh_snapshot(
    client, test_db_session
):
    dataset, old_uri = await _raster(test_db_session)
    titiler = _Titiler({old_uri: _OLD_TILE})
    with patch.object(tile_router, "_titiler_client", titiler.client):
        warm = await _tile(client, dataset.id)
        new_uri = await _swap_raster_pointer(test_db_session, dataset.id)
        await test_db_session.execute(
            text("UPDATE catalog.records SET visibility = 'private' WHERE id = :id"),
            {"id": dataset.record_id},
        )
        await test_db_session.commit()
        titiler.present = {new_uri: _NEW_TILE}

        refused = await _tile(client, dataset.id)

    assert warm.status_code == 200
    assert refused.status_code in (403, 404)
    assert not any(path.endswith(new_uri) for path in titiler.opened())
