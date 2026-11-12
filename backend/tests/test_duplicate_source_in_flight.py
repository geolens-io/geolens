"""A user gets one copy of one service layer or database table, even while imports are queued."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager, suppress
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text, update

from app.core.config import settings
from app.modules.catalog.datasets.api import router_reupload
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.sources import database_router
from app.platform.database_sources import (
    SpatialTable,
    SpatialTableListing,
    TableGeometry,
)
from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from app.platform.jobs.models import IngestJob
from app.platform.source_copies import service_identity
from app.processing.ingest import service as ingest_service
from app.processing.ingest import tasks_database, tasks_vector
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_database_import_door import _connection
from app.processing.ingest.tasks_reupload import reupload_service
from tests.test_service_reupload_3d import (
    _WELLS,
    _base_of,
    _fake_fetch,
    _fresh_base,
    _ingest,
    _source,
)

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
    monkeypatch.setattr(
        tasks_vector, "_fetch_arcgis_field_labels", AsyncMock(return_value=None)
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


def _wfs_url() -> str:
    return f"https://maps.example.com/geoserver{uuid.uuid4().hex[:6]}/wfs"


def _wfs_job(url: str, owner: uuid.UUID, status: str = "pending") -> IngestJob:
    return IngestJob(
        source_filename="Buildings",
        source_url=url,
        source_layer="buildings",
        created_by=owner,
        status=status,
        user_metadata={
            "title": f"Buildings {uuid.uuid4().hex[:8]}",
            "service_type": "WFS 2.0.0",
            "geometry_type": "Point",
            "commit_attempted_at": "2026-11-09T00:00:00+00:00",
        },
    )


async def _bind_wfs(session, owner: uuid.UUID, url: str) -> Dataset:
    dataset = await create_dataset(
        session, created_by=owner, name="Buildings", source_format="wfs"
    )
    restamp(
        dataset,
        SourceBinding.service("wfs", url=url, layer_id="buildings", enriched_uri=url),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await session.commit()
    return dataset


async def _preview_wfs(client, headers, url: str):
    with (
        patch("app.modules.catalog.sources.router.validate_url_for_ssrf"),
        _no_remote_preview(),
    ):
        return await client.post(
            "/services/preview/",
            json={"url": url, "service_type": "WFS 2.0.0", "layer_name": "buildings"},
            headers=headers,
        )


async def _run_service(job: IngestJob, owner: uuid.UUID) -> None:
    await tasks_vector.ingest_service.func(
        job_id=str(job.id),
        attempt_id=str(job.attempt_id),
        source_url=job.source_url,
        source_layer=job.source_layer,
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
    url = f"{_wfs_url()}?SERVICE=WFS&map=/a.map"
    owner = await get_user_id(test_db_session, "admin")
    existing = await _bind_wfs(test_db_session, owner, url)

    resp = await _preview_wfs(client, admin_auth_header, url)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["existing_dataset_id"] == str(existing.id)


async def test_a_published_layer_blocks_a_preview_without_its_trailing_slash(
    client: AsyncClient, admin_auth_header, test_db_session
):
    url = _wfs_url()
    owner = await get_user_id(test_db_session, "admin")
    existing = await _bind_wfs(test_db_session, owner, url + "/")

    resp = await _preview_wfs(client, admin_auth_header, url)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["existing_dataset_id"] == str(existing.id)


async def test_a_queued_wfs_layer_blocks_a_preview_spelled_another_way(
    client: AsyncClient, admin_auth_header, test_db_session
):
    url = _wfs_url()
    owner = await get_user_id(test_db_session, "admin")
    queued = _wfs_job(url + "/", owner, status="running")
    test_db_session.add(queued)
    await test_db_session.commit()

    resp = await _preview_wfs(
        client, admin_auth_header, f"{url}?service=WFS&request=GetCapabilities"
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["existing_job_id"] == str(queued.id)


def test_a_parameter_that_picks_the_service_keeps_identities_apart():
    def identity(url):
        return service_identity("WFS 2.0.0", url, layer_id=None, layer_name="buildings")

    base = "https://maps.example.com/cgi-bin/mapserv"
    assert identity(f"{base}?map=/a.map&SERVICE=WFS") == identity(f"{base}/?map=/a.map")
    assert identity(f"{base}?map=/a.map") != identity(f"{base}?map=/b.map")


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


async def _publish_at_once(session, monkeypatch, jobs, owner) -> None:
    """Run ``jobs`` together; one publishes and the other is refused."""
    session.add_all(jobs)
    await session.commit()
    before = await _datasets_of(session, owner)
    tables = await _data_tables(session)

    fetched = asyncio.Barrier(len(jobs))
    fetch = _fake_fetch(_WELLS)

    async def _fetch_together(*args, **kwargs):
        await fetch(*args, **kwargs)
        await fetched.wait()

    publishing = asyncio.Barrier(len(jobs))
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
        await session.refresh(job)
    done = [job for job in jobs if job.status == "complete"]
    refused = [job for job in jobs if job.status == "failed"]
    assert len(done) == 1 and len(refused) == 1, [j.error_message for j in jobs]
    [published], [loser] = done, refused
    assert loser.error_code == "duplicate_source"
    assert str(published.dataset_id) in loser.error_message
    assert loser.dataset_id is None
    assert await _datasets_of(session, owner) == before + 1
    live = await session.get(Dataset, published.dataset_id)
    assert await _data_tables(session) - tables == {live.table_name}


async def test_two_workers_publishing_one_layer_at_once_publish_one_dataset(
    test_db_session, monkeypatch
):
    base = _fresh_base()
    owner = await get_user_id(test_db_session, "admin")
    jobs = [_service_job(base, owner, status="pending") for _ in range(2)]
    await _publish_at_once(test_db_session, monkeypatch, jobs, owner)


async def test_two_spellings_of_one_wfs_layer_publishing_at_once_publish_one(
    test_db_session, monkeypatch
):
    url = _wfs_url()
    owner = await get_user_id(test_db_session, "admin")
    jobs = [_wfs_job(url + "/", owner), _wfs_job(url, owner)]
    await _publish_at_once(test_db_session, monkeypatch, jobs, owner)


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

    # The dataset outlives the test and would make the same source a duplicate.
    await test_db_session.delete(existing)
    await test_db_session.commit()


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


async def _reupload_from(session, monkeypatch, dataset_id, base: str) -> IngestJob:
    owner = await get_user_id(session, "admin")
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Wells",
        source_url=base,
        source_layer="0",
        created_by=owner,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    with _source(monkeypatch, _WELLS):
        await reupload_service.func(
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            dataset_id=str(dataset_id),
            source_url=base,
            source_layer="0",
            user_id=str(owner),
        )
    await session.refresh(job)
    return job


async def test_a_reupload_of_a_layer_into_another_dataset_is_refused(
    test_db_session, monkeypatch
):
    first = await _ingest(test_db_session, monkeypatch, _WELLS)
    other = await _ingest(test_db_session, monkeypatch, _WELLS)
    layer, other_layer = await _base_of(first), await _base_of(other)

    job = await _reupload_from(test_db_session, monkeypatch, other, layer)

    assert job.status == "failed"
    assert job.error_code == "duplicate_source"
    assert str(first) in job.error_message
    assert await _base_of(other) == other_layer


async def test_a_reupload_of_a_layer_into_its_own_dataset_is_allowed(
    test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch, _WELLS)

    job = await _reupload_from(
        test_db_session, monkeypatch, dataset_id, await _base_of(dataset_id)
    )

    assert job.status == "complete", job.error_message


async def _preview_reupload(client, headers, dataset_id, url: str):
    reported = {
        "srid": 4326,
        "geometry_type": "Point Z",
        "layer_name": "0",
        "feature_count": len(_WELLS),
        "columns": [{"name": "name", "type": "String"}],
        "sample_rows": [],
    }
    with (
        patch.object(router_reupload, "validate_url_for_ssrf", AsyncMock()),
        patch.object(
            router_reupload, "fetch_arcgis_layer_meta", AsyncMock(return_value={})
        ),
        patch.object(
            router_reupload, "run_service_preview", AsyncMock(return_value=reported)
        ),
    ):
        return await client.post(
            f"/datasets/{dataset_id}/reupload/service/preview",
            headers=headers,
            json={
                "url": url,
                "service_type": "ArcGIS FeatureServer",
                "layer_name": "0",
                "layer_id": "0",
            },
        )


async def test_the_reupload_door_refuses_a_layer_another_dataset_holds(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    first = await _ingest(test_db_session, monkeypatch, _WELLS)
    other = await _ingest(test_db_session, monkeypatch, _WELLS)
    layer = await _base_of(first)

    refused = await _preview_reupload(client, admin_auth_header, other, layer + "/")
    allowed = await _preview_reupload(client, admin_auth_header, first, layer + "/")

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["existing_dataset_id"] == str(first)
    assert allowed.status_code == 200, allowed.text


async def _import_as(
    session, monkeypatch, owner: uuid.UUID, base: str | None = None
) -> uuid.UUID:
    job = _service_job(base or _fresh_base(), owner, status="pending")
    session.add(job)
    await session.commit()
    with _source(monkeypatch, _WELLS):
        await _run_service(job, owner)
    await session.refresh(job)
    assert job.status == "complete", job.error_message
    return job.dataset_id


async def test_an_admin_reupload_into_a_users_dataset_checks_that_users_copies(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    _, alice_id = await create_user(client, admin_auth_header, "editor")
    alice = uuid.UUID(alice_id)
    first = await _import_as(test_db_session, monkeypatch, alice)
    other = await _import_as(test_db_session, monkeypatch, alice)
    layer, other_layer = await _base_of(first), await _base_of(other)

    refused = await _preview_reupload(client, admin_auth_header, other, layer)
    job = await _reupload_from(test_db_session, monkeypatch, other, layer)

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["existing_dataset_id"] == str(first)
    assert job.status == "failed"
    assert job.error_code == "duplicate_source"
    # The copy is Alice's, not the submitter's, so the reason doesn't name it.
    assert str(first) not in job.error_message
    assert await _base_of(other) == other_layer


def test_the_order_of_a_repeated_parameter_is_part_of_the_identity():
    def identity(url):
        return service_identity("WFS 2.0.0", url, layer_id=None, layer_name="roads")

    base = "https://maps.example.com/cgi-bin/mapserv"
    assert identity(f"{base}?map=/a.map&map=/b.map") != identity(
        f"{base}?map=/b.map&map=/a.map"
    )
    assert identity(f"{base}?map=/a.map&SERVICE=WFS&map=/b.map") == identity(
        f"{base}?map=/a.map&map=/b.map"
    )


async def test_a_dataset_left_without_a_layer_binding_matches_any_spelling(
    client: AsyncClient, admin_auth_header, test_db_session
):
    host = f"maps{uuid.uuid4().hex[:6]}.example.com"
    owner = await get_user_id(test_db_session, "admin")
    existing = await create_dataset(
        test_db_session,
        created_by=owner,
        name="Buildings",
        source_format="wfs",
        source_url=f"https://{host.upper()}/wfs/buildings/",
    )
    # The shape migration 0036 left when no ingest job named the layer.
    await test_db_session.execute(
        update(Dataset)
        .where(Dataset.id == existing.id)
        .values(origin_ref={"kind": "service", "service_type": "wfs"})
    )
    await test_db_session.commit()

    with (
        patch("app.modules.catalog.sources.router.validate_url_for_ssrf"),
        _no_remote_preview(),
    ):
        resp = await client.post(
            "/services/preview/",
            json={
                "url": f"https://{host}/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
                "layer_id": "buildings",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["existing_dataset_id"] == str(existing.id)


@pytest.mark.parametrize(
    ("copy_held_by", "outcome"),
    [("committer", "failed"), ("previewer", "complete")],
)
async def test_a_preview_committed_by_an_admin_is_checked_against_the_admin(
    client: AsyncClient,
    admin_auth_header,
    test_db_session,
    monkeypatch,
    copy_held_by,
    outcome,
):
    _, alice_id = await create_user(client, admin_auth_header, "editor")
    alice = uuid.UUID(alice_id)
    admin = await get_user_id(test_db_session, "admin")
    base = _fresh_base()
    held = _service_job(base, admin if copy_held_by == "committer" else alice)
    previewed = _service_job(base, alice, status="pending")
    test_db_session.add(held)
    await test_db_session.commit()
    with _source(monkeypatch, _WELLS):
        await _run_service(held, held.created_by)
        test_db_session.add(previewed)
        await test_db_session.commit()
        # The admin committed Alice's preview, so the dataset will be the admin's.
        await _run_service(previewed, admin)

    await test_db_session.refresh(previewed)
    assert previewed.status == outcome, previewed.error_message
    await test_db_session.refresh(held)
    assert held.dataset_id is not None
    # Alice can read her job but not the admin's dataset, so it goes unnamed.
    assert str(held.dataset_id) not in (previewed.error_message or "")


def test_only_parameter_names_ogc_makes_case_blind_are_folded():
    def identity(url):
        return service_identity("WFS 2.0.0", url, layer_id=None, layer_name="roads")

    base = "https://maps.example.com/geoserver/wfs"
    assert identity(f"{base}?TYPENAME=roads") == identity(f"{base}?typeName=roads")
    assert identity(f"{base}?workspace=a") != identity(f"{base}?Workspace=a")


async def test_a_users_preview_committed_by_an_admin_counts_as_the_admins_import(
    client: AsyncClient, admin_auth_header, test_db_session, deferred
):
    alice_headers, _ = await create_user(client, admin_auth_header, "editor")
    admin = await get_user_id(test_db_session, "admin")
    preview = {
        "url": _fresh_base(),
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
        previewed = await client.post(
            "/services/preview/", json=preview, headers=alice_headers
        )
        job_id = previewed.json()["job_id"]
        committed = await client.post(
            f"/ingest/commit/{job_id}",
            json={"title": "Wells", "visibility": "private"},
            headers=admin_auth_header,
        )
        assert committed.status_code == 202, committed.text

        admins = await client.post(
            "/services/preview/", json=preview, headers=admin_auth_header
        )
        alices = await client.post(
            "/services/preview/", json=preview, headers=alice_headers
        )

    assert admins.status_code == 409, admins.text
    assert admins.json()["detail"]["existing_job_id"] == job_id
    assert alices.status_code == 200, alices.text

    job = await test_db_session.get(IngestJob, uuid.UUID(job_id))
    job.status = "failed"
    await test_db_session.commit()
    deferred.reset_mock()
    retried = await client.post(f"/jobs/{job_id}/retry", headers=admin_auth_header)
    assert retried.status_code == 202, retried.text
    # A retry publishes for the account the commit chose.
    assert deferred.await_args.kwargs["user_id"] == str(admin)


@pytest.mark.parametrize("copy_exists", [True, False])
async def test_only_the_account_a_job_publishes_for_may_retry_it(
    client: AsyncClient,
    admin_auth_header,
    test_db_session,
    monkeypatch,
    deferred,
    copy_exists,
):
    alice_headers, alice_id = await create_user(client, admin_auth_header, "editor")
    admin = await get_user_id(test_db_session, "admin")
    base = _fresh_base()
    if copy_exists:
        await _import_as(test_db_session, monkeypatch, admin, base)
    committed = _service_job(base, uuid.UUID(alice_id), status="failed")
    committed.user_metadata = {**committed.user_metadata, "published_for": str(admin)}
    test_db_session.add(committed)
    await test_db_session.commit()

    previewer = await client.post(f"/jobs/{committed.id}/retry", headers=alice_headers)
    publisher = await client.post(
        f"/jobs/{committed.id}/retry", headers=admin_auth_header
    )

    assert previewer.status_code == 404, previewer.text
    assert previewer.json()["detail"] == "Job not found"
    assert publisher.status_code == (409 if copy_exists else 202), publisher.text


async def test_an_import_is_named_only_to_a_caller_who_can_read_its_job(
    client: AsyncClient, admin_auth_header, test_db_session
):
    # Bob committed Alice's preview while an admin; he is an editor now.
    _, alice_id = await create_user(client, admin_auth_header, "editor")
    bob_headers, bob_id = await create_user(client, admin_auth_header, "editor")
    base = _fresh_base()
    queued = _service_job(base, uuid.UUID(alice_id), status="running")
    queued.user_metadata = {**queued.user_metadata, "published_for": bob_id}
    test_db_session.add(queued)
    await test_db_session.commit()

    with (
        patch("app.modules.catalog.sources.router.validate_url_for_ssrf"),
        _no_remote_preview(),
    ):
        resp = await client.post(
            "/services/preview/",
            json={
                "url": base,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=bob_headers,
        )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "duplicate_source"
    assert "existing_job_id" not in detail and "existing_dataset_id" not in detail
    assert str(queued.id) not in resp.text


async def test_a_refused_publication_sends_the_ingest_failed_notice(
    test_db_session, monkeypatch
):
    from app.platform.notifications import events as events_mod

    monkeypatch.setattr(settings, "notify_on_ingest_failed", True, raising=False)
    sent: list = []

    async def _notify(notification):
        sent.append(notification)

    monkeypatch.setattr(events_mod, "notify", _notify)
    owner = await get_user_id(test_db_session, "admin")
    base = _fresh_base()
    await _import_as(test_db_session, monkeypatch, owner, base)
    sent.clear()
    second = _service_job(base, owner, status="pending")
    test_db_session.add(second)
    await test_db_session.commit()

    with _source(monkeypatch, _WELLS):
        await _run_service(second, owner)

    await test_db_session.refresh(second)
    assert second.error_code == "duplicate_source"
    assert [(n.event_type, n.data.get("job_id")) for n in sent] == [
        ("ingest_failed", str(second.id))
    ]
