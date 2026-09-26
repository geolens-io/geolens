"""A worker-side table swap reaches an API tile cache the worker cannot purge.

With ``REDIS_URL`` unset the worker has no tile cache, so the purge a re-upload
runs after its swap never reaches the API process's in-memory LRU. A vector
tile key that stayed the same across the swap kept serving the pre-swap bytes
for the whole ``tile_cache_ttl``. The vector and cluster keys now carry the
dataset's ``tile_cache_version``, which the swap rolls, so the API stops
reading the old entries once it re-reads the dataset row.

A page that has already read the new state says so in ``_v``, and the API
re-reads the row for it at once instead of when its 60 s snapshot expires.
A tile served from a snapshot older than that ``_v`` is sent ``no-store``, so
no cache keeps it under the page's URL.
"""

import asyncio
import contextlib
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from starlette.requests import Request

from app.platform.cache import provider as cache_provider
from app.platform.cache.tile_cache import InMemoryTileCacheProvider
from app.platform.jobs.models import IngestJob
from app.processing.tiles import router as tile_router
from app.processing.tiles.responses import _serving_tile_headers
from app.processing.tiles.router import _generation_table_key

from tests.factories import create_dataset, get_user_id
from tests.test_tile_cache_generation_key_1429 import PROVIDER_KINDS, _provider

TILE_ROUTES = [
    "/tiles/data.{table}/0/0/0.pbf",
    "/tiles/clusters/data.{table}/0/0/0.pbf",
]


async def _seed(session, tmp_path):
    """A public point dataset holding New York, and a queued re-upload of it."""
    from app.platform.refresh.service import create_pending_run

    admin_id = await get_user_id(session, "admin")
    table = f"swap2290_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        column_info=[{"name": "name", "type": "character varying"}],
    )
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), name text)"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO "data"."{table}" (geom, geom_4326, name) VALUES '
            "(ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), "
            "ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), 'New York')"
        )
    )
    await session.commit()

    source = tmp_path / "update.geojson"
    source.write_text('{"type":"FeatureCollection","features":[]}')
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="update.geojson",
        file_path=str(source),
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.flush()
    await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    await session.refresh(job)
    return admin_id, dataset, job


async def _stage_three_cities(file_path, staging_tn, db_conn_str, **kwargs):
    """Stands in for the GDAL subprocess: stages the replacement rows for real."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "data"."{staging_tn}" '
                "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "data"."{staging_tn}" (geom, name) VALUES '
                "(ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), 'Paris'), "
                "(ST_SetSRID(ST_MakePoint(-0.13, 51.51), 4326), 'London'), "
                "(ST_SetSRID(ST_MakePoint(13.40, 52.52), 4326), 'Berlin')"
            )
        )
        await session.commit()


async def _reupload_in_the_worker(admin_id, dataset, job, monkeypatch) -> None:
    """Run the worker's file re-upload the way a ``REDIS_URL``-less boot leaves it.

    ``init_tile_cache(in_memory_fallback=False)`` leaves the worker's singleton
    unset, so the swap's own purge finds no cache to purge.
    """
    from app.processing.ingest.tasks import reupload_file

    monkeypatch.setattr(cache_provider, "_tile_cache", None)
    ogrinfo = {
        "srid": 4326,
        "geometry_type": "Point",
        "layer_name": "update",
        "feature_count": 3,
        "columns": [{"name": "name", "type": "String"}],
    }
    storage = AsyncMock()
    with contextlib.ExitStack() as stack:
        for target, replacement in (
            (
                "app.processing.ingest.service.resolve_file_path",
                AsyncMock(side_effect=lambda path, job_id: path),
            ),
            (
                "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
                AsyncMock(),
            ),
            ("app.processing.ingest.ogr.run_ogrinfo", AsyncMock(return_value=ogrinfo)),
            (
                "app.processing.ingest.ogr.run_ogr2ogr",
                AsyncMock(side_effect=_stage_three_cities),
            ),
            # A real grant would put this module in the tenancy test group.
            ("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
            ("app.processing.ingest.tasks_staging.get_storage", lambda: storage),
        ):
            stack.enter_context(patch(target, new=replacement))
        await reupload_file(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=job.file_path,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )


async def _swap_landed(session, dataset_id, job_id) -> tuple[str, int]:
    job_status = await session.scalar(
        text("SELECT status FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
    )
    version = await session.scalar(
        text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
        {"id": dataset_id},
    )
    return job_status, version


def _age_metadata_snapshot(table_name: str) -> None:
    """Put the table's cached snapshot past its TTL, leaving the tile cache alone."""
    with tile_router._dataset_cache_lock:
        cached_at, meta = tile_router._dataset_cache[table_name]
        tile_router._dataset_cache[table_name] = (
            cached_at - tile_router._DATASET_CACHE_TTL,
            meta,
        )


async def _drop_table(session, table_name: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table_name}"'))
    await session.commit()


async def _page_state(client, admin_auth_header, session, dataset_id, spelling):
    """The ``_v`` a product page would send for the dataset as it stands now.

    The builder and viewer send the tile cache version from their layer
    response; the dataset page sends the ``updated_at`` of its dataset response.
    """
    if spelling == "tile_cache_version":
        version = await session.scalar(
            text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
            {"id": dataset_id},
        )
        return str(version)
    resp = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    return resp.json()["updated_at"]


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize("route", TILE_ROUTES)
async def test_a_swap_the_worker_cannot_purge_is_served_once_the_row_is_re_read(
    client: AsyncClient, test_db_session, tmp_path, monkeypatch, route: str
):
    admin_id, dataset, job = await _seed(test_db_session, tmp_path)
    table = dataset.table_name
    url = route.format(table=table)
    api_cache = InMemoryTileCacheProvider()
    try:
        with patch.object(tile_router, "get_tile_cache", return_value=api_cache):
            before = await client.get(url)
            assert before.status_code == 200, before.text

            await _reupload_in_the_worker(admin_id, dataset, job, monkeypatch)
            assert await _swap_landed(test_db_session, dataset.id, job.id) == (
                "complete",
                2,
            )

            # The stale read: nothing reached this process's cache.
            within_snapshot = await client.get(url)
            assert within_snapshot.content == before.content

            _age_metadata_snapshot(table)
            after = await client.get(url)

        with patch.object(tile_router, "get_tile_cache", return_value=None):
            tile_router._evict_dataset_meta(table)
            uncached = await client.get(url)

        assert after.status_code == 200, after.text
        assert after.content != before.content, (
            "the API served the pre-swap tile after re-reading the dataset row"
        )
        assert after.content == uncached.content
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize("spelling", ["tile_cache_version", "updated_at"])
@pytest.mark.parametrize("route", TILE_ROUTES)
async def test_a_page_that_read_the_swap_gets_the_new_tiles_at_once(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    tmp_path,
    monkeypatch,
    route: str,
    spelling: str,
):
    admin_id, dataset, job = await _seed(test_db_session, tmp_path)
    table = dataset.table_name
    url = route.format(table=table)
    api_cache = InMemoryTileCacheProvider()
    try:
        old_state = await _page_state(
            client, admin_auth_header, test_db_session, dataset.id, spelling
        )
        with patch.object(tile_router, "get_tile_cache", return_value=api_cache):
            before = await client.get(url, params={"_v": old_state})
            assert before.status_code == 200, before.text

            await _reupload_in_the_worker(admin_id, dataset, job, monkeypatch)
            new_state = await _page_state(
                client, admin_auth_header, test_db_session, dataset.id, spelling
            )
            assert new_state != old_state

            # A page still showing the old state costs no re-read.
            unrefreshed_page = await client.get(url, params={"_v": old_state})
            refreshed_page = await client.get(url, params={"_v": new_state})

        with patch.object(tile_router, "get_tile_cache", return_value=None):
            tile_router._evict_dataset_meta(table)
            uncached = await client.get(url)

        assert unrefreshed_page.content == before.content
        assert refreshed_page.status_code == 200, refreshed_page.text
        assert refreshed_page.content != before.content, (
            "a page that had read the new state was served the pre-swap tile"
        )
        assert refreshed_page.content == uncached.content
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
async def test_asking_for_a_version_before_it_exists_does_not_pin_the_old_snapshot(
    client: AsyncClient, test_db_session, tmp_path, monkeypatch
):
    """A snapshot is only ever kept for a ``_v`` it is at least as new as.

    Were the pre-swap snapshot stored against the ``_v`` that asked for it, a
    request naming the next version ahead of the swap would hand every later
    request for that version the pre-swap tiles until the snapshot expired.
    """
    admin_id, dataset, job = await _seed(test_db_session, tmp_path)
    table = dataset.table_name
    url = f"/tiles/data.{table}/0/0/0.pbf"
    api_cache = InMemoryTileCacheProvider()
    try:
        with patch.object(tile_router, "get_tile_cache", return_value=api_cache):
            early = await client.get(url, params={"_v": "2"})
            assert early.status_code == 200, early.text

            await _reupload_in_the_worker(admin_id, dataset, job, monkeypatch)
            after = await client.get(url, params={"_v": "2"})

        assert after.status_code == 200, after.text
        assert after.content != early.content
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


_SNAPSHOT_AT = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _snapshot() -> tile_router._DatasetMeta:
    return tile_router._DatasetMeta(
        dataset_id=uuid.uuid4(),
        record_id=uuid.uuid4(),
        table_name="roads",
        visibility="public",
        record_status="published",
        created_by=uuid.uuid4(),
        record_type="vector_dataset",
        geometry_type="Point",
        column_info=[],
        tile_cache_ttl=None,
        tile_columns=None,
        publication_version=0,
        tile_cache_version=3,
        updated_at=_SNAPSHOT_AT,
    )


@pytest.mark.parametrize(
    "raw,newer",
    [
        (None, False),
        ("4", True),
        ("3", False),
        ("2", False),
        ("2026-09-25T12:00:01Z", True),
        ("2026-09-25T14:00:01+02:00", True),
        ("2026-09-25T12:00:00Z", False),
        ("2026-09-25T11:59:59.999999+00:00", False),
        # Feature editing busts with Date.now(): too long for a version, and
        # a timestamp with no zone even where it parses as one.
        ("1790000000000", False),
        ("2026092512000", False),
        ("2026-09-25T12:00:01", False),
        ("2099-01-01", False),
        ("latest", False),
        ("", False),
        ("9" * 65, False),
    ],
)
def test_only_a_newer_state_in_either_spelling_forces_a_re_read(raw, newer):
    assert tile_router._client_saw_newer_state(raw, _snapshot()) is newer


# Newer than any row reaches, so every request carrying it asks for a re-read.
_UNREACHED_VERSION = "9999999999"


async def _registered_table(session) -> str:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=f"reread2290_{uuid.uuid4().hex[:10]}",
        record_type="vector_dataset",
        geometry_type="Point",
    )
    return dataset.table_name


def _count_queries(monkeypatch, session, queries: list) -> None:
    """Record every statement a real session runs, and still run it."""
    execute = session.execute

    async def counted(statement, *args, **kwargs):
        queries.append(statement)
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", counted)


def _age_forced_reread(cache_key: str) -> None:
    """Put the key's last forced re-read past its interval."""
    with tile_router._dataset_cache_lock:
        claimed_at = tile_router._forced_rereads[cache_key]
        tile_router._forced_rereads[cache_key] = (
            claimed_at - tile_router._FORCED_REREAD_INTERVAL
        )


async def test_an_unreached_version_re_reads_the_row_once_per_interval(
    test_db_session, monkeypatch
):
    table = await _registered_table(test_db_session)
    try:
        await tile_router._resolve_dataset_meta(table, test_db_session)
        queries: list = []
        _count_queries(monkeypatch, test_db_session, queries)

        for _ in range(20):
            await tile_router._resolve_dataset_meta(
                table, test_db_session, _UNREACHED_VERSION
            )
        assert len(queries) == 1

        _age_forced_reread(table)
        for _ in range(20):
            await tile_router._resolve_dataset_meta(
                table, test_db_session, _UNREACHED_VERSION
            )
        assert len(queries) == 2
    finally:
        tile_router._evict_dataset_meta(table)


async def test_concurrent_requests_for_an_unreached_version_share_one_re_read(
    test_db_session, monkeypatch
):
    """The re-read is claimed before its query, so requests during it don't query."""
    import app.core.db as db_module

    table = await _registered_table(test_db_session)
    try:
        await tile_router._resolve_dataset_meta(table, test_db_session)
        queries: list = []
        async with contextlib.AsyncExitStack() as stack:
            sessions = [
                await stack.enter_async_context(db_module.async_session())
                for _ in range(5)
            ]
            for session in sessions:
                _count_queries(monkeypatch, session, queries)
            await asyncio.gather(
                *(
                    tile_router._resolve_dataset_meta(
                        table, session, _UNREACHED_VERSION
                    )
                    for session in sessions
                )
            )
        assert len(queries) == 1
    finally:
        tile_router._evict_dataset_meta(table)


_CDN_POLICY = "public, max-age=60, s-maxage=86400"


class _CdnServing:
    """A hosted serving extension whose only policy is its CDN Cache-Control."""

    def get_tile_concurrency_limiter(self, tenant_id: str) -> None:
        return None

    def get_tile_cache_control(self) -> str:
        return _CDN_POLICY


def _request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode(), "headers": []})


@pytest.mark.parametrize(
    "query,scope,expected",
    [
        ("_v=4", "public", "no-store"),
        ("_v=4", "private", "no-store"),
        ("_v=2026-09-25T12:00:01Z", "public", "no-store"),
        ("_v=3", "public", "public"),
        ("_v=2", "private", "private"),
        ("", "public", "public"),
        ("", "private", "private"),
        ("pv=1", "public", "private"),
    ],
)
def test_only_a_v_newer_than_the_snapshot_forbids_caching(query, scope, expected):
    demoted = tile_router._demote_prewarmed_cache_scope(
        _request(query), _snapshot(), scope
    )
    assert demoted == expected


@pytest.mark.parametrize("empty", [False, True])
def test_a_no_store_scope_is_sent_bare_and_skips_the_cdn_policy(empty):
    headers = _serving_tile_headers("no-store", 300, _CDN_POLICY, empty=empty)
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize("route", TILE_ROUTES)
async def test_a_tile_older_than_the_page_is_not_cached_under_its_url(
    client: AsyncClient, test_db_session, tmp_path, monkeypatch, route: str
):
    import app.platform.extensions as ext_mod
    from app.modules.catalog.datasets.domain.models import Dataset
    from app.platform.catalog_locks import bump_tile_cache_version_atomic

    monkeypatch.setitem(ext_mod._extensions, "data_serving", _CdnServing())
    # Long enough that no request below can outlive the claim by accident.
    monkeypatch.setattr(tile_router, "_FORCED_REREAD_INTERVAL", 3600.0)
    _, dataset, _ = await _seed(test_db_session, tmp_path)
    table = dataset.table_name
    url = route.format(table=table)
    try:
        with patch.object(
            tile_router, "get_tile_cache", return_value=InMemoryTileCacheProvider()
        ):
            current = await client.get(url, params={"_v": "1"})
            ahead_of_row = await client.get(url, params={"_v": "2"})

            await bump_tile_cache_version_atomic(
                test_db_session, dataset_cls=Dataset, dataset_id=dataset.id
            )
            await test_db_session.commit()
            in_claim_window = await client.get(url, params={"_v": "2"})

            _age_forced_reread(table)
            caught_up = await client.get(url, params={"_v": "2"})
            unversioned = await client.get(url)
            older = await client.get(url, params={"_v": "1"})

        for resp in (
            current,
            ahead_of_row,
            in_claim_window,
            caught_up,
            unversioned,
            older,
        ):
            assert resp.status_code == 200, resp.text
        assert ahead_of_row.headers["cache-control"] == "no-store"
        assert in_claim_window.headers["cache-control"] == "no-store"
        for resp in (current, caught_up, unversioned, older):
            assert resp.headers["cache-control"] == _CDN_POLICY
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


def test_the_content_version_is_its_own_key_after_the_table_segment():
    dataset_id = uuid.uuid4()
    before = _generation_table_key("roads", dataset_id, 0, 1)
    after = _generation_table_key("roads", dataset_id, 0, 2)

    assert before != after
    assert before.startswith("roads:") and after.startswith("roads:")


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_invalidate_table_purges_every_content_version(kind):
    """A purge that can reach the cache still takes out every version's entries."""
    async with _provider(kind) as provider:
        dataset_id = uuid.uuid4()
        keys = [_generation_table_key("roads", dataset_id, 0, v) for v in (1, 2)]
        for key in keys:
            await provider.set(key, 5, 10, 15, b"tile", ttl=300)

        await provider.invalidate_table("roads")

        for key in keys:
            assert await provider.get(key, 5, 10, 15) is None
