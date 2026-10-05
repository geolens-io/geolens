"""A replaced vector table gets its quicklook drawn again, and the newest draw is kept."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import app.processing.vector.quicklook as quicklook_module
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.tasks_common import _generate_quicklook
from app.processing.ingest.tasks_reupload import reupload_file, reupload_service
from tests.factories import create_dataset, get_user_id
from tests.test_replacement_post_commit import _seed_job_and_run

pytestmark = pytest.mark.anyio

_WFS_BASE = "https://services.example.com/wfs"
_PARIS = [(2.35, 48.85)]
# Three continents, so the drawn extent and dots differ from the single point.
_SPREAD = [(-74.0, 40.7), (2.35, 48.85), (139.7, 35.7)]


@pytest.fixture
def storage(tmp_path, monkeypatch) -> LocalStorageProvider:
    provider = LocalStorageProvider(str(tmp_path / "objects"))
    for target in (
        "app.platform.storage.get_storage",
        "app.processing.ingest.tasks_common.get_storage",
        "app.processing.ingest.tasks_staging.get_storage",
        "app.modules.catalog.datasets.api.router.get_storage",
    ):
        monkeypatch.setattr(target, lambda: provider, raising=True)
    return provider


@pytest.fixture
async def tables():
    """Table names to drop, with their datasets' records, after the test."""
    import app.core.db as db_module

    created: list[tuple[str, uuid.UUID | None]] = []
    yield created
    async with db_module.async_session() as cleanup:
        for table, dataset_id in created:
            if dataset_id is not None:
                await cleanup.execute(
                    text("DELETE FROM catalog.ingest_jobs WHERE dataset_id = :id"),
                    {"id": dataset_id},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM catalog.records WHERE id = "
                        "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
                    ),
                    {"id": dataset_id},
                )
            await cleanup.execute(
                text(f'DROP TABLE IF EXISTS "data"."{table}" CASCADE')
            )
        await cleanup.commit()


def _points_sql(points: list[tuple[float, float]]) -> str:
    return ", ".join(
        f"('p{i}', ST_SetSRID(ST_MakePoint({x}, {y}), 4326))"
        for i, (x, y) in enumerate(points)
    )


async def _create_drawn_table(
    session: AsyncSession, table: str, points: list[tuple[float, float]]
) -> None:
    """A live feature table as the staging pipeline leaves it, with ``geom_4326``."""
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, name text, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
        )
    )
    await session.execute(
        text(f'INSERT INTO "data"."{table}" (name, geom) VALUES {_points_sql(points)}')
    )
    await session.execute(text(f'UPDATE "data"."{table}" SET geom_4326 = geom'))
    await session.commit()


async def _create_staged_table(table: str, points: list[tuple[float, float]]) -> None:
    """What ogr2ogr writes into an attempt's staging table."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "data"."{table}" '
                "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "data"."{table}" (name, geom) VALUES '
                f"{_points_sql(points)}"
            )
        )
        await session.commit()


async def _render(table: str) -> bytes:
    """What the quicklook renderer draws for ``table`` as it is now."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        return await quicklook_module.generate_vector_quicklook_with_timeout(
            session, table, "", 256, schema="data"
        )


async def _published_one_point_dataset(
    session: AsyncSession,
    storage: LocalStorageProvider,
    tables: list,
    *,
    visibility: str = "private",
) -> tuple[Dataset, uuid.UUID, bytes]:
    """A one-point dataset whose first ingest drew its quicklook."""
    import app.core.db as db_module

    admin_id = await get_user_id(session, "admin")
    table = f"qlredraw_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility=visibility,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="original.geojson",
        column_info=[{"name": "name", "type": "text"}],
    )
    tables.append((table, dataset.id))
    await _create_drawn_table(session, table, _PARIS)
    async with db_module.async_session() as ql_session:
        await _generate_quicklook(ql_session, dataset.id, table)
    _uri, before = await _stored_quicklook(storage, dataset.id)
    return dataset, admin_id, before


async def _stored_quicklook(
    storage: LocalStorageProvider, dataset_id: uuid.UUID
) -> tuple[str | None, bytes]:
    import app.core.db as db_module

    async with db_module.async_session() as session:
        uri = await session.scalar(
            select(Dataset.quicklook_256_uri).where(Dataset.id == dataset_id)
        )
    assert uri is not None
    return uri, await storage.get(uri)


async def _replace_from_file(
    session: AsyncSession, dataset: Dataset, admin_id: uuid.UUID
) -> None:
    upload = Path(settings.upload_staging_dir) / f"spread_{uuid.uuid4().hex}.geojson"
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_text('{"type":"FeatureCollection","features":[]}')
    job = await _seed_job_and_run(
        session,
        dataset_id=dataset.id,
        created_by=admin_id,
        origin_kind="upload",
        source_filename=upload.name,
        file_path=str(upload),
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )

    async def _fake_ogr2ogr(file_path, staging_table, db_conn_str, **kwargs):
        await _create_staged_table(staging_table, _SPREAD)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
                new=AsyncMock(),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.ogr.run_ogrinfo",
                new=AsyncMock(
                    return_value={
                        "srid": 4326,
                        "geometry_type": "Point",
                        "layer_name": "spread",
                        "feature_count": len(_SPREAD),
                        "columns": [{"name": "name", "type": "String"}],
                    }
                ),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr",
                new=AsyncMock(side_effect=_fake_ogr2ogr),
            )
        )
        await reupload_file.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=str(upload),
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )


async def _replace_from_service(
    session: AsyncSession, dataset: Dataset, admin_id: uuid.UUID
) -> None:
    """Bind the uploaded dataset to a live WFS layer in place."""
    job = await _seed_job_and_run(
        session,
        dataset_id=dataset.id,
        created_by=admin_id,
        origin_kind="service",
        source_filename="quakes",
        source_url=_WFS_BASE,
        source_layer="topp:quakes",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset.id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )

    async def _fake_service_fetch(
        gdal_source, layer_name, table_name, db_conn_str, service_type, **kwargs
    ):
        await _create_staged_table(table_name, _SPREAD)

    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service",
            new=AsyncMock(side_effect=_fake_service_fetch),
        ),
    ):
        await reupload_service.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            source_url=_WFS_BASE,
            source_layer="topp:quakes",
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )


@pytest.mark.parametrize("source", ["file", "service"])
async def test_a_replacement_draws_the_quicklook_from_the_new_table(
    test_db_session, storage, tables, source: str
) -> None:
    dataset, admin_id, before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    replace = _replace_from_file if source == "file" else _replace_from_service
    with patch("app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()):
        await replace(test_db_session, dataset, admin_id)

    import app.core.db as db_module

    # Read on a session of its own: an open read here would hold the table
    # against the teardown's DROP.
    async with db_module.async_session() as session:
        count = await session.scalar(
            text(f'SELECT count(*) FROM "data"."{dataset.table_name}"')
        )
    assert count == len(_SPREAD), "the replacement did not publish"
    uri, after = await _stored_quicklook(storage, dataset.id)
    assert uri.startswith(f"vectors/{dataset.id}/quicklook_256_")
    assert after != before, "the quicklook still shows the replaced data"
    assert after == await _render(dataset.table_name)


async def _draw(dataset: Dataset) -> None:
    import app.core.db as db_module

    async with db_module.async_session() as session:
        await _generate_quicklook(session, dataset.id, dataset.table_name)


async def _publish_spread(session: AsyncSession, dataset: Dataset) -> None:
    """Replace the table with three points and roll the tile version, as a replacement does."""
    await session.execute(text(f'DELETE FROM "data"."{dataset.table_name}"'))
    await session.execute(
        text(
            f'INSERT INTO "data"."{dataset.table_name}" (name, geom, geom_4326) '
            "SELECT name, geom, geom FROM (VALUES "
            f"{_points_sql(_SPREAD)}) AS v(name, geom)"
        )
    )
    await session.execute(
        text(
            "UPDATE catalog.datasets SET tile_cache_version = "
            "coalesce(tile_cache_version, 1) + 1 WHERE id = :id"
        ),
        {"id": dataset.id},
    )
    await session.commit()


@pytest.mark.parametrize("stall", ["read", "upload"])
async def test_an_older_draw_that_lands_last_draws_the_newer_table(
    test_db_session, storage, tables, monkeypatch, stall: str
) -> None:
    """A draw that read the table before a replacement, and put after its draw, draws again."""
    dataset, _admin_id, before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    held = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def _hold_first(real, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1 and stall == "upload":
            held.set()
            await release.wait()
        result = await real(*args, **kwargs)
        if calls == 1 and stall == "read":
            held.set()
            await release.wait()
        return result

    if stall == "read":
        real = quicklook_module.generate_vector_quicklook_with_timeout
        monkeypatch.setattr(
            quicklook_module,
            "generate_vector_quicklook_with_timeout",
            partial(_hold_first, real),
        )
    else:
        monkeypatch.setattr(storage, "put", partial(_hold_first, storage.put))

    older = asyncio.create_task(_draw(dataset))
    try:
        await asyncio.wait_for(held.wait(), timeout=10)
        await _publish_spread(test_db_session, dataset)
        await asyncio.wait_for(_draw(dataset), timeout=30)
    finally:
        release.set()
        await asyncio.wait_for(older, timeout=30)

    _uri, stored = await _stored_quicklook(storage, dataset.id)
    assert stored != before, "the older draw of the replaced data was kept"
    assert stored == await _render(dataset.table_name)


async def test_draws_of_two_datasets_finish_on_a_one_connection_pool(
    test_db_session, storage, tables, monkeypatch
) -> None:
    """A redraw holds one pooled connection, so a full pool only queues the next."""
    import app.core.db as db_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.processing.ingest.publish_followups import _redraw_quicklook

    first, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    second, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    for dataset in (first, second):
        await _publish_spread(test_db_session, dataset)

    engine = create_async_engine(
        db_module.engine.url, pool_size=1, max_overflow=0, pool_timeout=3
    )
    try:
        with monkeypatch.context() as patched:
            patched.setattr(
                db_module,
                "async_session",
                async_sessionmaker(engine, expire_on_commit=False),
            )
            await asyncio.wait_for(
                asyncio.gather(
                    _redraw_quicklook(first.id, first.table_name),
                    _redraw_quicklook(second.id, second.table_name),
                ),
                timeout=30,
            )
    finally:
        await engine.dispose()

    for dataset in (first, second):
        _uri, stored = await _stored_quicklook(storage, dataset.id)
        assert stored == await _render(dataset.table_name), dataset.table_name


async def test_a_stalled_upload_leaves_the_table_free_for_a_replacement(
    test_db_session, storage, tables, monkeypatch
) -> None:
    """A replacement's rename takes the live table while a draw's upload is stuck."""
    import app.core.db as db_module

    dataset, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    uploading = asyncio.Event()
    release_upload = asyncio.Event()
    real_put = storage.put

    async def _stalled_put(key, data):
        uploading.set()
        await release_upload.wait()
        return await real_put(key, data)

    monkeypatch.setattr(storage, "put", _stalled_put)
    draw = asyncio.create_task(_draw(dataset))
    try:
        await asyncio.wait_for(uploading.wait(), timeout=10)
        async with db_module.async_session() as swap:
            await swap.execute(text("SET LOCAL lock_timeout = '2s'"))
            try:
                await swap.execute(
                    text(
                        f'ALTER TABLE "data"."{dataset.table_name}" '
                        f'RENAME TO "{dataset.table_name}_probe"'
                    )
                )
            except DBAPIError as exc:
                pytest.fail(f"the draw held the table through its upload: {exc}")
            finally:
                await swap.rollback()
    finally:
        release_upload.set()
        await asyncio.wait_for(draw, timeout=30)


async def test_a_redraw_gives_the_public_quicklook_a_new_etag(
    client, test_db_session, storage, tables
) -> None:
    """A browser revalidating the replaced image gets the redrawn one."""
    dataset, _admin_id, before = await _published_one_point_dataset(
        test_db_session, storage, tables, visibility="public"
    )
    url = f"/datasets/{dataset.id}/quicklook"
    first = await client.get(url)
    assert first.status_code == 200
    assert first.content == before
    held = first.headers["etag"]

    await _publish_spread(test_db_session, dataset)
    await _draw(dataset)

    revalidated = await client.get(url, headers={"If-None-Match": held})
    assert revalidated.status_code == 200
    assert revalidated.content == await _render(dataset.table_name)
    assert revalidated.content != before
    assert revalidated.headers["etag"] not in (None, held)


@pytest.mark.parametrize("redraws", [1, 2])
async def test_a_read_that_loses_the_image_to_a_redraw_serves_the_new_one(
    client, test_db_session, storage, tables, monkeypatch, redraws: int
) -> None:
    """Redraws that reap the image between the pointer read and the fetch are not a 404."""
    dataset, _admin_id, before = await _published_one_point_dataset(
        test_db_session, storage, tables, visibility="public"
    )
    real_get = storage.get
    remaining = redraws

    async def _redraw_then_get(key):
        nonlocal remaining
        if remaining:
            remaining -= 1
            await _publish_spread(test_db_session, dataset)
            await _draw(dataset)
        return await real_get(key)

    monkeypatch.setattr(storage, "get", _redraw_then_get)
    response = await client.get(f"/datasets/{dataset.id}/quicklook")

    assert response.status_code == 200
    assert response.content != before


async def test_a_draw_whose_dataset_was_deleted_removes_its_upload(
    test_db_session, storage, tables, monkeypatch
) -> None:
    """A delete that reaps the quicklook before the draw's upload leaves no orphan."""
    import app.core.db as db_module

    dataset, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    keys: list[str] = []
    real_put = storage.put

    async def _deleted_before_put(stored_key, data):
        keys.append(stored_key)
        # The delete commits and reaps vectors/{id}/ while the draw renders.
        async with db_module.async_session() as delete:
            await delete.execute(
                text(
                    "DELETE FROM catalog.records WHERE id = "
                    "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
                ),
                {"id": dataset.id},
            )
            await delete.commit()
        await storage.delete(stored_key)
        return await real_put(stored_key, data)

    monkeypatch.setattr(storage, "put", _deleted_before_put)
    await _draw(dataset)

    assert keys
    assert not await storage.exists(keys[0]), "the upload outlived its dataset"


async def test_a_commit_that_lands_but_reports_failure_keeps_the_image(
    test_db_session, storage, tables
) -> None:
    """A lost COMMIT acknowledgement must not delete the image the pointer now names."""
    import app.core.db as db_module

    dataset, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    await _publish_spread(test_db_session, dataset)

    async with db_module.async_session() as session:
        real_commit = session.commit

        async def _commit_then_drop() -> None:
            await real_commit()
            raise ConnectionError("connection lost after COMMIT")

        session.commit = _commit_then_drop
        await _generate_quicklook(session, dataset.id, dataset.table_name)

    uri, _png = await _stored_quicklook(storage, dataset.id)
    assert await storage.exists(uri), "the committed pointer names a deleted image"


async def test_a_redraw_writes_a_new_key_and_removes_the_replaced_image(
    test_db_session, storage, tables
) -> None:
    """The image a browser or the reconcile probe saw keeps no identity once it is replaced."""
    dataset, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    first_uri, _ = await _stored_quicklook(storage, dataset.id)

    await _publish_spread(test_db_session, dataset)
    await _draw(dataset)

    second_uri, _ = await _stored_quicklook(storage, dataset.id)
    assert second_uri != first_uri
    assert not await storage.exists(first_uri), "the replaced image was left behind"


async def test_an_older_draw_leaves_the_newer_pointer_and_its_own_image_unkept(
    test_db_session, storage, tables, monkeypatch
) -> None:
    """A draw the data outran keeps neither the pointer nor its upload."""
    dataset, _admin_id, _before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    held = asyncio.Event()
    release = asyncio.Event()
    puts: list[str] = []
    real_put = storage.put

    async def _hold_first(key, data):
        puts.append(key)
        if len(puts) == 1:
            held.set()
            await release.wait()
        return await real_put(key, data)

    monkeypatch.setattr(storage, "put", _hold_first)
    older = asyncio.create_task(_draw(dataset))
    try:
        await asyncio.wait_for(held.wait(), timeout=10)
        await _publish_spread(test_db_session, dataset)
        await asyncio.wait_for(_draw(dataset), timeout=30)
    finally:
        release.set()
        await asyncio.wait_for(older, timeout=30)

    uri, _ = await _stored_quicklook(storage, dataset.id)
    assert puts[0] != uri
    assert uri in puts
    assert not await storage.exists(puts[0]), "the superseded draw's image was kept"
