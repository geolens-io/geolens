"""A refresh or file re-upload that brings the data the dataset already holds publishes nothing."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.modules.catalog.collections.models import DatasetVersion
from app.platform.refresh.models import DatasetRefreshRun
from tests.factories import get_user_id
from tests.test_previous_version_2590 import _cleanup, _replace, _seed
from tests.test_refresh_gate_1269 import _runs_ordered
from tests.test_service_reupload_3d import (
    _FLAT_WELLS,
    _dataset,
    _ingest,
    _refresh,
)

pytestmark = pytest.mark.anyio


async def _state(session, dataset_id: uuid.UUID) -> dict:
    dataset = await _dataset(session, dataset_id)
    state = {
        "current_version": dataset.current_version,
        "last_refreshed_at": dataset.last_refreshed_at,
        "last_checked_at": dataset.last_checked_at,
        "tile_cache_version": dataset.tile_cache_version,
        "oid": await session.scalar(
            text("SELECT to_regclass(:table)::oid"),
            {"table": f'data."{dataset.table_name}"'},
        ),
        "versions": await session.scalar(
            select(func.count()).where(DatasetVersion.dataset_id == dataset_id)
        ),
        "kept": await session.scalar(
            select(func.count()).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.kept_table.is_not(None),
            )
        ),
        "side_tables": await session.scalar(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'data' "
                "AND tablename LIKE :prefix AND tablename <> :table"
            ),
            {"prefix": f"{dataset.table_name}%", "table": dataset.table_name},
        ),
    }
    await session.commit()
    return state


async def _forget_last_writer(session, dataset_id: uuid.UUID) -> None:
    """Clear who wrote the record last, so a replacement must name its submitter."""
    await session.execute(
        text(
            "UPDATE catalog.records SET updated_by = NULL WHERE id = "
            "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": dataset_id},
    )
    await session.commit()


async def _last_writer(session, dataset_id: uuid.UUID):
    writer = await session.scalar(
        text(
            "SELECT r.updated_by FROM catalog.records r JOIN catalog.datasets d "
            "ON d.record_id = r.id WHERE d.id = :id"
        ),
        {"id": dataset_id},
    )
    await session.commit()
    return writer


async def test_a_refresh_of_unchanged_data_publishes_no_version(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)
    before = await _state(test_db_session, dataset_id)
    await _forget_last_writer(test_db_session, dataset_id)

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _FLAT_WELLS)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    assert run.verification["data_unchanged"] is True
    assert await _last_writer(test_db_session, dataset_id) == await get_user_id(
        test_db_session, "admin"
    )
    assert run.dataset_version_id is None
    assert run.feature_count_after == len(_FLAT_WELLS)
    after = await _state(test_db_session, dataset_id)
    for key in ("current_version", "tile_cache_version", "oid", "versions", "kept"):
        assert after[key] == before[key], key
    assert after["side_tables"] == 0
    assert after["last_refreshed_at"] > before["last_refreshed_at"]
    assert after["last_checked_at"] > before["last_checked_at"]


async def test_a_refresh_of_changed_data_still_publishes(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)
    before = await _state(test_db_session, dataset_id)
    moved = [(x + 0.5, y, z) for x, y, z in _FLAT_WELLS]

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, moved)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    assert run.verification["data_unchanged"] is False
    assert run.dataset_version_id is not None
    after = await _state(test_db_session, dataset_id)
    assert after["current_version"] == before["current_version"] + 1
    assert after["oid"] != before["oid"]
    assert after["kept"] == before["kept"] + 1


async def test_a_refresh_publishes_when_the_live_table_cannot_be_compared(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    from app.processing.ingest import metadata

    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)
    before = await _state(test_db_session, dataset_id)
    staged_digest = metadata.compute_table_content_digest

    async def _live_digest_fails(*args, lock=True, **kwargs):
        if not lock:
            raise RuntimeError("canceling statement due to statement timeout")
        return await staged_digest(*args, lock=lock, **kwargs)

    monkeypatch.setattr(metadata, "compute_table_content_digest", _live_digest_fails)
    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _FLAT_WELLS)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    assert run.verification["data_unchanged"] is False
    assert run.dataset_version_id is not None
    after = await _state(test_db_session, dataset_id)
    assert after["current_version"] == before["current_version"] + 1


async def _run_of(session, job_id: uuid.UUID) -> DatasetRefreshRun:
    run = await session.scalar(
        select(DatasetRefreshRun)
        .where(DatasetRefreshRun.ingest_job_id == job_id)
        .execution_options(populate_existing=True)
    )
    await session.commit()
    return run


async def test_a_file_reupload_of_unchanged_data_publishes_no_version(
    test_db_session,
):
    """A different file holding the same rows in another order changes nothing."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await _replace(session, dataset, admin_id, ["paris", "london"])
        before = await _state(session, dataset.id)
        await _forget_last_writer(session, dataset.id)

        job = await _replace(
            session,
            dataset,
            admin_id,
            ["london", "paris"],
            filename="renamed.geojson",
            file_hash="e" * 64,
        )

        run = await _run_of(session, job.id)
        assert run.status == "succeeded", run.verification
        assert run.verification["data_unchanged"] is True
        assert run.dataset_version_id is None
        assert await _last_writer(session, dataset.id) == admin_id
        after = await _state(session, dataset.id)
        for key in ("current_version", "tile_cache_version", "oid", "versions", "kept"):
            assert after[key] == before[key], key
        assert after["last_refreshed_at"] > before["last_refreshed_at"]

        job = await _replace(session, dataset, admin_id, ["paris"])

        run = await _run_of(session, job.id)
        assert run.verification["data_unchanged"] is False
        assert run.dataset_version_id is not None
        changed = await _state(session, dataset.id)
        assert changed["current_version"] == before["current_version"] + 1
        assert changed["kept"] == before["kept"] + 1
    finally:
        await _cleanup(session, dataset)


async def test_an_unchanged_refresh_clears_a_stale_source_health(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """A refresh that reached the source drops the probe's old verdict, as a publish does."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)
    await test_db_session.execute(
        text(
            "UPDATE catalog.datasets SET source_health = 'inaccessible', "
            "source_health_detail = 'HTTP 403' WHERE id = :id"
        ),
        {"id": dataset_id},
    )
    await test_db_session.commit()

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _FLAT_WELLS)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.verification["data_unchanged"] is True
    health = (
        await test_db_session.execute(
            text(
                "SELECT source_health, source_health_detail FROM catalog.datasets "
                "WHERE id = :id"
            ),
            {"id": dataset_id},
        )
    ).one()
    await test_db_session.commit()
    assert tuple(health) == (None, None)


@pytest.mark.parametrize("failing", ["staged digest", "column comparison"])
async def test_a_comparison_that_errors_still_publishes_the_file(
    test_db_session, monkeypatch, failing
):
    """A database error while comparing aborts only the comparison, not the publish."""
    from app.processing.ingest import metadata, tasks_reupload

    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await _replace(session, dataset, admin_id, ["paris", "london"])
        before = await _state(session, dataset.id)
        if failing == "staged digest":
            digest = metadata.compute_table_content_digest

            async def _times_out(db, *args, lock=True, **kwargs):
                if lock:
                    await db.execute(text("SET LOCAL statement_timeout = 1"))
                    await db.execute(text("SELECT pg_sleep(1)"))
                return await digest(db, *args, lock=lock, **kwargs)

            monkeypatch.setattr(metadata, "compute_table_content_digest", _times_out)
        else:

            async def _errors(db, *args, **kwargs):
                await db.execute(text("SELECT 1 / 0"))

            monkeypatch.setattr(tasks_reupload, "_same_columns", _errors)

        job = await _replace(
            session,
            dataset,
            admin_id,
            ["london", "paris"],
            filename="renamed.geojson",
            file_hash="e" * 64,
        )

        run = await _run_of(session, job.id)
        assert run.status == "succeeded", run.verification
        assert run.verification["data_unchanged"] is False
        assert run.dataset_version_id is not None
        after = await _state(session, dataset.id)
        assert after["current_version"] == before["current_version"] + 1
    finally:
        await _cleanup(session, dataset)


async def test_a_live_write_after_the_digest_is_not_unchanged(test_db_session):
    """A feature write between the live digest and the hold changes the witness."""
    from app.core.db import async_session
    from app.platform.catalog_locks import record_live_data_write
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import compute_table_content_digest
    from app.processing.ingest.tasks_reupload import (
        _hold_live_table,
        _live_content_digest,
        _LiveComparison,
    )

    Dataset = get_processing_port().get_dataset_orm_class()
    session = test_db_session
    _, seeded = await _seed(session)
    live = f'"data"."{seeded.table_name}"'
    staged = f"{seeded.table_name}_staged"
    try:
        await session.execute(text(f'CREATE TABLE "data"."{staged}" (LIKE {live})'))
        await session.execute(
            text(f'INSERT INTO "data"."{staged}" SELECT * FROM {live}')
        )
        await session.commit()
        live_content = await _live_content_digest(
            seeded.table_name, schema="data", dataset_id=seeded.id, has_geometry=True
        )

        async def _compare() -> bool:
            comparison = _LiveComparison()
            comparison.verification = {}
            comparison.staging_table = staged
            comparison.live_content = live_content
            async with async_session() as publication:
                comparison.content_digest = await compute_table_content_digest(
                    publication, staged, schema="data", has_geometry=True
                )
                dataset = await publication.get(Dataset, seeded.id)
                await _hold_live_table(publication, dataset, schema="data")
                await comparison._compare_live(publication, dataset)
                await publication.rollback()
            return comparison.verification["data_unchanged"]

        assert await _compare() is True
        # The digest above still describes the rows from before this edit.
        async with async_session() as editor:
            await editor.execute(text(f"UPDATE {live} SET name = 'Boston'"))
            await record_live_data_write(editor, await editor.get(Dataset, seeded.id))
            await editor.commit()

        assert await _compare() is False
    finally:
        await session.rollback()
        await session.execute(text(f'DROP TABLE IF EXISTS "data"."{staged}"'))
        await session.commit()
        await _cleanup(session, seeded)
