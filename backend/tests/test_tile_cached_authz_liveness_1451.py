"""Cached tile authorization must not outlive the catalog row it came from (#1451).

``_resolve_dataset_meta`` answers a cache hit without touching the database, so
for up to ``_DATASET_CACHE_TTL`` seconds a worker keeps authorizing against a
dataset row that may already be gone. GH-1443 retired freed table names, which
closed the half a caller could reach through the API. Direct DDL on the ``data``
schema is not that half: ``CREATE TABLE data.roads`` needs no registration, and
``ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO
geolens_reader`` (scripts/lib/configure-runtime-db-role.sh) hands the tile role
read access to it without ``grant_reader_access`` ever running. Inside the TTL an
anonymous tile request would be authorized against the deleted dataset's
``public`` visibility and answered from a relation nobody registered.

The #1441 eviction listener is process-local and REDIS_URL is unset by default,
so a delete only ever evicts in the worker that served it — which is why these
tests warm the cache and then delete WITHOUT evicting: that is not a contrived
state, it is what every other uvicorn worker holds.

The fix asks the catalog once per tile the pool actually has to build. Two of
these tests cover the other half of that bargain, because where the question is
asked matters as much as asking it: a tile answered from the byte cache must
still reach the database zero times, and the check must sit after the FAIR-01
permit and immediately before the relation read, holding no API-pool connection
across the wait and leaving no await for a delete to slip through.
"""

import gzip
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.processing.tiles import router as tile_router
from tests.factories import get_user_id


pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_request() -> Request:
    """The minimum scope ``_acquire_and_serve_tile`` reads off a request."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/tiles/data.roads/0/0/0.pbf",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1234),
            "scheme": "http",
        }
    )


@pytest.fixture(autouse=True)
def _restore_dataset_cache():
    """The meta cache is a process global — hand it back exactly as found.

    These tests deliberately leave warm entries pointing at deleted datasets;
    leaking one into the rest of the session would decide another test's
    authorization.
    """
    with tile_router._dataset_cache_lock:
        before = dict(tile_router._dataset_cache)
    yield
    with tile_router._dataset_cache_lock:
        tile_router._dataset_cache.clear()
        tile_router._dataset_cache.update(before)


@pytest.fixture
async def drop_tables(test_db_session: AsyncSession):
    """Drop relations the test created out-of-band.

    A recreated relation is by definition unregistered, so no delete path will
    ever reap it.
    """
    created: list[str] = []

    def _register(table_name: str) -> str:
        created.append(table_name)
        return table_name

    yield _register

    for table_name in created:
        await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{table_name}"'))
    await test_db_session.commit()


async def _create_point_relation(session: AsyncSession, table_name: str, label: str):
    """The shape ``column_info`` describes, holding one point inside tile 0/0/0.

    Column compatibility is a precondition of the disclosure — a restore from
    backup satisfies it, and without it the cached ``column_info`` would make the
    tile query fail on its own rather than return the recreated rows.
    """
    await session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            "  gid SERIAL PRIMARY KEY,"
            "  name TEXT,"
            "  value INTEGER,"
            "  geom GEOMETRY(Point, 3857),"
            "  geom_4326 GEOMETRY(Point, 4326)"
            ")"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, value, geom, geom_4326) VALUES ('
            "  :label, 42,"
            "  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            "  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            ")"
        ),
        {"label": label},
    )
    await session.commit()


async def _make_public_dataset(session: AsyncSession, table_name: str, title: str):
    """A published public dataset over ``table_name`` — anonymously tileable."""
    from tests.factories import create_dataset

    admin_id = await get_user_id(session, "admin")
    return await create_dataset(
        session,
        created_by=admin_id,
        name=title,
        table_name=table_name,
        record_type="vector_dataset",
        visibility="public",
        record_status="published",
        geometry_type="Point",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )


async def _delete_dataset(session: AsyncSession, dataset_id: uuid.UUID, title: str):
    """Delete through the real service, then commit — and evict nothing.

    #1441 moved the meta eviction out of ``delete_dataset`` and into the two
    delete ENDPOINTS, after their commit. Driving the service directly therefore
    reproduces a real worker's state rather than simulating it: the row is gone,
    the table is dropped, the name is retired, and this process's metadata map is
    untouched — exactly what every worker that did not serve the delete holds.
    """
    from app.modules.catalog.datasets.domain.service import delete_dataset

    class _NoStagedObjects:
        async def list(self, prefix: str) -> list[str]:
            return []

        async def delete(self, key: str) -> None:  # pragma: no cover - none listed
            raise AssertionError("no keys were listed")

    with patch(
        "app.platform.storage.provider.get_storage", return_value=_NoStagedObjects()
    ):
        await delete_dataset(session, dataset_id, title)
    await session.commit()


def _cached_meta(table_name: str):
    with tile_router._dataset_cache_lock:
        entry = tile_router._dataset_cache.get(table_name)
    return None if entry is None else entry[1]


# ---------------------------------------------------------------------------
# The scenario the issue describes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_template",
    [
        "/tiles/data.{table}/0/0/0.pbf",
        "/tiles/clusters/data.{table}/0/0/0.pbf",
    ],
    ids=["vector", "cluster"],
)
async def test_recreated_relation_is_not_served_under_a_deleted_datasets_authorization(
    client: AsyncClient,
    test_db_session: AsyncSession,
    drop_tables,
    url_template: str,
):
    """The four steps from GH-1451, end to end, on both tile endpoints.

    Both endpoints reach the physical relation through ``_acquire_and_serve_tile``,
    so both are the same call site — but only one of them was exercised when the
    check was written, and a future third endpoint that skips the funnel would
    pass a vector-only test.
    """
    table_name = f"roads_{uuid.uuid4().hex[:12]}"
    title = f"Roads {uuid.uuid4().hex[:6]}"
    drop_tables(table_name)

    # 1. Public dataset A occupies `roads`. A tile worker caches meta(A).
    dataset_a = await _make_public_dataset(test_db_session, table_name, title)
    await _create_point_relation(test_db_session, table_name, "public_row")
    await tile_router._resolve_dataset_meta(table_name, test_db_session)
    assert _cached_meta(table_name).visibility == "public"

    # 2. A is deleted. The table is dropped and the name retired; this process
    #    never hears about it.
    await _delete_dataset(test_db_session, dataset_a.id, title)

    # 3. Someone with a database session recreates `roads` and does NOT register
    #    it. Nothing in the product can do this — that is the point.
    await _create_point_relation(test_db_session, table_name, "unregistered_row")

    assert _cached_meta(table_name) is not None, (
        "the warm entry is the whole premise: without it this request would "
        "404 in _resolve_dataset_meta and prove nothing"
    )

    # 4. An anonymous tile request inside the TTL.
    response = await client.get(url_template.format(table=table_name))

    assert response.status_code == 404, (
        "an unregistered relation was served under a deleted dataset's cached "
        f"authorization (got {response.status_code})"
    )
    # An MVT names its source layer `data.{table}`; a 404 body cannot.
    assert f"data.{table_name}".encode() not in response.content


async def test_refusal_evicts_the_stale_entry_it_refused(
    client: AsyncClient,
    test_db_session: AsyncSession,
    drop_tables,
):
    """One refusal, not a refusal per request for the rest of the TTL.

    Leaving the entry in place would keep every later request paying the probe to
    reach the same answer, and would leave a metadata map that disagrees with the
    catalog for a minute after the disagreement was detected.
    """
    table_name = f"trails_{uuid.uuid4().hex[:12]}"
    title = f"Trails {uuid.uuid4().hex[:6]}"
    drop_tables(table_name)

    dataset = await _make_public_dataset(test_db_session, table_name, title)
    await _create_point_relation(test_db_session, table_name, "public_row")
    await tile_router._resolve_dataset_meta(table_name, test_db_session)

    await _delete_dataset(test_db_session, dataset.id, title)
    await _create_point_relation(test_db_session, table_name, "unregistered_row")

    assert (await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")).status_code == 404
    assert _cached_meta(table_name) is None, (
        "the entry that authorized the refused request survived it"
    )


async def test_a_live_dataset_still_serves_its_own_tiles(
    client: AsyncClient,
    test_db_session: AsyncSession,
    drop_tables,
):
    """The control: the probe must not turn normal serving into a 404.

    A liveness check that fails closed on live datasets is worse than the leak it
    prevents, and this is the case a mocked probe would never catch.
    """
    table_name = f"parks_{uuid.uuid4().hex[:12]}"
    title = f"Parks {uuid.uuid4().hex[:6]}"
    drop_tables(table_name)

    await _make_public_dataset(test_db_session, table_name, title)
    await _create_point_relation(test_db_session, table_name, "public_row")
    await tile_router._resolve_dataset_meta(table_name, test_db_session)

    response = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")

    # httpx decodes Content-Encoding: gzip, so .content is the MVT itself. The
    # tile carries no `name` property — columns are opt-in — so the layer name
    # is what identifies the relation the tile was built from.
    assert response.status_code == 200, response.text
    assert f"data.{table_name}".encode() in response.content


# ---------------------------------------------------------------------------
# The cost bound the check has to respect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tile_kind", ["vector", "cluster"])
async def test_a_cached_tile_still_reaches_the_database_zero_times(tile_kind: str):
    """A byte-cache hit must cost no round-trip — PERF-006 / PERF-002.

    ``_dataset_cache`` exists to keep the hot path off the database, so a
    liveness check placed in ``_resolve_dataset_meta`` would be paid on every
    tile ever served. This pins where the check lives, not only what it does:
    the probe belongs on the path that is about to read the relation.
    """
    from fastapi import FastAPI

    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user

    table_name = f"cached_{tile_kind}"
    meta = tile_router._DatasetMeta(
        dataset_id=uuid.uuid4(),
        record_id=uuid.uuid4(),
        table_name=table_name,
        visibility="public",
        record_status="published",
        created_by=uuid.uuid4(),
        record_type="vector_dataset",
        geometry_type="Point",
        column_info=[],
        tile_cache_ttl=30,
        tile_columns=None,
    )
    db = AsyncMock()
    cache = SimpleNamespace(
        get=AsyncMock(return_value=gzip.compress(b"cached-mvt")),
        set=AsyncMock(),
    )

    app = FastAPI()
    app.include_router(tile_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_optional_user] = lambda: None

    path = (
        f"/tiles/data.{table_name}/0/0/0.pbf"
        if tile_kind == "vector"
        else f"/tiles/clusters/data.{table_name}/0/0/0.pbf"
    )

    with (
        patch.object(
            tile_router, "_resolve_dataset_meta", AsyncMock(return_value=meta)
        ),
        patch.object(tile_router, "get_tile_cache", lambda: cache),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get(path)

    assert response.status_code == 200
    db.execute.assert_not_awaited()


class _RecordingSession:
    """A session that logs when it is queried and when it lets its connection go."""

    def __init__(self, events: list[str], *, registered: bool = True) -> None:
        self._events = events
        self._registered = registered

    async def execute(self, _stmt):
        self._events.append("db.execute")
        value = uuid.uuid4() if self._registered else None
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    async def rollback(self) -> None:
        self._events.append("db.rollback")


class _RecordingTileConnection:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def transaction(self):
        return _null_async_context(self._events, "txn")


class _RecordingTilePool:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.connection = _RecordingTileConnection(events)

    def acquire(self):
        return _null_async_context(self._events, "pool.acquire", self.connection)


@asynccontextmanager
async def _null_async_context(events: list[str], label: str, value=None):
    events.append(label)
    yield value


async def test_the_catalog_is_asked_between_capacity_and_the_relation_read():
    """Order is the fix, so order is what this pins (codex P1/P2 on #1454).

    Ahead of the tile pool the probe held an API-pool connection for the whole
    FAIR-01 wait, which is how a burst of uncached coordinates starves the CRUD
    traffic the separate tile pool exists to protect. Any await between the check
    and the read reopens the window the check closes. Both failure modes are
    invisible to a test that only asserts the 404, so this one asserts where.
    """
    events: list[str] = []
    pool = _RecordingTilePool(events)
    dataset_id = uuid.uuid4()

    async def _query(_pool, _conn):
        events.append("tile_query")
        return b"mvt"

    async def _record_role_bind(_conn, _tid):
        events.append("set_role")

    with (
        patch.object(tile_router, "get_tile_pool", lambda: pool),
        patch.object(
            tile_router, "set_tenant_role_for_tile_request", _record_role_bind
        ),
    ):
        response = await tile_router._acquire_and_serve_tile(
            request=_bare_request(),
            db=_RecordingSession(events),
            dataset_id=dataset_id,
            table_name="roads",
            z=0,
            x=0,
            y=0,
            tid=None,
            schema="data",
            query_callable=_query,
            tile_cache=None,
            cache_key="roads",
            cache_ttl=60,
            base_headers={},
        )

    assert response.status_code == 200
    assert events == [
        "pool.acquire",
        "txn",
        "set_role",
        "db.execute",
        "db.rollback",
        "tile_query",
    ], events


async def test_a_refused_tile_is_a_404_not_a_service_error():
    """The pool block maps a broad exception to 503; a refusal must escape that.

    Moving the check inside that block put it under a handler that would have
    reported the deleted dataset as a tile-service outage, which reads as
    something to page about and hides the reason the tile was withheld.
    """
    events: list[str] = []
    pool = _RecordingTilePool(events)

    async def _query(_pool, _conn):  # pragma: no cover - must never run
        raise AssertionError("the relation was read after the catalog refused")

    with (
        patch.object(tile_router, "get_tile_pool", lambda: pool),
        patch.object(tile_router, "set_tenant_role_for_tile_request", AsyncMock()),
        pytest.raises(HTTPException) as excinfo,
    ):
        await tile_router._acquire_and_serve_tile(
            request=_bare_request(),
            db=_RecordingSession(events, registered=False),
            dataset_id=uuid.uuid4(),
            table_name="roads",
            z=0,
            x=0,
            y=0,
            tid=None,
            schema="data",
            query_callable=_query,
            tile_cache=None,
            cache_key="roads",
            cache_ttl=60,
            base_headers={},
        )

    assert excinfo.value.status_code == 404
