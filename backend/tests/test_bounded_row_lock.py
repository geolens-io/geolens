"""Each lock site raises CatalogLockConflict with its message, answers the keyed 409, and keeps its lock_timeout scope."""

from __future__ import annotations

import base64
import uuid
from io import BytesIO

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy import select, text

import app.core.db as db_module
from app.modules.catalog.collections.service import lock_collection_for_write
from app.modules.catalog.features.retention import hold_table_for_setting
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.service_crud import lock_map_for_asset_write
from app.modules.catalog.maps.service_layers import lock_map_layers
from app.modules.catalog.stories.models import Story
from app.modules.catalog.stories.service import _bounded_lock
from app.platform.catalog_locks import CatalogLockConflict, bounded_row_lock
from tests.factories import create_collection_via_api

pytestmark = pytest.mark.anyio


_STORY = "Another change to this story is in progress. Retry shortly."
_MAP = "Another change to this map is in progress. Retry shortly."
_COLLECTION = "Another change to this collection is in progress. Retry shortly."
_ASSET = "Another write to this map's assets is in progress. Retry shortly."
_TABLE = "Another operation is changing this dataset's table."


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _fail_locking_statements(session, monkeypatch, sqlstate: str) -> None:
    real = session.execute

    async def execute(stmt, *args, **kwargs):
        if "FOR " in str(stmt) or "LOCK TABLE" in str(stmt):
            raise DBAPIError("lock", {}, _Orig(sqlstate))
        return await real(stmt, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute)


async def _show(session) -> str:
    return await session.scalar(text("SHOW lock_timeout"))


async def _new_map(client, headers) -> uuid.UUID:
    resp = await client.post(
        "/maps/", json={"name": f"lock-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _fixtures(client, headers):
    map_id = await _new_map(client, headers)
    coll = uuid.UUID((await create_collection_via_api(client, headers))["id"])
    story = await client.post(
        "/stories/", json={"title": "Locked", "summary": ""}, headers=headers
    )
    assert story.status_code == 201, story.text
    return map_id, coll, uuid.UUID(story.json()["id"])


# (name, conflict message, resets the bound after the lock)
_SITES = [
    ("story", _STORY, True),
    ("map", _MAP, True),
    ("asset", _ASSET, False),
    ("collection", _COLLECTION, True),
    ("table", _TABLE, False),
]


def _call(name, session, map_id, coll, story, table):
    return {
        "story": lambda: _bounded_lock(
            session, select(Story).where(Story.id == story).with_for_update()
        ),
        "map": lambda: lock_map_layers(session, map_id),
        "asset": lambda: lock_map_for_asset_write(session, map_id),
        "collection": lambda: lock_collection_for_write(session, coll),
        "table": lambda: hold_table_for_setting(session, table),
    }[name]()


@pytest.fixture
async def data_table(client):
    table = f"bounded_lock_{uuid.uuid4().hex[:8]}"
    async with db_module.async_session() as setup:
        await setup.execute(
            text(f'CREATE TABLE data."{table}" (id serial PRIMARY KEY)')
        )
        await setup.commit()
    yield table
    async with db_module.async_session() as cleanup:
        await cleanup.execute(text(f'DROP TABLE IF EXISTS data."{table}"'))
        await cleanup.commit()


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01"])
@pytest.mark.parametrize(("name", "expected", "_reset"), _SITES)
async def test_conflict_keeps_site_body_and_default_timeout(
    client, admin_auth_header, data_table, monkeypatch, name, expected, _reset, sqlstate
):
    """A lost wait or deadlock raises CatalogLockConflict with the site's message and the rolled-back session is on its default timeout."""
    map_id, coll, story = await _fixtures(client, admin_auth_header)
    async with db_module.async_session() as waiter:
        default = await _show(waiter)
        _fail_locking_statements(waiter, monkeypatch, sqlstate)
        with pytest.raises(CatalogLockConflict) as raised:
            await _call(name, waiter, map_id, coll, story, data_table)
        assert str(raised.value) == expected
        monkeypatch.undo()
        assert await _show(waiter) == default


@pytest.mark.parametrize(("name", "_expected", "resets"), _SITES)
async def test_success_resets_the_bound_only_where_it_did_before(
    client, admin_auth_header, data_table, name, _expected, resets
):
    """After the lock is held, story, map layer and collection sites are back on the default timeout; map image and table sites keep 2s."""
    map_id, coll, story = await _fixtures(client, admin_auth_header)
    async with db_module.async_session() as session:
        default = await _show(session)
        await _call(name, session, map_id, coll, story, data_table)
        assert await _show(session) == (default if resets else "2s")
        await session.rollback()
        assert await _show(session) == default


def _keyed(message: str) -> dict:
    return {"code": "catalog_lock_conflict", "message": message}


async def _held_request(client, headers, name, map_id, coll, story):
    """Send the route whose lock ``name`` names while another session holds its row."""
    model, row, request = {
        "story": (
            Story,
            story,
            lambda: client.delete(f"/stories/{story}", headers=headers),
        ),
        "map": (
            Map,
            map_id,
            lambda: client.put(
                f"/maps/{map_id}/groups/", json={"group_ids": []}, headers=headers
            ),
        ),
        "asset": (
            Map,
            map_id,
            lambda: client.put(
                f"/maps/{map_id}/thumbnail/",
                json={"data_uri": _thumbnail()},
                headers=headers,
            ),
        ),
        "collection": (
            Collection,
            coll,
            lambda: client.patch(
                f"/catalog/collections/{coll}",
                json={"description": "held"},
                headers=headers,
            ),
        ),
    }[name]
    async with db_module.async_session() as holder:
        await holder.execute(select(model.id).where(model.id == row).with_for_update())
        try:
            return await request()
        finally:
            await holder.rollback()


def _thumbnail() -> str:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(128, 64, 32)).save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("story", _STORY), ("map", _MAP), ("asset", _ASSET), ("collection", _COLLECTION)],
)
async def test_held_row_answers_the_keyed_409(
    client, admin_auth_header, name, expected
):
    """A route waiting on a held story, map, map image or collection row answers 409 catalog_lock_conflict with the site's message."""
    map_id, coll, story = await _fixtures(client, admin_auth_header)
    resp = await _held_request(client, admin_auth_header, name, map_id, coll, story)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _keyed(expected)


async def test_bounded_row_lock_reset_flag(client, admin_auth_header):
    """reset=True lifts the bound once the lock is held; reset=False keeps it for the transaction."""
    map_id = await _new_map(client, admin_auth_header)
    stmt = select(Map.id).where(Map.id == map_id).with_for_update()
    async with db_module.async_session() as session:
        default = await _show(session)
        await bounded_row_lock(session, stmt, message="busy")
        assert await _show(session) == default
        await bounded_row_lock(
            session,
            stmt,
            message="busy",
            lock_timeout="1500ms",
            reset=False,
        )
        assert await _show(session) == "1500ms"
        await session.rollback()
        assert await _show(session) == default
