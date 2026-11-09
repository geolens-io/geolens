"""A user gets one copy of one service layer or database table, even while imports are queued."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager, suppress
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.sources import database_router
from app.platform.database_sources import (
    SpatialTable,
    SpatialTableListing,
    TableGeometry,
)
from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from app.platform.jobs.models import IngestJob
from app.processing.ingest import service as ingest_service
from app.processing.ingest import tasks_database, tasks_vector
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_database_import_door import _connection
from tests.test_service_reupload_3d import _WELLS, _fake_fetch, _fresh_base, _source

pytestmark = pytest.mark.anyio

DB_URL = "/services/databases/gis/imports/"


@pytest.fixture
def deferred(monkeypatch) -> AsyncMock:
    defer = AsyncMock()
    monkeypatch.setattr(ingest_service, "defer_async_with_tenant", defer)
    return defer


@pytest.fixture(autouse=True)
def no_layer_metadata(monkeypatch):
    monkeypatch.setattr(
        tasks_vector,
        "_fetch_arcgis_layer_meta_or_none",
        AsyncMock(return_value=None),
    )


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})
    table = SpatialTable(
        schema_name="dbo",
        table_name="parcels",
        object_type="table",
        geometry_column="shape",
        column_type="geometry",
        srid=4326,
    )
    monkeypatch.setattr(
        database_router,
        "list_spatial_tables",
        AsyncMock(return_value=SpatialTableListing(tables=[table], truncated=False)),
    )


@contextmanager
def _no_remote_preview():
    """Answer any preview that gets past the duplicate check without a fetch."""
    with (
        patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new=AsyncMock(side_effect=AssertionError("previewed")),
        ),
        patch(
            "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
            new=AsyncMock(side_effect=AssertionError("previewed")),
        ),
    ):
        yield


async def _data_tables(session) -> set[str]:
    rows = await session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'data'")
    )
    return {row[0] for row in rows}


async def _datasets_of(session, user_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .where(Record.created_by == user_id)
    )


def _service_job(base: str, owner: uuid.UUID, **values) -> IngestJob:
    return IngestJob(
        source_filename="Wells",
        source_url=base,
        source_layer="0",
        created_by=owner,
        **values,
        user_metadata={
            "title": f"Wells {uuid.uuid4().hex[:8]}",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": 0,
            "geometry_type": "Point",
            "commit_attempted_at": "2026-11-09T00:00:00+00:00",
        },
    )


async def _run_service(job: IngestJob, owner: uuid.UUID) -> None:
    await tasks_vector.ingest_service.func(
        job_id=str(job.id),
        attempt_id=str(job.attempt_id),
        source_url=job.source_url,
        source_layer="0",
        user_id=str(owner),
    )


async def test_a_queued_service_import_makes_the_second_preview_a_duplicate(
    client: AsyncClient, editor_auth_header, test_db_session, deferred
):
    base = _fresh_base()
    preview = {
        "url": base,
        "service_type": "ArcGIS:FeatureServer",
        "layer_name": "0",
        "layer_id": 0,
    }
    canned = {
        "srid": 4326,
        "geometry_type": "Point",
        "layer_name": "Wells",
        "feature_count": None,
        "columns": [{"name": "OBJECTID", "type": "Integer64"}],
        "sample_rows": [{"OBJECTID": 1}],
    }
    with (
        patch("app.modules.catalog.sources.router.validate_url_for_ssrf"),
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch(
            "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
            new=AsyncMock(return_value=canned),
        ),
    ):
        first = await client.post(
            "/services/preview/", json=preview, headers=editor_auth_header
        )
        assert first.status_code == 200, first.text
        # A preview nobody committed is not an import.
        again = await client.post(
            "/services/preview/", json=preview, headers=editor_auth_header
        )
        assert again.status_code == 200, again.text

        job_id = first.json()["job_id"]
        committed = await client.post(
            f"/ingest/commit/{job_id}",
            json={"title": "Wells", "visibility": "private"},
            headers=editor_auth_header,
        )
        assert committed.status_code == 202, committed.text

        duplicate = await client.post(
            "/services/preview/", json=preview, headers=editor_auth_header
        )
        assert duplicate.status_code == 409, duplicate.text
        detail = duplicate.json()["detail"]
        assert detail["code"] == "duplicate_source"
        assert detail["existing_job_id"] == job_id
        assert "existing_dataset_id" not in detail
        assert "existing_title" not in detail

        job = await test_db_session.get(IngestJob, uuid.UUID(job_id))
        job.status = "failed"
        await test_db_session.commit()
        retried = await client.post(
            "/services/preview/", json=preview, headers=editor_auth_header
        )
        assert retried.status_code == 200, retried.text


@pytest.mark.parametrize("ended", ["failed", "cancelled"])
async def test_a_queued_database_import_makes_the_second_a_duplicate(
    client: AsyncClient, editor_auth_header, test_db_session, database, deferred, ended
):
    body = {"schema_name": "dbo", "table_name": "parcels", "title": "Parcels"}
    first = await client.post(DB_URL, json=body, headers=editor_auth_header)
    assert first.status_code == 202, first.text

    duplicate = await client.post(DB_URL, json=body, headers=editor_auth_header)

    assert duplicate.status_code == 409, duplicate.text
    detail = duplicate.json()["detail"]
    assert detail["code"] == "duplicate_source"
    assert detail["existing_job_id"] == first.json()["job_id"]
    assert "existing_dataset_id" not in detail
    assert "existing_title" not in detail

    job = await test_db_session.get(IngestJob, uuid.UUID(first.json()["job_id"]))
    job.status = ended
    await test_db_session.commit()
    after = await client.post(DB_URL, json=body, headers=editor_auth_header)
    assert after.status_code == 202, after.text


async def test_a_published_layer_blocks_a_preview_of_its_url_as_stored(
    client: AsyncClient, admin_auth_header, test_db_session
):
    url = f"https://maps.example.com/wfs{uuid.uuid4().hex[:6]}?SERVICE=WFS&map=/a.map"
    owner = await get_user_id(test_db_session, "admin")
    existing = await create_dataset(
        test_db_session, created_by=owner, name="Buildings", source_format="wfs"
    )
    restamp(
        existing,
        SourceBinding.service("wfs", url=url, layer_id="buildings", enriched_uri=url),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await test_db_session.commit()

    with (
        patch("app.modules.catalog.sources.router.validate_url_for_ssrf"),
        _no_remote_preview(),
    ):
        resp = await client.post(
            "/services/preview/",
            json={"url": url, "service_type": "WFS 2.0.0", "layer_name": "buildings"},
            headers=admin_auth_header,
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["existing_dataset_id"] == str(existing.id)


async def test_a_queued_layer_blocks_a_preview_that_spells_its_url_differently(
    client: AsyncClient, admin_auth_header, test_db_session
):
    base = _fresh_base()
    owner = await get_user_id(test_db_session, "admin")
    queued = _service_job(base, owner, status="running")
    test_db_session.add(queued)
    await test_db_session.commit()

    with (
        patch("app.modules.catalog.sources.router.validate_url_for_ssrf"),
        _no_remote_preview(),
    ):
        resp = await client.post(
            "/services/preview/",
            json={
                "url": f"{base}/0/query/?f=json",
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "Wells",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["existing_job_id"] == str(queued.id)


async def test_two_workers_publishing_one_layer_at_once_publish_one_dataset(
    test_db_session, monkeypatch
):
    base = _fresh_base()
    owner = await get_user_id(test_db_session, "admin")
    jobs = [_service_job(base, owner, status="pending") for _ in range(2)]
    test_db_session.add_all(jobs)
    await test_db_session.commit()
    before = await _datasets_of(test_db_session, owner)
    tables = await _data_tables(test_db_session)

    fetched = asyncio.Barrier(2)
    fetch = _fake_fetch(_WELLS)

    async def _fetch_together(*args, **kwargs):
        await fetch(*args, **kwargs)
        await fetched.wait()

    publishing = asyncio.Barrier(2)
    publish = tasks_vector._publish_attempt_staging_table

    async def _publish_together(*args, **kwargs):
        # Both attempts reach publication together unless the first holds
        # the other back; then this wait runs out and the first goes on.
        with suppress(TimeoutError):
            async with asyncio.timeout(1):
                await publishing.wait()
        await publish(*args, **kwargs)

    monkeypatch.setattr(
        tasks_vector, "_publish_attempt_staging_table", _publish_together
    )
    with _source(monkeypatch, _WELLS):
        with patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service", new=_fetch_together
        ):
            await asyncio.gather(*(_run_service(job, owner) for job in jobs))

    for job in jobs:
        await test_db_session.refresh(job)
    done = [job for job in jobs if job.status == "complete"]
    refused = [job for job in jobs if job.status == "failed"]
    assert len(done) == 1 and len(refused) == 1, [j.error_message for j in jobs]
    [published], [loser] = done, refused
    assert loser.error_code == "duplicate_source"
    assert str(published.dataset_id) in loser.error_message
    assert loser.dataset_id is None
    assert await _datasets_of(test_db_session, owner) == before + 1
    live = await test_db_session.get(Dataset, published.dataset_id)
    assert await _data_tables(test_db_session) - tables == {live.table_name}


async def test_a_database_job_refused_at_publication_leaves_no_table_or_dataset(
    client: AsyncClient,
    admin_auth_header,
    test_db_session,
    database,
    deferred,
    monkeypatch,
):
    body = {"schema_name": "dbo", "table_name": "parcels"}
    queued = await client.post(DB_URL, json=body, headers=admin_auth_header)
    assert queued.status_code == 202, queued.text
    owner = await get_user_id(test_db_session, "admin")
    # Published by another request after this job passed the door.
    existing = await create_dataset(
        test_db_session, created_by=owner, name="Parcels", source_format="database"
    )
    restamp(
        existing,
        SourceBinding.database("gis", schema="dbo", table="parcels"),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await test_db_session.commit()
    before = await _datasets_of(test_db_session, owner)
    tables = await _data_tables(test_db_session)

    async def _copy(connection, *, target_schema, target_table, **_):
        await _fake_fetch(_WELLS)(
            "", "", target_table, "", "database", schema=target_schema
        )

    monkeypatch.setattr(tasks_database, "copy_database_table", _copy)
    monkeypatch.setattr(
        tasks_database,
        "probe_table_geometry",
        AsyncMock(return_value=TableGeometry(column="shape", srid=4326)),
    )

    await tasks_database.ingest_database.func(**deferred.await_args.kwargs)

    job = await test_db_session.get(IngestJob, uuid.UUID(queued.json()["job_id"]))
    await test_db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "duplicate_source"
    assert str(existing.id) in job.error_message
    assert job.dataset_id is None
    assert await _datasets_of(test_db_session, owner) == before
    assert await _data_tables(test_db_session) == tables


async def test_a_retry_is_refused_while_the_owner_holds_a_copy_and_allowed_after(
    client: AsyncClient,
    admin_auth_header,
    test_db_session,
    deferred,
    monkeypatch,
):
    base = _fresh_base()
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    owner = uuid.UUID(owner_id)
    old = _service_job(base, owner, status="failed")
    copy = _service_job(base, owner, status="pending")
    test_db_session.add_all([old, copy])
    await test_db_session.commit()
    with _source(monkeypatch, _WELLS):
        await _run_service(copy, owner)
    await test_db_session.refresh(copy)
    assert copy.status == "complete", copy.error_message

    # The admin restarting the job holds no copy; the owner's copy counts.
    refused = await client.post(f"/jobs/{old.id}/retry", headers=admin_auth_header)

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "duplicate_source"
    assert detail["existing_dataset_id"] == str(copy.dataset_id)
    deferred.assert_not_awaited()

    dataset = await test_db_session.get(Dataset, copy.dataset_id)
    record = await test_db_session.get(Record, dataset.record_id)
    deleted = await client.request(
        "DELETE",
        f"/datasets/{copy.dataset_id}",
        json={"confirm_title": record.title},
        headers=owner_headers,
    )
    assert deleted.status_code in (200, 204), deleted.text
    allowed = await client.post(f"/jobs/{old.id}/retry", headers=admin_auth_header)
    assert allowed.status_code == 202, allowed.text


async def test_a_retry_that_passed_the_door_is_refused_at_publication(
    client: AsyncClient, admin_auth_header, test_db_session, deferred, monkeypatch
):
    base = _fresh_base()
    owner = await get_user_id(test_db_session, "admin")
    old = _service_job(base, owner, status="failed")
    again = _service_job(base, owner, status="pending")
    test_db_session.add_all([old, again])
    await test_db_session.commit()

    retried = await client.post(f"/jobs/{old.id}/retry", headers=admin_auth_header)
    assert retried.status_code == 202, retried.text
    with _source(monkeypatch, _WELLS):
        await _run_service(again, owner)
        await test_db_session.refresh(again)
        assert again.status == "complete", again.error_message
        await tasks_vector.ingest_service.func(**deferred.await_args.kwargs)

    await test_db_session.refresh(old)
    assert old.status == "failed"
    assert old.error_code == "duplicate_source"
    assert str(again.dataset_id) in old.error_message
    assert old.dataset_id is None
