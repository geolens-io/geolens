"""A file replacement builds geometry from the columns the dataset's geometry was built from."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
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
from app.processing.ingest.tasks import reupload_file
from app.core.geometry_build_errors import (
    GEOMETRY_BUILD_SENTENCES,
    GeometryBuildError,
    columns_missing,
)
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

    async def first_import(self, path: Path, **columns) -> Dataset:
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

    async def failed_import(self, path: Path, **columns) -> IngestJob:
        """Run an import that fails, and return its job."""
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
        with (
            patch(
                "app.processing.ingest.service.resolve_file_path",
                AsyncMock(return_value=str(path)),
            ),
            contextlib.suppress(Exception),
        ):
            await ingest_file.func(
                job_id=str(job_id),
                file_path=str(path),
                user_id=str(self.admin_id),
                attempt_id=str(attempt_id),
            )
        job = await self.session.get(IngestJob, job_id, populate_existing=True)
        assert job.status == "failed"
        return job

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

    async def preview(
        self, dataset: Dataset, job_id: uuid.UUID, body: dict | None = None
    ):
        return await self.client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/preview",
            headers=self.headers,
            json=body or {},
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

    async def replace(
        self, dataset: Dataset, path: Path, body: dict | None = None
    ) -> DatasetRefreshRun:
        """Preview, commit with the preview's fingerprint, and run the worker."""
        job_id = await self.upload_job(dataset, path)
        response = await self.preview(dataset, job_id, body)
        assert response.status_code == 200, response.text
        fingerprint = response.json()["review_fingerprint"]
        await self.commit_and_run(
            dataset,
            job_id,
            {
                **(body or {}),
                **({"review_fingerprint": fingerprint} if fingerprint else {}),
            },
        )
        run = await self.run_for(job_id)
        assert run.status == "succeeded", (
            run.error_code,
            run.verification.get("review_reasons"),
            run.verification.get("geometry_contract"),
            run.verification.get("review_fingerprint"),
            response.json()["review_reasons"],
        )
        return run

    async def run_for(self, job_id: uuid.UUID) -> DatasetRefreshRun:
        return (
            await self.session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.ingest_job_id == job_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def restore(self, dataset: Dataset, expected: int) -> None:
        """Admit a restore through the API, then run the task it deferred."""
        from app.processing.ingest.tasks import restore_previous_version

        deferred = AsyncMock()
        with patch(
            "app.modules.catalog.datasets.api.router_previous_version."
            "defer_async_with_tenant",
            deferred,
        ):
            response = await self.client.post(
                f"/api/datasets/{dataset.id}/previous-version/restore",
                json={"expected_version_number": expected},
                headers=self.headers,
            )
        assert response.status_code == 202, response.text
        await restore_previous_version(**deferred.await_args.kwargs)

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
_GROWN = [*_XY_ROWS, ("d", -73.9, 40.8)]
_EXPECTED_GROWN = [*_EXPECTED, ("d", "POINT(-73.9 40.8)")]


async def test_an_xy_csv_replaced_with_the_same_file_and_then_a_new_one_keeps_points(
    harness: _Harness,
):
    """The import records the columns, and every replacement builds points from them."""
    source = _xy_csv(harness.tmp_path / "places.csv")
    dataset = await harness.first_import(source, x_column="lon", y_column="lat")
    assert dataset.origin_ref["x_column"] == "lon"
    assert dataset.origin_ref["y_column"] == "lat"
    assert dataset.origin_ref["column_srid"] == 4326
    assert await harness.points(dataset) == _EXPECTED

    await harness.replace(dataset, _xy_csv(harness.tmp_path / "same.csv"))
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 3
    assert await harness.points(dataset) == _EXPECTED

    await harness.replace(dataset, _xy_csv(harness.tmp_path / "grown.csv", _GROWN))
    dataset = await harness.reload(dataset.id)
    assert dataset.geometry_type.upper().endswith("POINT")
    assert dataset.feature_count == 4
    assert await harness.points(dataset) == _EXPECTED_GROWN
    assert dataset.origin_ref["x_column"] == "lon"
    assert dataset.origin_ref["y_column"] == "lat"


async def test_a_dataset_imported_before_the_columns_were_recorded_reads_its_job(
    harness: _Harness,
):
    """With no columns on the binding, the import job supplies them.

    A replacement with unchanged data then records them on the binding, so the
    next one does not need the job.
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
    assert dataset.current_version == 1
    assert dataset.origin_ref["x_column"] == "lon"
    assert dataset.origin_ref["filename"] == "older.csv"

    await harness.session.execute(
        update(IngestJob)
        .where(IngestJob.dataset_id == dataset.id)
        .values(user_metadata={})
    )
    await harness.session.commit()
    await harness.replace(dataset, _xy_csv(harness.tmp_path / "newer.csv", _GROWN))
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 4


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

    with pytest.raises(GeometryBuildError):
        await harness.commit_and_run(dataset, job_id, {})
    job = await harness.session.get(IngestJob, job_id, populate_existing=True)
    assert job.status == "failed"
    assert job.error_code == "geometry_columns_missing"
    assert job.error_message == str(columns_missing(["lat"]))
    run = await harness.run_for(job_id)
    assert run.error_code == "geometry_columns_missing"
    dataset = await harness.reload(dataset.id)
    assert await harness.points(dataset) == _EXPECTED


@pytest.mark.parametrize("column", ["shape_wkt", "geometry", "wkt"])
async def test_a_wkt_column_is_rebuilt(harness: _Harness, column: str):
    """``geometry`` is renamed at import and ``wkt`` is one GDAL reads on its own."""
    dataset = await harness.first_import(
        _wkt_csv(harness.tmp_path / "shapes.csv", column), geom_column=column
    )
    assert dataset.origin_ref["geom_column"] == column

    await harness.replace(
        dataset, _wkt_csv(harness.tmp_path / "more.csv", column, _GROWN)
    )
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 4
    assert await harness.points(dataset) == _EXPECTED_GROWN


async def test_chosen_columns_win_over_a_wkt_column_gdal_detects(harness: _Harness):
    """A replacement that gains a ``wkt`` column still builds from the chosen pair."""
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "coords.csv", header="name,coord_x,coord_y"),
        x_column="coord_x",
        y_column="coord_y",
    )
    competing = harness.tmp_path / "competing.csv"
    competing.write_text(
        "name,coord_x,coord_y,wkt\n"
        + "".join(f'{n},{x},{y},"POINT (1 2)"\n' for n, x, y in _GROWN)
    )

    await harness.replace(dataset, competing)
    dataset = await harness.reload(dataset.id)
    assert await harness.points(dataset) == _EXPECTED_GROWN


async def test_projected_coordinates_are_rebuilt_in_their_recorded_crs(
    harness: _Harness,
):
    """A replacement with no override reads the columns in the import's CRS."""
    mercator = [
        (n, round(x * 111319.49, 2), round(y * 111319.49, 2)) for n, x, y in _XY_ROWS
    ]
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "metres.csv", mercator, header="name,x,y"),
        x_column="x",
        y_column="y",
        srid_override=3857,
    )
    assert dataset.origin_ref["column_srid"] == 3857
    before = await harness.points(dataset)

    more = [*mercator, ("d", 1000.0, 1000.0)]
    await harness.replace(
        dataset, _xy_csv(harness.tmp_path / "more.csv", more, header="name,x,y")
    )
    dataset = await harness.reload(dataset.id)
    assert dataset.feature_count == 4
    assert (await harness.points(dataset))[:3] == before


async def test_header_spellings_ogr2ogr_launders_match_the_chosen_names(
    harness: _Harness,
):
    """Headers are compared as they are stored, so the same file replaces itself."""
    header = "name,Longitude-Deg,Latitude-Deg"
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "degrees.csv", header=header),
        x_column="longitude_deg",
        y_column="latitude_deg",
    )

    await harness.replace(
        dataset, _xy_csv(harness.tmp_path / "again.csv", _GROWN, header=header)
    )
    dataset = await harness.reload(dataset.id)
    assert await harness.points(dataset) == _EXPECTED_GROWN


async def test_a_restored_version_keeps_the_columns_it_was_built_from(
    harness: _Harness,
):
    """Replace from a file with geometry of its own, restore, then replace from the CSV."""
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "places.csv"), x_column="lon", y_column="lat"
    )
    native = harness.tmp_path / "native.geojson"
    native.write_text(
        '{"type":"FeatureCollection","features":['
        + ",".join(
            f'{{"type":"Feature","properties":{{"name":"{n}","lon":{x},"lat":{y}}},'
            f'"geometry":{{"type":"Point","coordinates":[{x},{y}]}}}}'
            for n, x, y in _XY_ROWS[:2]
        )
        + "]}"
    )
    await harness.replace(dataset, native)
    dataset = await harness.reload(dataset.id)
    assert "x_column" not in dataset.origin_ref

    await harness.restore(dataset, 1)
    dataset = await harness.reload(dataset.id)
    assert dataset.origin_ref["x_column"] == "lon"

    await harness.replace(dataset, _xy_csv(harness.tmp_path / "after.csv", _GROWN))
    dataset = await harness.reload(dataset.id)
    assert await harness.points(dataset) == _EXPECTED_GROWN


@pytest.mark.parametrize(
    "header,rows,code",
    [
        ("name,lon,lat", [("a", -73.98, "north")], "geometry_xy_not_numeric"),
        ("name,lon,lat", [("a", -73.98, 95.0)], "geometry_xy_outside_wgs84"),
        ("name,wkt_text", None, "geometry_wkt_malformed"),
    ],
)
async def test_a_build_failure_is_stored_with_its_code(
    harness: _Harness, header: str, rows, code: str
):
    """The job and run carry the code the frontend translates."""
    if rows is None:
        dataset = await harness.first_import(
            _wkt_csv(harness.tmp_path / "shapes.csv", "wkt_text"),
            geom_column="wkt_text",
        )
        bad = harness.tmp_path / "bad.csv"
        bad.write_text('name,wkt_text\na,"POINT (1 2"\n')
    else:
        dataset = await harness.first_import(
            _xy_csv(harness.tmp_path / "places.csv"), x_column="lon", y_column="lat"
        )
        bad = _xy_csv(harness.tmp_path / "bad.csv", rows, header=header)

    job_id = await harness.upload_job(dataset, bad)
    with pytest.raises(GeometryBuildError):
        await harness.commit_and_run(dataset, job_id, {})
    job = await harness.session.get(IngestJob, job_id, populate_existing=True)
    assert (job.status, job.error_code) == ("failed", code)
    assert job.error_message == GEOMETRY_BUILD_SENTENCES[code].format(rows=1)
    assert (await harness.run_for(job_id)).error_code == code


@pytest.mark.parametrize("replacement", ["changed", "native"])
async def test_an_older_import_keeps_its_columns_through_a_replacement_and_restore(
    harness: _Harness, replacement: str
):
    """The first version records the columns its import job holds when it is kept."""
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

    if replacement == "changed":
        source = _xy_csv(harness.tmp_path / "changed.csv", _XY_ROWS[:2])
    else:
        source = _native_geojson(harness.tmp_path / "native.geojson")
    await harness.replace(dataset, source)
    await harness.restore(await harness.reload(dataset.id), 1)

    dataset = await harness.reload(dataset.id)
    await harness.replace(dataset, _xy_csv(harness.tmp_path / "after.csv", _GROWN))
    dataset = await harness.reload(dataset.id)
    assert await harness.points(dataset) == _EXPECTED_GROWN


@pytest.mark.parametrize(
    "single,multi,stored",
    [
        ("POINT ({x} {y})", "MULTIPOINT (({x} {y}))", "MULTIPOINT"),
        (
            "LINESTRING ({x} {y}, 0 0)",
            "MULTILINESTRING (({x} {y}, 0 0))",
            "MULTILINESTRING",
        ),
        (
            "POLYGON (({x} {y}, 0 0, 0 1, {x} {y}))",
            "MULTIPOLYGON ((({x} {y}, 0 0, 0 1, {x} {y})))",
            "MULTIPOLYGON",
        ),
    ],
)
async def test_single_and_multi_geometries_of_one_family_are_stored_multi(
    harness: _Harness, single: str, multi: str, stored: str
):
    def mixed(path: Path, rows) -> Path:
        lines = ["name,shape_wkt"] + [
            f'{n},"{(single if i % 2 == 0 else multi).format(x=x, y=y)}"'
            for i, (n, x, y) in enumerate(rows)
        ]
        path.write_text("\n".join(lines) + "\n")
        return path

    dataset = await harness.first_import(
        mixed(harness.tmp_path / "mixed.csv", _XY_ROWS), geom_column="shape_wkt"
    )
    assert dataset.geometry_type.upper() == stored

    await harness.replace(dataset, mixed(harness.tmp_path / "more.csv", _GROWN))
    dataset = await harness.reload(dataset.id)
    assert (dataset.geometry_type.upper(), dataset.feature_count) == (stored, 4)


async def test_a_workbook_offers_its_sheets_before_the_columns_are_checked(
    harness: _Harness,
):
    """The default sheet may lack the columns; the chosen one may not."""
    book = harness.tmp_path / "book.xlsx"
    notes = _xy_csv(
        harness.tmp_path / "notes.csv", [("a", "x", "y")], header="name,c,d"
    )
    places = _xy_csv(harness.tmp_path / "places.csv")
    _ogr2ogr(book, notes, "-f", "XLSX", "-nln", "notes")
    # Typed cells, so the XLSX driver reads the first row as the header.
    _ogr2ogr(book, places, "-update", "-nln", "places", "-oo", "AUTODETECT_TYPE=YES")
    dataset = await harness.first_import(
        book, x_column="lon", y_column="lat", layer_name="places"
    )
    assert await harness.points(dataset) == _EXPECTED

    again = harness.tmp_path / "again.xlsx"
    _ogr2ogr(again, notes, "-f", "XLSX", "-nln", "notes")
    _ogr2ogr(again, places, "-update", "-nln", "places", "-oo", "AUTODETECT_TYPE=YES")
    job_id = await harness.upload_job(dataset, again)
    response = await harness.preview(dataset, job_id)
    assert response.status_code == 200, response.text
    assert {layer["name"] for layer in response.json()["all_layers"]} == {
        "notes",
        "places",
    }
    refused = await harness.preview(dataset, job_id, {"layer_name": "notes"})
    assert refused.json()["detail"]["code"] == "geometry_columns_missing"
    chosen = await harness.preview(dataset, job_id, {"layer_name": "places"})
    assert chosen.status_code == 200, chosen.text
    await harness.commit_and_run(dataset, job_id, {"layer_name": "places"})
    assert (await harness.run_for(job_id)).status == "succeeded"


async def test_a_wkt_build_shows_a_crs_change_in_the_preview_the_worker_accepts(
    harness: _Harness,
):
    """Preview and worker name the same CRS change, so the reviewed run publishes."""
    dataset = await harness.first_import(
        _wkt_csv(harness.tmp_path / "shapes.csv", "shape_wkt"), geom_column="shape_wkt"
    )
    run = await harness.replace(
        dataset,
        _wkt_csv(harness.tmp_path / "nad83.csv", "shape_wkt", _GROWN),
        {"srid_override": 4269},
    )
    assert run.verification["review_reasons"] == ["srid_changed"]
    assert run.verification["review_acknowledged_by"] == "preview"


def _native_geojson(path: Path) -> Path:
    features = ",".join(
        f'{{"type":"Feature","properties":{{"name":"{n}","lon":{x},"lat":{y}}},'
        f'"geometry":{{"type":"Point","coordinates":[{x},{y}]}}}}'
        for n, x, y in _XY_ROWS[:2]
    )
    path.write_text(f'{{"type":"FeatureCollection","features":[{features}]}}')
    return path


def _ogr2ogr(destination: Path, source: Path, *args: str) -> None:
    done = subprocess.run(
        ["ogr2ogr", *args, str(destination), str(source)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


async def _replace_from_service(harness: _Harness, dataset: Dataset) -> None:
    """Replace the dataset's data from a WFS layer that serves two points."""
    from app.platform.refresh.service import create_pending_run
    from app.processing.ingest.tasks import reupload_service

    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="layer",
        source_url="https://services.example.com/wfs",
        source_layer="places",
        created_by=harness.admin_id,
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset.id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )
    harness.session.add(job)
    await harness.session.flush()
    await create_pending_run(
        harness.session,
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="manual",
        triggered_by=harness.admin_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
    )
    await harness.session.commit()
    job_id, attempt_id = job.id, job.attempt_id

    async def _served(gdal_source, layer_name, table_name, *args, schema, **kwargs):
        if kwargs.get("on_spawn") is not None:
            kwargs["on_spawn"]()
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table_name}" (gid serial PRIMARY KEY, '
                    "name varchar, lon double precision, lat double precision, "
                    "geom geometry(Point, 4326))"
                )
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}"."{table_name}" (name, lon, lat, geom) '
                    "VALUES ('a', -73.98, 40.75, "
                    "ST_SetSRID(ST_MakePoint(-73.98, 40.75), 4326)), "
                    "('b', -73.95, 40.78, ST_SetSRID(ST_MakePoint(-73.95, 40.78), 4326))"
                )
            )
            await session.commit()

    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch(
            "app.modules.catalog.sources.preview.build_gdal_source",
            return_value=("WFS:https://services.example.com/wfs", "places"),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service",
            new=AsyncMock(side_effect=_served),
        ),
    ):
        await reupload_service(
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset.id),
            source_url="https://services.example.com/wfs",
            source_layer="places",
            user_id=str(harness.admin_id),
            token=None,
        )
    run = await harness.run_for(job_id)
    assert run.status == "succeeded", (run.error_code, run.verification)


async def _legacy_import(harness: _Harness) -> Dataset:
    """An x/y import whose binding predates recording the columns."""
    dataset = await harness.first_import(
        _xy_csv(harness.tmp_path / "older.csv"), x_column="lon", y_column="lat"
    )
    await harness.session.execute(
        update(Dataset)
        .where(Dataset.id == dataset.id)
        .values(origin_ref={"kind": "upload", "filename": "older.csv"})
    )
    await harness.session.commit()
    return await harness.reload(dataset.id)


async def test_an_older_import_replaced_from_a_service_keeps_its_columns_for_restore(
    harness: _Harness,
):
    """The kept first version records the columns its import job holds."""
    dataset = await _legacy_import(harness)
    await _replace_from_service(harness, dataset)
    kept = await harness.session.scalar(
        text(
            "SELECT geometry_columns FROM catalog.dataset_versions "
            "WHERE dataset_id = :id AND version_number = 1"
        ),
        {"id": dataset.id},
    )
    assert (kept["x_column"], kept["y_column"]) == ("lon", "lat")
    await harness.restore(await harness.reload(dataset.id), 1)

    dataset = await harness.reload(dataset.id)
    assert dataset.origin_ref["x_column"] == "lon"
    await harness.replace(dataset, _xy_csv(harness.tmp_path / "after.csv", _GROWN))
    assert await harness.points(await harness.reload(dataset.id)) == _EXPECTED_GROWN


async def test_an_original_version_kept_before_versions_recorded_columns_restores(
    harness: _Harness,
):
    """Version 1 kept with no columns reads them from its import job on restore."""
    dataset = await _legacy_import(harness)
    await harness.replace(dataset, _native_geojson(harness.tmp_path / "native.geojson"))
    await harness.session.execute(
        text(
            "UPDATE catalog.dataset_versions SET geometry_columns = NULL "
            "WHERE dataset_id = :id AND version_number = 1"
        ),
        {"id": dataset.id},
    )
    await harness.session.commit()

    await harness.restore(await harness.reload(dataset.id), 1)
    dataset = await harness.reload(dataset.id)
    assert dataset.origin_ref["x_column"] == "lon"
    await harness.replace(dataset, _xy_csv(harness.tmp_path / "after.csv", _GROWN))
    assert await harness.points(await harness.reload(dataset.id)) == _EXPECTED_GROWN


@pytest.mark.parametrize(
    "rows,dimensions",
    [
        (["POINT ZM (1 2 3 4)", "POINT Z (5 6 7)"], "XYZ, XYZM"),
        (["POINT M (1 2 3)", "POINT ZM (5 6 7 8)"], "XYM, XYZM"),
        (["POINT (1 2)", "MULTIPOINT Z ((5 6 7))"], "XY, XYZ"),
    ],
)
async def test_wkt_rows_that_disagree_on_dimensions_are_refused(
    harness: _Harness, rows: list[str], dimensions: str
):
    """No row loses an ordinate: the import names the dimensions it found."""
    path = harness.tmp_path / "dims.csv"
    path.write_text(
        "name,shape_wkt\n" + "".join(f'{i},"{row}"\n' for i, row in enumerate(rows))
    )
    job = await harness.failed_import(path, geom_column="shape_wkt")
    assert job.error_code == "geometry_wkt_mixed_dimensions"
    assert job.error_message == GEOMETRY_BUILD_SENTENCES[
        "geometry_wkt_mixed_dimensions"
    ].format(dimensions=dimensions)


@pytest.mark.parametrize(
    "rows,stored",
    [
        (["POINT Z (1 2 3)", "POINT (5 6 7)"], "POINT Z (5 6 7)"),
        (["POINT ZM (1 2 3 4)", "POINT (5 6 7 8)"], "POINT ZM (5 6 7 8)"),
    ],
)
async def test_wkt_rows_that_agree_on_dimensions_keep_their_ordinates(
    harness: _Harness, rows: list[str], stored: str
):
    path = harness.tmp_path / "dims.csv"
    path.write_text(
        "name,shape_wkt\n" + "".join(f'{i},"{row}"\n' for i, row in enumerate(rows))
    )
    dataset = await harness.first_import(path, geom_column="shape_wkt")
    value = await harness.session.scalar(
        text(
            f"SELECT ST_AsText(geom) FROM data.\"{dataset.table_name}\" WHERE name = '1'"
        )
    )
    assert value == stored


async def test_implicit_3d_wkt_shows_the_same_review_in_preview_and_worker(
    harness: _Harness,
):
    """``LINESTRING (x y z, ...)`` is 3D to PostGIS, and the preview says so too."""

    def implicit(path: Path, rows) -> Path:
        lines = ["name,shape_wkt"] + [
            f'{n},"LINESTRING ({x} {y} 10, {x + 0.01} {y} 12)"' for n, x, y in rows
        ]
        path.write_text("\n".join(lines) + "\n")
        return path

    dataset = await harness.first_import(
        implicit(harness.tmp_path / "high.csv", _XY_ROWS), geom_column="shape_wkt"
    )
    run = await harness.replace(
        dataset,
        implicit(harness.tmp_path / "nad83.csv", _GROWN),
        {"srid_override": 4269},
    )
    assert run.verification["review_reasons"] == ["srid_changed"]
    assert run.verification["review_acknowledged_by"] == "preview"
