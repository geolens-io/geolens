"""An admin's dataset list against a job that has just reported ``complete``.

A publish commits its job as complete before its post-commit steps purge the
catalog cache, so a client that polls the job and then lists can land between
the two. Each test lists as the admin once before the publish, then polls the
job and lists again from inside that window, on the real task, routes and
database.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select, text

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.models import IngestJob
from app.platform.storage import provider as storage_provider
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.tasks import reupload_service
from app.processing.ingest.tasks_vector import ingest_file

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_GEOJSON = (
    b'{"type":"FeatureCollection","features":['
    b'{"type":"Feature","properties":{"name":"a"},'
    b'"geometry":{"type":"Point","coordinates":[1.0,2.0]}}]}'
)


class _Poller:
    """An admin client that polls a job, then lists datasets."""

    def __init__(self, client, headers) -> None:
        self.client = client
        self.headers = headers
        self.job_id: uuid.UUID | None = None
        self.job_status: str | None = None
        self.listed: dict[str, dict] = {}

    async def list(self) -> dict[str, dict]:
        response = await self.client.get("/datasets/", headers=self.headers)
        assert response.status_code == 200, response.text
        return {row["id"]: row for row in response.json()["datasets"]}

    async def poll_then_list(self) -> None:
        response = await self.client.get(f"/jobs/{self.job_id}", headers=self.headers)
        assert response.status_code == 200, response.text
        self.job_status = response.json()["status"]
        self.listed = await self.list()

    async def between_commit_and_purge(self) -> None:
        """Stands in for the task's own purge: the poll lands first."""
        await self.poll_then_list()
        await invalidate_catalog_cache()


@pytest.fixture
async def job_ids(client, admin_auth_header, test_db_session):
    """Jobs a test ran; each is removed afterwards with its dataset and table."""
    ids: list[uuid.UUID] = []
    yield ids
    session = test_db_session
    session.expire_all()
    for job_id in ids:
        dataset = (
            await session.execute(
                select(Dataset.id, Dataset.table_name, Record.id, Record.title)
                .join(Record, Record.id == Dataset.record_id)
                .join(IngestJob, IngestJob.dataset_id == Dataset.id)
                .where(IngestJob.id == job_id)
            )
        ).one_or_none()
        if dataset is not None:
            dataset_id, table_name, record_id, title = dataset
            await client.request(
                "DELETE",
                f"/datasets/{dataset_id}",
                json={"confirm_title": title},
                headers=admin_auth_header,
            )
        await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        if dataset is not None:
            await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
            await session.execute(delete(Record).where(Record.id == record_id))
            for name in (table_name, f"{table_name}_old"):
                await session.execute(text(f'DROP TABLE IF EXISTS data."{name}"'))
        await session.commit()


@pytest.fixture
def store(tmp_path, monkeypatch) -> LocalStorageProvider:
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    monkeypatch.setattr(storage_provider, "_storage", storage)
    return storage


async def _fake_ogr2ogr(file_path, table_name, db_conn_str, *, schema, **kwargs):
    from app.core.db import async_session

    async with async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "{schema}"."{table_name}" '
                "(gid serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}"."{table_name}" (name, geom) '
                "VALUES ('a', ST_SetSRID(ST_Point(1, 2), 4326))"
            )
        )
        await session.commit()


async def test_a_first_import_is_listed_once_its_job_reads_complete(
    client, admin_auth_header, test_db_session, tmp_path, store, job_ids
) -> None:
    await invalidate_catalog_cache()
    poller = _Poller(client, admin_auth_header)
    before = await poller.list()

    admin_id = (
        await test_db_session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()
    source = tmp_path / "points.geojson"
    source.write_bytes(_GEOJSON)
    title = f"Listed after publish {uuid.uuid4().hex[:8]}"
    job = IngestJob(
        source_filename="points.geojson",
        file_path=str(source),
        created_by=admin_id,
        status="pending",
        user_metadata={"title": title},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = poller.job_id = job.id
    job_ids.append(job_id)

    ogrinfo = {
        "srid": 4326,
        "geometry_type": "Point",
        "columns": [{"name": "name", "type": "String"}],
    }
    with (
        patch(
            "app.processing.ingest.service.resolve_file_path",
            AsyncMock(return_value=str(source)),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogrinfo",
            AsyncMock(return_value=ogrinfo),
        ),
        patch("app.processing.ingest.ogr.run_ogr2ogr", new=_fake_ogr2ogr),
        patch("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
        patch(
            "app.processing.ingest.publish_followups.invalidate_catalog_cache",
            AsyncMock(side_effect=poller.between_commit_and_purge),
        ),
        patch("app.processing.embeddings.helpers.defer_embedding", AsyncMock()),
    ):
        await ingest_file.func(
            job_id=str(job_id),
            file_path=str(source),
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )

    test_db_session.expire_all()
    dataset_id = (await test_db_session.get(IngestJob, job_id)).dataset_id
    assert dataset_id is not None
    assert str(dataset_id) not in before
    assert poller.job_status == "complete"
    assert str(dataset_id) in poller.listed


async def _fake_run_ogr2ogr_service(
    gdal_source, layer_name, table_name, db_conn_str, service_type, *, schema, **kw
) -> None:
    if kw.get("on_spawn") is not None:
        kw["on_spawn"]()
    from app.core.db import async_session

    async with async_session() as session:
        await session.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table_name}"'))
        await session.execute(
            text(
                f'CREATE TABLE "{schema}"."{table_name}" '
                "(gid serial PRIMARY KEY, name text, value integer)"
            )
        )
        await session.commit()


async def test_a_service_reupload_lists_the_new_origin_once_its_job_reads_complete(
    client, admin_auth_header, test_db_session, job_ids
) -> None:
    await invalidate_catalog_cache()
    poller = _Poller(client, admin_auth_header)
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Origin after reupload {uuid.uuid4().hex[:8]}",
        visibility="public",
        feature_count=1,
        source_filename="original.geojson",
        column_info=[
            {"name": "name", "type": "character varying"},
            {"name": "value", "type": "integer"},
        ],
    )
    job = IngestJob(
        dataset_id=dataset.id,
        source_filename="roads_wfs",
        source_url="https://services.example.com/wfs",
        source_layer="roads",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset.id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )
    test_db_session.add(job)
    await test_db_session.commit()
    poller.job_id = job.id
    job_ids.append(job.id)
    assert (await poller.list())[str(dataset.id)]["origin"] == "upload"

    metadata = {
        "srid": 4326,
        "geometry_type": "MULTIPOLYGON",
        "feature_count": 2,
        "extent_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "column_info": [
            {"name": "name", "type": "character varying", "ordinal_position": 1},
            {"name": "value", "type": "integer", "ordinal_position": 2},
        ],
    }
    metadata_steps = (
        "ensure_geom_column",
        "clip_to_mercator_bounds",
        "add_4326_column",
        "grant_reader_access",
        "refresh_attribute_metadata",
        "compute_table_content_digest",
    )
    quality = {
        "overall": 92,
        "metadata_completeness": 90,
        "geometry_validity": 100,
        "attribute_completeness": 85,
        "crs_defined": 100,
    }
    with ExitStack() as stack:
        for name in metadata_steps:
            stack.enter_context(
                patch(f"app.processing.ingest.metadata.{name}", AsyncMock())
            )
        # services.example.com does not resolve here.
        stack.enter_context(
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock())
        )
        stack.enter_context(
            patch(
                "app.modules.catalog.sources.preview.build_gdal_source",
                return_value=("WFS:https://services.example.com/wfs", "roads"),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr_service",
                new=_fake_run_ogr2ogr_service,
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.metadata.extract_metadata",
                AsyncMock(return_value=metadata),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.metadata.get_sample_values",
                AsyncMock(return_value={"name": ["Main St"]}),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.metadata.score_quality",
                AsyncMock(return_value=quality),
            )
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.publish_followups.invalidate_catalog_cache",
                AsyncMock(side_effect=poller.between_commit_and_purge),
            )
        )
        await reupload_service(
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            dataset_id=str(dataset.id),
            source_url=job.source_url,
            source_layer=job.source_layer,
            user_id=str(admin_id),
            token=None,
        )

    assert poller.job_status == "complete"
    assert poller.listed[str(dataset.id)]["origin"] == "service"
