"""A replaced vector table gets its quicklook drawn again, and the newest draw is kept."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
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
    session: AsyncSession, storage: LocalStorageProvider, tables: list
) -> tuple[Dataset, uuid.UUID, bytes]:
    """A one-point dataset whose first ingest drew its quicklook."""
    import app.core.db as db_module

    admin_id = await get_user_id(session, "admin")
    table = f"qlredraw_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility="private",
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="original.geojson",
        column_info=[{"name": "name", "type": "character varying"}],
    )
    tables.append((table, dataset.id))
    await _create_drawn_table(session, table, _PARIS)
    async with db_module.async_session() as ql_session:
        await _generate_quicklook(ql_session, dataset.id, table)
    before = await storage.get(f"vectors/{dataset.id}/quicklook_256.png")
    return dataset, admin_id, before


async def _stored_quicklook(
    storage: LocalStorageProvider, dataset_id: uuid.UUID
) -> tuple[str | None, bytes]:
    import app.core.db as db_module

    async with db_module.async_session() as session:
        uri = await session.scalar(
            select(Dataset.quicklook_256_uri).where(Dataset.id == dataset_id)
        )
    return uri, await storage.get(f"vectors/{dataset_id}/quicklook_256.png")


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
    assert uri == f"vectors/{dataset.id}/quicklook_256.png"
    assert after != before, "the quicklook still shows the replaced data"
    assert after == await _render(dataset.table_name)


async def _wait_until_waiting_or_done(task: asyncio.Task) -> None:
    """Return once ``task`` has finished or a session waits on an advisory lock."""
    import app.core.db as db_module

    for _ in range(200):
        if task.done():
            return
        # A fresh session per poll: pg_stat_activity is a per-transaction snapshot.
        async with db_module.async_session() as probe:
            waiting = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_locks l "
                    "JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE l.locktype = 'advisory' AND NOT l.granted "
                    "AND a.datname = current_database()"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the second draw neither finished nor waited")


async def test_an_older_draw_never_lands_over_a_newer_one(
    test_db_session, storage, tables
) -> None:
    """A draw that read the table before a replacement cannot put after a later draw."""
    import app.core.db as db_module

    dataset, _admin_id, before = await _published_one_point_dataset(
        test_db_session, storage, tables
    )
    real = quicklook_module.generate_vector_quicklook_with_timeout
    first_drawn = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0

    async def _slow_first(db, table_name, geometry_type, size=256, **kwargs):
        nonlocal calls
        calls += 1
        png = await real(db, table_name, geometry_type, size, **kwargs)
        if calls == 1:
            first_drawn.set()
            await release_first.wait()
        return png

    async def _draw() -> None:
        async with db_module.async_session() as session:
            await _generate_quicklook(session, dataset.id, dataset.table_name)

    with patch.object(
        quicklook_module, "generate_vector_quicklook_with_timeout", _slow_first
    ):
        older = asyncio.create_task(_draw())
        await asyncio.wait_for(first_drawn.wait(), timeout=10)
        # The older draw has read the one point; the table now holds three.
        await test_db_session.execute(
            text(f'DELETE FROM "data"."{dataset.table_name}"')
        )
        await test_db_session.execute(
            text(
                f'INSERT INTO "data"."{dataset.table_name}" (name, geom, geom_4326) '
                "SELECT name, geom, geom FROM (VALUES "
                f"{_points_sql(_SPREAD)}) AS v(name, geom)"
            )
        )
        await test_db_session.commit()
        newer = asyncio.create_task(_draw())
        try:
            await _wait_until_waiting_or_done(newer)
        finally:
            release_first.set()
        await asyncio.wait_for(asyncio.gather(older, newer), timeout=30)

    _uri, stored = await _stored_quicklook(storage, dataset.id)
    assert stored != before, "the draw of the replaced data was kept"
    assert stored == await _render(dataset.table_name)
