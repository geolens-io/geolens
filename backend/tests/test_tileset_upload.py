"""A tileset zip uploads, previews, commits and publishes, never reaches GDAL, and an
interrupted attempt is reaped by the job sweep."""

from __future__ import annotations

import inspect
import io
import json
import math
import os
import re
import stat
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import select, text

import app.platform.storage.provider as storage_provider
from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.core.upload_errors import UnsafeUploadError
from app.core.tiles3d import (
    TILESET_ASSET_KEY,
    UNPUBLISHED_TILESET_ATTEMPTS_FIELD,
    tileset_attempt_prefix,
    tileset_prefix,
)
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import (
    fail_stale_jobs,
    reap_unpublished_tileset_attempts,
    unpublished_tileset_attempts_from_metadata,
)
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.reap import PrefixDeleteError
from app.platform.storage.s3 import S3StorageProvider
from app.processing.embeddings.tasks import embed_record
from app.processing.ingest import router as ingest_router
from app.processing.ingest.tasks import ingest_file, ingest_tileset, task_app
from app.processing.ingest.tasks_tileset import unpack_tileset
from app.processing.ingest.tileset import Tileset, TilesetLayout, inspect_tileset
from app.processing.raster.models import DatasetAsset
from tests.factories import create_user
from tests.test_publish_followups import followups as followups
from tests.test_raster_replace_1221 import _ack_lost_on_publish, _publish_commit_lost
from tests.tiles3d_archives import (
    REGION,
    b3dm,
    build_zip,
    cmpt,
    glb,
    gltf_json,
    i3dm,
    pnts,
    three_tz,
    tileset_json,
    zip_bytes,
)

_GLB = b"glTF" + bytes(60)
_B3DM = b"b3dm" + bytes(28)


def campus_zip(**json_kw) -> bytes:
    """A tileset inside one top-level folder, the way most tools export it."""
    return zip_bytes(
        [
            ("campus/", b""),
            ("campus/tileset.json", tileset_json(**json_kw)),
            ("campus/0/0.glb", _GLB),
            ("campus/0/1.b3dm", _B3DM),
        ]
    )


def unpacked_size(**json_kw) -> int:
    return len(tileset_json(**json_kw)) + len(_GLB) + len(_B3DM)


def compressible_zip() -> bytes:
    """600 kB unpacked, about a quarter of that zipped, well under the ratio bound."""
    digits = b"".join(f"{i:08d}".encode() for i in range(75_000))
    return zip_bytes([("tileset.json", tileset_json()), ("0/0.glb", digits)])


@pytest.fixture
async def uploader(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """An editor whose datasets and jobs are removed afterwards."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    yield headers, uuid.UUID(user_id)
    # A committed tiles3d row blocks the migration tests' downgrades past 0065.
    await test_db_session.rollback()
    for table in ("records", "ingest_jobs"):
        await test_db_session.execute(
            text(f"DELETE FROM catalog.{table} WHERE created_by = :user"),
            {"user": user_id},
        )
    await test_db_session.commit()


@pytest.fixture
def queued(monkeypatch) -> list:
    """Each deferred task and its arguments, instead of the queue."""
    calls: list = []

    async def _defer(task, **kwargs):
        calls.append((task, kwargs))

    monkeypatch.setattr("app.processing.ingest.service.defer_async_with_tenant", _defer)
    monkeypatch.setattr(
        "app.processing.embeddings.helpers.defer_async_with_tenant", _defer
    )
    return calls


def _quota(cap: int):
    return patch(
        "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
        new=AsyncMock(return_value=cap),
    )


async def upload(
    client: AsyncClient,
    headers: dict,
    data: bytes,
    *,
    kind: str | None = "tiles3d",
    filename: str = "campus.zip",
):
    return await client.post(
        "/ingest/upload",
        files={"file": (filename, data, "application/zip")},
        data={"kind": kind} if kind else {},
        headers=headers,
    )


async def commit(client: AsyncClient, headers: dict, job_id: str, **fields):
    return await client.post(
        f"/ingest/commit/{job_id}",
        json={"title": "Campus", "visibility": "public", **fields},
        headers=headers,
    )


async def run_queued(queued: list) -> None:
    task, kwargs = queued.pop()
    assert task is ingest_tileset, f"dispatched {task.name}"
    await task.func(**kwargs)


async def publish(
    client, headers, queued, data: bytes, *, filename: str = "campus.zip"
) -> str:
    """Upload, preview, commit and run the worker; returns the job id."""
    uploaded = await upload(client, headers, data, filename=filename)
    assert uploaded.status_code == 201, uploaded.text
    job_id = uploaded.json()["job_id"]
    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    committed = await commit(client, headers, job_id)
    assert committed.status_code == 202, committed.text
    await run_queued(queued)
    return job_id


async def load_job(session, job_id) -> IngestJob:
    session.expire_all()
    return (
        await session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()


async def tileset_objects(dataset_id=None) -> list[str]:
    prefix = tileset_prefix(dataset_id) if dataset_id else "tiles3d/"
    return sorted(await storage_provider.get_storage().list(prefix))


# --- The published tileset -----------------------------------------------


async def test_a_tileset_publishes_its_dataset_pointer_and_objects(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """One transaction creates the record, the dataset with its facts, and the pointer."""
    headers, user_id = uploader
    uploaded = await upload(client, headers, campus_zip())
    assert uploaded.status_code == 201, uploaded.text
    job_id = uploaded.json()["job_id"]

    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json() == {
        "job_id": job_id,
        "source_filename": "campus.zip",
        "version": "1.1",
        "geometric_error": 70.0,
        "bounding_volume": "region",
        "extent_bbox": pytest.approx([math.degrees(v) for v in REGION[:4]]),
        "unpacked_bytes": unpacked_size(),
        "entry_count": 4,
    }
    staged = (await load_job(test_db_session, job_id)).file_path

    committed = await commit(client, headers, job_id)
    assert committed.status_code == 202, committed.text
    await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert job.status == "complete", job.error_message
    dataset = (
        await test_db_session.execute(
            select(Dataset).where(Dataset.id == job.dataset_id)
        )
    ).scalar_one()
    record = await test_db_session.get(Record, dataset.record_id)
    assert (record.record_type, record.created_by) == ("tiles3d_dataset", user_id)
    assert (dataset.source_format, dataset.table_name[:8]) == ("3dtiles", "tiles3d_")
    assert (
        dataset.tileset_version,
        dataset.tileset_geometric_error,
        dataset.tileset_bounding_volume,
    ) == ("1.1", 70.0, "region")
    assert dataset.quality_detail["attribute_completeness"] is None
    attempt = tileset_attempt_prefix(dataset.id, job.attempt_id)
    pointer = (
        await test_db_session.execute(
            select(DatasetAsset).where(
                DatasetAsset.dataset_id == dataset.id,
                DatasetAsset.key == TILESET_ASSET_KEY,
            )
        )
    ).scalar_one()
    assert (pointer.href, pointer.size_bytes) == (
        f"{attempt}tileset.json",
        unpacked_size(),
    )
    assert await tileset_objects(dataset.id) == [
        f"{attempt}0/0.glb",
        f"{attempt}0/1.b3dm",
        f"{attempt}tileset.json",
    ]
    assert await storage_provider.get_storage().get(f"{attempt}0/0.glb") == _GLB
    assert not Path(staged).exists()
    # The tileset route refuses a pointer whose path segments leave this set.
    _, dataset_name, attempt_name, _ = pointer.href.split("/")
    assert re.fullmatch(r"[A-Za-z0-9_-]+", dataset_name)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", attempt_name)
    base = storage_provider.get_storage().base_dir
    for key in await tileset_objects(dataset.id):
        assert (base / key).is_file() and not (base / key).is_symlink(), key

    detail = await client.get(f"/datasets/{dataset.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert {k: body["tileset"][k] for k in ("size_bytes", "version")} == {
        "size_bytes": unpacked_size(),
        "version": "1.1",
    }
    assert body["tileset"]["geometric_error"] == 70.0
    assert body["tileset"]["bounding_volume"] == "region"
    assert body["extent_bbox"] == pytest.approx(
        [math.degrees(v) for v in REGION[:4]], abs=1e-6
    )
    assert queued == [(embed_record, {"record_id": str(record.id)})]


async def test_an_antimeridian_region_reads_back_as_the_crossing_pair(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The stored extent is the two-ring split, and it reads back west > east."""
    headers, _ = uploader
    region = [math.radians(170), -0.3, math.radians(-170), -0.2, 0.0, 10.0]
    job_id = await publish(
        client, headers, queued, campus_zip(volume={"region": region})
    )
    job = await load_job(test_db_session, job_id)

    detail = await client.get(f"/datasets/{job.dataset_id}", headers=headers)

    assert detail.status_code == 200, detail.text
    assert detail.json()["extent_bbox"] == pytest.approx(
        [170.0, math.degrees(-0.3), -170.0, math.degrees(-0.2)], abs=1e-6
    )


@pytest.mark.parametrize(
    ("volume", "kind"),
    [({"box": [0.0] * 12}, "box"), ({"sphere": [0.0, 0.0, 0.0, 5.0]}, "sphere")],
)
async def test_a_box_or_sphere_tileset_has_no_extent(
    client: AsyncClient, test_db_session, uploader, queued, volume, kind
) -> None:
    """Only a region yields an extent; the stored kind says why it is null."""
    headers, _ = uploader
    job_id = await publish(client, headers, queued, campus_zip(volume=volume))
    job = await load_job(test_db_session, job_id)

    body = (await client.get(f"/datasets/{job.dataset_id}", headers=headers)).json()

    assert body["extent_bbox"] is None
    assert body["tileset"]["bounding_volume"] == kind


async def test_the_dataset_lists_the_tileset_contents(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The worker records the content types and required extensions it read."""
    headers, _ = uploader
    data = campus_zip(extra={"extensionsRequired": ["3DTILES_implicit_tiling"]})

    job = await load_job(test_db_session, await publish(client, headers, queued, data))
    body = (await client.get(f"/datasets/{job.dataset_id}", headers=headers)).json()

    assert body["tileset"]["content_types"] == ["b3dm", "glb"]
    assert body["tileset"]["extensions_required"] == ["3DTILES_implicit_tiling"]


async def test_a_finder_zip_publishes_without_its_metadata(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """Only the tileset's own files are stored from a zip Finder compressed."""
    headers, _ = uploader
    appledouble = b"\x00\x05\x16\x07" + bytes(28)
    data = zip_bytes(
        [
            ("campus/", b""),
            ("campus/tileset.json", tileset_json()),
            ("campus/0/0.glb", _GLB),
            ("campus/.DS_Store", b"Bud1" + bytes(64)),
            ("__MACOSX/", b""),
            ("__MACOSX/campus/._tileset.json", appledouble),
            ("__MACOSX/campus/0/._0.glb", appledouble),
        ]
    )

    job = await load_job(test_db_session, await publish(client, headers, queued, data))

    assert job.status == "complete", job.error_message
    attempt = tileset_attempt_prefix(job.dataset_id, job.attempt_id)
    assert await tileset_objects(job.dataset_id) == [
        f"{attempt}0/0.glb",
        f"{attempt}tileset.json",
    ]


async def test_a_3tz_tileset_publishes_without_its_index(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """A .3tz publishes its tileset; its index is neither stored nor served."""
    headers, _ = uploader
    data = three_tz([("tileset.json", tileset_json()), ("0/0.glb", _GLB)])

    job_id = await publish(client, headers, queued, data, filename="campus.3tz")
    job = await load_job(test_db_session, job_id)

    assert job.status == "complete", job.error_message
    attempt = tileset_attempt_prefix(job.dataset_id, job.attempt_id)
    assert await tileset_objects(job.dataset_id) == [
        f"{attempt}0/0.glb",
        f"{attempt}tileset.json",
    ]
    route = f"/datasets/{job.dataset_id}/tiles3d"
    served = await client.get(f"{route}/tileset.json", headers=headers)
    assert served.status_code == 200, served.text
    index = await client.get(f"{route}/@3dtilesIndex1@", headers=headers)
    assert index.status_code == 404, index.text


def _dji_style_tileset() -> list[tuple[str, bytes]]:
    """3D Tiles 1.0 as DJI Terra writes it, with REPLACE LODs and every tile format."""

    def tile(uri: str, **more) -> dict:
        volume = {"sphere": [0, 0, 0, 10]}
        return {
            "boundingVolume": volume,
            "geometricError": 0,
            "content": {"uri": uri},
            **more,
        }

    model = b3dm(glb(gltf_json()))
    root = json.loads(tileset_json(version="1.0"))
    root["root"]["children"] = [
        tile(
            "lod/low.b3dm",
            geometricError=10,
            refine="REPLACE",
            children=[tile("lod/high.b3dm")],
        ),
        tile("city/tileset.json"),
        tile("points/points.pnts"),
        tile("trees/tree.i3dm"),
        tile("composite/tile.cmpt"),
    ]
    city = json.loads(tileset_json(version="1.0"))
    city["root"]["content"] = {"uri": "0.b3dm"}
    return [
        ("tileset.json", json.dumps(root).encode()),
        ("lod/low.b3dm", model),
        ("lod/high.b3dm", model),
        ("city/tileset.json", json.dumps(city).encode()),
        ("city/0.b3dm", model),
        ("points/points.pnts", pnts()),
        ("trees/tree.i3dm", i3dm(glb(gltf_json()))),
        ("composite/tile.cmpt", cmpt(model, i3dm(glb(gltf_json())))),
    ]


async def test_a_3d_tiles_1_0_tileset_publishes_and_serves_every_file(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """1.0 content publishes and serves as is: JSON as JSON, tiles as octet-stream."""
    headers, _ = uploader
    entries = _dji_style_tileset()

    job_id = await publish(client, headers, queued, zip_bytes(entries))
    job = await load_job(test_db_session, job_id)

    assert job.status == "complete", job.error_message
    for name, data in entries:
        served = await client.get(
            f"/datasets/{job.dataset_id}/tiles3d/{name}", headers=headers
        )
        assert served.status_code == 200, name
        expected = (
            "application/json" if name.endswith(".json") else "application/octet-stream"
        )
        assert served.headers["content-type"] == expected, name
        assert served.content == data, name


# --- Refusals ------------------------------------------------------------


async def test_a_zip_slip_archive_is_refused_before_any_write(
    client: AsyncClient, test_db_session, uploader, tmp_path
) -> None:
    """The door refuses the archive, and nothing reaches the tileset prefix."""
    headers, _ = uploader
    data = zip_bytes([("tileset.json", tileset_json()), ("../../escape.glb", _GLB)])

    refused = await upload(client, headers, data)

    assert refused.status_code == 422, refused.text
    assert "below the archive root" in refused.json()["detail"]["message"]
    job = (
        await test_db_session.execute(
            select(IngestJob).where(IngestJob.created_by == uploader[1])
        )
    ).scalar_one()
    assert (job.status, job.file_path) == ("failed", "")
    assert await tileset_objects() == []
    assert list((tmp_path / "staging").glob("*.zip")) == []


async def test_content_outside_the_tileset_is_refused_at_the_door(
    client: AsyncClient, test_db_session, uploader
) -> None:
    """A tileset whose content URI climbs out of it is refused before any write."""
    document = json.loads(tileset_json())
    document["root"]["content"] = {"uri": "../../other-dataset/tileset.json"}
    data = zip_bytes([("tileset.json", json.dumps(document).encode())])

    refused = await upload(client, uploader[0], data)

    assert refused.status_code == 422, refused.text
    assert "names content outside the tileset" in refused.json()["detail"]["message"]
    assert await tileset_objects() == []


def _external_tileset_naming_outside_content() -> bytes:
    nested = json.loads(tileset_json())
    nested["root"]["content"] = {"uri": "https://example.com/0.b3dm"}
    return json.dumps(nested).encode()


@pytest.mark.parametrize(
    ("name", "member"),
    [
        ("sub/tileset.json", _external_tileset_naming_outside_content()),
        (
            "0/0.b3dm",
            b3dm(glb(gltf_json(images=[{"uri": "https://example.com/0.png"}]))),
        ),
    ],
    ids=["external-tileset", "b3dm"],
)
async def test_a_file_naming_outside_content_is_refused_before_the_first_put(
    client: AsyncClient, test_db_session, uploader, queued, name: str, member: bytes
) -> None:
    """The worker refuses any file naming outside content, before writing anything."""
    root = json.loads(tileset_json())
    root["root"]["content"] = {"uri": name}
    data = zip_bytes([("tileset.json", json.dumps(root).encode()), (name, member)])

    headers, _ = uploader
    uploaded = await upload(client, headers, data)
    assert uploaded.status_code == 201, uploaded.text
    job_id = uploaded.json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202

    with pytest.raises(UnsafeUploadError):
        await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert job.status == "failed"
    assert f"{name} names content outside" in job.error_message
    assert await tileset_objects() == []


@pytest.mark.parametrize("door", ["multipart", "presigned"])
async def test_kind_on_a_file_that_is_not_a_zip_is_refused(
    client: AsyncClient, test_db_session, uploader, monkeypatch, door
) -> None:
    """A tileset is a .zip or .3tz; the kind routes no other file past a check."""
    headers, user_id = uploader
    monkeypatch.setattr(
        settings, "storage_provider", "s3" if door == "presigned" else "local"
    )
    if door == "multipart":
        resp = await upload(client, headers, b"SQLite format 3\x00", filename="x.gpkg")
    else:
        resp = await client.post(
            "/ingest/upload/presigned",
            json={"filename": "x.gpkg", "file_size": 16, "kind": "tiles3d"},
            headers=headers,
        )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "tileset_extension_mismatch"
    assert "uploaded as a .zip or .3tz archive" in detail["message"]
    jobs = await test_db_session.execute(
        select(IngestJob.id).where(IngestJob.created_by == user_id)
    )
    assert jobs.all() == []


@pytest.mark.parametrize("door", ["multipart", "presigned"])
async def test_a_3tz_without_the_tileset_kind_is_refused(
    client: AsyncClient, test_db_session, uploader, monkeypatch, door
) -> None:
    """A .3tz holds only a tileset, so no upload door takes one without the kind."""
    headers, user_id = uploader
    monkeypatch.setattr(
        settings, "storage_provider", "s3" if door == "presigned" else "local"
    )
    if door == "multipart":
        data = three_tz([("tileset.json", tileset_json())])
        resp = await upload(client, headers, data, kind=None, filename="campus.3tz")
    else:
        resp = await client.post(
            "/ingest/upload/presigned",
            json={"filename": "campus.3tz", "file_size": 64},
            headers=headers,
        )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "tileset_kind_required"
    assert "Upload it with kind=tiles3d" in detail["message"]
    jobs = await test_db_session.execute(
        select(IngestJob.id).where(IngestJob.created_by == user_id)
    )
    assert jobs.all() == []


@pytest.mark.parametrize("door", ["multipart", "presigned"])
async def test_a_stored_extension_list_without_3tz_refuses_it(
    client: AsyncClient, uploader, monkeypatch, door
) -> None:
    """An allowed list stored without .3tz refuses a .3tz tileset with the usual 400."""
    headers, _ = uploader
    monkeypatch.setattr(
        settings, "storage_provider", "s3" if door == "presigned" else "local"
    )

    async def _stored(_db):
        return [".zip", ".geojson"]

    monkeypatch.setattr(ingest_router, "get_allowed_extensions_list", _stored)
    if door == "multipart":
        data = three_tz([("tileset.json", tileset_json())])
        resp = await upload(client, headers, data, filename="campus.3tz")
    else:
        resp = await client.post(
            "/ingest/upload/presigned",
            json={"filename": "campus.3tz", "file_size": 64, "kind": "tiles3d"},
            headers=headers,
        )

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "disallowed_extension"
    assert "'.3tz' not allowed" in detail["message"]


async def test_an_unknown_kind_is_refused(client: AsyncClient, uploader) -> None:
    """kind accepts 'tiles3d' and nothing else."""
    resp = await upload(client, uploader[0], campus_zip(), kind="pointcloud")

    assert resp.status_code == 422, resp.text


async def test_fan_out_queues_nothing_for_a_tileset(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """A tileset job has no layers, so the fan-out door queues no vector import."""
    headers, _ = uploader
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]

    resp = await client.post(
        f"/ingest/commit-fan-out/{job_id}",
        json={"layers": [{"layer_name": "campus"}]},
        headers=headers,
    )

    assert resp.status_code == 422, resp.text
    assert queued == []
    assert (await load_job(test_db_session, job_id)).status == "pending"


# --- GDAL isolation (Rule 2) ---------------------------------------------


@contextmanager
def _gdal_unreachable(monkeypatch):
    reached: list[str] = []

    def _record(name):
        async def _async(*args, **kwargs):
            reached.append(name)
            raise AssertionError(f"{name} reached")

        return _async

    monkeypatch.setattr(
        "app.processing.ingest.ogr.asyncio.create_subprocess_exec",
        _record("a GDAL subprocess"),
    )

    def _rasterio_open(*args, **kwargs):
        reached.append("rasterio.open")
        raise AssertionError("rasterio.open reached")

    monkeypatch.setattr("rasterio.open", _rasterio_open)
    yield reached


async def test_a_tileset_upload_never_reaches_gdal(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """Upload, preview, commit and publish run without a GDAL process or open."""
    headers, _ = uploader
    with _gdal_unreachable(monkeypatch) as reached:
        job_id = await publish(client, headers, queued, campus_zip())

    assert reached == []
    assert (await load_job(test_db_session, job_id)).status == "complete"


async def test_a_zip_without_kind_takes_every_gdal_check(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """The same archive without kind is previewed and queued as geospatial data."""
    from app.processing.ingest import ogr, validation

    headers, _ = uploader
    checked: list[str] = []
    zip_safety = validation.validate_zip_safety
    directives = ogr.validate_content_directives

    def _zip_safety(path):
        checked.append("validate_zip_safety")
        return zip_safety(path)

    def _directives(path, filename=None):
        checked.append("validate_content_directives")
        return directives(path, filename)

    monkeypatch.setattr(validation, "validate_zip_safety", _zip_safety)
    monkeypatch.setattr(ogr, "validate_content_directives", _directives)

    uploaded = await upload(client, headers, campus_zip(), kind=None)
    job_id = uploaded.json()["job_id"]
    await client.post(f"/ingest/preview/{job_id}", headers=headers)
    committed = await commit(client, headers, job_id)

    assert uploaded.status_code == 201, uploaded.text
    assert "file_type" not in (await load_job(test_db_session, job_id)).user_metadata
    assert checked[:2] == ["validate_content_directives", "validate_zip_safety"]
    assert committed.status_code == 202, committed.text
    # A small import goes to the priority queue through a configured deferrer.
    assert queued[-1][0].job.task_name == ingest_file.name


# --- Quota ---------------------------------------------------------------


async def test_the_unpacked_total_is_checked_at_the_upload_door(
    client: AsyncClient, test_db_session, uploader
) -> None:
    """A zip that fits the quota but unpacks past it gets the quota's 413."""
    headers, _ = uploader
    data = compressible_zip()
    with _quota(400_000):
        resp = await upload(client, headers, data)

    assert len(data) < 400_000
    assert resp.status_code == 413, resp.text
    assert "Storage quota exceeded" in resp.json()["detail"]


async def test_the_unpacked_total_is_checked_again_at_commit(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """Usage that grew after the upload is caught at commit, before anything is queued."""
    headers, _ = uploader
    job_id = (await upload(client, headers, compressible_zip())).json()["job_id"]

    with _quota(400_000):
        resp = await commit(client, headers, job_id)

    assert resp.status_code == 413, resp.text
    assert queued == []
    assert (await load_job(test_db_session, job_id)).status == "pending"


async def test_the_publish_reservation_refuses_an_overshoot(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """The worker reserves under the per-user lock and publishes nothing past the cap."""
    headers, _ = uploader
    job_id = (await upload(client, headers, compressible_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202

    with _quota(400_000), pytest.raises(Exception, match="Storage quota exceeded"):
        await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert (job.status, job.dataset_id) == ("failed", None)
    assert "Storage quota exceeded" in job.error_message
    assert await tileset_objects() == []


async def test_a_failed_publish_commits_no_tiles3d_record(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """The record, the dataset and the pointer commit together or not at all."""
    headers, user_id = uploader
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202
    monkeypatch.setattr(
        "app.processing.ingest.tasks_tileset.compute_quality_score",
        AsyncMock(side_effect=RuntimeError("publish interrupted")),
    )

    with pytest.raises(RuntimeError, match="publish interrupted"):
        await run_queued(queued)

    records = await test_db_session.execute(
        select(Record.id).where(
            Record.created_by == user_id, Record.record_type == "tiles3d_dataset"
        )
    )
    assert records.all() == []
    assert (await load_job(test_db_session, job_id)).status == "failed"
    assert await tileset_objects() == []


async def test_a_lost_publish_commit_still_in_progress_keeps_the_unpacked_tileset(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """A publishing commit still in progress when its acknowledgement is lost reaps nothing."""
    headers, _ = uploader
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202

    with _publish_commit_lost(job_id) as fired:
        await run_queued(queued)

    assert fired["count"] == 1, "the publishing commit never fired"
    assert await tileset_objects() != [], (
        "the unpacked tileset was reaped while the commit that decides whether "
        "it is live was still in progress"
    )
    job = await load_job(test_db_session, job_id)
    assert (job.status, job.dataset_id) == ("running", None)


async def test_a_lost_publish_commit_that_aborted_reaps_the_unpacked_tileset(
    client: AsyncClient, test_db_session, uploader, queued
) -> None:
    """A publishing commit that aborted published nothing, so the unpacked tileset is reaped."""
    headers, _ = uploader
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202

    with (
        _publish_commit_lost(job_id, aborted=True) as fired,
        pytest.raises(ConnectionResetError),
    ):
        await run_queued(queued)

    assert fired["count"] == 1, "the publishing commit never fired"
    assert await tileset_objects() == []
    job = await load_job(test_db_session, job_id)
    assert (job.status, job.dataset_id) == ("failed", None)


async def test_a_lost_acknowledgement_that_landed_still_runs_the_followups(
    client: AsyncClient, test_db_session, uploader, queued, followups
) -> None:
    """A tileset publish observed after its acknowledgement was lost runs its follow-ups once."""
    headers, _ = uploader
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202

    with _ack_lost_on_publish(
        uuid.UUID(job_id), failure=ConnectionResetError("dropped")
    ) as fired:
        await run_queued(queued)

    assert fired["count"] == 1, "the publishing commit never fired"
    assert followups == [
        ("notice", "ingest_complete"),
        ("cache",),
        ("embed",),
        ("bill", "ingest_jobs"),
    ]
    assert followups.billing == [job_id]
    assert (await load_job(test_db_session, job_id)).status == "complete"


# --- Tenancy -------------------------------------------------------------


class _RecordingStorage:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def put(self, key, data) -> str:
        data.read()
        self.keys.append(key)
        return key


async def test_every_key_goes_through_the_tenant_resolver(
    tmp_path, monkeypatch
) -> None:
    """A hosted worker writes under its tenant's prefix, and none without one."""
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", tileset_json()), ("0/0.glb", _GLB)],
    )
    tileset = inspect_tileset(path)
    storage = _RecordingStorage()
    monkeypatch.setattr(storage_provider, "_storage", storage)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())

    with pytest.raises(RuntimeError, match="tenant context"):
        await unpack_tileset(path, tileset, prefix)
    assert storage.keys == []

    tenant = str(uuid.uuid4())
    token = current_tenant_var.set(tenant)
    try:
        await unpack_tileset(path, tileset, prefix)
    finally:
        current_tenant_var.reset(token)
    assert sorted(storage.keys) == [
        f"tenants/{tenant}/{prefix}0/0.glb",
        f"tenants/{tenant}/{prefix}tileset.json",
    ]


# --- Unpacking -----------------------------------------------------------


async def test_a_damaged_member_is_refused_while_unpacking(
    tmp_path, monkeypatch
) -> None:
    """A member that fails its checksum reads as a refusal, not a storage error."""
    path = tmp_path / "t.zip"
    build_zip(
        path,
        [("tileset.json", tileset_json()), ("0/0.glb", b"ORIGINAL-PAYLOAD")],
        compression=zipfile.ZIP_STORED,
    )
    path.write_bytes(
        path.read_bytes().replace(b"ORIGINAL-PAYLOAD", b"ORIGINAL-PAYLOAX")
    )
    tileset = inspect_tileset(str(path))
    monkeypatch.setattr(storage_provider, "_storage", _RecordingStorage())
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())

    with pytest.raises(UnsafeUploadError, match="could not be read"):
        await unpack_tileset(str(path), tileset, prefix)


async def test_unpacking_never_creates_a_link(tmp_path, monkeypatch) -> None:
    """Even an entry marked as a symlink reaches storage as a regular file."""
    link = zipfile.ZipInfo("0/link.glb")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = build_zip(
        tmp_path / "t.zip", [("tileset.json", tileset_json()), (link, b"/etc")]
    )
    # The archive check refuses this entry, so the layout is built by hand to
    # exercise the unpack on its own.
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
    tileset = Tileset(
        layout=TilesetLayout(
            files=tuple((info, info.filename) for info in entries),
            entry_point=entries[0],
            unpacked_bytes=sum(info.file_size for info in entries),
            entry_count=len(entries),
        ),
        facts=inspect_tileset(
            build_zip(tmp_path / "ok.zip", [("tileset.json", tileset_json())])
        ).facts,
    )
    storage = LocalStorageProvider(base_dir=str(tmp_path / "store"))
    monkeypatch.setattr(storage_provider, "_storage", storage)
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())

    await unpack_tileset(path, tileset, prefix)

    written = storage.base_dir / f"{prefix}0/link.glb"
    assert written.is_file() and not written.is_symlink()
    assert written.read_bytes() == b"/etc"


# --- The task contract ---------------------------------------------------


def test_the_tileset_task_keeps_its_name_queue_and_arguments() -> None:
    """A queued tileset job resolves to this task and binds these arguments."""
    task = task_app.tasks["app.processing.ingest.tasks_tileset.ingest_tileset"]
    signature = inspect.signature(task.func)

    assert task is ingest_tileset
    assert (task.queue, task.retry_strategy, task.pass_context) == (
        "raster",
        None,
        False,
    )
    assert [(p.name, p.kind, p.default) for p in signature.parameters.values()] == [
        ("job_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("file_path", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("user_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("attempt_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, None),
        ("kwargs", inspect.Parameter.VAR_KEYWORD, inspect.Parameter.empty),
    ]


# --- Presigned doors on S3 -----------------------------------------------


@pytest.fixture
def s3_storage(client, monkeypatch):
    """S3 mode against a moto bucket, on every storage lookup."""
    credential = uuid.uuid4().hex
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, credential)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tiles3d")
        storage = S3StorageProvider(
            bucket="tiles3d",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )
        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setattr(storage_provider, "_storage", storage)
        yield storage


async def presigned_upload(
    client, headers, storage, data: bytes, *, filename: str = "campus.zip"
):
    presigned = await client.post(
        "/ingest/upload/presigned",
        json={"filename": filename, "file_size": len(data), "kind": "tiles3d"},
        headers=headers,
    )
    assert presigned.status_code == 201, presigned.text
    body = presigned.json()
    # Stands in for the browser's PUT to the presigned URL.
    await storage.put(body["s3_key"], io.BytesIO(data))
    completed = await client.post(
        f"/ingest/upload/presigned/{body['job_id']}/complete", json={}, headers=headers
    )
    return body, completed


async def test_a_presigned_tileset_publishes_from_s3(
    client: AsyncClient, test_db_session, uploader, queued, s3_storage
) -> None:
    """The presigned doors read the archive in place and the worker unpacks it to S3."""
    headers, _ = uploader
    body, completed = await presigned_upload(client, headers, s3_storage, campus_zip())
    assert completed.status_code == 200, completed.text
    job_id = body["job_id"]

    previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["unpacked_bytes"] == unpacked_size()
    assert (await commit(client, headers, job_id)).status_code == 202
    await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert job.status == "complete", job.error_message
    attempt = tileset_attempt_prefix(job.dataset_id, job.attempt_id)
    assert await s3_storage.list(tileset_prefix(job.dataset_id)) == [
        f"{attempt}0/0.glb",
        f"{attempt}0/1.b3dm",
        f"{attempt}tileset.json",
    ]
    assert await s3_storage.list(f"staging/{job_id}/") == []


async def test_a_3tz_tileset_is_accepted_at_the_presigned_doors(
    client: AsyncClient, uploader, s3_storage
) -> None:
    """The presigned doors take a .3tz tileset and read it in place."""
    headers, _ = uploader
    data = three_tz([("tileset.json", tileset_json()), ("0/0.glb", _GLB)])

    body, completed = await presigned_upload(
        client, headers, s3_storage, data, filename="campus.3tz"
    )

    assert completed.status_code == 200, completed.text
    previewed = await client.post(f"/ingest/preview/{body['job_id']}", headers=headers)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["unpacked_bytes"] == len(tileset_json()) + len(_GLB)


async def test_the_unpacked_total_is_checked_at_presigned_complete(
    client: AsyncClient, test_db_session, uploader, s3_storage
) -> None:
    """The quota's 413 at completion drops the staging object and its frozen copy."""
    headers, _ = uploader
    data = compressible_zip()

    with _quota(400_000):
        body, completed = await presigned_upload(client, headers, s3_storage, data)

    assert len(data) < 400_000
    assert completed.status_code == 413, completed.text
    assert await s3_storage.list(f"staging/{body['job_id']}/") == []
    job = await load_job(test_db_session, body["job_id"])
    assert (job.status, job.file_path) == ("pending", "")


async def test_a_refused_archive_is_dropped_at_presigned_complete(
    client: AsyncClient, uploader, s3_storage
) -> None:
    """A zip-slip entry is a 422 at completion, with both objects gone."""
    headers, _ = uploader
    data = zip_bytes([("tileset.json", tileset_json()), ("../escape.glb", _GLB)])

    body, completed = await presigned_upload(client, headers, s3_storage, data)

    assert completed.status_code == 422, completed.text
    assert "below the archive root" in completed.json()["detail"]["message"]
    assert await s3_storage.list(f"staging/{body['job_id']}/") == []


async def test_a_member_past_the_multipart_threshold_streams_whole(
    tmp_path, s3_storage
) -> None:
    """A member larger than one S3 part reaches the bucket byte for byte."""
    large = os.urandom(9 * 1024 * 1024)
    path = build_zip(
        tmp_path / "t.zip",
        [("tileset.json", tileset_json()), ("0/large.glb", large)],
        compression=zipfile.ZIP_STORED,
    )
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())

    await unpack_tileset(path, inspect_tileset(path), prefix)

    assert await s3_storage.get(f"{prefix}0/large.glb") == large


# --- Interruption ----------------------------------------------------------


class _DiesAfterTwoPuts:
    """The configured storage, until the third put kills the attempt."""

    def __init__(self, storage) -> None:
        self._storage = storage
        self.puts = 0

    def __getattr__(self, name):
        return getattr(self._storage, name)

    async def put(self, key, data):
        if self.puts == 2:
            raise RuntimeError("worker killed")
        self.puts += 1
        return await self._storage.put(key, data)


async def interrupted_attempt(client, headers, queued, monkeypatch) -> str:
    """Commit a tileset whose attempt writes two objects and never cleans up."""
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202
    real = storage_provider.get_storage()
    monkeypatch.setattr(storage_provider, "_storage", _DiesAfterTwoPuts(real))
    # As after a SIGKILL: the attempt's own cleanup never runs.
    monkeypatch.setattr(
        "app.processing.ingest.tasks_tileset.delete_prefix", AsyncMock(return_value=0)
    )
    with pytest.raises(RuntimeError, match="worker killed"):
        await run_queued(queued)
    monkeypatch.setattr(storage_provider, "_storage", real)
    return job_id


async def test_an_interrupted_attempts_objects_are_reaped(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """The prefix named before the first put licenses reaping what was written."""
    job_id = await interrupted_attempt(client, uploader[0], queued, monkeypatch)
    job = await load_job(test_db_session, job_id)
    (prefix,) = job.user_metadata[UNPUBLISHED_TILESET_ATTEMPTS_FIELD]
    assert job.status == "failed"
    assert len(await tileset_objects()) == 2

    outcome = await fail_stale_jobs(test_db_session, detailed=True)

    assert await tileset_objects() == []
    assert outcome.storage_objects_reaped >= 2
    job = await load_job(test_db_session, job_id)
    assert UNPUBLISHED_TILESET_ATTEMPTS_FIELD not in job.user_metadata


async def test_the_live_attempt_is_never_reaped(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """After a retry publishes, the dead attempt is reaped and the live one kept."""
    headers, _ = uploader
    job_id = await interrupted_attempt(client, headers, queued, monkeypatch)
    retried = await client.post(f"/jobs/{job_id}/retry", headers=headers)
    assert retried.status_code == 202, retried.text
    await run_queued(queued)
    job = await load_job(test_db_session, job_id)
    dead, live = job.user_metadata[UNPUBLISHED_TILESET_ATTEMPTS_FIELD]
    assert job.status == "complete", job.error_message
    assert live == tileset_attempt_prefix(job.dataset_id, job.attempt_id)
    published = sorted(await storage_provider.get_storage().list(live))
    assert len(published) == 3

    await fail_stale_jobs(test_db_session, detailed=True)

    assert await storage_provider.get_storage().list(dead) == []
    assert await tileset_objects() == published
    job = await load_job(test_db_session, job_id)
    assert UNPUBLISHED_TILESET_ATTEMPTS_FIELD not in job.user_metadata


@pytest.fixture
async def job_row(test_db_session):
    """Insert one ingest job row, removed afterwards."""
    ids: list = []

    async def _insert(**fields) -> IngestJob:
        job = IngestJob(file_path="", **fields)
        test_db_session.add(job)
        await test_db_session.commit()
        ids.append(job.id)
        return job

    yield _insert
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.ingest_jobs WHERE id = ANY(:ids)"), {"ids": ids}
    )
    await test_db_session.commit()


async def test_a_killed_running_attempt_is_reaped_once_settled(
    client: AsyncClient, test_db_session, job_row
) -> None:
    """A running row past its lease is settled failed, then its prefix is reaped."""
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())
    for key in (f"{prefix}tileset.json", f"{prefix}0/0.glb"):
        await storage_provider.get_storage().put(key, b"{}")
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    job = await job_row(
        status="running",
        started_at=stale,
        heartbeat_at=stale,
        user_metadata={UNPUBLISHED_TILESET_ATTEMPTS_FIELD: [prefix]},
    )

    await fail_stale_jobs(test_db_session, detailed=True)

    assert await tileset_objects() == []
    row = await load_job(test_db_session, job.id)
    assert row.status == "failed"
    assert UNPUBLISHED_TILESET_ATTEMPTS_FIELD not in row.user_metadata


async def test_a_hand_edited_record_is_ignored(
    client: AsyncClient, test_db_session, job_row
) -> None:
    """Only the exact shape of one attempt's prefix is ever reaped."""
    dataset_id = uuid.uuid4()
    prefix = tileset_attempt_prefix(dataset_id, uuid.uuid4())
    kept = sorted([f"{prefix}tileset.json", f"tiles3d/{dataset_id}/other/x.glb"])
    for key in kept:
        await storage_provider.get_storage().put(key, b"{}")
    await job_row(
        status="failed",
        user_metadata={
            UNPUBLISHED_TILESET_ATTEMPTS_FIELD: [
                "tiles3d/",
                f"tiles3d/{dataset_id}/",
                prefix[:-1],
                f"{prefix}../",
                f"{prefix}0/",
                prefix.upper(),
            ]
        },
    )

    await fail_stale_jobs(test_db_session, detailed=True)

    assert await tileset_objects() == kept


async def test_the_sweep_reaps_under_the_tenant_prefix(client, monkeypatch) -> None:
    """A hosted sweep resolves each recorded prefix for its own tenant."""
    tenant = str(uuid.uuid4())
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())
    storage = storage_provider.get_storage()
    await storage.put(f"tenants/{tenant}/{prefix}tileset.json", b"{}")
    await storage.put(f"{prefix}tileset.json", b"{}")
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    token = current_tenant_var.set(tenant)
    try:
        counts = await reap_unpublished_tileset_attempts((prefix,))
    finally:
        current_tenant_var.reset(token)

    assert counts == (1, 0, 0)
    assert await storage.list(f"tenants/{tenant}/") == []
    assert await storage.list(prefix) == [f"{prefix}tileset.json"]


async def test_a_partial_reap_keeps_the_record_for_the_next_pass(
    client, test_db_session, job_row, monkeypatch
) -> None:
    """A PrefixDeleteError leaves the prefix on the job row for the next pass."""
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())
    job = await job_row(
        status="failed", user_metadata={UNPUBLISHED_TILESET_ATTEMPTS_FIELD: [prefix]}
    )
    monkeypatch.setattr(
        "app.platform.storage.reap.delete_prefix",
        AsyncMock(side_effect=PrefixDeleteError("1 of 2 deletes failed")),
    )

    counts = await reap_unpublished_tileset_attempts((prefix,))

    assert counts == (0, 0, 1)
    row = await load_job(test_db_session, job.id)
    assert row.user_metadata[UNPUBLISHED_TILESET_ATTEMPTS_FIELD] == [prefix]


async def test_an_unreadable_pointer_licenses_no_delete(
    client, test_db_session, job_row, monkeypatch
) -> None:
    """When the live pointer cannot be read, nothing is deleted and the record stays."""
    prefix = tileset_attempt_prefix(uuid.uuid4(), uuid.uuid4())
    await storage_provider.get_storage().put(f"{prefix}tileset.json", b"{}")
    job = await job_row(
        status="failed", user_metadata={UNPUBLISHED_TILESET_ATTEMPTS_FIELD: [prefix]}
    )
    monkeypatch.setattr(
        "app.modules.catalog.datasets.domain.service.get_tileset_href",
        AsyncMock(side_effect=RuntimeError("the catalog is unavailable")),
    )

    counts = await reap_unpublished_tileset_attempts((prefix,))

    assert counts == (0, 1, 0)
    assert await storage_provider.get_storage().list(prefix) == [
        f"{prefix}tileset.json"
    ]
    row = await load_job(test_db_session, job.id)
    assert row.user_metadata[UNPUBLISHED_TILESET_ATTEMPTS_FIELD] == [prefix]


@pytest.mark.parametrize(
    "recorded",
    [None, "tiles3d/a/b/", [1, None], ["tiles3d/"], ["tiles3d/x/y/"]],
    ids=["missing", "string", "not-strings", "root", "not-uuids"],
)
def test_only_an_attempt_shaped_prefix_is_read_back(recorded) -> None:
    """Anything but tiles3d/{uuid}/{uuid}/ is dropped before the reap."""
    metadata = (
        {} if recorded is None else {UNPUBLISHED_TILESET_ATTEMPTS_FIELD: recorded}
    )

    assert unpublished_tileset_attempts_from_metadata(metadata) == ()


async def test_the_attempt_names_its_prefix_before_the_first_put(
    client: AsyncClient, test_db_session, uploader, queued, monkeypatch
) -> None:
    """The job row already names the prefix when the first object is written."""
    headers, _ = uploader
    job_id = (await upload(client, headers, campus_zip())).json()["job_id"]
    assert (await commit(client, headers, job_id)).status_code == 202
    real = storage_provider.get_storage()
    recorded: list = []

    class _Watching:
        def __getattr__(self, name):
            return getattr(real, name)

        async def put(self, key, data):
            if not recorded:
                recorded.append((await load_job(test_db_session, job_id)).user_metadata)
                await test_db_session.rollback()
            return await real.put(key, data)

    monkeypatch.setattr(storage_provider, "_storage", _Watching())
    await run_queued(queued)

    job = await load_job(test_db_session, job_id)
    assert recorded[0][UNPUBLISHED_TILESET_ATTEMPTS_FIELD] == [
        tileset_attempt_prefix(job.dataset_id, job.attempt_id)
    ]
