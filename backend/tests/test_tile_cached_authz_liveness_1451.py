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

The fix asks the catalog once per tile the pool actually has to build, and half
these tests are about WHERE it asks, which took four review rounds to settle. It
cannot be earlier: a tile answered from the byte cache must still reach the
database zero times, which is what `_dataset_cache` is for. It cannot be later:
everything past that point acts on the cached authorization, starting with the
COLD-02 seam that would wake storage for a deleted dataset, and a tile request
then takes an API-pool connection, a FAIR-01 permit and a tile-pool connection in
that order — so the check must finish and hand its connection back before the
first of them, or two paths hold a pair in opposite orders and stall.
"""

import gzip
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.tiles import router as tile_router
from tests.factories import get_user_id


pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _fake_meta(table_name: str):
    """A published public meta, as a warm cache entry would hand one back."""
    return tile_router._DatasetMeta(
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
    tile ever served. This is the lower bound on how early the check may sit;
    the ordering test below is the upper bound.
    """
    from fastapi import FastAPI

    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user

    table_name = f"cached_{tile_kind}"
    meta = _fake_meta(table_name)
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
        self.acquired = 0
        self.connection = _RecordingTileConnection(events)

    def acquire(self):
        self.acquired += 1
        return _null_async_context(self._events, "pool.acquire", self.connection)


@asynccontextmanager
async def _null_async_context(events: list[str], label: str, value=None):
    events.append(label)
    yield value


@pytest.mark.parametrize("tile_kind", ["vector", "cluster"])
async def test_the_catalog_is_asked_before_anything_acts_on_the_cached_meta(
    tile_kind: str,
):
    """Order is the fix, so order is what this pins (codex, rounds 1-4).

    Past the byte-cache short-circuit a tile request touches four things in
    sequence: the COLD-02 seam, an API-pool connection, a FAIR-01 permit, and a
    tile-pool connection. Each review round found the check sitting after one
    more of them.

    The seam is a correctness problem — it enqueues a restore for the dataset the
    cached metadata names, so a deleted one buys storage work and a 202. The
    other three are a lock-order problem: `get_db` holds its connection until the
    response is written, so a metadata-cache MISS carries it into both later
    waits, and any position that takes one of those while asking for the API pool
    inverts a pair against it. Two bounded resources acquired in opposite orders
    stall under ordinary mixed load, no attacker involved.

    A 404 assertion sees none of this, so this asserts the sequence.
    """
    from fastapi import FastAPI

    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user

    events: list[str] = []
    table_name = f"ordered_{tile_kind}"
    meta = _fake_meta(table_name)
    pool = _RecordingTilePool(events)
    session = _RecordingSession(events)

    async def _query(*_args, **_kwargs):
        events.append("tile_query")
        return b"mvt"

    async def _record_cold_seam(*_args, **_kwargs):
        events.append("cold_seam")
        return None

    async def _record_role_bind(_conn, _tid):
        events.append("set_role")

    app = FastAPI()
    app.include_router(tile_router.router)
    app.dependency_overrides[get_db] = lambda: session
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
        patch.object(tile_router, "get_tile_cache", lambda: None),
        patch.object(tile_router, "get_tile_pool", lambda: pool),
        patch.object(tile_router, "_check_cold_rehydrate", _record_cold_seam),
        patch.object(
            tile_router, "set_tenant_role_for_tile_request", _record_role_bind
        ),
        patch.object(tile_router, "get_tile", _query),
        patch.object(tile_router, "get_cluster_tile", _query),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get(path)

    assert response.status_code == 200, response.text
    assert events == [
        "db.execute",
        "db.rollback",
        "cold_seam",
        "pool.acquire",
        "txn",
        "set_role",
        "tile_query",
    ], events


async def test_both_tile_endpoints_ask_before_they_act():
    """The check lives in two endpoints, so nothing structural funnels it.

    It used to sit in `_acquire_and_serve_tile`, which both endpoints reach, but
    that is below the COLD-02 seam and below the capacity acquisitions, and both
    of those turned out to matter. Moving it up traded a funnel for a convention,
    so the convention is enforced here instead: a third tile route that resolves
    cached metadata and forgets this call would otherwise be a silent regression.
    """
    import ast
    import inspect
    import textwrap

    for endpoint in (tile_router.tile_endpoint, tile_router.cluster_tile_endpoint):
        source = textwrap.dedent(inspect.getsource(endpoint))
        calls = [
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        name = endpoint.__name__

        assert "_assert_dataset_still_registered" in calls, (
            f"{name} reads a data-schema relation off cached authorization "
            "without re-checking the catalog (#1451)"
        )
        probe_at = calls.index("_assert_dataset_still_registered")
        for later in ("_check_cold_rehydrate", "_acquire_and_serve_tile"):
            assert probe_at < calls.index(later), (
                f"{name} calls {later} before the #1451 catalog check, so it "
                "acts on cached authorization the catalog may no longer back"
            )


@pytest.mark.parametrize("tile_kind", ["vector", "cluster"])
async def test_a_refusal_costs_no_capacity_and_no_storage_work(tile_kind: str):
    """A refused tile takes no permit, no pool slot, and wakes no cold storage.

    All three follow from the check sitting above them. The COLD-02 seam is the
    one that bites hardest: it acts on the same cached ``record_status``, so a
    deleted dataset left cold in the map would have bought a restore job and a
    202 for a row the catalog no longer has.
    """
    from fastapi import FastAPI

    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user

    events: list[str] = []
    table_name = f"refused_{tile_kind}"
    pool = _RecordingTilePool(events)

    async def _query(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("the relation was read after the catalog refused")

    async def _cold_seam(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("cold rehydrate ran for a dataset that was deleted")

    app = FastAPI()
    app.include_router(tile_router.router)
    app.dependency_overrides[get_db] = lambda: _RecordingSession(
        events, registered=False
    )
    app.dependency_overrides[get_optional_user] = lambda: None

    path = (
        f"/tiles/data.{table_name}/0/0/0.pbf"
        if tile_kind == "vector"
        else f"/tiles/clusters/data.{table_name}/0/0/0.pbf"
    )

    with (
        patch.object(
            tile_router,
            "_resolve_dataset_meta",
            AsyncMock(return_value=_fake_meta(table_name)),
        ),
        patch.object(tile_router, "get_tile_cache", lambda: None),
        patch.object(tile_router, "get_tile_pool", lambda: pool),
        patch.object(tile_router, "_check_cold_rehydrate", _cold_seam),
        patch.object(tile_router, "set_tenant_role_for_tile_request", AsyncMock()),
        patch.object(tile_router, "get_tile", _query),
        patch.object(tile_router, "get_cluster_tile", _query),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get(path)

    assert response.status_code == 404
    assert events == ["db.execute", "db.rollback"], events
    assert pool.acquired == 0
