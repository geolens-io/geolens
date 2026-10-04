"""File replacements with review reasons publish only once a person has reviewed them."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.extensions.defaults_catalog_port import DefaultCatalogPort
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.tasks import reupload_file
from tests.factories import create_dataset, get_user_id

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"),
    pytest.mark.requires_ogr2ogr,
]

_POINTS = [(-73.98, 40.75), (-73.95, 40.78), (-74.0, 40.71)]


def _geometry(kind: str, x: float, y: float) -> dict:
    if kind == "Point":
        return {"type": "Point", "coordinates": [x, y]}
    ring = [[x, y], [x + 0.01, y], [x + 0.01, y + 0.01], [x, y]]
    return {"type": "Polygon", "coordinates": [ring]}


def _geojson(
    path: Path, columns: dict[str, object], *, kind: str = "Point", rows: int = 3
) -> Path:
    features = [
        {
            "type": "Feature",
            "properties": {
                name: (f"{value}{i}" if isinstance(value, str) else value + i)
                for name, value in columns.items()
            },
            "geometry": _geometry(kind, *_POINTS[i % len(_POINTS)]),
        }
        for i in range(rows)
    ]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


def _ogr2ogr(destination: Path, source: Path, *args: str) -> Path:
    done = subprocess.run(
        ["ogr2ogr", *args, str(destination), str(source)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return destination


@dataclass
class _Harness:
    client: AsyncClient
    headers: dict[str, str]
    session: object
    admin_id: uuid.UUID
    tmp_path: Path
    task: MagicMock
    storage: MagicMock

    async def dataset(self, *, record_type: str = "vector_dataset") -> Dataset:
        """An empty dataset whose first replacement has nothing to review."""
        table = f"frr_{uuid.uuid4().hex[:10]}"
        spatial = record_type == "vector_dataset"
        dataset = await create_dataset(
            self.session,
            created_by=self.admin_id,
            name=f"File review {table}",
            table_name=table,
            record_type=record_type,
            geometry_type="MULTIPOINT" if spatial else None,
            feature_count=0,
            column_info=[],
        )
        geometry = ", geom geometry, geom_4326 geometry" if spatial else ""
        await self.session.execute(
            text(f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY{geometry})')
        )
        await self.session.commit()
        return dataset

    async def upload_job(
        self, dataset: Dataset, file_path: str, filename: str
    ) -> uuid.UUID:
        """A pending re-upload job, as the upload endpoint leaves it."""
        job = IngestJob(
            dataset_id=dataset.id,
            status="pending",
            attempt_id=uuid.uuid4(),
            source_filename=filename,
            file_path=file_path,
            created_by=self.admin_id,
            user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
        )
        self.session.add(job)
        await self.session.commit()
        return job.id

    async def preview(
        self, dataset: Dataset, job_id: uuid.UUID, body: dict | None = None
    ) -> dict:
        response = await self.client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/preview",
            headers=self.headers,
            json=body or {},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def commit(
        self, dataset: Dataset, job_id: uuid.UUID, body: dict | None = None
    ) -> None:
        response = await self.client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/commit",
            headers=self.headers,
            json=body or {},
        )
        assert response.status_code == 202, response.text

    async def run_worker(
        self,
        *,
        ogr2ogr_error: Exception | None = None,
        claim_error: Exception | None = None,
    ) -> None:
        """Run the task the last request queued, reading a staged key from its local copy."""
        kwargs = self.task.defer_async.await_args.kwargs
        self.task.defer_async.reset_mock()

        async def _resolve(path: str, job_id: str) -> str:
            if not path.startswith("staging/"):
                return path
            download = self.tmp_path / f"download-{uuid.uuid4().hex}{Path(path).suffix}"
            download.write_bytes((self.tmp_path / Path(path).name).read_bytes())
            return str(download)

        patches = [
            patch(
                "app.processing.ingest.service.resolve_file_path",
                new=AsyncMock(side_effect=_resolve),
            )
        ]
        if ogr2ogr_error is not None:
            patches.append(
                patch(
                    "app.processing.ingest.ogr.run_ogr2ogr",
                    new=AsyncMock(side_effect=ogr2ogr_error),
                )
            )
        if claim_error is not None:
            patches.append(
                patch(
                    "app.processing.ingest.publication._claim",
                    new=AsyncMock(side_effect=claim_error),
                )
            )
        expected = tuple(
            type(error) for error in (ogr2ogr_error, claim_error) if error is not None
        )
        for active in patches:
            active.start()
        try:
            await reupload_file(**kwargs)
        except expected:
            pass
        finally:
            for active in patches:
                active.stop()

    async def replace(
        self,
        dataset: Dataset,
        path: Path,
        *,
        reviewed: bool = True,
        preview_body: dict | None = None,
        commit_body: dict | None = None,
    ) -> tuple[dict, DatasetRefreshRun]:
        """Preview, commit with the preview's fingerprint when ``reviewed``, and run."""
        job_id = await self.upload_job(dataset, str(path), path.name)
        preview = await self.preview(dataset, job_id, preview_body)
        body = dict(commit_body or {})
        if reviewed and preview["review_fingerprint"]:
            body["review_fingerprint"] = preview["review_fingerprint"]
        await self.commit(dataset, job_id, body)
        await self.run_worker()
        return preview, await self.run_for(job_id)

    async def run_for(self, job_id: uuid.UUID) -> DatasetRefreshRun:
        return (
            await self.session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.ingest_job_id == job_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def job(self, job_id: uuid.UUID) -> IngestJob:
        return (
            await self.session.execute(
                select(IngestJob)
                .where(IngestJob.id == job_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def reload(self, dataset: Dataset) -> Dataset:
        return (
            await self.session.execute(
                select(Dataset)
                .where(Dataset.id == dataset.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def live_columns(self, dataset: Dataset) -> list[str]:
        return list(
            (
                await self.session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'data' AND table_name = :t "
                        "ORDER BY ordinal_position"
                    ),
                    {"t": dataset.table_name},
                )
            ).scalars()
        )

    async def accept(self, dataset: Dataset, run_id: uuid.UUID, headers=None):
        return await self.client.post(
            f"/datasets/{dataset.id}/refresh",
            headers=headers or self.headers,
            json={"accept_blocked_run_id": str(run_id)},
        )


@pytest.fixture
async def harness(
    client: AsyncClient, admin_auth_header, test_db_session, tmp_path
) -> _Harness:
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    task.configure.return_value = task
    storage = MagicMock()
    storage.delete = AsyncMock()
    storage.put = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.size = AsyncMock(return_value=0)
    with (
        patch.object(DefaultCatalogPort, "reupload_file_task", return_value=task),
        patch.object(settings, "upload_staging_dir", str(tmp_path)),
        # A real grant would put this module in the tenancy test group.
        patch("app.processing.ingest.metadata.grant_reader_access", new=AsyncMock()),
        patch("app.processing.ingest.tasks_staging.get_storage", lambda: storage),
        patch("app.platform.storage.get_storage", lambda: storage),
    ):
        yield _Harness(
            client=client,
            headers=admin_auth_header,
            session=test_db_session,
            admin_id=await get_user_id(test_db_session, "admin"),
            tmp_path=tmp_path,
            task=task,
            storage=storage,
        )


_BASE = {"name": "n", "population": 100, "legacy": "l"}
_DROPPED = {"name": "n", "population": 100}


async def _published(harness: _Harness, path: Path, **kwargs) -> Dataset:
    """A dataset whose live data is ``path``, published by a clean replacement."""
    dataset = await harness.dataset(**kwargs)
    _preview, run = await harness.replace(dataset, path)
    assert run.status == "succeeded", (run.error_code, run.verification)
    return await harness.reload(dataset)


async def _blocked_by_staged_upload(
    harness: _Harness, dataset: Dataset, path: Path
) -> tuple[uuid.UUID, DatasetRefreshRun]:
    """Commit ``path`` as a staged object with no fingerprint and run it."""
    key = f"staging/{uuid.uuid4()}/{path.name}"
    job_id = await harness.upload_job(dataset, key, path.name)
    await harness.commit(dataset, job_id)
    await harness.run_worker()
    return job_id, await harness.run_for(job_id)


# 1, 3, 4, 5, 6: what the worker decides without a matching fingerprint


async def test_a_commit_without_a_fingerprint_that_drops_a_column_is_blocked(
    harness: _Harness,
):
    """The run blocks, the live data stays and the staged upload is kept."""
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))
    version_before = dataset.current_version
    columns_before = await harness.live_columns(dataset)
    harness.storage.delete.reset_mock()

    _geojson(harness.tmp_path / "b.geojson", _DROPPED)
    job_id, run = await _blocked_by_staged_upload(
        harness, dataset, harness.tmp_path / "b.geojson"
    )

    job = await harness.job(job_id)
    assert (job.status, job.error_code) == ("failed", "review_required")
    assert run.status == "blocked"
    assert run.verification["review_reasons"] == ["destructive_schema_change"]
    assert run.verification["review_fingerprint"]
    after = await harness.reload(dataset)
    assert after.current_version == version_before
    assert {c["name"] for c in after.column_info} >= {"legacy"}
    assert await harness.live_columns(dataset) == columns_before
    count = await harness.session.scalar(
        text(f'SELECT count(*) FROM "data"."{dataset.table_name}"')
    )
    assert count == 3
    harness.storage.delete.assert_not_awaited()


async def test_a_commit_with_the_previews_fingerprint_publishes(harness: _Harness):
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))

    preview, run = await harness.replace(
        dataset, _geojson(harness.tmp_path / "b.geojson", _DROPPED)
    )

    assert preview["review_reasons"] == ["destructive_schema_change"]
    assert run.status == "succeeded"
    assert run.verification["review_acknowledged_by"] == "preview"
    assert "legacy" not in await harness.live_columns(dataset)


async def test_a_commit_with_a_different_fingerprint_is_blocked(harness: _Harness):
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))

    _preview, run = await harness.replace(
        dataset,
        _geojson(harness.tmp_path / "b.geojson", _DROPPED),
        reviewed=False,
        commit_body={"review_fingerprint": "0" * 64},
    )

    assert run.status == "blocked"
    assert run.verification["review_acknowledged_by"] is None


async def test_an_empty_file_over_a_non_empty_dataset_is_blocked(harness: _Harness):
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))
    source = _geojson(harness.tmp_path / "source.geojson", _BASE)
    empty = _ogr2ogr(harness.tmp_path / "empty.gpkg", source, "-where", "1 = 0")

    _preview, run = await harness.replace(dataset, empty, reviewed=False)

    assert run.status == "blocked"
    assert run.verification["review_reasons"] == ["empty_result"]


async def test_a_polygon_file_over_a_point_dataset_is_blocked(harness: _Harness):
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))

    _preview, run = await harness.replace(
        dataset,
        _geojson(harness.tmp_path / "b.geojson", _BASE, kind="Polygon"),
        reviewed=False,
    )

    assert run.status == "blocked"
    assert run.verification["review_reasons"] == ["geometry_type_changed"]


async def test_a_file_whose_geometries_are_all_null_is_blocked(harness: _Harness):
    """Rows that keep their attributes but lose every geometry wait for review."""
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))
    version_before = dataset.current_version
    nulls = harness.tmp_path / "b.geojson"
    features = json.loads(_geojson(nulls, _BASE).read_text())
    for feature in features["features"]:
        feature["geometry"] = None
    nulls.write_text(json.dumps(features))

    _preview, run = await harness.replace(dataset, nulls, reviewed=False)

    assert run.status == "blocked", run.verification
    assert run.verification["review_reasons"] == ["geometry_type_changed"]
    assert (await harness.reload(dataset)).current_version == version_before
    located = await harness.session.scalar(
        text(f'SELECT count(geom) FROM "data"."{dataset.table_name}"')
    )
    assert located == 3


async def test_a_replacement_with_nothing_to_review_publishes_without_a_fingerprint(
    harness: _Harness,
):
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))

    preview, run = await harness.replace(
        dataset,
        _geojson(harness.tmp_path / "b.geojson", {**_BASE, "extra": "e"}, rows=5),
        reviewed=False,
    )

    assert (preview["review_reasons"], preview["review_fingerprint"]) == ([], None)
    assert run.status == "succeeded"
    assert run.verification["decision"] == "allowed"
    assert run.verification["review_acknowledged_by"] is None


async def test_a_column_added_while_the_replacement_stages_holds_it_for_review(
    harness: _Harness,
):
    """The verdict compares the live columns as they are when publication begins."""
    import app.core.db as db_module
    from app.modules.catalog.layers.service import add_column
    from app.processing.ingest import catalog_projection

    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))
    real_measure = catalog_projection.measure

    async def _measure_after_a_column_edit(*args, **kwargs):
        async with db_module.async_session() as other:
            live = await other.get(Dataset, dataset.id)
            await add_column(other, live, "added_late", "text")
            await other.execute(
                text(f'UPDATE "data"."{live.table_name}" SET added_late = \'kept\'')
            )
            await other.commit()
        return await real_measure(*args, **kwargs)

    with patch.object(
        catalog_projection, "measure", side_effect=_measure_after_a_column_edit
    ):
        _preview, run = await harness.replace(
            dataset, _geojson(harness.tmp_path / "b.geojson", _BASE)
        )

    assert run.status == "blocked", run.verification
    assert run.schema_diff["columns_removed"] == [
        {"name": "added_late", "type": "text"}
    ]
    assert "added_late" in await harness.live_columns(dataset)
    kept = await harness.session.scalar(
        text(
            f'SELECT count(*) FROM "data"."{dataset.table_name}" WHERE added_late = \'kept\''
        )
    )
    assert kept == 3


async def _until_a_session_waits_on_a_lock() -> None:
    import app.core.db as db_module

    for _ in range(300):
        async with db_module.async_session() as probe:
            waiting = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the replacement never waited on a lock")


@pytest.mark.parametrize("held_first", [False, True], ids=["inserted", "held_table"])
async def test_a_feature_inserted_while_the_replacement_publishes_holds_it_for_review(
    harness: _Harness, held_first: bool
):
    """A feature write in flight when publication begins is counted before the swap."""
    import app.core.db as db_module
    from sqlalchemy.orm import joinedload

    from app.modules.catalog.features.idempotency import held_table_oid
    from app.modules.catalog.features.service import (
        effective_geometry_type,
        insert_feature,
        refresh_dataset_metadata,
    )

    source = _geojson(harness.tmp_path / "source.geojson", _BASE)
    dataset = await harness.dataset()
    await harness.replace(
        dataset, _ogr2ogr(harness.tmp_path / "e1.gpkg", source, "-where", "1 = 0")
    )
    job_id = await harness.upload_job(
        dataset,
        str(_ogr2ogr(harness.tmp_path / "e2.gpkg", source, "-where", "1 = 0")),
        "e2.gpkg",
    )
    await harness.commit(dataset, job_id)

    async with db_module.async_session() as writer:
        live = (
            await writer.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset.id)
            )
        ).scalar_one()
        geometry_type = await effective_geometry_type(writer, live)

        async def _write() -> None:
            await insert_feature(
                writer,
                live.table_name,
                {"type": "Point", "coordinates": [-73.97, 40.76]},
                {"name": "late"},
                live.column_info or [],
                geometry_type,
                dataset_srid=live.srid,
            )
            await refresh_dataset_metadata(writer, live)

        # A feature write holds the table before its DML; resumed while
        # publication waits, it must neither deadlock nor be dropped.
        if held_first:
            await held_table_oid(writer, live.table_name)
        else:
            await _write()
        worker = asyncio.create_task(harness.run_worker())
        await _until_a_session_waits_on_a_lock()
        if held_first:
            await _write()
        await writer.commit()
    await worker

    run = await harness.run_for(job_id)
    assert run.status == "blocked", run.verification
    assert run.verification["review_reasons"] == ["empty_result"]
    kept = await harness.session.scalar(
        text(
            f'SELECT count(*) FROM "data"."{dataset.table_name}" WHERE name = \'late\''
        )
    )
    assert kept == 1


async def test_live_geometry_is_read_before_the_live_table_is_locked(
    harness: _Harness,
):
    """Readers of the live table are not held behind its geometry-type scan."""
    import app.core.db as db_module
    from app.processing.ingest import metadata

    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))
    real = metadata.get_geometry_types
    reads: list[int] = []

    async def _scan_while_reading_the_live_table(session, table_name, **kwargs):
        if table_name == dataset.table_name:
            async with db_module.async_session() as reader:
                await reader.execute(text("SET LOCAL lock_timeout = '1s'"))
                reads.append(
                    await reader.scalar(
                        text(f'SELECT count(*) FROM "data"."{table_name}"')
                    )
                )
        return await real(session, table_name, **kwargs)

    with patch.object(
        metadata, "get_geometry_types", new=_scan_while_reading_the_live_table
    ):
        _preview, run = await harness.replace(
            dataset, _geojson(harness.tmp_path / "b.geojson", _BASE)
        )

    # The preview reads the live geometry too; every read got through.
    assert reads == [3, 3]
    assert run.status == "succeeded"


# 7: the preview and the worker fingerprint the same subject


def _csv(path: Path, columns: list[str]) -> Path:
    rows = [",".join(columns)] + [
        ",".join(f"{column}{i}" for column in columns) for i in range(3)
    ]
    path.write_text("\n".join(rows) + "\n")
    return path


def _gpkg(tmp: Path, name: str, columns: dict[str, object]) -> Path:
    """A two-layer GeoPackage whose ``roads`` layer has ``columns``."""
    target = tmp / name
    _ogr2ogr(target, _geojson(tmp / f"{name}.roads.geojson", columns), "-nln", "roads")
    _ogr2ogr(
        target,
        _geojson(tmp / f"{name}.other.geojson", {"other": "o"}),
        "-update",
        "-nln",
        "other",
    )
    return target


def _shapefile(tmp: Path, name: str, columns: dict[str, object]) -> Path:
    return _ogr2ogr(
        tmp / f"{name}.shp.zip",
        _geojson(tmp / f"{name}.geojson", columns),
        "-f",
        "ESRI Shapefile",
    )


def _feet(tmp: Path, name: str, columns: dict[str, object]) -> Path:
    """New York State Plane points, in a GeoPackage that records no CRS."""
    source = _geojson(tmp / f"{name}.wgs84.geojson", columns)
    projected = _ogr2ogr(tmp / f"{name}.2263.gpkg", source, "-t_srs", "EPSG:2263")
    return _ogr2ogr(tmp / name, projected, "-a_srs", "None")


# Stored as src_geom, road_name and "mixed case".
_LAUNDERED = {"geom": "g", "Road-Name": "r", "Mixed Case": "m"}

_ROUND_TRIPS = {
    "csv": (
        lambda tmp: _csv(tmp / "a.csv", ["name", "code", "legacy"]),
        lambda tmp: _csv(tmp / "b.csv", ["name", "code"]),
        {"record_type": "table"},
        {},
    ),
    "geojson_polygon": (
        lambda tmp: _geojson(tmp / "a.geojson", _BASE, kind="Polygon"),
        lambda tmp: _geojson(tmp / "b.geojson", _DROPPED, kind="Polygon"),
        {},
        {},
    ),
    "gpkg_layer": (
        lambda tmp: _gpkg(tmp, "a.gpkg", _BASE),
        lambda tmp: _gpkg(tmp, "b.gpkg", _DROPPED),
        {},
        {"layer_name": "roads"},
    ),
    "shapefile": (
        lambda tmp: _shapefile(tmp, "a", _BASE),
        lambda tmp: _shapefile(tmp, "b", _DROPPED),
        {},
        {},
    ),
    "laundered_and_reserved_names": (
        lambda tmp: _geojson(tmp / "a.geojson", {**_BASE, **_LAUNDERED}),
        lambda tmp: _geojson(tmp / "b.geojson", {**_DROPPED, **_LAUNDERED}),
        {},
        {},
    ),
    "srid_override": (
        lambda tmp: _geojson(tmp / "a.geojson", _BASE),
        lambda tmp: _feet(tmp, "b.gpkg", _DROPPED),
        {},
        {"srid_override": 2263},
    ),
}


@pytest.mark.parametrize("case", sorted(_ROUND_TRIPS))
async def test_the_previews_fingerprint_is_the_one_the_worker_computes(
    harness: _Harness, case: str
):
    make_base, make_changed, dataset_kwargs, options = _ROUND_TRIPS[case]
    if case == "gpkg_layer":
        dataset = await harness.dataset(**dataset_kwargs)
        await harness.replace(
            dataset,
            make_base(harness.tmp_path),
            preview_body={"layer_name": "roads"},
            commit_body={"layer_name": "roads"},
        )
        dataset = await harness.reload(dataset)
    else:
        dataset = await _published(
            harness, make_base(harness.tmp_path), **dataset_kwargs
        )

    preview, run = await harness.replace(
        dataset,
        make_changed(harness.tmp_path),
        preview_body=options,
        commit_body=options,
    )

    assert preview["review_fingerprint"], preview
    assert run.verification["review_fingerprint"] == preview["review_fingerprint"], (
        preview["review_reasons"],
        run.verification["review_reasons"],
        preview["schema_diff"],
        run.schema_diff,
        run.verification["geometry_contract"],
    )
    assert run.status == "succeeded"
    if case == "srid_override":
        assert "srid_changed" in preview["review_reasons"]


# 8: accepting a blocked file run


async def _blocked_dataset(harness: _Harness):
    dataset = await _published(harness, _geojson(harness.tmp_path / "a.geojson", _BASE))
    _geojson(harness.tmp_path / "b.geojson", _DROPPED)
    job_id, run = await _blocked_by_staged_upload(
        harness, dataset, harness.tmp_path / "b.geojson"
    )
    assert run.status == "blocked"
    return dataset, job_id, run


async def test_accepting_a_blocked_upload_run_publishes_it_once(harness: _Harness):
    dataset, _job_id, blocked = await _blocked_dataset(harness)

    response = await harness.accept(dataset, blocked.id)
    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["origin_kind"], body["trigger"]) == ("upload", "manual")
    await harness.run_worker()

    accepted = await harness.run_for(uuid.UUID(body["job_id"]))
    assert accepted.status == "succeeded"
    assert accepted.verification["review_acknowledged_by"] == "accepted_run"
    assert accepted.verification["accepted_blocked_run_id"] == str(blocked.id)
    assert "legacy" not in await harness.live_columns(dataset)
    await harness.session.refresh(blocked)
    assert blocked.verification["acceptance_consumed_by_run_id"] == body["run_id"]

    again = await harness.accept(dataset, blocked.id)
    assert again.status_code == 422


async def test_accepting_after_the_upload_is_gone_answers_upload_unavailable(
    harness: _Harness,
):
    dataset, _job_id, blocked = await _blocked_dataset(harness)
    harness.storage.exists.return_value = False

    response = await harness.accept(dataset, blocked.id)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "upload_unavailable"
    await harness.session.refresh(blocked)
    assert "acceptance_consumed_by_run_id" not in blocked.verification


async def test_a_failed_accepting_attempt_gives_the_acceptance_back_and_keeps_the_upload(
    harness: _Harness,
):
    dataset, _job_id, blocked = await _blocked_dataset(harness)
    response = await harness.accept(dataset, blocked.id)
    assert response.status_code == 202, response.text
    harness.storage.delete.reset_mock()

    await harness.run_worker(ogr2ogr_error=IngestionError("ogr2ogr failed"))

    failed = await harness.run_for(uuid.UUID(response.json()["job_id"]))
    assert failed.status == "failed"
    await harness.session.refresh(blocked)
    assert "acceptance_consumed_by_run_id" not in blocked.verification
    harness.storage.delete.assert_not_awaited()
    retry = await harness.accept(dataset, blocked.id)
    assert retry.status_code == 202, retry.text


async def test_an_accepting_attempt_that_fails_before_reading_its_job_keeps_the_upload(
    harness: _Harness,
):
    dataset, _job_id, blocked = await _blocked_dataset(harness)
    response = await harness.accept(dataset, blocked.id)
    assert response.status_code == 202, response.text
    harness.storage.delete.reset_mock()

    await harness.run_worker(
        claim_error=OperationalError("SELECT", {}, ConnectionError("lost"))
    )

    failed = await harness.run_for(uuid.UUID(response.json()["job_id"]))
    assert failed.status == "failed"
    await harness.session.refresh(blocked)
    assert "acceptance_consumed_by_run_id" not in blocked.verification
    harness.storage.delete.assert_not_awaited()
    retry = await harness.accept(dataset, blocked.id)
    assert retry.status_code == 202, retry.text
    await harness.run_worker()
    accepted = await harness.run_for(uuid.UUID(retry.json()["job_id"]))
    assert accepted.status == "succeeded"


async def test_a_blocked_replacement_is_not_offered_or_taken_by_generic_retry(
    harness: _Harness,
):
    """A held replacement proceeds only through acceptance, never as a new import."""
    dataset, job_id, blocked = await _blocked_dataset(harness)
    jobs_before = await harness.session.scalar(select(func.count(IngestJob.id)))

    status = await harness.client.get(f"/jobs/{job_id}", headers=harness.headers)
    retry = await harness.client.post(f"/jobs/{job_id}/retry", headers=harness.headers)

    assert status.status_code == 200, status.text
    assert status.json()["can_retry"] is False
    assert retry.status_code == 400, retry.text
    assert (await harness.job(job_id)).status == "failed"
    assert await harness.session.scalar(select(func.count(IngestJob.id))) == jobs_before
    harness.storage.delete.assert_not_awaited()


async def test_a_failed_accepting_attempt_is_not_offered_or_taken_by_generic_retry(
    harness: _Harness,
):
    """A re-upload that failed for another reason, with its upload kept, is not replayed either."""
    dataset, _job_id, blocked = await _blocked_dataset(harness)
    response = await harness.accept(dataset, blocked.id)
    assert response.status_code == 202, response.text
    await harness.run_worker(ogr2ogr_error=IngestionError("ogr2ogr failed"))
    job_id = response.json()["job_id"]
    jobs_before = await harness.session.scalar(select(func.count(IngestJob.id)))

    status = await harness.client.get(f"/jobs/{job_id}", headers=harness.headers)
    retry = await harness.client.post(f"/jobs/{job_id}/retry", headers=harness.headers)

    assert status.json()["can_retry"] is False
    assert retry.status_code == 400, retry.text
    assert await harness.session.scalar(select(func.count(IngestJob.id))) == jobs_before


async def test_a_viewer_cannot_accept_a_blocked_upload_run(
    harness: _Harness, viewer_auth_header
):
    dataset, _job_id, blocked = await _blocked_dataset(harness)

    response = await harness.accept(dataset, blocked.id, headers=viewer_auth_header)

    assert response.status_code in (403, 404)
    await harness.session.refresh(blocked)
    assert "acceptance_consumed_by_run_id" not in blocked.verification


# 9: a manifest apply carries no fingerprint


async def test_a_manifest_apply_that_drops_a_column_ends_blocked(
    test_db_session, clean_tables
):
    from app.processing.ingest.manifest_service import apply_manifest
    from app.processing.ingest.manifest_sources import (
        classify_manifest_source,
        manifest_dataset_fingerprint,
        manifest_job_metadata,
    )
    from tests.test_manifest_reapply_publication import (
        _admin,
        _entry,
        _http_request,
        _request,
        _reupload_task,
        _run_worker,
        _stage_fixture,
    )

    _stage_fixture()
    user = await _admin(test_db_session)
    key = "roads-review"
    table = f"manifest_review_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        test_db_session,
        created_by=user.id,
        name="Road centerlines",
        table_name=table,
        record_type="vector_dataset",
        geometry_type="POINT",
        feature_count=1,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "legacy", "type": "text"},
        ],
    )
    await test_db_session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), "
            "name text, legacy text)"
        )
    )
    original = _request(_entry(key, title="Roads", intent="published")).datasets[0]
    prepared = await classify_manifest_source(original.sources[0])
    test_db_session.add(
        IngestJob(
            dataset_id=dataset.id,
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="complete",
            user_metadata=manifest_job_metadata(
                original, prepared, fingerprint=manifest_dataset_fingerprint(original)
            ),
        )
    )
    await test_db_session.commit()

    update = _request(_entry(key, title="Resurveyed roads", intent="published"))
    with _reupload_task() as task:
        response = await apply_manifest(test_db_session, update, user, _http_request())
    assert response.results[0].action == "update"
    await _run_worker(task)

    run = (
        await test_db_session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.ingest_job_id == response.results[0].job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert run.status == "blocked"
    assert run.verification["review_reasons"] == ["destructive_schema_change"]
