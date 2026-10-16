"""The admin token revocations re-check the admin under the maps' row locks,
before any token or cache-denial write.

Each test lets the request's manage_users check pass, commits a change to
the admin's standing from a second session, and lets the request run on.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.admin.service import AdminService
from app.modules.catalog.maps.models import MapShareToken
from app.modules.embed_tokens import admin_router
from app.modules.embed_tokens.models import EmbedToken
from tests.factories import create_user
from tests.test_write_access_recheck_map_sharing import (
    _active_embed_hashes,
    _denied_in_cache,
)
from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _commit,
    _deactivate,
    _map_with_layer,
    _move_to_role,
    people,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_init_tile_pool_for_tests")]


@pytest.fixture
async def shared_map(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A public map its owner has shared and embedded: (map, embed token id,
    embed token hash)."""
    owner_headers, owner_id = people["owner"]
    map_id, _ = await _map_with_layer(test_db_session, owner_id, visibility="public")
    shared = await client.post(f"/maps/{map_id}/share/", headers=owner_headers)
    assert shared.status_code == 200, shared.text
    minted = await client.post(
        f"/maps/{map_id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert minted.status_code == 201, minted.text
    [token_hash] = await _active_embed_hashes(test_db_session, map_id)
    return map_id, uuid.UUID(minted.json()["id"]), token_hash


@pytest.fixture
async def revoking_admin(client: AsyncClient, admin_auth_header: dict) -> tuple:
    headers, user_id = await create_user(client, admin_auth_header, "admin")
    return headers, uuid.UUID(user_id)


def _standing_change(change: str | None, user_id: uuid.UUID):
    if change == "demoted":
        return _move_to_role(user_id, "editor")
    if change == "deactivated":
        return _deactivate(user_id)
    return None


async def _active_shares(map_id: uuid.UUID) -> int:
    async with db_module.async_session() as session:
        return await session.scalar(
            select(func.count())
            .select_from(MapShareToken)
            .where(MapShareToken.map_id == map_id, MapShareToken.is_active.is_(True))
        )


async def _embed_still_live(map_id: uuid.UUID, token_hash: str) -> bool:
    async with db_module.async_session() as session:
        hashes = await _active_embed_hashes(session, map_id)
    return hashes == [token_hash] and not await _denied_in_cache(token_hash)


@pytest.mark.parametrize("change", ["demoted", "deactivated", None])
async def test_the_admin_share_revocation_rechecks_the_admin(
    client: AsyncClient,
    shared_map: tuple,
    revoking_admin: tuple,
    monkeypatch: pytest.MonkeyPatch,
    change: str | None,
) -> None:
    map_id, _, token_hash = shared_map
    headers, admin_id = revoking_admin
    async with db_module.async_session() as session:
        share_id = await session.scalar(
            select(MapShareToken.id).where(MapShareToken.map_id == map_id)
        )
    original = AdminService.revoke_share_token_with_cascade
    statement = _standing_change(change, admin_id)

    # Runs after require_permission("manage_users"), before the map lock.
    async def change_then_revoke(self, token_id, actor):
        if statement is not None:
            await _commit(statement)
        return await original(self, token_id, actor)

    monkeypatch.setattr(
        AdminService, "revoke_share_token_with_cascade", change_then_revoke
    )
    resp = await client.delete(f"/admin/share-tokens/{share_id}", headers=headers)

    if change is None:
        assert resp.status_code == 204, resp.text
        assert await _active_shares(map_id) == 0
        assert not await _embed_still_live(map_id, token_hash)
    else:
        assert resp.status_code == 403, resp.text
        assert await _active_shares(map_id) == 1
        assert await _embed_still_live(map_id, token_hash)


@pytest.mark.parametrize(
    "path", ["/admin/embed-tokens/bulk-revoke/", "/admin/embed-tokens/bulk-revoke"]
)
@pytest.mark.parametrize("change", ["demoted", "deactivated", None])
async def test_the_admin_bulk_embed_revocation_rechecks_the_admin(
    client: AsyncClient,
    shared_map: tuple,
    revoking_admin: tuple,
    monkeypatch: pytest.MonkeyPatch,
    change: str | None,
    path: str,
) -> None:
    map_id, token_id, token_hash = shared_map
    headers, admin_id = revoking_admin
    original = admin_router.lock_maps_for_admin_write
    statement = _standing_change(change, admin_id)

    # Runs after require_permission("manage_users"), before the map locks.
    async def change_then_lock(session, map_ids, user):
        if statement is not None:
            await _commit(statement)
        return await original(session, map_ids, user)

    monkeypatch.setattr(admin_router, "lock_maps_for_admin_write", change_then_lock)
    resp = await client.post(path, json={"token_ids": [str(token_id)]}, headers=headers)

    if change is None:
        assert resp.status_code == 200, resp.text
        assert resp.json()["revoked_count"] == 1
        assert not await _embed_still_live(map_id, token_hash)
    else:
        assert resp.status_code == 403, resp.text
        assert await _embed_still_live(map_id, token_hash)
    async with db_module.async_session() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(EmbedToken)
            .where(EmbedToken.id == token_id, EmbedToken.is_active.is_(True))
        )
    assert active == (0 if change is None else 1)
