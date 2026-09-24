"""A tiles3d dataset takes its own branch at delete, quota, the record, the response and re-upload."""

import uuid
from unittest.mock import patch

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import text

from app.core.config import settings
from app.core.tiles3d import TILESET_ASSET_KEY, tileset_prefix
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.quota.service import get_user_quota_usage
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.raster.models import DatasetAsset
from tests.factories import create_dataset, get_user_id

_UNPACKED_BYTES = 7_340_032


@pytest.fixture
async def tileset(test_db_session):
    """A published tileset whose pointer row names its second unpack attempt."""
    owner = User(username=f"tiles3d-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db_session.add(owner)
    await test_db_session.flush()
    record = Record(
        title=f"Campus tileset {uuid.uuid4().hex[:8]}",
        record_type="tiles3d_dataset",
        visibility="public",
        record_status="published",
        created_by=owner.id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"tiles3d_{uuid.uuid4().hex[:12]}",
        source_format="3dtiles",
    )
    test_db_session.add(dataset)
    await test_db_session.flush()
    test_db_session.add(
        DatasetAsset(
            dataset_id=dataset.id,
            key=TILESET_ASSET_KEY,
            href=f"{tileset_prefix(dataset.id)}a2/tileset.json",
            media_type="application/json",
            size_bytes=_UNPACKED_BYTES,
        )
    )
    await test_db_session.commit()
    await test_db_session.refresh(dataset, ["record"])
    record_id, owner_id = record.id, owner.id
    yield dataset
    # A committed tiles3d row blocks every later downgrade past 0065 in this
    # worker's database (see tests/alembic_helpers.py).
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
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tiles3d")
        yield S3StorageProvider(
            bucket="tiles3d",
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
        )


async def test_delete_reaps_every_attempt_and_the_pointer(
    client: AsyncClient, admin_auth_header: dict, test_db_session, tileset, storage
) -> None:
    """Deleting a tileset empties its prefix and drops its pointer row, and nothing else."""
    prefix = tileset_prefix(tileset.id)
    attempts = [f"{prefix}a1/tileset.json", f"{prefix}a2/tileset.json"]
    content = f"{prefix}a2/tiles/0/0/0.glb"
    neighbour = f"{tileset_prefix(uuid.uuid4())}a1/tileset.json"
    for key in (*attempts, content, neighbour):
        await storage.put(key, b"{}")

    with patch("app.platform.storage.provider.get_storage", return_value=storage):
        resp = await client.request(
            "DELETE",
            f"/datasets/{tileset.id}",
            json={"confirm_title": tileset.record.title},
            headers=admin_auth_header,
        )

    assert resp.status_code == 204, resp.text
    assert await storage.list(prefix) == []
    assert await storage.exists(neighbour)
    pointer_rows = await test_db_session.execute(
        text("SELECT count(*) FROM catalog.dataset_assets WHERE dataset_id = :id"),
        {"id": tileset.id},
    )
    assert pointer_rows.scalar_one() == 0


async def test_quota_counts_the_unpacked_tileset(test_db_session, tileset) -> None:
    """The owner's storage use is the tileset's unpacked size."""
    usage = await get_user_quota_usage(test_db_session, tileset.record.created_by)

    assert usage.bytes_used == _UNPACKED_BYTES
    assert usage.dataset_count == 1


async def test_the_detail_response_carries_the_tileset_block(
    client: AsyncClient, admin_auth_header: dict, test_db_session, tileset
) -> None:
    """A tileset's detail response has the block; a vector dataset's does not."""
    admin_id = await get_user_id(test_db_session, "admin")
    vector = await create_dataset(test_db_session, created_by=admin_id)

    tileset_resp = await client.get(
        f"/datasets/{tileset.id}", headers=admin_auth_header
    )
    vector_resp = await client.get(f"/datasets/{vector.id}", headers=admin_auth_header)

    assert tileset_resp.status_code == 200, tileset_resp.text
    assert tileset_resp.json()["tileset"] == {"size_bytes": _UNPACKED_BYTES}
    assert vector_resp.status_code == 200, vector_resp.text
    assert vector_resp.json()["tileset"] is None


async def test_the_ogc_record_lists_the_tileset_format_only(
    client: AsyncClient, admin_auth_header: dict, tileset
) -> None:
    """The OGC record lists the tileset's JSON format, and OGC Features has no collection."""
    record = await client.get(
        f"/collections/datasets/items/{tileset.id}", headers=admin_auth_header
    )
    features = await client.get(f"/collections/{tileset.id}", headers=admin_auth_header)

    assert record.status_code == 200, record.text
    assert record.json()["properties"]["formats"] == ["application/json"]
    assert features.status_code == 404


_DOORS = [
    pytest.param(
        "/reupload",
        {
            "files": {
                "file": ("campus.zip", b"PK\x05\x06" + bytes(18), "application/zip")
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
        {"json": {"filename": "campus.zip", "file_size": 1024}},
        id="presigned",
    ),
    pytest.param(
        "/reupload/presigned/{job}/complete",
        {"json": {"parts": []}},
        id="presigned-complete",
    ),
]


@pytest.mark.parametrize(("door", "body"), _DOORS)
async def test_every_reupload_door_refuses_a_tileset(
    client: AsyncClient, admin_auth_header: dict, tileset, monkeypatch, door, body
) -> None:
    """Each re-upload door answers a tileset with the 3D Tiles 400."""
    # The presigned doors refuse any non-S3 deployment before reading the dataset.
    monkeypatch.setattr(settings, "storage_provider", "s3")
    path = f"/datasets/{tileset.id}" + door.format(job=uuid.uuid4())

    resp = await client.post(path, headers=admin_auth_header, **body)

    assert resp.status_code == 400, resp.text
    assert "3D Tiles datasets do not support reupload" in resp.json()["detail"]
