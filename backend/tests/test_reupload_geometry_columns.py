"""A file replacement builds geometry from the columns the dataset's geometry was built from."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text, update

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.extensions.defaults_catalog_port import DefaultCatalogPort
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.storage import provider as storage_provider
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.tasks import reupload_file
from app.processing.ingest.tasks_vector import ingest_file
from tests.factories import get_user_id

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"),
    pytest.mark.requires_ogr2ogr,
]

_XY_ROWS = [("a", -73.98, 40.75), ("b", -73.95, 40.78), ("c", -74.0, 40.71)]


def _xy_csv(path: Path, rows=_XY_ROWS, *, header: str = "name,lon,lat") -> Path:
    lines = [header] + [",".join(str(v) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def _wkt_csv(path: Path, column: str, rows=_XY_ROWS) -> Path:
    lines = [f"name,{column}"] + [f'{n},"POINT ({x} {y})"' for n, x, y in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


class _Harness:
    def __init__(self, client, headers, session, admin_id, tmp_path, task):
        self.client = client
        self.headers = headers
        self.session = session
        self.admin_id = admin_id
        self.tmp_path = tmp_path
        self.task = task

    async def first_import(self, path: Path, **columns: str) -> Dataset:
        """Import ``path`` as the ingest commit does, building geometry from ``columns``."""
        job = IngestJob(
            source_filename=path.name,
            file_path=str(path),
            created_by=self.admin_id,
            status="pending",
            user_metadata={"title": f"Columns {uuid.uuid4().hex[:8]}", **columns},
        )
        self.session.add(job)
        await self.session.commit()
        job_id, attempt_id = job.id, job.attempt_id
        with patch(
            "app.processing.ingest.service.resolve_file_path",
            AsyncMock(return_value=str(path)),
        ):
            await ingest_file.func(
                job_id=str(job_id),
                file_path=str(path),
                user_id=str(self.admin_id),
                attempt_id=str(attempt_id),
            )
        job = await self.session.get(IngestJob, job_id, populate_existing=True)
        assert job.status == "complete", job.error_message
        return await self.reload(job.dataset_id)

    async def reload(self, dataset_id: uuid.UUID) -> Dataset:
        return (
            await self.session.execute(
                select(Dataset)
                .where(Dataset.id == dataset_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def upload_job(self, dataset: Dataset, path: Path) -> uuid.UUID:
        job = IngestJob(
            dataset_id=dataset.id,
            status="pending",
            attempt_id=uuid.uuid4(),
            source_filename=path.name,
            file_path=str(path),
            created_by=self.admin_id,
            user_metadata={
                "reupload": True,
                "dataset_id": str(dataset.id),
                "start_data_revision": dataset.data_revision,
            },
        )
        self.session.add(job)
        await self.session.commit()
        return job.id

    async def preview(self, dataset: Dataset, job_id: uuid.UUID):
        return await self.client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/preview",
            headers=self.headers,
            json={},
        )

    async def commit_and_run(self, dataset: Dataset, job_id: uuid.UUID, body: dict):
        response = await self.client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/commit",
            headers=self.headers,
            json=body,
        )
        assert response.status_code == 202, response.text
        kwargs = self.task.defer_async.await_args.kwargs
        self.task.defer_async.reset_mock()
        await reupload_file(**kwargs)

    async def replace(self, dataset: Dataset, path: Path) -> DatasetRefreshRun:
        """Preview, commit with the preview's fingerprint, and run the worker."""
        job_id = await self.upload_job(dataset, path)
        response = await self.preview(dataset, job_id)
        assert response.status_code == 200, response.text
        fingerprint = response.json()["review_fingerprint"]
        await self.commit_and_run(
            dataset, job_id, {"review_fingerprint": fingerprint} if fingerprint else {}
        )
        run = (
            await self.session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.ingest_job_id == job_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert run.status == "succeeded", (run.error_code, run.verification)
        return run

    async def points(self, dataset: Dataset) -> list[tuple[str, str]]:
        rows = await self.session.execute(
            text(
                f'SELECT name, ST_AsText(geom_4326) FROM data."{dataset.table_name}" '
                "ORDER BY name"
            )
        )
        return [tuple(row) for row in rows]


@pytest.fixture
async def harness(client, admin_auth_header, test_db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_provider, "_storage", LocalStorageProvider(str(tmp_path / "objects"))
    )
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    task.configure.return_value = task
    with (
        patch.object(DefaultCatalogPort, "reupload_file_task", return_value=task),
        patch.object(settings, "upload_staging_dir", str(tmp_path)),
        patch("app.processing.ingest.metadata.grant_reader_access", new=AsyncMock()),
        patch("app.processing.embeddings.helpers.defer_embedding", AsyncMock()),
    ):
        yield _Harness(
            client,
            admin_auth_header,
            test_db_session,
            await get_user_id(test_db_session, "admin"),
            tmp_path,
            task,
        )


_EXPECTED = [
    ("a", "POINT(-73.98 40.75)"),
    ("b", "POINT(-73.95 40.78)"),
    ("c", "POINT(-74 40.71)"),
]


async def test_an_xy_csv_replaced_with_the_same_file_and_then_a_new_one_keeps_points(
    harness: _Harness,
):
    """The import records the columns, and every replacement builds points from them."""
    source = _xy_csv(harness.tmp_path / "places.csv")
    dataset = await harness.first_import(source, x_column="lon", y_column="lat")
    assert dataset.origin_ref["x_column"] == "lon"
    assert dataset.origin_ref["y_column"] == "lat"
    assert await harness.points(dataset) == _EXPECTED

    await harness.replace(dataset, _xy_csv(harness.tmp_path / "same.csv"))
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 3
    assert await harness.points(dataset) == _EXPECTED

    grown = _XY_ROWS + [("d", -73.9, 40.8)]
    await harness.replace(dataset, _xy_csv(harness.tmp_path / "grown.csv", grown))
    dataset = await harness.reload(dataset.id)
    assert dataset.geometry_type.upper().endswith("POINT")
    assert dataset.feature_count == 4
    assert await harness.points(dataset) == [*_EXPECTED, ("d", "POINT(-73.9 40.8)")]
    assert dataset.origin_ref["x_column"] == "lon"
    assert dataset.origin_ref["y_column"] == "lat"


async def test_a_dataset_imported_before_the_columns_were_recorded_reads_its_job(
    harness: _Harness,
):
    """With no columns on the binding, the newest completed job supplies them.

    A replacement with unchanged data leaves the binding alone, so its own job
    must carry the columns to the next one.
    """
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "older.csv"), x_column="lon", y_column="lat"
    )
    await harness.session.execute(
        update(Dataset)
        .where(Dataset.id == dataset.id)
        .values(origin_ref={"kind": "upload", "filename": "older.csv"})
    )
    await harness.session.commit()
    dataset = await harness.reload(dataset.id)

    await harness.replace(dataset, _xy_csv(harness.tmp_path / "same.csv"))
    dataset = await harness.reload(dataset.id)
    assert "x_column" not in dataset.origin_ref

    grown = _XY_ROWS + [("d", -73.9, 40.8)]
    await harness.replace(dataset, _xy_csv(harness.tmp_path / "newer.csv", grown))
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 4
    assert dataset.origin_ref["x_column"] == "lon"


async def test_a_replacement_missing_a_column_is_refused_by_name(harness: _Harness):
    """Both the preview and a commit that skips it name the missing column."""
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "places.csv"), x_column="lon", y_column="lat"
    )
    no_lat = _xy_csv(harness.tmp_path / "no_lat.csv", header="name,lon,latitude_deg")

    job_id = await harness.upload_job(dataset, no_lat)
    response = await harness.preview(dataset, job_id)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "geometry_columns_missing", detail
    assert detail["columns"] == "lat"
    assert "(lat)" in detail["message"]

    with pytest.raises(IngestionError, match=r"\(lat\)"):
        await harness.commit_and_run(dataset, job_id, {})
    job = await harness.session.get(IngestJob, job_id, populate_existing=True)
    assert job.status == "failed"
    assert "(lat)" in job.error_message
    dataset = await harness.reload(dataset.id)
    assert await harness.points(dataset) == _EXPECTED


@pytest.mark.parametrize("column", ["shape_wkt", "geometry"])
async def test_a_wkt_column_gdal_does_not_detect_is_rebuilt(
    harness: _Harness, column: str
):
    """``geometry`` is renamed at import, and the replacement reads it renamed too."""
    dataset = await harness.first_import(
        _wkt_csv(harness.tmp_path / "shapes.csv", column), geom_column=column
    )
    assert dataset.origin_ref["geom_column"] == column

    grown = _XY_ROWS + [("d", -73.9, 40.8)]
    await harness.replace(
        dataset, _wkt_csv(harness.tmp_path / "more.csv", column, grown)
    )
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 4
    assert await harness.points(dataset) == [*_EXPECTED, ("d", "POINT(-73.9 40.8)")]
