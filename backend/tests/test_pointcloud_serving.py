"""The point cloud route serves only a live attempt's COPC file, by range and sandboxed, and caches a granted read briefly."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import boto3
import jwt
import pytest
from cachetools import TLRUCache
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import event, select, text
from starlette.requests import Request
from structlog.testing import capture_logs

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.core.pointcloud import (
    POINTCLOUD_ASSET_KEY,
    POINTCLOUD_MEDIA_TYPE,
    pointcloud_attempt_key,
    pointcloud_prefix,
)
from app.modules.audit.models import AuditLog
from app.modules.auth import dependencies as auth_dependencies
from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.api import pointcloud_access
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.raster.models import DatasetAsset
from tests.factories import create_user, get_user_id
from tests.test_pooled_connection_release_1848 import (  # noqa: F401
    _holds_connection,
    request_sessions,
)

_ROUTE_MODULE = "app.modules.catalog.datasets.api.router_pointcloud"
_COPC = b"LASF" + bytes(range(256)) * 16


@pytest.fixture(autouse=True)
def _no_cached_grants():
    pointcloud_access._grants.clear()
    yield
    pointcloud_access._grants.clear()


class _SpyStorage:
    """A real provider that records every read the route asks it for."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.read: list[tuple] = []

    async def put(self, key: str, data: bytes) -> str:
        return await self.inner.put(key, data)

    def get_stream(self, key: str):
        self.read.append(("whole", key))
        return self.inner.get_stream(key)

    def get_range_stream(self, key: str, start: int, length: int):
        self.read.append(("range", key, start, length))
        return self.inner.get_range_stream(key, start, length)


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
async def grantee(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """A user holding a role of their own, which is removed afterwards."""
    headers, user_id = await create_user(client, admin_auth_header, "viewer")
    role = Role(name=f"copc-grant-{uuid.uuid4().hex[:8]}")
    test_db_session.add(role)
    await test_db_session.flush()
    test_db_session.add(UserRole(user_id=uuid.UUID(user_id), role_id=role.id))
    role_id = role.id
    await test_db_session.commit()
    yield headers, role_id
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.roles WHERE id = :id"), {"id": role_id}
    )
    await test_db_session.commit()


@pytest.fixture
async def make_pointcloud(test_db_session):
    """Commit point clouds with a pointer row on demand, and delete them afterwards."""
    record_ids: list[uuid.UUID] = []

    async def make(
        *,
        owner_id=None,
        visibility="public",
        href=None,
        pointer=True,
        size_bytes=len(_COPC),
        record_type="pointcloud_dataset",
    ) -> tuple[uuid.UUID, uuid.UUID]:
        if owner_id is None:
            owner_id = await get_user_id(test_db_session, "admin")
        record = Record(
            title=f"LiDAR tile {uuid.uuid4().hex[:8]}",
            record_type=record_type,
            visibility=visibility,
            record_status="published",
            created_by=owner_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        record_ids.append(record.id)
        attempt = uuid.uuid4()
        dataset = Dataset(
            record_id=record.id,
            table_name=f"pc_{uuid.uuid4().hex[:12]}",
            source_format="copc",
            pointcloud_attempt_id=attempt,
        )
        test_db_session.add(dataset)
        await test_db_session.flush()
        if pointer:
            test_db_session.add(
                DatasetAsset(
                    dataset_id=dataset.id,
                    key=POINTCLOUD_ASSET_KEY,
                    href=(href or pointcloud_attempt_key)(dataset.id, attempt),
                    media_type=POINTCLOUD_MEDIA_TYPE,
                    size_bytes=size_bytes,
                )
            )
        dataset_id = dataset.id
        await test_db_session.commit()
        return dataset_id, attempt

    yield make
    # A committed point cloud row blocks every later downgrade past 0070 in
    # this worker's database (see tests/alembic_helpers.py).
    await test_db_session.rollback()
    for record_id in record_ids:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
    await test_db_session.commit()


async def _published(make_pointcloud, storage, **kwargs) -> tuple[uuid.UUID, uuid.UUID]:
    dataset_id, attempt = await make_pointcloud(**kwargs)
    await storage.put(pointcloud_attempt_key(dataset_id, attempt), _COPC)
    return dataset_id, attempt


def _url(dataset_id: uuid.UUID, attempt: uuid.UUID, name: str = "data") -> str:
    return f"/datasets/{dataset_id}/copc/{attempt}/{name}.copc.laz"


def _assert_sandboxed(resp) -> None:
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert {"Authorization", "X-Api-Key"} <= {
        name.strip() for name in resp.headers["vary"].split(",")
    }
    assert resp.headers["cache-control"].startswith("private")


async def test_a_range_is_served_from_one_ranged_read(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """A byte range answers 206 with its window, read once, under the attempt's strong ETag."""
    dataset_id, attempt = await _published(make_pointcloud, storage)

    resp = await client.get(_url(dataset_id, attempt), headers={"Range": "bytes=4-99"})

    assert resp.status_code == 206
    assert resp.content == _COPC[4:100]
    assert resp.headers["content-range"] == f"bytes 4-99/{len(_COPC)}"
    assert resp.headers["content-length"] == "96"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["etag"] == f'"{attempt}"'
    assert resp.headers["content-type"] == POINTCLOUD_MEDIA_TYPE
    assert storage.read == [
        ("range", pointcloud_attempt_key(dataset_id, attempt), 4, 96)
    ]
    _assert_sandboxed(resp)


async def test_the_advertised_url_serves_the_file(
    client: AsyncClient, admin_auth_header: dict, make_pointcloud, storage
) -> None:
    """The dataset response's ``pointcloud.url`` is the route that serves the file."""
    dataset_id, attempt = await _published(make_pointcloud, storage)

    detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
    url = detail.json()["pointcloud"]["url"]
    resp = await client.get(url.removeprefix("/api"))

    assert url == f"/api{_url(dataset_id, attempt)}"
    assert resp.status_code == 200
    assert resp.content == _COPC


async def test_head_reads_nothing_and_reports_the_stored_size(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """HEAD answers with the pointer row's size and the ETag, and never reads storage."""
    dataset_id, attempt = await _published(make_pointcloud, storage)

    resp = await client.head(_url(dataset_id, attempt))

    assert resp.status_code == 200
    assert resp.headers["content-length"] == str(len(_COPC))
    assert resp.headers["etag"] == f'"{attempt}"'
    assert resp.content == b""
    assert storage.read == []


async def test_the_whole_file_is_served_byte_for_byte_uncompressed(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """A GET without Range answers 200 with the stored bytes, never gzip-encoded."""
    dataset_id, attempt = await _published(make_pointcloud, storage)

    resp = await client.get(
        _url(dataset_id, attempt), headers={"Accept-Encoding": "gzip"}
    )

    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == _COPC
    assert resp.headers["etag"] == f'"{attempt}"'


@pytest.mark.parametrize(
    "range_header",
    ["bytes=0--1", "bytes=100-99", "bytes=abc", f"bytes={len(_COPC)}-"],
    ids=["malformed", "reversed", "garbage", "past-the-end"],
)
async def test_an_invalid_or_unsatisfiable_range_is_refused_with_416(
    client: AsyncClient, make_pointcloud, storage, range_header: str
) -> None:
    """The route parses ranges strictly: 416 with the real size, and nothing read."""
    dataset_id, attempt = await _published(make_pointcloud, storage)

    resp = await client.get(_url(dataset_id, attempt), headers={"Range": range_header})

    assert resp.status_code == 416
    assert resp.headers["content-range"] == f"bytes */{len(_COPC)}"
    assert storage.read == []
    _assert_sandboxed(resp)


async def test_the_validators_are_the_attempt(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """If-None-Match on the attempt answers 304, If-Match on another 412, If-Range on another the whole file."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    url = _url(dataset_id, attempt)

    held = await client.get(url, headers={"If-None-Match": f'"{attempt}"'})
    changed = await client.get(url, headers={"If-Match": f'"{uuid.uuid4()}"'})
    stale_range = await client.get(
        url, headers={"Range": "bytes=0-9", "If-Range": f'"{uuid.uuid4()}"'}
    )

    assert held.status_code == 304
    assert held.headers["cache-control"] == "private, max-age=3600"
    assert changed.status_code == 412
    assert stale_range.status_code == 200
    assert stale_range.content == _COPC


async def test_only_the_live_attempt_under_its_stored_name_is_served(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """A stale attempt, another name and another dataset's attempt answer 404 before storage is read."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    other_id, other_attempt = await _published(make_pointcloud, storage)
    await storage.put(
        f"{pointcloud_prefix(dataset_id)}{uuid.uuid4()}/data.copc.laz", b"x"
    )

    refused = [
        await client.get(_url(dataset_id, uuid.uuid4())),
        await client.get(_url(dataset_id, attempt, name="other")),
        await client.get(_url(dataset_id, attempt, name="data.copc.laz")),
        await client.get(_url(dataset_id, other_attempt)),
        await client.get(_url(other_id, attempt)),
    ]

    assert [resp.status_code for resp in refused] == [404] * 5
    assert storage.read == []


async def test_only_a_point_cloud_dataset_is_served(
    client: AsyncClient, admin_auth_header: dict, make_pointcloud, storage
) -> None:
    """A tileset dataset answers 404 here even with a point cloud pointer, and storage is never read."""
    dataset_id, attempt = await _published(
        make_pointcloud, storage, record_type="tiles3d_dataset"
    )

    resp = await client.get(_url(dataset_id, attempt), headers=admin_auth_header)

    assert resp.status_code == 404
    assert storage.read == []


_CORRUPT_POINTERS = [
    pytest.param(lambda d, a: f"rasters/{d}/{a}/data.copc.laz", id="other-root"),
    pytest.param(
        lambda d, a: f"{pointcloud_prefix(uuid.uuid4())}{a}/data.copc.laz",
        id="other-dataset",
    ),
    pytest.param(lambda d, a: f"{pointcloud_prefix(d)}data.copc.laz", id="no-attempt"),
    pytest.param(
        lambda d, a: f"{pointcloud_prefix(d)}a1/data.copc.laz", id="not-a-uuid"
    ),
    pytest.param(
        lambda d, a: f"{pointcloud_prefix(d)}{a}/other.copc.laz", id="other-name"
    ),
    pytest.param(
        lambda d, a: f"{pointcloud_prefix(d)}../{a}/data.copc.laz", id="dot-dot"
    ),
]


@pytest.mark.parametrize("href", _CORRUPT_POINTERS)
async def test_a_corrupted_pointer_serves_nothing_and_logs(
    client: AsyncClient, make_pointcloud, storage, href
) -> None:
    """A pointer that isn't exactly one of the dataset's attempt objects is refused and logged."""
    dataset_id, attempt = await make_pointcloud(href=href)

    with capture_logs() as logs:
        resp = await client.get(_url(dataset_id, attempt))

    assert resp.status_code == 404
    assert storage.read == []
    assert [
        entry
        for entry in logs
        if entry["event"] == "pointcloud_pointer_malformed"
        and entry["dataset_id"] == str(dataset_id)
    ]


@pytest.mark.parametrize("size_bytes", [None, -1], ids=["no-size", "negative-size"])
async def test_a_pointer_without_a_usable_size_serves_nothing(
    client: AsyncClient, make_pointcloud, storage, size_bytes
) -> None:
    """The route trusts the pointer's size for HEAD and ranges, so a missing or negative one is 404."""
    dataset_id, attempt = await _published(
        make_pointcloud, storage, size_bytes=size_bytes
    )

    resp = await client.get(_url(dataset_id, attempt))

    assert resp.status_code == 404
    assert storage.read == []


async def test_a_point_cloud_without_a_pointer_serves_nothing(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """A point cloud whose pointer row is missing answers 404 without reading storage."""
    dataset_id, attempt = await make_pointcloud(pointer=False)

    resp = await client.get(_url(dataset_id, attempt))

    assert resp.status_code == 404
    assert storage.read == []


async def test_access_is_decided_before_any_storage_read(
    client: AsyncClient, viewer_auth_header: dict, make_pointcloud, storage, owner
) -> None:
    """A private point cloud is 404 to anonymous and to a user without a grant, 206 to its owner."""
    owner_headers, owner_id = owner
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner_id, visibility="private"
    )
    url = _url(dataset_id, attempt)

    anonymous = await client.get(url, headers={"Range": "bytes=0-9"})
    stranger = await client.get(
        url, headers={**viewer_auth_header, "Range": "bytes=0-9"}
    )
    assert anonymous.status_code == stranger.status_code == 404
    assert storage.read == []
    _assert_sandboxed(anonymous)
    _assert_sandboxed(stranger)

    mine = await client.get(url, headers={**owner_headers, "Range": "bytes=0-9"})
    assert mine.status_code == 206
    assert mine.content == _COPC[:10]


async def test_an_api_key_reads_a_private_file_by_header_or_query(
    client: AsyncClient, admin_auth_header: dict, make_pointcloud, storage, owner
) -> None:
    """The owner's API key opens a private file sent as a header or in the query."""
    owner_id = owner[1]
    created = await client.post(
        "/admin/api-keys/",
        json={"user_id": str(owner_id), "name": "copc reader"},
        headers=admin_auth_header,
    )
    assert created.status_code == 201
    key = created.json()["key"]
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner_id, visibility="private"
    )

    by_header = await client.get(_url(dataset_id, attempt), headers={"X-Api-Key": key})
    by_query = await client.get(_url(dataset_id, attempt), params={"api_key": key})

    assert by_header.status_code == by_query.status_code == 200
    assert by_header.content == by_query.content == _COPC


async def test_a_restricted_point_cloud_serves_a_grant_holder(
    client: AsyncClient,
    viewer_auth_header: dict,
    test_db_session,
    make_pointcloud,
    storage,
    grantee,
) -> None:
    """A restricted point cloud is 200 to a holder of a granted role and 404 to anyone else."""
    grantee_headers, role_id = grantee
    dataset_id, attempt = await _published(
        make_pointcloud, storage, visibility="restricted"
    )
    test_db_session.add(DatasetGrant(dataset_id=dataset_id, role_id=role_id))
    await test_db_session.commit()

    granted = await client.get(_url(dataset_id, attempt), headers=grantee_headers)
    stranger = await client.get(_url(dataset_id, attempt), headers=viewer_auth_header)

    assert granted.status_code == 200
    assert granted.content == _COPC
    assert stranger.status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": f"Bearer {uuid.uuid4().hex}"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"X-Api-Key": uuid.uuid4().hex},
    ],
    ids=["unknown-bearer", "other-scheme", "unknown-key"],
)
async def test_an_unresolvable_credential_is_a_sandboxed_401(
    client: AsyncClient, make_pointcloud, storage, headers: dict
) -> None:
    """A supplied credential that doesn't resolve is 401 on a public point cloud, never anonymous."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    served = await client.get(_url(dataset_id, attempt))
    assert served.status_code == 200, (
        "precondition: an anonymous read is served and cached"
    )

    resp = await client.get(_url(dataset_id, attempt), headers=headers)

    assert resp.status_code == 401
    assert resp.headers["cache-control"] == "private, no-store"
    _assert_sandboxed(resp)


async def test_a_download_token_is_not_a_credential(
    client: AsyncClient, make_pointcloud, storage, owner
) -> None:
    """A ``token`` query parameter doesn't open a private point cloud."""
    owner_headers, owner_id = owner
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner_id, visibility="private"
    )
    minted = await client.post(
        f"/auth/download-token/{dataset_id}", headers=owner_headers
    )
    assert minted.status_code == 200, minted.text

    resp = await client.get(
        _url(dataset_id, attempt), params={"token": minted.json()["token"]}
    )

    assert resp.status_code == 404
    assert storage.read == []


async def test_the_connection_is_released_before_storage_is_read(
    client: AsyncClient,
    make_pointcloud,
    storage,
    request_sessions,  # noqa: F811
) -> None:
    """Whether access was decided or cached, no transaction is open when the file starts to stream."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    held: list[bool] = []
    read = storage.get_range_stream

    def recording(key: str, start: int, length: int):
        held.append(_holds_connection(request_sessions))
        return read(key, start, length)

    storage.get_range_stream = recording
    decided = await client.get(
        _url(dataset_id, attempt), headers={"Range": "bytes=0-9"}
    )
    cached = await client.get(_url(dataset_id, attempt), headers={"Range": "bytes=0-9"})

    assert decided.status_code == cached.status_code == 206
    assert held == [False, False]


async def test_missing_and_forbidden_answer_alike(
    client: AsyncClient, make_pointcloud, storage, owner
) -> None:
    """A private point cloud and an unknown id answer the same 404, and a missing object 404 too."""
    private_id, private_attempt = await _published(
        make_pointcloud, storage, owner_id=owner[1], visibility="private"
    )
    unstored_id, unstored_attempt = await make_pointcloud()

    forbidden = await client.get(_url(private_id, private_attempt))
    unknown = await client.get(_url(uuid.uuid4(), uuid.uuid4()))
    unstored = await client.get(_url(unstored_id, unstored_attempt))

    assert forbidden.status_code == unknown.status_code == unstored.status_code == 404
    assert forbidden.json() == unknown.json()


async def test_every_answer_is_sandboxed_and_privately_cached(
    client: AsyncClient, make_pointcloud, storage, owner
) -> None:
    """The file is private for an hour; a 404 and a malformed id's 422 are private and uncached."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    private_id, private_attempt = await _published(
        make_pointcloud, storage, owner_id=owner[1], visibility="private"
    )

    whole = await client.get(_url(dataset_id, attempt))
    part = await client.get(_url(dataset_id, attempt), headers={"Range": "bytes=0-9"})
    forbidden = await client.get(_url(private_id, private_attempt))
    malformed = await client.get(
        f"/datasets/{dataset_id}/copc/not-a-uuid/data.copc.laz"
    )

    for resp in (whole, part):
        assert resp.headers["cache-control"] == "private, max-age=3600"
    assert malformed.status_code == 422
    for resp in (forbidden, malformed):
        assert resp.headers["cache-control"] == "private, no-store"
    for resp in (whole, part, forbidden, malformed):
        _assert_sandboxed(resp)


async def test_storage_errors_never_name_a_key_or_path(
    client: AsyncClient, make_pointcloud, storage, tmp_path
) -> None:
    """A missing object is 404, a failing store 502, and no body names the key or path."""
    missing_id, missing_attempt = await make_pointcloud()
    dataset_id, attempt = await _published(make_pointcloud, storage)

    missing = await client.get(_url(missing_id, missing_attempt))

    async def unreadable(key: str, start: int, length: int):
        raise OSError(f"{tmp_path}/{key} is unreadable")
        yield  # an async generator, like every provider's get_range_stream

    storage.inner.get_range_stream = unreadable
    failed = await client.get(_url(dataset_id, attempt), headers={"Range": "bytes=0-9"})

    assert missing.status_code == 404
    assert failed.status_code == 502
    for resp in (missing, failed):
        assert pointcloud_prefix(dataset_id) not in resp.text
        assert pointcloud_prefix(missing_id) not in resp.text
        assert str(tmp_path) not in resp.text
        _assert_sandboxed(resp)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_the_route_answers_get_and_head_only(
    client: AsyncClient, make_pointcloud, storage, method
) -> None:
    """Every method but GET and HEAD is refused."""
    dataset_id, attempt = await _published(make_pointcloud, storage)

    resp = await client.request(method, _url(dataset_id, attempt))

    assert resp.status_code == 405
    assert storage.read == []
    _assert_sandboxed(resp)


async def test_the_route_is_exempt_from_the_per_ip_limit(
    client: AsyncClient, make_pointcloud, storage, monkeypatch
) -> None:
    """With a one-per-second global limit, a burst of range reads is all served while another route refuses."""
    from app.platform import ratelimit

    dataset_id, attempt = await _published(make_pointcloud, storage)
    monkeypatch.setattr(ratelimit, "get_cached_global_rate_limit", lambda: 1)
    ratelimit.limiter.enabled = True
    ratelimit.limiter._storage.reset()
    try:
        reads = [
            (
                await client.get(
                    _url(dataset_id, attempt), headers={"Range": f"bytes={i}-{i}"}
                )
            ).status_code
            for i in range(5)
        ]
        others = [
            (await client.get(f"/datasets/{dataset_id}")).status_code for _ in range(3)
        ]
    finally:
        ratelimit.limiter.enabled = False
        ratelimit.limiter._storage.reset()

    assert reads == [206] * 5
    assert 429 in others, (
        "precondition: the limit is live for a route that isn't exempt"
    )


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
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="copc")
        provider = S3StorageProvider(
            bucket="copc",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )
        yield _install(provider, monkeypatch)


async def test_each_store_serves_ranges_and_misses_as_404(
    client: AsyncClient, make_pointcloud, any_storage
) -> None:
    """A range deep in a multi-chunk file arrives byte for byte, and a missing object is 404."""
    payload = bytes(range(256)) * (10 * 1024)
    dataset_id, attempt = await make_pointcloud(size_bytes=len(payload))
    await any_storage.put(pointcloud_attempt_key(dataset_id, attempt), payload)
    missing_id, missing_attempt = await make_pointcloud(size_bytes=len(payload))

    part = await client.get(
        _url(dataset_id, attempt), headers={"Range": "bytes=2000000-2100000"}
    )
    whole = await client.get(_url(dataset_id, attempt))
    missing = await client.get(
        _url(missing_id, missing_attempt), headers={"Range": "bytes=0-9"}
    )

    assert part.status_code == 206
    assert part.content == payload[2_000_000:2_100_001]
    assert whole.status_code == 200
    assert whole.content == payload
    assert missing.status_code == 404


class _Clock:
    """The grant cache's clock, moved by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    tick = _Clock()
    grants = TLRUCache(maxsize=16, ttu=pointcloud_access._grants.ttu, timer=tick)
    monkeypatch.setattr(pointcloud_access, "_grants", grants)
    monkeypatch.setattr(pointcloud_access, "time", SimpleNamespace(monotonic=tick))
    return tick


async def _audited(session, dataset_id: uuid.UUID) -> list[tuple]:
    rows = await session.execute(
        select(AuditLog.user_id, AuditLog.details)
        .where(
            AuditLog.action == "dataset.pointcloud_read",
            AuditLog.resource_id == dataset_id,
        )
        .order_by(AuditLog.created_at)
    )
    return [tuple(row) for row in rows]


async def _token(session, user_id: uuid.UUID, *, seconds: int) -> str:
    """A signed access token for ``user_id`` that expires in ``seconds``."""
    user = await session.get(User, user_id)
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "username": user.username,
            "jti": uuid.uuid4().hex,
            "token_version": user.token_version,
            "iat": now,
            "exp": now + timedelta(seconds=seconds),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


async def _api_key(client: AsyncClient, admin_auth_header: dict, user_id) -> str:
    created = await client.post(
        "/admin/api-keys/",
        json={"user_id": str(user_id), "name": "copc reader"},
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text
    return created.json()["key"]


async def test_a_cached_grant_serves_without_touching_the_database(
    client: AsyncClient, test_db_session, make_pointcloud, storage
) -> None:
    """After one granted read, further reads by the same caller run no SQL and write no audit row."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    url = _url(dataset_id, attempt)
    statements: list[str] = []

    def record(conn, cursor, statement, *args) -> None:
        # The test client warms every request's session with these two; the
        # app's own session opens no connection until a query needs one.
        if statement != "SELECT 1" and not statement.startswith(
            "SET LOCAL statement_timeout"
        ):
            statements.append(statement)

    engine = test_db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        decided = await client.get(url, headers={"Range": "bytes=0-9"})
        deciding = len(statements)
        hits = [
            (await client.get(url, headers={"Range": f"bytes={i}-{i + 9}"})).status_code
            for i in range(3)
        ]
        head = await client.head(url)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert decided.status_code == 206
    assert deciding > 0, "precondition: the listener sees the deciding read's queries"
    assert hits == [206] * 3
    assert head.status_code == 200
    assert statements[deciding:] == []
    assert await _audited(test_db_session, dataset_id) == [
        (None, {"attempt_id": str(attempt), "credential": "anonymous"})
    ]


async def test_each_credential_is_decided_and_audited_once(
    client: AsyncClient, test_db_session, make_pointcloud, storage, owner
) -> None:
    """Anonymous and signed-in readers each fill their own grant, one audit row apiece."""
    owner_headers, owner_id = owner
    dataset_id, attempt = await _published(make_pointcloud, storage)
    url = _url(dataset_id, attempt)

    for _ in range(3):
        assert (await client.get(url)).status_code == 200
        assert (await client.get(url, headers=owner_headers)).status_code == 200

    assert await _audited(test_db_session, dataset_id) == [
        (None, {"attempt_id": str(attempt), "credential": "anonymous"}),
        (owner_id, {"attempt_id": str(attempt), "credential": "authorization"}),
    ]


async def test_an_anonymous_grant_lives_thirty_seconds(
    client: AsyncClient, test_db_session, make_pointcloud, storage, clock
) -> None:
    """The cache answers for 30 s after a grant, and the next read is decided again."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    url = _url(dataset_id, attempt)

    assert (await client.get(url)).status_code == 200
    clock.now += 29.5
    assert (await client.get(url)).status_code == 200
    assert len(await _audited(test_db_session, dataset_id)) == 1

    clock.now += 1
    assert (await client.get(url)).status_code == 200
    assert len(await _audited(test_db_session, dataset_id)) == 2


@pytest.mark.parametrize("credential", ["token", "api_key"])
async def test_a_grant_never_outlives_its_credential(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    make_pointcloud,
    storage,
    owner,
    clock,
    credential: str,
) -> None:
    """A credential expiring in 10 s keeps its grant under 10 s, not the full 30 s."""
    owner_id = owner[1]
    if credential == "token":
        token = await _token(test_db_session, owner_id, seconds=10)
        headers = {"Authorization": f"Bearer {token}"}
    else:
        key = await _api_key(client, admin_auth_header, owner_id)
        await test_db_session.execute(
            text("UPDATE catalog.api_keys SET expires_at = :at WHERE user_id = :user"),
            {"at": datetime.now(UTC) + timedelta(seconds=10), "user": owner_id},
        )
        await test_db_session.commit()
        headers = {"X-Api-Key": key}
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner_id, visibility="private"
    )
    url = _url(dataset_id, attempt)

    assert (await client.get(url, headers=headers)).status_code == 200
    clock.now += 5
    assert (await client.get(url, headers=headers)).status_code == 200
    assert len(await _audited(test_db_session, dataset_id)) == 1

    clock.now += 6
    assert (await client.get(url, headers=headers)).status_code == 200
    assert len(await _audited(test_db_session, dataset_id)) == 2


async def test_a_refusal_is_never_cached(
    client: AsyncClient, test_db_session, make_pointcloud, storage, owner
) -> None:
    """A point cloud refused as private is served on the next read once it is public."""
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner[1], visibility="private"
    )
    url = _url(dataset_id, attempt)
    assert (await client.get(url)).status_code == 404

    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET visibility = 'public' WHERE id = "
            "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": dataset_id},
    )
    await test_db_session.commit()

    assert (await client.get(url)).status_code == 200


async def test_a_key_sent_with_an_authorization_header_is_decided_every_time(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    make_pointcloud,
    storage,
    owner,
) -> None:
    """Two credentials on one request are never cached, so each read is decided and audited."""
    owner_headers, owner_id = owner
    key = await _api_key(client, admin_auth_header, owner_id)
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner_id, visibility="private"
    )

    for _ in range(3):
        resp = await client.get(
            _url(dataset_id, attempt), headers={**owner_headers, "X-Api-Key": key}
        )
        assert resp.status_code == 200

    assert (
        await _audited(test_db_session, dataset_id)
        == [
            (
                owner_id,
                {"attempt_id": str(attempt), "credential": "api_key+authorization"},
            )
        ]
        * 3
    )


async def test_a_bearer_resolved_by_an_extension_is_decided_every_time(
    client: AsyncClient, test_db_session, make_pointcloud, storage, owner, monkeypatch
) -> None:
    """A bearer that isn't this service's JWT has no expiry the cache can trust, so it is never cached."""
    owner_id = owner[1]
    session_token = uuid.uuid4().hex

    class _Extension:
        async def resolve_identity_from_token(self, token, request, db):
            return await db.get(User, owner_id) if token == session_token else None

    monkeypatch.setattr(auth_dependencies, "get_identity_extension", _Extension)
    dataset_id, attempt = await _published(
        make_pointcloud, storage, owner_id=owner_id, visibility="private"
    )

    for _ in range(3):
        resp = await client.get(
            _url(dataset_id, attempt),
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200

    assert len(await _audited(test_db_session, dataset_id)) == 3


async def test_a_cached_grant_still_serves_only_the_stored_name(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """With a grant cached, another file name under the same attempt is still 404."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    assert (await client.get(_url(dataset_id, attempt))).status_code == 200
    storage.read.clear()

    other = await client.get(_url(dataset_id, attempt, name="other"))

    assert other.status_code == 404
    assert storage.read == []


async def test_a_replaced_file_is_decided_again(
    client: AsyncClient, test_db_session, make_pointcloud, storage
) -> None:
    """After a new attempt goes live, its URL serves the new bytes at once and the old URL is 404."""
    dataset_id, first = await _published(make_pointcloud, storage)
    assert (await client.get(_url(dataset_id, first))).status_code == 200

    second = uuid.uuid4()
    replacement = _COPC[::-1]
    await storage.put(pointcloud_attempt_key(dataset_id, second), replacement)
    await test_db_session.execute(
        text(
            "UPDATE catalog.dataset_assets SET href = :href, size_bytes = :size "
            "WHERE dataset_id = :id AND key = 'pointcloud'"
        ),
        {
            "href": pointcloud_attempt_key(dataset_id, second),
            "size": len(replacement),
            "id": dataset_id,
        },
    )
    await test_db_session.execute(
        text("UPDATE catalog.datasets SET pointcloud_attempt_id = :a WHERE id = :id"),
        {"a": second, "id": dataset_id},
    )
    await test_db_session.commit()

    moved = await client.get(_url(dataset_id, second))
    stale = await client.get(_url(dataset_id, first))

    assert moved.status_code == 200
    assert moved.content == replacement
    assert stale.status_code == 404


class _Touched(Exception):
    pass


class _Untouchable:
    """A session that fails the test on any use."""

    def __getattr__(self, name: str):
        raise _Touched(name)


async def test_another_tenant_never_shares_a_grant(
    client: AsyncClient, make_pointcloud, storage
) -> None:
    """A grant cached in one tenant answers there without the database, and is decided again in another."""
    dataset_id, attempt = await _published(make_pointcloud, storage)
    assert (await client.get(_url(dataset_id, attempt))).status_code == 200
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": _url(dataset_id, attempt),
            "headers": [],
            "query_string": b"",
            "client": ("203.0.113.9", 1),
        }
    )

    async def read():
        return await pointcloud_access.authorize_pointcloud_read(
            request,
            _Untouchable(),
            None,
            dataset_id=dataset_id,
            attempt_id=attempt,
            name="data",
        )

    assert (await read()).attempt_id == attempt
    tenant = current_tenant_var.set(str(uuid.uuid4()))
    try:
        with pytest.raises(_Touched):
            await read()
    finally:
        current_tenant_var.reset(tenant)
