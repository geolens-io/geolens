"""A manifest re-apply brings the record to the manifest's title, summary and publication."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy import select, text

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from app.processing.ingest.tasks import reupload_file
from tests.factories import create_dataset

pytestmark = pytest.mark.anyio

_FIXTURE = "tests/fixtures/ingest/basic_attrs.geojson"


def _entry(key: str, *, title: str, intent: str, description: str | None = None):
    entry = {
        "key": key,
        "title": title,
        "sources": [{"type": "vector", "uri": _FIXTURE, "format": "geojson"}],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": intent},
    }
    if description is not None:
        entry["description"] = description
    return entry


def _request(entry: dict) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        {
            "manifest_version": "1",
            "catalog": {"title": "Manifest catalog"},
            "datasets": [entry],
        }
    )


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


def _stage_fixture() -> None:
    destination = Path(settings.upload_staging_dir) / _FIXTURE
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", destination)


async def _published_by_manifest(session, user: User, key: str) -> uuid.UUID:
    """A public, published dataset an earlier apply of ``key`` created."""
    table = f"manifest_pub_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=user.id,
        name="Road centerlines",
        description="Original survey",
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
    original = _request(
        _entry(key, title="Road centerlines", intent="published")
    ).datasets[0]
    prepared = await classify_manifest_source(original.sources[0])
    session.add(
        IngestJob(
            dataset_id=dataset.id,
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="complete",
            completed_at=datetime.now(timezone.utc),
            user_metadata=manifest_job_metadata(
                original, prepared, fingerprint=manifest_dataset_fingerprint(original)
            ),
        )
    )
    await session.commit()
    return dataset.id


@contextmanager
def _reupload_task():
    task = MagicMock()
    task.defer_async = AsyncMock()
    port = MagicMock()
    port.reupload_file_task.return_value = task
    with patch(
        "app.processing.ingest.manifest_service.get_catalog_port", return_value=port
    ):
        yield task


async def _stage_rows(file_path, staging_table, db_conn_str, **kwargs):
    """Stands in for ogr2ogr, whose connection is not the test database's."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "data"."{staging_table}" '
                "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "data"."{staging_table}" (geom, name) VALUES '
                "(ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), 'Paris')"
            )
        )
        await session.commit()


async def _run_worker(task) -> None:
    with (
        patch(
            "app.processing.ingest.service.resolve_file_path",
            new=AsyncMock(side_effect=lambda path, job_id: path),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr",
            new=AsyncMock(side_effect=_stage_rows),
        ),
        # A real grant would put this module in the tenancy test group.
        patch("app.processing.ingest.metadata.grant_reader_access", new=AsyncMock()),
        patch(
            "app.processing.ingest.tasks_staging.get_storage", return_value=AsyncMock()
        ),
    ):
        await reupload_file(**task.defer_async.await_args.kwargs)


async def test_a_reapply_moves_the_record_to_the_new_title_summary_and_draft(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    key = "roads-unpublish"
    dataset_id = await _published_by_manifest(test_db_session, user, key)
    publication_before = await test_db_session.scalar(
        select(Dataset.publication_version).where(Dataset.id == dataset_id)
    )
    update = _request(
        _entry(key, title="Updated roads", intent="draft", description="Resurveyed")
    )

    with _reupload_task() as task:
        response = await apply_manifest(test_db_session, update, user, _http_request())
    assert response.results[0].action == "update"
    job_id = response.results[0].job_id

    await _run_worker(task)

    job = (
        await test_db_session.execute(
            select(IngestJob)
            .where(IngestJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert (job.status, job.error_message) == ("complete", None)
    dataset = (
        await test_db_session.execute(
            select(Dataset)
            .where(Dataset.id == dataset_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    record = dataset.record
    await test_db_session.refresh(record)
    assert (record.title, record.summary) == ("Updated roads", "Resurveyed")
    assert (record.visibility, record.record_status) == ("private", "draft")
    # Tile URLs signed while the record was public stop working.
    assert dataset.publication_version > publication_before

    with _reupload_task() as task:
        again = await apply_manifest(test_db_session, update, user, _http_request())
    assert again.results[0].action == "skip"
    task.defer_async.assert_not_awaited()
