"""A replacement keeps the data it replaced, and a restore publishes it again."""

import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.jobs.heartbeat import (
    PREVIOUS_VERSION_NAME_PATTERN,
    is_previous_version_table,
    previous_version_table,
)
from app.platform.jobs.models import IngestJob
from tests.factories import create_dataset, create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio

_CITIES = {
    "new_york": "(ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), 'New York')",
    "paris": "(ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), 'Paris')",
    "london": "(ST_SetSRID(ST_MakePoint(-0.13, 51.51), 4326), 'London')",
}


async def _seed(session, *, visibility: str = "public"):
    """A point dataset holding New York, owned by the admin."""
    admin_id = await get_user_id(session, "admin")
    table = f"prev2590_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility=visibility,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        column_info=[{"name": "name", "type": "character varying"}],
    )
    # Plain values: the commits below expire the ORM instance.
    dataset = SimpleNamespace(id=dataset.id, table_name=table)
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
    return admin_id, dataset


async def _queue(session, dataset, admin_id, *, origin_kind: str, metadata: dict):
    from app.platform.refresh.service import create_pending_run

    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="update.geojson",
        file_path="/tmp/update.geojson",
        created_by=admin_id,
        user_metadata={"dataset_id": str(dataset.id), **metadata},
    )
    session.add(job)
    await session.flush()
    await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind=origin_kind,
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    await session.refresh(job)
    return job


def _stager(cities: list[str]):
    async def _stage(file_path, staging_tn, db_conn_str, **kwargs):
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(
                text(
                    f'CREATE TABLE "data"."{staging_tn}" '
                    "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
                )
            )
            rows = ", ".join(_CITIES[city] for city in cities)
            await session.execute(
                text(f'INSERT INTO "data"."{staging_tn}" (geom, name) VALUES {rows}')
            )
            await session.commit()

    return _stage


async def _replace(session, dataset, admin_id, cities: list[str]) -> IngestJob:
    """Run a file replacement of the dataset with ``cities`` through the worker."""
    from app.processing.ingest.tasks import reupload_file

    job = await _queue(
        session, dataset, admin_id, origin_kind="upload", metadata={"reupload": True}
    )
    ogrinfo = {
        "srid": 4326,
        "geometry_type": "Point",
        "layer_name": "update",
        "feature_count": len(cities),
        "columns": [{"name": "name", "type": "String"}],
    }
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
                AsyncMock(side_effect=_stager(cities)),
            ),
            ("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
            ("app.processing.ingest.tasks_staging.get_storage", lambda: AsyncMock()),
            (
                "app.processing.ingest.tasks_reupload.sha256_file",
                lambda path: "f" * 64,
            ),
            (
                "app.processing.ingest.tasks_reupload.derive_source_format",
                lambda path: "geojson",
            ),
            (
                "app.processing.ingest.tasks_reupload.UploadedSource."
                "release_file_replacement",
                AsyncMock(),
            ),
        ):
            stack.enter_context(patch(target, new=replacement))
        await reupload_file(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=job.file_path,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )
    assert await _job_status(session, job.id) == "complete"
    return job


async def _restore(client, headers, session, dataset, expected: int, **patches):
    """Admit a restore through the API, then run the task it deferred."""
    from app.processing.ingest.tasks import restore_previous_version

    deferred = AsyncMock()
    with patch(
        "app.modules.catalog.datasets.api.router_previous_version."
        "defer_async_with_tenant",
        deferred,
    ):
        response = await client.post(
            f"/api/datasets/{dataset.id}/previous-version/restore",
            json={"expected_version_number": expected},
            headers=headers,
        )
    assert response.status_code == 202, response.text
    kwargs = deferred.await_args.kwargs
    with contextlib.ExitStack() as stack:
        for target, replacement in patches.items():
            stack.enter_context(patch(target, new=replacement))
        await restore_previous_version(**kwargs)
    return response.json()


async def _job_status(session, job_id) -> str:
    return await session.scalar(
        text("SELECT status FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
    )


async def _names(session, table: str) -> list[str]:
    rows = await session.execute(
        text(f'SELECT name FROM "data"."{table}" ORDER BY name')
    )
    return [row[0] for row in rows]


async def _dataset_row(session, dataset_id):
    return (
        await session.execute(
            text(
                "SELECT current_version, tile_cache_version, previous_version_number, "
                "previous_version_bytes, previous_version_retained_at, "
                "scheduled_refresh_hold FROM catalog.datasets WHERE id = :id"
            ),
            {"id": dataset_id},
        )
    ).one()


async def _relation_exists(session, table: str) -> bool:
    # A pg_class read takes the statement's snapshot, unlike to_regclass's cache.
    return await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'data' AND c.relname = :t)"
        ),
        {"t": table},
    )


async def _cleanup(session, dataset) -> None:
    await session.rollback()
    for table in (
        dataset.table_name,
        previous_version_table(dataset.table_name, dataset.id),
    ):
        await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


def test_the_producer_and_the_recognizer_agree() -> None:
    """Whatever name the producer makes, the recognizer knows, within 63 characters."""
    for base in ("parcels", "a", "x" * 80):
        name = previous_version_table(base, uuid.uuid4())
        assert is_previous_version_table(name), name
        assert len(name) <= 63
    assert not is_previous_version_table("parcels_previous")


async def test_a_replacement_keeps_the_replaced_table(
    test_db_session, admin_auth_header
) -> None:
    """The replaced rows stay in the previous-version table, hidden and unregisterable."""
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import (
        discover_unregistered_tables,
        register_existing_table,
    )

    session = test_db_session
    admin_id, dataset = await _seed(session)
    previous = previous_version_table(dataset.table_name, dataset.id)
    try:
        await _replace(session, dataset, admin_id, ["paris", "london"])

        assert await _names(session, dataset.table_name) == ["London", "Paris"]
        assert await _names(session, previous) == ["New York"]
        row = await _dataset_row(session, dataset.id)
        assert row.current_version == 2
        assert row.previous_version_number == 1
        assert row.previous_version_bytes > 0
        assert row.previous_version_retained_at is not None

        found = {
            table.table_name
            for table in await discover_unregistered_tables(session, limit=5000)
        }
        assert previous not in found
        matched = await session.scalar(
            text("SELECT :name ~ :pattern"),
            {"name": previous, "pattern": PREVIOUS_VERSION_NAME_PATTERN},
        )
        assert matched is True

        with pytest.raises(ValueError, match="previous version"):
            await register_existing_table(
                session,
                RegisterRequest(table_name=previous, title="Kept"),
                SimpleNamespace(id=admin_id),
            )
    finally:
        await _cleanup(session, dataset)


async def test_a_restore_publishes_the_previous_version(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    """The restore republishes version 1 as version 3 and keeps version 2 restorable."""
    from app.platform.refresh.execution import (
        RefreshAdmissionRequest,
        ScheduledRefreshHeld,
        prepare_admitted_refresh,
        release_scheduled_refresh_hold,
    )

    session = test_db_session
    admin_id, dataset = await _seed(session)
    previous = previous_version_table(dataset.table_name, dataset.id)
    try:
        await _replace(session, dataset, admin_id, ["paris", "london"])
        tiles_before = (await _dataset_row(session, dataset.id)).tile_cache_version

        admitted = await _restore(
            client,
            admin_auth_header,
            session,
            dataset,
            1,
            # Leaves the job's follow-up record as the terminal commit wrote it.
            **{"app.processing.ingest.publication.run_publish_followups": AsyncMock()},
        )

        assert await _names(session, dataset.table_name) == ["New York"]
        assert await _names(session, previous) == ["London", "Paris"]
        row = await _dataset_row(session, dataset.id)
        assert row.current_version == 3
        assert row.previous_version_number == 2
        assert row.tile_cache_version > tiles_before
        assert row.scheduled_refresh_hold == "restored"

        version = (
            await session.execute(
                text(
                    "SELECT restored_from_version, feature_count "
                    "FROM catalog.dataset_versions "
                    "WHERE dataset_id = :id AND version_number = 3"
                ),
                {"id": dataset.id},
            )
        ).one()
        assert version.restored_from_version == 1
        assert version.feature_count == 1

        run = (
            await session.execute(
                text(
                    "SELECT origin_kind, status FROM catalog.dataset_refresh_runs "
                    "WHERE id = :id"
                ),
                {"id": admitted["run_id"]},
            )
        ).one()
        assert (run.origin_kind, run.status) == ("restore", "succeeded")
        metadata = await session.scalar(
            text("SELECT user_metadata FROM catalog.ingest_jobs WHERE id = :id"),
            {"id": admitted["job_id"]},
        )
        owed = metadata["publish_obligations"]
        assert owed["task"] == "restore_previous_version"
        assert owed["tile_cache"] == dataset.table_name

        request = RefreshAdmissionRequest(
            source_binding_fingerprint="fp",
            local_edit_baseline=None,
            origin_kind="service",
        )
        with pytest.raises(ScheduledRefreshHeld) as held:
            await prepare_admitted_refresh(
                session,
                dataset=dataset,
                actor=SimpleNamespace(id=admin_id),
                request=request,
                trigger="scheduled",
                scheduled_for=row.previous_version_retained_at,
                occurrence_key="occ",
            )
        assert held.value.reason == "restored"
        await release_scheduled_refresh_hold(session, dataset.id)
        await session.commit()
        assert (await _dataset_row(session, dataset.id)).scheduled_refresh_hold is None
    finally:
        await _cleanup(session, dataset)


async def test_three_cycles_keep_the_index_and_key_names(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    """Replace, replace, restore: each table keeps its own key name and the live one its GIST index."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    table = dataset.table_name
    previous = previous_version_table(table, dataset.id)
    try:
        await _replace(session, dataset, admin_id, ["paris"])
        await _replace(session, dataset, admin_id, ["london"])
        await _restore(client, admin_auth_header, session, dataset, 2)

        assert await _names(session, table) == ["Paris"]
        assert await _names(session, previous) == ["London"]
        keys = dict(
            (
                await session.execute(
                    text(
                        "SELECT c.relname, con.conname FROM pg_constraint con "
                        "JOIN pg_class c ON c.oid = con.conrelid "
                        "WHERE con.contype = 'p' AND c.relname IN (:live, :prev)"
                    ),
                    {"live": table, "prev": previous},
                )
            ).all()
        )
        assert keys == {table: f"{table}_pkey", previous: f"{previous[:58]}_pkey"}
        gist = await session.scalar(
            text(
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'data' "
                "AND tablename = :t AND indexdef LIKE '%USING gist (geom_4326)%'"
            ),
            {"t": table},
        )
        assert gist >= 1
    finally:
        await _cleanup(session, dataset)


async def test_dropping_the_previous_version(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    """A stale version or an active run refuses the drop; otherwise the table goes."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    previous = previous_version_table(dataset.table_name, dataset.id)
    url = f"/api/datasets/{dataset.id}/previous-version"
    try:
        await _replace(session, dataset, admin_id, ["paris"])

        stale = await client.delete(
            url, params={"expected_version_number": 7}, headers=admin_auth_header
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "previous_version_changed"

        job = await _queue(
            session, dataset, admin_id, origin_kind="upload", metadata={}
        )
        busy = await client.delete(
            url, params={"expected_version_number": 1}, headers=admin_auth_header
        )
        assert busy.status_code == 409, busy.text
        assert busy.json()["detail"]["code"] == "dataset_busy"
        assert await _relation_exists(session, previous)
        await session.execute(
            text(
                "UPDATE catalog.dataset_refresh_runs SET status = 'cancelled' "
                "WHERE ingest_job_id = :id"
            ),
            {"id": job.id},
        )
        await session.commit()

        dropped = await client.delete(
            url, params={"expected_version_number": 1}, headers=admin_auth_header
        )
        assert dropped.status_code == 204, dropped.text
        assert not await _relation_exists(session, previous)
        row = await _dataset_row(session, dataset.id)
        assert row.previous_version_number is None
        assert row.previous_version_bytes is None

        gone = await client.delete(
            url, params={"expected_version_number": 1}, headers=admin_auth_header
        )
        assert gone.status_code == 404
        assert gone.json()["detail"]["code"] == "no_previous_version"
    finally:
        await _cleanup(session, dataset)


async def test_deleting_the_dataset_drops_its_previous_version(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    """No previous-version relation outlives its dataset."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    previous = previous_version_table(dataset.table_name, dataset.id)
    try:
        await _replace(session, dataset, admin_id, ["paris"])
        assert await _relation_exists(session, previous)

        deleted = await client.request(
            "DELETE",
            f"/api/datasets/{dataset.id}",
            json={"confirm_title": "Test Dataset"},
            headers=admin_auth_header,
        )
        assert deleted.status_code == 204, deleted.text
        assert not await _relation_exists(session, previous)
    finally:
        await _cleanup(session, dataset)


@pytest.mark.parametrize(
    ("visibility", "expected"), [("public", 403), ("private", 404)]
)
async def test_a_non_writer_can_neither_restore_nor_drop(
    client: AsyncClient,
    test_db_session,
    editor_auth_header,
    visibility: str,
    expected: int,
) -> None:
    """An editor who does not own the dataset is refused, and nothing is admitted."""
    session = test_db_session
    _, dataset = await _seed(session, visibility=visibility)
    await session.execute(
        text("UPDATE catalog.datasets SET previous_version_number = 1 WHERE id = :id"),
        {"id": dataset.id},
    )
    await session.commit()
    try:
        restore = await client.post(
            f"/api/datasets/{dataset.id}/previous-version/restore",
            json={"expected_version_number": 1},
            headers=editor_auth_header,
        )
        drop = await client.delete(
            f"/api/datasets/{dataset.id}/previous-version",
            params={"expected_version_number": 1},
            headers=editor_auth_header,
        )
        assert (restore.status_code, drop.status_code) == (expected, expected)
        runs = await session.scalar(
            text(
                "SELECT count(*) FROM catalog.dataset_refresh_runs WHERE dataset_id = :id"
            ),
            {"id": dataset.id},
        )
        assert runs == 0
    finally:
        await _cleanup(session, dataset)


async def test_restore_admission_refusals(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    """No previous version, a raster, a stale version and an active run are each refused."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    url = f"/api/datasets/{dataset.id}/previous-version/restore"
    try:
        none = await client.post(
            url, json={"expected_version_number": 1}, headers=admin_auth_header
        )
        assert none.status_code == 404, none.text
        assert none.json()["detail"]["code"] == "no_previous_version"

        await _replace(session, dataset, admin_id, ["paris"])
        stale = await client.post(
            url, json={"expected_version_number": 5}, headers=admin_auth_header
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "previous_version_changed"

        await _queue(session, dataset, admin_id, origin_kind="upload", metadata={})
        busy = await client.post(
            url, json={"expected_version_number": 1}, headers=admin_auth_header
        )
        assert busy.status_code == 409, busy.text
        assert busy.json()["detail"]["code"] == "dataset_busy"

        raster = await create_raster_dataset(session, created_by=admin_id)
        not_vector = await client.post(
            f"/api/datasets/{raster.id}/previous-version/restore",
            json={"expected_version_number": 1},
            headers=admin_auth_header,
        )
        assert not_vector.status_code == 422, not_vector.text
        assert not_vector.json()["detail"]["code"] == "restore_not_applicable"
    finally:
        await _cleanup(session, dataset)


async def test_the_detail_and_versions_name_the_previous_version(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    """The dataset detail summarizes the previous version and the history names a restore's source."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await _replace(session, dataset, admin_id, ["paris", "london"])
        await _replace(session, dataset, admin_id, ["paris"])

        detail = await client.get(
            f"/api/datasets/{dataset.id}", headers=admin_auth_header
        )
        assert detail.status_code == 200, detail.text
        summary = detail.json()["previous_version"]
        assert summary["version_number"] == 2
        assert summary["feature_count"] == 2
        assert summary["size_bytes"] > 0

        await _restore(client, admin_auth_header, session, dataset, 2)
        versions = await client.get(
            f"/api/datasets/{dataset.id}/versions/", headers=admin_auth_header
        )
        restored = {
            v["version_number"]: v["restored_from_version"]
            for v in versions.json()["versions"]
        }
        assert restored == {2: None, 3: None, 4: 2}
    finally:
        await _cleanup(session, dataset)
