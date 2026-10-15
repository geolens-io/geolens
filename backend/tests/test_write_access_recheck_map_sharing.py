"""Map share, embed token and layer-removal writes re-check the caller under
the map row lock, before any cache denial no rollback can undo.

Each test lets the handler's guard pass, commits a change to the caller's
standing from a second session straight after it, and lets the request run on.
The write must be refused with the guard's 403 or 404 and leave nothing behind.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.catalog.maps import router as maps_router
from app.modules.catalog.maps import router_sharing
from app.modules.catalog.maps.models import MapLayer, MapShareToken
from app.modules.embed_tokens import router as embed_router
from app.modules.embed_tokens.models import EmbedToken
from app.platform.cache import tenant_cache_key
from app.platform.cache.provider import get_cache

from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _deactivate,
    _demote_to_viewer,
    _map_with_layer,
    _then,
    _transfer_map,
    people,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_init_tile_pool_for_tests")]


async def _denied_in_cache(token_hash: str) -> bool:
    entry = await get_cache().get(tenant_cache_key(f"embed_token:{token_hash}"))
    return entry is not None and entry.get("is_valid") is False


async def _active_embed_hashes(session: AsyncSession, map_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(EmbedToken.token_hash).where(
            EmbedToken.map_id == map_id, EmbedToken.is_active.is_(True)
        )
    )
    return list(result.scalars())


async def test_embed_token_mint_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    map_id, _ = await _map_with_layer(test_db_session, owner_id)
    first = await client.post(
        f"/maps/{map_id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert first.status_code == 201, first.text
    [held] = await _active_embed_hashes(test_db_session, map_id)

    monkeypatch.setattr(
        embed_router,
        "check_map_ownership",
        _then(
            embed_router.check_map_ownership, _transfer_map(map_id, people["target"])
        ),
    )
    resp = await client.post(
        f"/maps/{map_id}/embed-tokens/", json={}, headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert await _active_embed_hashes(test_db_session, map_id) == [held]
    assert not await _denied_in_cache(held)


async def test_embed_token_revoke_is_refused_after_a_role_downgrade(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    map_id, _ = await _map_with_layer(test_db_session, owner_id)
    created = await client.post(
        f"/maps/{map_id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert created.status_code == 201, created.text
    [held] = await _active_embed_hashes(test_db_session, map_id)

    monkeypatch.setattr(
        embed_router,
        "check_map_ownership",
        _then(embed_router.check_map_ownership, _demote_to_viewer(owner_id)),
    )
    resp = await client.delete(
        f"/maps/{map_id}/embed-tokens/{created.json()['id']}/", headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Missing permission: edit_metadata"
    assert await _active_embed_hashes(test_db_session, map_id) == [held]
    assert not await _denied_in_cache(held)


async def test_share_revoke_is_refused_after_a_deactivation(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    map_id, _ = await _map_with_layer(test_db_session, owner_id, visibility="public")
    shared = await client.post(f"/maps/{map_id}/share/", headers=owner_headers)
    assert shared.status_code == 200, shared.text
    minted = await client.post(
        f"/maps/{map_id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert minted.status_code == 201, minted.text
    [held] = await _active_embed_hashes(test_db_session, map_id)

    monkeypatch.setattr(
        router_sharing,
        "check_map_ownership",
        _then(router_sharing.check_map_ownership, _deactivate(owner_id)),
    )
    resp = await client.delete(f"/maps/{map_id}/share/", headers=owner_headers)

    assert resp.status_code == 403, resp.text
    active_shares = await test_db_session.scalar(
        select(func.count())
        .select_from(MapShareToken)
        .where(MapShareToken.map_id == map_id, MapShareToken.is_active.is_(True))
    )
    assert active_shares == 1
    assert await _active_embed_hashes(test_db_session, map_id) == [held]
    assert not await _denied_in_cache(held)


async def test_share_expiry_update_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    map_id, _ = await _map_with_layer(test_db_session, owner_id, visibility="public")
    shared = await client.post(f"/maps/{map_id}/share/", headers=owner_headers)
    assert shared.status_code == 200, shared.text
    expiry = select(MapShareToken.expires_at).where(MapShareToken.map_id == map_id)
    before = await test_db_session.scalar(expiry)

    monkeypatch.setattr(
        router_sharing,
        "check_map_ownership",
        _then(
            router_sharing.check_map_ownership, _transfer_map(map_id, people["target"])
        ),
    )
    resp = await client.patch(
        f"/maps/{map_id}/share/", json={"expires_in_days": 7}, headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    async with db_module.async_session() as session:
        assert await session.scalar(expiry) == before


@pytest.mark.parametrize("bulk", [False, True])
async def test_layer_removal_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    bulk: bool,
) -> None:
    owner_headers, owner_id = people["owner"]
    map_id, layer_id = await _map_with_layer(test_db_session, owner_id)

    monkeypatch.setattr(
        maps_router,
        "check_map_ownership",
        _then(maps_router.check_map_ownership, _transfer_map(map_id, people["target"])),
    )
    if bulk:
        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": [str(layer_id)]},
            headers=owner_headers,
        )
    else:
        resp = await client.delete(
            f"/maps/{map_id}/layers/{layer_id}", headers=owner_headers
        )

    assert resp.status_code == 403, resp.text
    assert await test_db_session.scalar(
        select(MapLayer.id).where(MapLayer.id == layer_id)
    )
