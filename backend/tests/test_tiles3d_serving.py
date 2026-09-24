"""The tileset route serves only a published tileset's own files, sandboxed and privately cached."""

import uuid

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import text
from structlog.testing import capture_logs

from app.core.tiles3d import TILESET_ASSET_KEY, tileset_prefix
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.raster.models import DatasetAsset
from tests.factories import create_user, get_user_id

_ROUTE_MODULE = "app.modules.catalog.datasets.api.router_tiles3d"
_ROOT = b'{"asset": {"version": "1.1"}, "geometricError": 10}'


class _SpyStorage:
    """A real provider that records every key the route asks it to read."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.read: list[str] = []

    async def put(self, key: str, data: bytes) -> str:
        return await self.inner.put(key, data)

    def get_stream(self, key: str):
        self.read.append(key)
        return self.inner.get_stream(key)


def _install(provider, monkeypatch) -> _SpyStorage:
    spy = _SpyStorage(provider)
    monkeypatch.setattr(f"{_ROUTE_MODULE}.get_storage", lambda: spy)
    return spy


@pytest.fixture
def storage(tmp_path, monkeypatch) -> _SpyStorage:
    return _install(LocalStorageProvider(base_dir=str(tmp_path)), monkeypatch)


@pytest.fixture
async def owner(client: AsyncClient, admin_auth_header: dict):
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    return headers, uuid.UUID(user_id)


@pytest.fixture
async def make_tileset(test_db_session):
    """Commit datasets with a tileset pointer on demand, and delete them afterwards."""
    record_ids: list[uuid.UUID] = []

    async def make(
        *,
        owner_id=None,
        visibility="public",
        href=None,
        carrier=True,
        record_type="tiles3d_dataset",
    ):
        if owner_id is None:
            owner_id = await get_user_id(test_db_session, "admin")
        record = Record(
            title=f"Campus tileset {uuid.uuid4().hex[:8]}",
            record_type=record_type,
            visibility=visibility,
            record_status="published",
            created_by=owner_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        record_ids.append(record.id)
        dataset = Dataset(
            record_id=record.id,
            table_name=f"tiles3d_{uuid.uuid4().hex[:12]}",
            source_format="3dtiles",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()
        if carrier:
            pointer = href or (lambda d: f"{tileset_prefix(d)}a1/tileset.json")
            test_db_session.add(
                DatasetAsset(
                    dataset_id=dataset.id,
                    key=TILESET_ASSET_KEY,
                    href=pointer(dataset.id),
                    media_type="application/json",
                    size_bytes=len(_ROOT),
                )
            )
        dataset_id = dataset.id
        await test_db_session.commit()
        return dataset_id

    yield make
    # A committed tiles3d row blocks every later downgrade past 0065 in this
    # worker's database (see tests/alembic_helpers.py).
    await test_db_session.rollback()
    for record_id in record_ids:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
    await test_db_session.commit()


def _url(dataset_id: uuid.UUID, path: str) -> str:
    return f"/datasets/{dataset_id}/tiles3d/{path}"


def _assert_sandboxed(resp) -> None:
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert {"Authorization", "X-Api-Key"} <= {
        name.strip() for name in resp.headers["vary"].split(",")
    }
    assert resp.headers["cache-control"].startswith("private")


_ESCAPES = [
    pytest.param("%2e%2e/secret.json", id="dot-dot"),
    pytest.param("%252e%252e/secret.json", id="double-encoded"),
    pytest.param("%5c%2e%2e%5csecret.json", id="backslash"),
    pytest.param("a%5csecret.json", id="encoded-backslash"),
    pytest.param("%2Fsecret.json", id="absolute"),
    pytest.param("/secret.json", id="leading-slash"),
    pytest.param("%2e/tileset.json", id="dot"),
    pytest.param("sub//tileset.json", id="empty-segment"),
    pytest.param("tileset.json%00.png", id="nul"),
]


@pytest.mark.parametrize("path", _ESCAPES)
async def test_a_path_that_could_leave_the_attempt_reads_nothing(
    client: AsyncClient, make_tileset, storage, path
) -> None:
    """Each escape, as it arrives after decoding, is refused before storage is read."""
    dataset_id = await make_tileset()
    prefix = tileset_prefix(dataset_id)
    await storage.put(f"{prefix}a1/tileset.json", _ROOT)
    await storage.put(f"{prefix}secret.json", b"secret")

    resp = await client.get(_url(dataset_id, path))

    assert resp.status_code == 404
    assert storage.read == []
    assert b"secret" not in resp.content
    _assert_sandboxed(resp)


async def test_the_attempt_prefix_keeps_its_trailing_slash(
    client: AsyncClient, make_tileset, storage
) -> None:
    """Attempt a1 serves its own files and never reaches a sibling attempt a10."""
    dataset_id = await make_tileset()
    prefix = tileset_prefix(dataset_id)
    await storage.put(f"{prefix}a1/tileset.json", b"a1")
    await storage.put(f"{prefix}a10/tileset.json", b"a10")

    live = await client.get(_url(dataset_id, "tileset.json"))
    sibling = await client.get(_url(dataset_id, "0/tileset.json"))

    assert live.status_code == 200
    assert live.content == b"a1"
    assert sibling.status_code == 404
    assert b"a10" not in sibling.content


_CORRUPT_POINTERS = [
    pytest.param(lambda d: f"rasters/{d}/cog/tileset.json", id="other-root"),
    pytest.param(
        lambda d: f"{tileset_prefix(uuid.uuid4())}a1/tileset.json", id="other-dataset"
    ),
    pytest.param(lambda d: f"{tileset_prefix(d)}tileset.json", id="no-attempt"),
    pytest.param(lambda d: f"{tileset_prefix(d)}a1/sub/tileset.json", id="too-deep"),
    pytest.param(lambda d: f"{tileset_prefix(d)}../x/tileset.json", id="dot-dot"),
    pytest.param(lambda d: f"{tileset_prefix(d)}a1/other.json", id="not-the-entry"),
]


@pytest.mark.parametrize("href", _CORRUPT_POINTERS)
async def test_a_corrupted_pointer_serves_nothing_and_logs(
    client: AsyncClient, make_tileset, storage, href
) -> None:
    """A pointer outside the dataset's own attempt layout is refused and logged."""
    dataset_id = await make_tileset(href=href)

    with capture_logs() as logs:
        resp = await client.get(_url(dataset_id, "tileset.json"))

    assert resp.status_code == 404
    assert storage.read == []
    assert [
        entry
        for entry in logs
        if entry["event"] == "tileset_pointer_outside_prefix"
        and entry["dataset_id"] == str(dataset_id)
    ]


async def test_a_tileset_without_a_pointer_serves_nothing(
    client: AsyncClient, make_tileset, storage
) -> None:
    """A tileset whose pointer row is missing answers 404 without reading storage."""
    dataset_id = await make_tileset(carrier=False)

    resp = await client.get(_url(dataset_id, "tileset.json"))

    assert resp.status_code == 404
    assert storage.read == []


async def test_access_is_decided_before_any_storage_read(
    client: AsyncClient, viewer_auth_header: dict, make_tileset, storage, owner
) -> None:
    """A private tileset is 404 to anonymous and to a user without a grant, 200 to its owner."""
    owner_headers, owner_id = owner
    dataset_id = await make_tileset(owner_id=owner_id, visibility="private")
    await storage.put(f"{tileset_prefix(dataset_id)}a1/tileset.json", _ROOT)

    anonymous = await client.get(_url(dataset_id, "tileset.json"))
    stranger = await client.get(
        _url(dataset_id, "tileset.json"), headers=viewer_auth_header
    )
    assert anonymous.status_code == stranger.status_code == 404
    assert storage.read == []
    _assert_sandboxed(anonymous)
    _assert_sandboxed(stranger)

    mine = await client.get(_url(dataset_id, "tileset.json"), headers=owner_headers)
    assert mine.status_code == 200
    assert mine.content == _ROOT


async def test_missing_and_forbidden_answer_alike(
    client: AsyncClient, make_tileset, storage, owner
) -> None:
    """A missing file, a private tileset and an unknown id all answer 404."""
    public_id = await make_tileset()
    private_id = await make_tileset(owner_id=owner[1], visibility="private")

    missing = await client.get(_url(public_id, "tiles/0.glb"))
    forbidden = await client.get(_url(private_id, "tileset.json"))
    unknown = await client.get(_url(uuid.uuid4(), "tileset.json"))

    assert missing.status_code == forbidden.status_code == unknown.status_code == 404
    assert forbidden.json() == unknown.json()


async def test_only_a_tileset_dataset_is_served(
    client: AsyncClient, admin_auth_header: dict, make_tileset, storage
) -> None:
    """A raster dataset answers 404 here even with a tileset pointer, and storage is never read."""
    raster_id = await make_tileset(record_type="raster_dataset")
    await storage.put(f"{tileset_prefix(raster_id)}a1/tileset.json", _ROOT)
    await storage.put(f"rasters/{raster_id}/tileset.json", _ROOT)

    resp = await client.get(_url(raster_id, "tileset.json"), headers=admin_auth_header)

    assert resp.status_code == 404
    assert storage.read == []


_CONTENT_TYPES = [
    ("tileset.json", "application/json"),
    ("tiles/0.glb", "model/gltf-binary"),
    ("tiles/0.gltf", "model/gltf+json"),
    ("tiles/0.b3dm", "application/octet-stream"),
    ("tiles/0.pnts", "application/octet-stream"),
    ("tiles/0.bin", "application/octet-stream"),
    ("textures/a.png", "image/png"),
    ("textures/a.JPG", "image/jpeg"),
    ("textures/a.jpeg", "image/jpeg"),
    ("textures/a.webp", "image/webp"),
    ("textures/a.ktx2", "image/ktx2"),
    ("textures/a.svg", "application/octet-stream"),
    ("page.html", "application/octet-stream"),
    ("page.htm", "application/octet-stream"),
    ("page.xhtml", "application/octet-stream"),
    ("script.js", "application/octet-stream"),
    ("data.xml", "application/octet-stream"),
    ("README", "application/octet-stream"),
]


@pytest.mark.parametrize(("path", "content_type"), _CONTENT_TYPES)
async def test_only_tileset_formats_keep_their_type(
    client: AsyncClient, make_tileset, storage, path, content_type
) -> None:
    """3D Tiles, glTF and texture types pass; SVG, HTML, script and the rest are octet-stream."""
    dataset_id = await make_tileset()
    await storage.put(
        f"{tileset_prefix(dataset_id)}a1/{path}", b"<svg onload=alert(1)/>"
    )

    resp = await client.get(_url(dataset_id, path))

    assert resp.status_code == 200
    assert resp.headers["content-type"].split(";")[0] == content_type
    _assert_sandboxed(resp)


async def test_every_answer_is_privately_cached(
    client: AsyncClient, make_tileset, storage, owner
) -> None:
    """Tileset files, both kinds of 404 and a malformed id's 422 are private to the caller."""
    dataset_id = await make_tileset()
    private_id = await make_tileset(owner_id=owner[1], visibility="private")
    prefix = tileset_prefix(dataset_id)
    await storage.put(f"{prefix}a1/tileset.json", _ROOT)
    await storage.put(f"{prefix}a1/tiles/0.glb", b"glb")

    entry = await client.get(_url(dataset_id, "tileset.json"))
    content = await client.get(_url(dataset_id, "tiles/0.glb"))
    missing = await client.get(_url(dataset_id, "tiles/1.glb"))
    forbidden = await client.get(_url(private_id, "tileset.json"))
    malformed = await client.get("/datasets/not-a-uuid/tiles3d/tileset.json")

    assert entry.headers["cache-control"] == "private, max-age=60"
    assert content.headers["cache-control"] == "private, max-age=3600"
    assert malformed.status_code == 422
    for resp in (missing, forbidden, malformed):
        assert resp.headers["cache-control"] == "private, no-store"
    for resp in (entry, content, missing, forbidden, malformed):
        _assert_sandboxed(resp)


async def test_storage_errors_never_name_a_key_or_path(
    client: AsyncClient, make_tileset, storage, tmp_path
) -> None:
    """A missing or refused key is 404 and a failing store 502, and no body names the key."""
    dataset_id = await make_tileset()
    prefix = tileset_prefix(dataset_id)

    missing = await client.get(_url(dataset_id, "tiles/0.glb"))
    refused = await client.get(_url(dataset_id, "tiles/a..b.glb"))

    async def unreadable(key: str):
        raise OSError(f"{tmp_path}/{key} is unreadable")
        yield  # an async generator, like every provider's get_stream

    storage.inner.get_stream = unreadable
    failed = await client.get(_url(dataset_id, "tileset.json"))

    assert missing.status_code == refused.status_code == 404
    assert failed.status_code == 502
    for resp in (missing, refused, failed):
        assert prefix not in resp.text
        assert str(tmp_path) not in resp.text
        _assert_sandboxed(resp)


@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "PATCH", "DELETE"])
async def test_the_route_answers_get_only(
    client: AsyncClient, make_tileset, storage, method
) -> None:
    """Every method but GET is refused."""
    dataset_id = await make_tileset()

    resp = await client.request(method, _url(dataset_id, "tileset.json"))

    assert resp.status_code == 405
    assert storage.read == []
    _assert_sandboxed(resp)


@pytest.fixture(params=["local", "s3"])
def any_storage(request, tmp_path, monkeypatch):
    """The local adapter, or the S3 adapter against a moto bucket."""
    if request.param == "local":
        yield _install(LocalStorageProvider(base_dir=str(tmp_path)), monkeypatch)
        return
    credential = uuid.uuid4().hex
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, credential)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tiles3d")
        provider = S3StorageProvider(
            bucket="tiles3d",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )
        yield _install(provider, monkeypatch)


async def test_each_store_streams_a_file_whole_and_misses_as_404(
    client: AsyncClient, make_tileset, any_storage
) -> None:
    """A file larger than one storage chunk arrives byte for byte, and a missing one is 404."""
    dataset_id = await make_tileset()
    payload = bytes(range(256)) * (10 * 1024)
    await any_storage.put(f"{tileset_prefix(dataset_id)}a1/tiles/big.glb", payload)

    resp = await client.get(_url(dataset_id, "tiles/big.glb"))
    missing = await client.get(_url(dataset_id, "tiles/none.glb"))

    assert resp.status_code == 200
    assert resp.content == payload
    assert missing.status_code == 404
