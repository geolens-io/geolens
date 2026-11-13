"""A contended row lock answers CatalogLockConflict and leaves the session on the default lock_timeout."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

import app.core.db as db_module
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.collections.service import lock_collection_for_write
from app.modules.catalog.features.retention import hold_table_for_setting
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.service_crud import lock_map_for_asset_write
from app.modules.catalog.maps.service_layers import lock_map_layers
from app.modules.catalog.stories.models import Story
from app.modules.catalog.stories.service import lock_story
from app.platform.catalog_locks import CatalogLockConflict, bounded_row_lock
from tests.factories import create_collection_via_api

pytestmark = pytest.mark.anyio


async def _show_lock_timeout(session) -> str:
    return await session.scalar(text("SHOW lock_timeout"))


async def _assert_conflict_then_default(waiter, call, message: str) -> None:
    default = await _show_lock_timeout(waiter)
    with pytest.raises(CatalogLockConflict) as raised:
        await call()
    assert str(raised.value) == message
    assert await _show_lock_timeout(waiter) == default


async def _map_id(client, headers) -> uuid.UUID:
    resp = await client.post(
        "/maps/", json={"name": f"lock-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def test_map_layers_lock_conflict_restores_default(client, admin_auth_header):
    """lock_map_layers raises the shared conflict and the session keeps its default timeout."""
    map_id = await _map_id(client, admin_auth_header)
    async with db_module.async_session() as holder, db_module.async_session() as waiter:
        await holder.execute(select(Map.id).where(Map.id == map_id).with_for_update())
        await _assert_conflict_then_default(
            waiter,
            lambda: lock_map_layers(waiter, map_id),
            "Another change to this map is in progress. Retry shortly.",
        )
        await holder.rollback()


async def test_map_asset_lock_conflict_restores_default(client, admin_auth_header):
    """lock_map_for_asset_write raises the shared conflict and the session keeps its default timeout."""
    map_id = await _map_id(client, admin_auth_header)
    async with db_module.async_session() as holder, db_module.async_session() as waiter:
        await holder.execute(select(Map.id).where(Map.id == map_id).with_for_update())
        await _assert_conflict_then_default(
            waiter,
            lambda: lock_map_for_asset_write(waiter, map_id),
            "Another change to this map's assets is in progress. Retry shortly.",
        )
        await holder.rollback()


async def test_collection_lock_conflict_restores_default(client, admin_auth_header):
    """lock_collection_for_write raises the shared conflict and the session keeps its default timeout."""
    created = await create_collection_via_api(client, admin_auth_header)
    collection_id = uuid.UUID(created["id"])
    async with db_module.async_session() as holder, db_module.async_session() as waiter:
        await holder.execute(
            select(Collection.id)
            .where(Collection.id == collection_id)
            .with_for_update()
        )
        await _assert_conflict_then_default(
            waiter,
            lambda: lock_collection_for_write(waiter, collection_id),
            "Another change to this collection is in progress. Retry shortly.",
        )
        await holder.rollback()


async def test_story_lock_conflict_restores_default(client, admin_auth_header):
    """lock_story raises the shared conflict and the session keeps its default timeout."""
    resp = await client.post(
        "/stories/", json={"title": "Locked", "summary": ""}, headers=admin_auth_header
    )
    assert resp.status_code == 201, resp.text
    story_id = uuid.UUID(resp.json()["id"])
    async with db_module.async_session() as holder, db_module.async_session() as waiter:
        await holder.execute(
            select(Story.id).where(Story.id == story_id).with_for_update()
        )
        await _assert_conflict_then_default(
            waiter,
            lambda: lock_story(waiter, story_id, None),
            "Another change to this story is in progress. Retry shortly.",
        )
        await holder.rollback()


async def test_retention_table_lock_conflict_restores_default(client):
    """hold_table_for_setting raises the shared conflict and the session keeps its default timeout."""
    table = f"bounded_lock_{uuid.uuid4().hex[:8]}"
    async with db_module.async_session() as setup:
        await setup.execute(
            text(f'CREATE TABLE data."{table}" (id serial PRIMARY KEY)')
        )
        await setup.commit()
    try:
        async with (
            db_module.async_session() as holder,
            db_module.async_session() as waiter,
        ):
            await holder.execute(
                text(f'LOCK TABLE ONLY data."{table}" IN ACCESS EXCLUSIVE MODE')
            )
            await _assert_conflict_then_default(
                waiter,
                lambda: hold_table_for_setting(waiter, table),
                "Another change to this dataset's table is in progress. Retry shortly.",
            )
            await holder.rollback()
    finally:
        async with db_module.async_session() as cleanup:
            await cleanup.execute(text(f'DROP TABLE IF EXISTS data."{table}"'))
            await cleanup.commit()


async def test_bounded_row_lock_reset_flag(client, admin_auth_header):
    """reset=True lifts the bound once the lock is held; reset=False keeps it for the transaction."""
    map_id = await _map_id(client, admin_auth_header)
    stmt = select(Map.id).where(Map.id == map_id).with_for_update()
    async with db_module.async_session() as session:
        default = await _show_lock_timeout(session)
        await bounded_row_lock(session, stmt, what="map", lock_timeout="1500ms")
        assert await _show_lock_timeout(session) == default
        await bounded_row_lock(
            session, stmt, what="map", lock_timeout="1500ms", reset=False
        )
        assert await _show_lock_timeout(session) == "1500ms"
        await session.rollback()
        assert await _show_lock_timeout(session) == default
