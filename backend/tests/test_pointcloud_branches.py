"""A point cloud takes its own branch at delete, quota, the record, the response, re-upload and quality."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import boto3
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import text

from app.core.config import settings
from app.core.pointcloud import (
    POINTCLOUD_ASSET_KEY,
    POINTCLOUD_MEDIA_TYPE,
    pointcloud_attempt_key,
    pointcloud_path,
    pointcloud_prefix,
)
from app.core.record_types import RECORD_TYPES, is_table_or_raster_backed
from app.modules.auth.models import User
from app.modules.catalog.datasets.api.router_reupload import (
    _assert_compatible_record_type,
)
from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordContact
from app.modules.quota.service import get_user_quota_usage
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.ingest.metadata_quality import score_quality
from app.processing.raster.models import DatasetAsset
from tests.factories import create_dataset, get_user_id

_FILE_BYTES = 229_729_892


@pytest.fixture
async def pointcloud(test_db_session):
    """A published point cloud whose dataset and pointer row name its live upload attempt."""
    owner = User(username=f"copc-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db_session.add(owner)
    await test_db_session.flush()
    record = Record(
        title=f"LiDAR tile {uuid.uuid4().hex[:8]}",
        record_type="pointcloud_dataset",
        visibility="public",
        record_status="published",
        created_by=owner.id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    attempt = uuid.uuid4()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"pc_{uuid.uuid4().hex[:12]}",
        source_format="copc",
        pointcloud_attempt_id=attempt,
        pointcloud_point_count=39_025_611,
        pointcloud_point_format=6,
        pointcloud_vertical_crs="NGF-IGN69 height",
    )
    test_db_session.add(dataset)
    await test_db_session.flush()
    test_db_session.add(
        DatasetAsset(
            dataset_id=dataset.id,
            key=POINTCLOUD_ASSET_KEY,
            href=pointcloud_attempt_key(dataset.id, attempt),
            media_type=POINTCLOUD_MEDIA_TYPE,
            size_bytes=_FILE_BYTES,
        )
    )
    await test_db_session.commit()
    await test_db_session.refresh(dataset, ["record"])
    record_id, owner_id = record.id, owner.id
    yield dataset
    # A committed point cloud row blocks every later downgrade past 0070 in
    # this worker's database (see tests/alembic_helpers.py).
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await test_db_session.execute(
        text("DELETE FROM catalog.users WHERE id = :id"), {"id": owner_id}
    )
    await test_db_session.commit()


@pytest.fixture(params=["local", "s3"])
def storage(request, tmp_path, monkeypatch):
    """The local adapter, or the S3 adapter against a moto bucket."""
    if request.param == "local":
        yield LocalStorageProvider(base_dir=str(tmp_path))
        return
    credential = uuid.uuid4().hex
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, credential)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="copc")
        yield S3StorageProvider(
            bucket="copc",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )


async def test_delete_reaps_every_attempt_and_the_pointer(
    client: AsyncClient, admin_auth_header: dict, test_db_session, pointcloud, storage
) -> None:
    """Deleting a point cloud empties its prefix and drops its pointer row, and nothing else."""
    prefix = pointcloud_prefix(pointcloud.id)
    attempts = [f"{prefix}a1/data.copc.laz", f"{prefix}a2/data.copc.laz"]
    neighbour = f"{pointcloud_prefix(uuid.uuid4())}a1/data.copc.laz"
    for key in (*attempts, neighbour):
        await storage.put(key, b"LASF")

    with patch("app.platform.storage.provider.get_storage", return_value=storage):
        resp = await client.request(
            "DELETE",
            f"/datasets/{pointcloud.id}",
            json={"confirm_title": pointcloud.record.title},
            headers=admin_auth_header,
        )

    assert resp.status_code == 204, resp.text
    assert await storage.list(prefix) == []
    assert await storage.exists(neighbour)
    pointer_rows = await test_db_session.execute(
        text("SELECT count(*) FROM catalog.dataset_assets WHERE dataset_id = :id"),
        {"id": pointcloud.id},
    )
    assert pointer_rows.scalar_one() == 0


async def test_quota_counts_the_point_cloud_file(test_db_session, pointcloud) -> None:
    """The owner's storage use is the point cloud file's size."""
    usage = await get_user_quota_usage(test_db_session, pointcloud.record.created_by)

    assert usage.bytes_used == _FILE_BYTES
    assert usage.dataset_count == 1


async def test_the_detail_response_carries_the_point_cloud_block(
    client: AsyncClient, admin_auth_header: dict, test_db_session, pointcloud
) -> None:
    """A point cloud's detail response has the block; a vector dataset's does not."""
    admin_id = await get_user_id(test_db_session, "admin")
    vector = await create_dataset(test_db_session, created_by=admin_id)

    pointcloud_resp = await client.get(
        f"/datasets/{pointcloud.id}", headers=admin_auth_header
    )
    vector_resp = await client.get(f"/datasets/{vector.id}", headers=admin_auth_header)

    assert pointcloud_resp.status_code == 200, pointcloud_resp.text
    assert pointcloud_resp.json()["pointcloud"] == {
        "url": f"/api{pointcloud_path(pointcloud.id, pointcloud.pointcloud_attempt_id)}",
        "size_bytes": _FILE_BYTES,
        "point_count": 39_025_611,
        "point_format": 6,
        "vertical_crs": "NGF-IGN69 height",
    }
    assert pointcloud_resp.json()["tileset"] is None
    assert "pointcloud" not in (pointcloud_resp.json()["stac_assets"] or {})
    assert vector_resp.status_code == 200, vector_resp.text
    assert vector_resp.json()["pointcloud"] is None


async def test_the_ogc_record_lists_the_point_cloud_file(
    client: AsyncClient, admin_auth_header: dict, pointcloud
) -> None:
    """The OGC record lists the served COPC file and its format, and OGC Features has no collection."""
    record = await client.get(
        f"/collections/datasets/items/{pointcloud.id}", headers=admin_auth_header
    )
    features = await client.get(
        f"/collections/{pointcloud.id}", headers=admin_auth_header
    )

    assert record.status_code == 200, record.text
    asset = record.json()["assets"][POINTCLOUD_ASSET_KEY]
    assert asset["href"].endswith(
        pointcloud_path(pointcloud.id, pointcloud.pointcloud_attempt_id)
    )
    assert asset["type"] == POINTCLOUD_MEDIA_TYPE
    assert asset["roles"] == ["data"]
    assert record.json()["properties"]["formats"] == [POINTCLOUD_MEDIA_TYPE]
    assert features.status_code == 404


async def test_the_feeds_publish_the_point_cloud_file_as_a_download(
    client: AsyncClient, admin_auth_header: dict, test_db_session, pointcloud
) -> None:
    """DCAT, GeoDCAT-AP and DCAT-US publish the served COPC file as a download, and no row is stored."""
    test_db_session.add(
        RecordContact(
            record_id=pointcloud.record_id,
            role="pointOfContact",
            name="LiDAR Team",
            email="lidar@example.com",
        )
    )
    await test_db_session.commit()
    url_suffix = pointcloud_path(pointcloud.id, pointcloud.pointcloud_attempt_id)

    dcat = await client.get(
        f"/datasets/{pointcloud.id}/dcat/", headers=admin_auth_header
    )
    geodcat = await client.get(
        f"/datasets/{pointcloud.id}/geodcat-ap/", headers=admin_auth_header
    )
    dcat_us = await client.get(
        f"/datasets/{pointcloud.id}/dcat-us/3.0/", headers=admin_auth_header
    )

    assert dcat.status_code == 200, dcat.text
    [dcat_dist] = dcat.json()["dcat:distribution"]
    assert dcat_dist["dcat:accessURL"].endswith(url_suffix)
    assert dcat_dist["dcat:mediaType"] == POINTCLOUD_MEDIA_TYPE
    assert geodcat.status_code == 200, geodcat.text
    [geodcat_dist] = geodcat.json()["dcat:distribution"]
    assert geodcat_dist["dcat:downloadURL"]["@id"].endswith(url_suffix)
    assert dcat_us.status_code == 200, dcat_us.text
    [dcat_us_dist] = dcat_us.json()["distribution"]
    assert dcat_us_dist["downloadURL"].endswith(url_suffix)
    stored = await test_db_session.execute(
        text("SELECT count(*) FROM catalog.record_distributions WHERE record_id = :id"),
        {"id": pointcloud.record_id},
    )
    assert stored.scalar_one() == 0


async def test_a_point_cloud_without_a_live_attempt_advertises_no_file(
    client: AsyncClient, admin_auth_header: dict, test_db_session, pointcloud
) -> None:
    """With no attempt on the dataset row, no surface names a file to fetch."""
    await test_db_session.execute(
        text("UPDATE catalog.datasets SET pointcloud_attempt_id = NULL WHERE id = :id"),
        {"id": pointcloud.id},
    )
    await test_db_session.commit()

    detail = await client.get(f"/datasets/{pointcloud.id}", headers=admin_auth_header)
    record = await client.get(
        f"/collections/datasets/items/{pointcloud.id}", headers=admin_auth_header
    )
    dcat = await client.get(
        f"/datasets/{pointcloud.id}/dcat/", headers=admin_auth_header
    )

    assert detail.status_code == record.status_code == dcat.status_code == 200
    assert detail.json()["pointcloud"]["url"] is None
    assert POINTCLOUD_ASSET_KEY not in record.json()["assets"]
    assert not dcat.json().get("dcat:distribution")


_DOORS = [
    pytest.param(
        "/reupload",
        {
            "files": {
                "file": ("tile.laz", b"LASF" + bytes(16), "application/octet-stream")
            }
        },
        id="multipart",
    ),
    pytest.param(
        "/reupload/service/preview",
        {
            "json": {
                "url": "https://example.com/wfs",
                "service_type": "wfs",
                "layer_name": "buildings",
            }
        },
        id="service-preview",
    ),
    pytest.param("/reupload/{job}/preview", {}, id="preview"),
    pytest.param("/reupload/{job}/commit", {"json": {}}, id="commit"),
    pytest.param(
        "/reupload/presigned",
        {"json": {"filename": "tile.laz", "file_size": 1024}},
        id="presigned",
    ),
    pytest.param(
        "/reupload/presigned/{job}/complete",
        {"json": {"parts": []}},
        id="presigned-complete",
    ),
]


@pytest.mark.parametrize(("door", "body"), _DOORS)
async def test_every_reupload_door_refuses_a_point_cloud(
    client: AsyncClient, admin_auth_header: dict, pointcloud, monkeypatch, door, body
) -> None:
    """Each re-upload door answers a point cloud with the point cloud 400."""
    # The presigned doors refuse any non-S3 deployment before reading the dataset.
    monkeypatch.setattr(settings, "storage_provider", "s3")
    path = f"/datasets/{pointcloud.id}" + door.format(job=uuid.uuid4())

    resp = await client.post(path, headers=admin_auth_header, **body)

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "pointcloud_reupload_unsupported"
    assert detail["message"].startswith("Point cloud datasets do not support reupload")


def _dataset_of(record_type: str) -> SimpleNamespace:
    return SimpleNamespace(record=SimpleNamespace(record_type=record_type))


@pytest.mark.parametrize(
    ("record_type", "code", "message"),
    [
        (
            "tiles3d_dataset",
            "tileset_reupload_unsupported",
            "3D Tiles datasets do not support reupload",
        ),
        (
            "pointcloud_dataset",
            "pointcloud_reupload_unsupported",
            "Point cloud datasets do not support reupload",
        ),
        (
            "hologram_dataset",
            "reupload_unsupported",
            "Datasets of this type do not support reupload",
        ),
    ],
)
def test_reupload_refuses_every_type_without_a_table_or_raster(
    record_type: str, code: str, message: str
) -> None:
    """A tileset keeps its refusal text; a point cloud and an unknown type are refused too."""
    with pytest.raises(HTTPException) as refused:
        _assert_compatible_record_type(_dataset_of(record_type), "data.zip")

    assert refused.value.status_code == 400
    assert refused.value.detail["code"] == code
    assert refused.value.detail["message"].startswith(message)


@pytest.mark.parametrize("record_type", ["vector_dataset", "table", "raster_dataset"])
def test_reupload_still_admits_table_and_raster_types(record_type: str) -> None:
    """The guard lets a vector, table or raster dataset through to its own checks."""
    filename = "data.tif" if record_type == "raster_dataset" else "data.zip"

    _assert_compatible_record_type(_dataset_of(record_type), filename)


def test_only_tilesets_and_point_clouds_lack_a_table_or_raster() -> None:
    """Among the known record types, exactly the two file-stored ones answer False."""
    assert {t for t in RECORD_TYPES if not is_table_or_raster_backed(t)} == {
        "tiles3d_dataset",
        "pointcloud_dataset",
    }
    assert not is_table_or_raster_backed("hologram_dataset")
    assert not is_table_or_raster_backed(None)


@pytest.mark.parametrize(
    "record_type", ["tiles3d_dataset", "pointcloud_dataset", "hologram_dataset"]
)
async def test_quality_scores_metadata_only_for_a_file_stored_type(
    test_db_session, pointcloud, record_type: str
) -> None:
    """A type with no table or raster is scored on its metadata alone, without touching a table."""
    score = await score_quality(
        test_db_session,
        pointcloud.table_name,
        [],
        record=pointcloud.record,
        record_type=record_type,
        geometry_type=None,
        srid=None,
    )

    assert score["geometry_validity"] is None
    assert score["attribute_completeness"] is None
    assert score["crs_defined"] is None
    assert score["overall"] == round(score["metadata_completeness"])


async def test_quality_scores_an_unflushed_record_as_vector_data(
    test_db_session, pointcloud
) -> None:
    """A record_type of None keeps the vector scoring it always had."""
    score = await score_quality(
        test_db_session,
        pointcloud.table_name,
        [],
        record=pointcloud.record,
        record_type=None,
        geometry_type=None,
        srid=None,
    )

    assert score["geometry_validity"] is not None
    assert score["attribute_completeness"] is not None
