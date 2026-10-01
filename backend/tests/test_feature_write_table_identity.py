"""A feature write by gid must not land in a table that replaced the one read.

A reupload swaps a new table in under the dataset's table name, and the owner
of a registered table can drop and recreate it. Either way the new table can
reuse gids, so an editor opened before the replacement would write to an
unrelated feature. Reads return a ``table_id``; a write that sends it back is
refused once the table it names is gone.
"""

import asyncio
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import is_lock_conflict
from app.modules.catalog.features import router as features_router

from tests.factories import create_dataset, get_user_id

PARIS = {"type": "Point", "coordinates": [2.35, 48.85]}
LONDON = {"type": "Point", "coordinates": [-0.13, 51.51]}
_COLUMNS = (
    "gid serial PRIMARY KEY, geom geometry(Point, 4326), "
    "geom_4326 geometry(Point, 4326), name text"
)


async def _drop(session, dataset) -> None:
    for table in (dataset.table_name, f"{dataset.table_name}_next"):
        await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


@pytest.fixture
async def dataset(client: AsyncClient, admin_auth_header, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    table = f"ident_{uuid.uuid4().hex[:10]}"
    seeded = await create_dataset(
        test_db_session,
        created_by=admin_id,
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=0,
        column_info=[{"name": "name", "type": "character varying"}],
    )
    await test_db_session.execute(text(f'CREATE TABLE "data"."{table}" ({_COLUMNS})'))
    await test_db_session.commit()
    yield seeded
    await _drop(test_db_session, seeded)


async def _add(client: AsyncClient, dataset, headers: dict) -> dict:
    response = await client.post(
        f"/datasets/{dataset.id}/features/",
        json={"geometry": PARIS, "properties": {"name": "pin"}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _read(client: AsyncClient, dataset, headers: dict, gid: int) -> dict:
    response = await client.get(
        f"/datasets/{dataset.id}/features/{gid}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _write(
    method: str,
    client: AsyncClient,
    dataset,
    headers: dict,
    gid: int,
    table_id: str | None,
):
    url = f"/datasets/{dataset.id}/features/{gid}"
    params = {} if table_id is None else {"table_id": table_id}
    if method == "put":
        return client.put(
            url,
            json={"geometry": LONDON, "properties": {"name": "mine"}},
            params=params,
            headers=headers,
        )
    if method == "patch":
        return client.patch(
            url, json={"properties": {"name": "mine"}}, params=params, headers=headers
        )
    return client.delete(url, params=params, headers=headers)


_APPLIED = {"put": 200, "patch": 200, "delete": 204}


def _keyed_create(client: AsyncClient, dataset, headers: dict, key: str, attempt: int):
    return client.post(
        f"/datasets/{dataset.id}/features/",
        json={"geometry": PARIS, "properties": {"name": f"attempt {attempt}"}},
        headers={
            **headers,
            "Idempotency-Key": key,
            "Idempotency-Attempt": str(attempt),
        },
    )


async def _stage_replacement(session, dataset, gid: int, how: str) -> None:
    """Put a new table under the dataset's name, holding ``gid`` for another row.

    ``reupload`` swaps it in the way a reupload does and bumps the versions;
    ``overwrite`` drops and recreates the table the way a registered table's
    owner can, and GeoLens records nothing. The caller commits.
    """
    table = dataset.table_name
    target = f"{table}_next" if how == "reupload" else table
    if how == "overwrite":
        await session.execute(text(f'DROP TABLE "data"."{table}"'))
    await session.execute(text(f'CREATE TABLE "data"."{target}" ({_COLUMNS})'))
    await session.execute(
        text(
            f'INSERT INTO "data"."{target}" (gid, geom, geom_4326, name) VALUES '
            "(:gid, ST_SetSRID(ST_MakePoint(9, 9), 4326), "
            "ST_SetSRID(ST_MakePoint(9, 9), 4326), 'unrelated')"
        ),
        {"gid": gid},
    )
    if how == "reupload":
        await session.execute(
            text(f'ALTER TABLE "data"."{table}" RENAME TO "{table}_old"')
        )
        await session.execute(
            text(f'ALTER TABLE "data"."{target}" RENAME TO "{table}"')
        )
        await session.execute(text(f'DROP TABLE "data"."{table}_old"'))
        await session.execute(
            text(
                "UPDATE catalog.datasets SET current_version = current_version + 1, "
                "tile_cache_version = tile_cache_version + 1 WHERE id = :id"
            ),
            {"id": dataset.id},
        )


async def _rows(session, dataset) -> list[tuple]:
    result = await session.execute(
        text(
            "SELECT gid, name, ST_X(geom_4326), ST_Y(geom_4326) "
            f'FROM "data"."{dataset.table_name}" ORDER BY gid'
        )
    )
    return [tuple(row) for row in result]


async def _tile_cache_version(session, dataset) -> int:
    return await session.scalar(
        text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
        {"id": dataset.id},
    )


@pytest.mark.parametrize("how", ["reupload", "overwrite"])
@pytest.mark.parametrize("method", ["put", "patch", "delete"])
async def test_a_write_read_before_the_table_was_replaced_is_refused(
    client: AsyncClient, admin_auth_header, dataset, test_db_session, method, how
):
    gid = (await _add(client, dataset, admin_auth_header))["id"]
    table_id = (await _read(client, dataset, admin_auth_header, gid))["table_id"]
    await _stage_replacement(test_db_session, dataset, gid, how)
    await test_db_session.commit()
    tile_version = await _tile_cache_version(test_db_session, dataset)

    response = await _write(method, client, dataset, admin_auth_header, gid, table_id)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "dataset_replaced"
    # A new version, so tiles cached from the old table are not served at it.
    assert detail["tile_cache_version"] > tile_version
    stored = await _tile_cache_version(test_db_session, dataset)
    assert stored == detail["tile_cache_version"]
    assert await _rows(test_db_session, dataset) == [(gid, "unrelated", 9.0, 9.0)]


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
async def test_a_write_with_the_table_id_of_a_fresh_read_is_applied(
    client: AsyncClient, admin_auth_header, dataset, test_db_session, method
):
    gid = (await _add(client, dataset, admin_auth_header))["id"]
    before = (await _read(client, dataset, admin_auth_header, gid))["table_id"]
    await _stage_replacement(test_db_session, dataset, gid, "reupload")
    await test_db_session.commit()
    after = (await _read(client, dataset, admin_auth_header, gid))["table_id"]

    response = await _write(method, client, dataset, admin_auth_header, gid, after)

    assert after != before
    assert response.status_code == _APPLIED[method], response.text
    if method != "delete":
        assert response.json()["table_id"] == after
        assert (await _rows(test_db_session, dataset))[0][1] == "mine"
    else:
        assert await _rows(test_db_session, dataset) == []


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
async def test_a_write_without_a_table_id_is_applied_as_before(
    client: AsyncClient, admin_auth_header, dataset, method
):
    gid = (await _add(client, dataset, admin_auth_header))["id"]

    response = await _write(method, client, dataset, admin_auth_header, gid, None)

    assert response.status_code == _APPLIED[method], response.text


async def test_creates_reads_and_writes_name_the_same_table(
    client: AsyncClient, admin_auth_header, dataset
):
    created = await _add(client, dataset, admin_auth_header)
    read = await _read(client, dataset, admin_auth_header, created["id"])
    patched = await _write(
        "patch", client, dataset, admin_auth_header, created["id"], read["table_id"]
    )

    assert read["table_id"]
    assert created["table_id"] == read["table_id"]
    assert patched.json()["table_id"] == read["table_id"]


async def test_a_refused_retry_returns_the_table_id_to_write_with(
    client: AsyncClient, admin_auth_header, dataset
):
    """The editor's next save updates the feature in the 409 with its table_id."""
    sketch = uuid.uuid4().hex

    gid = (await _keyed_create(client, dataset, admin_auth_header, sketch, 1)).json()[
        "id"
    ]
    await _write("patch", client, dataset, admin_auth_header, gid, None)
    refused = await _keyed_create(client, dataset, admin_auth_header, sketch, 2)
    read = await _read(client, dataset, admin_auth_header, gid)

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "feature_changed"
    assert refused.json()["detail"]["feature"]["table_id"] == read["table_id"]


@pytest.mark.parametrize("how", ["reupload", "overwrite"])
async def test_a_repeat_finding_the_table_replaced_rolls_the_tile_version(
    client: AsyncClient, admin_auth_header, dataset, test_db_session, how
):
    sketch = uuid.uuid4().hex
    created = await _keyed_create(client, dataset, admin_auth_header, sketch, 1)
    gid = created.json()["id"]
    await _stage_replacement(test_db_session, dataset, gid, how)
    await test_db_session.commit()
    tile_version = await _tile_cache_version(test_db_session, dataset)

    repeat = await _keyed_create(client, dataset, admin_auth_header, sketch, 2)

    assert repeat.status_code == 409, repeat.text
    detail = repeat.json()["detail"]
    assert detail["code"] == "feature_gone"
    assert detail["tile_cache_version"] > tile_version
    stored = await _tile_cache_version(test_db_session, dataset)
    assert stored == detail["tile_cache_version"]
    assert await _rows(test_db_session, dataset) == [(gid, "unrelated", 9.0, 9.0)]


async def test_a_repeat_whose_feature_was_deleted_keeps_the_tile_version(
    client: AsyncClient, admin_auth_header, dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    created = await _keyed_create(client, dataset, admin_auth_header, sketch, 1)
    await _write(
        "delete", client, dataset, admin_auth_header, created.json()["id"], None
    )
    tile_version = await _tile_cache_version(test_db_session, dataset)

    repeat = await _keyed_create(client, dataset, admin_auth_header, sketch, 2)

    assert repeat.status_code == 409, repeat.text
    assert repeat.json()["detail"]["code"] == "feature_gone"
    assert "tile_cache_version" not in repeat.json()["detail"]
    assert await _tile_cache_version(test_db_session, dataset) == tile_version


async def _await_lock_wait_query() -> str:
    """Block until some backend is parked on a lock, and return what it is running."""
    import app.core.db as db_module

    for _ in range(600):
        async with db_module.async_session() as probe:
            query = await probe.scalar(
                text(
                    "SELECT query FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' LIMIT 1"
                )
            )
        if query:
            return query
        await asyncio.sleep(0.01)
    raise AssertionError("no backend ever parked on a lock")


async def test_a_replacement_committing_while_the_write_waits_is_seen(
    client: AsyncClient, admin_auth_header, dataset, test_db_session
):
    """The table id is compared once the write holds the table, not before.

    Read before the replacement commits, it would still name the old table,
    and the write that waited for the swap would then run against the new one.
    """
    import app.core.db as db_module

    gid = (await _add(client, dataset, admin_auth_header))["id"]
    table_id = (await _read(client, dataset, admin_auth_header, gid))["table_id"]
    tile_version = await _tile_cache_version(test_db_session, dataset)
    async with db_module.async_session() as swap:
        await _stage_replacement(swap, dataset, gid, "reupload")
        write = asyncio.create_task(
            _write("patch", client, dataset, admin_auth_header, gid, table_id)
        )
        try:
            waiting_on = await _await_lock_wait_query()
        finally:
            await swap.commit()
    response = await write

    assert dataset.table_name in waiting_on
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "dataset_replaced"
    # Past the swap's own version, and the one now stored.
    refused_version = response.json()["detail"]["tile_cache_version"]
    assert refused_version > tile_version + 1
    assert await _tile_cache_version(test_db_session, dataset) == refused_version
    assert await _rows(test_db_session, dataset) == [(gid, "unrelated", 9.0, 9.0)]


async def test_a_replacement_waits_for_a_write_whose_table_id_matched(
    client: AsyncClient, admin_auth_header, dataset, test_db_session
):
    import app.core.db as db_module

    gid = (await _add(client, dataset, admin_auth_header))["id"]
    table_id = (await _read(client, dataset, admin_auth_header, gid))["table_id"]
    reached = asyncio.Event()
    release = asyncio.Event()
    real_update = features_router.update_feature

    async def hold_before_the_write(*args, **kwargs):
        reached.set()
        await release.wait()
        return await real_update(*args, **kwargs)

    with patch.object(features_router, "update_feature", hold_before_the_write):
        write = asyncio.create_task(
            _write("patch", client, dataset, admin_auth_header, gid, table_id)
        )
        try:
            await asyncio.wait_for(reached.wait(), timeout=10)
            async with db_module.async_session() as swap:
                await swap.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError) as blocked:
                    await swap.execute(
                        text(
                            f'ALTER TABLE "data"."{dataset.table_name}" '
                            f'RENAME TO "{dataset.table_name}_old"'
                        )
                    )
                await swap.rollback()
        finally:
            release.set()
        response = await write

    assert is_lock_conflict(blocked.value)
    assert response.status_code == 200, response.text
    assert (await _rows(test_db_session, dataset))[0][1] == "mine"


def test_the_table_id_is_published_as_a_plain_optional_query_value():
    """A nullable schema makes generated clients accept None and then send it."""
    from app.api.main import app

    path = app.openapi()["paths"]["/datasets/{dataset_id}/features/{gid}"]
    for method in ("put", "patch", "delete"):
        (param,) = [p for p in path[method]["parameters"] if p["name"] == "table_id"]
        assert param["in"] == "query"
        assert param["required"] is False
        assert param["schema"]["type"] == "string"
        assert "anyOf" not in param["schema"]


async def test_holding_the_table_binds_a_tenant_role_that_can_read_it(monkeypatch):
    """Multi-tenant: the runtime login has no data-schema privilege of its own."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.core.db.tenant_session import (
        _before_tenant_cursor_execute,
        current_tenant_var,
    )
    from app.modules.catalog.features.idempotency import held_table_oid

    tenant = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    roles = []
    token = current_tenant_var.set(tenant)
    try:
        await held_table_oid(db, "roads")
        for call in [*db.execute.await_args_list, *db.scalar.await_args_list]:
            statement, *params = call.args
            cursor = MagicMock()
            _before_tenant_cursor_execute(
                object(),
                cursor,
                str(statement),
                params[0] if params else {},
                SimpleNamespace(),
                False,
            )
            roles += [c.args[0] for c in cursor.execute.call_args_list]
    finally:
        current_tenant_var.reset(token)

    reader = f'SET LOCAL ROLE "geolens_reader_t_{tenant.replace("-", "_")}"'
    assert roles == [reader, reader]
