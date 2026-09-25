"""A 3D Tiles archive imports by URL through the real door, fetch, checks and publish."""

from __future__ import annotations

import base64
import json
import logging
import socket
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import boto3
import httpx
import pytest
import structlog
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import select, text

import app.platform.storage.provider as storage_provider
from app.core.config import settings
from app.core.failure_reason import INTERNAL_FAILURE_REASON
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
from app.core.tiles3d import tileset_attempt_prefix, tileset_prefix
from app.platform.jobs.models import IngestJob
from app.platform.storage.s3 import S3StorageProvider
from app.processing.ingest import tasks_url_fetch
from app.processing.ingest.tasks import ingest_tileset
from app.processing.ingest.tileset import TILESET_UNPACKED_BYTES_FIELD
from tests._logging_state import configured_logging
from tests.factories import create_user
from tests.tiles3d_archives import tileset_json, zip_bytes

# Resolves public at submission and at connect. Nothing connects to it: the
# connection beneath the guard transport is stubbed.
ORIGIN = "files.example.test"
ORIGIN_IP = "93.184.216.34"
ARCHIVE_URL = f"https://{ORIGIN}/exports/campus.zip"
PRIVATE_HOST = "metadata.example.test"

_GLB = b"glTF" + bytes(60)
_B3DM = b"b3dm" + bytes(28)
_CHUNK = 64 * 1024
_MiB = 1024 * 1024


def campus_zip() -> bytes:
    """A tileset inside one top-level folder, the way most tools export it."""
    return zip_bytes(
        [
            ("campus/", b""),
            ("campus/tileset.json", tileset_json()),
            ("campus/0/0.glb", _GLB),
            ("campus/0/1.b3dm", _B3DM),
        ]
    )


def compressible_zip() -> bytes:
    """600 kB unpacked, about a quarter of that zipped."""
    digits = b"".join(f"{i:08d}".encode() for i in range(75_000))
    return zip_bytes([("tileset.json", tileset_json()), ("0/0.glb", digits)])


def refused_archive(case: str) -> bytes:
    if case == "zip_slip":
        return zip_bytes([("tileset.json", tileset_json()), ("../../escape.glb", _GLB)])
    if case == "no_tileset_json":
        return zip_bytes([("campus/0/0.glb", _GLB)])
    if case == "content_outside":
        document = json.loads(tileset_json())
        document["root"]["content"] = {"uri": "../../other-dataset/tileset.json"}
        return zip_bytes([("tileset.json", json.dumps(document).encode())])
    if case == "truncated":
        return campus_zip()[:-10]
    assert case == "over_unpacked_cap"
    return campus_zip()


# --- The origin, behind the real SSRF-safe client -------------------------


class _Body(httpx.AsyncByteStream):
    """A response body served in chunks, counting the bytes the client pulled."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = chunks
        self.pulled = 0

    async def __aiter__(self):
        for chunk in self._chunks:
            self.pulled += len(chunk)
            yield chunk


class Origin:
    """A remote server reached through the real ``make_safe_client``.

    Only DNS answers and the connection beneath the guard transport are
    stubbed, so the client, its IP pinning and its redirect hook run as shipped.
    ``resolved`` records the stubbed hosts looked up, and ``connections`` each
    connection as (pinned address, Host header).
    """

    def __init__(self, monkeypatch, respond, *, hosts: dict[str, str] | None = None):
        self.resolved: list[str] = []
        self.connections: list[tuple[str, str]] = []
        addresses = {ORIGIN: ORIGIN_IP, **(hosts or {})}
        real_getaddrinfo = socket.getaddrinfo

        def _getaddrinfo(host, port, *args, **kwargs):
            if host not in addresses:
                return real_getaddrinfo(host, port, *args, **kwargs)
            self.resolved.append(host)
            sockaddr = (addresses[host], port or 0)
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)
            ]

        async def _connect(transport, request: httpx.Request) -> httpx.Response:
            self.connections.append((request.url.host, request.headers["host"]))
            return await respond(request)

        monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _connect)


def serve(body: bytes):
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Body([body]))

    return respond


# --- Fixtures and the import steps ---------------------------------------


@pytest.fixture
async def uploader(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """An editor whose records and jobs are removed afterwards."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    yield headers, uuid.UUID(user_id)
    # A committed tiles3d row blocks the migration tests' downgrades past 0065.
    await test_db_session.rollback()
    params = {"user": user_id}
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE created_by = :user"), params
    )
    await test_db_session.execute(
        text("DELETE FROM catalog.ingest_jobs WHERE created_by = :user"), params
    )
    await test_db_session.commit()


@pytest.fixture
def deferred(monkeypatch) -> list:
    """Each task the doors defer, with its arguments, instead of the queue."""
    calls: list = []

    async def _defer(task, /, **kwargs):
        calls.append((task, kwargs))

    for target in (
        "app.core.db.tenant_session.defer_async_with_tenant",
        "app.processing.ingest.service.defer_async_with_tenant",
        "app.processing.embeddings.helpers.defer_async_with_tenant",
    ):
        monkeypatch.setattr(target, _defer)
    return calls


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


def take(deferred: list, task) -> dict:
    """The arguments of the one deferral of ``task``, removed from the list."""
    matches = [kwargs for queued, kwargs in deferred if queued is task]
    assert len(matches) == 1, [queued for queued, _ in deferred]
    deferred[:] = [
        (queued, kwargs) for queued, kwargs in deferred if queued is not task
    ]
    return matches[0]


async def submit(client: AsyncClient, headers: dict, url: str, **fields):
    return await client.post(
        "/ingest/upload/url",
        json={"url": url, "kind": "tiles3d", **fields},
        headers=headers,
    )


async def download(deferred: list) -> None:
    """Run the queued download the way the worker does."""
    await tasks_url_fetch.fetch_url.func(
        None, **take(deferred, tasks_url_fetch.fetch_url)
    )


async def import_url(
    client, headers, deferred, url: str = ARCHIVE_URL, **fields
) -> str:
    """Submit a tileset URL and run its download; returns the job id."""
    submitted = await submit(client, headers, url, **fields)
    assert submitted.status_code == 201, submitted.text
    await download(deferred)
    return submitted.json()["job_id"]


async def upload(
    client: AsyncClient, headers: dict, data: bytes, filename="campus.zip"
):
    return await client.post(
        "/ingest/upload",
        files={"file": (filename, data, "application/zip")},
        data={"kind": "tiles3d"},
        headers=headers,
    )


async def commit(client: AsyncClient, headers: dict, job_id: str):
    return await client.post(
        f"/ingest/commit/{job_id}",
        json={"title": "Campus", "visibility": "public"},
        headers=headers,
    )


async def load_job(session, job_id) -> IngestJob:
    session.expire_all()
    return (
        await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(str(job_id)))
        )
    ).scalar_one()


async def job_ids_of(session, user_id: uuid.UUID) -> list[uuid.UUID]:
    session.expire_all()
    rows = await session.execute(
        select(IngestJob.id).where(IngestJob.created_by == user_id)
    )
    return list(rows.scalars())


def staged_files() -> list[Path]:
    return [p for p in Path(settings.upload_staging_dir).iterdir() if p.is_file()]


@contextmanager
def _gdal_unreachable(monkeypatch):
    reached: list[str] = []

    async def _subprocess(*args, **kwargs):
        reached.append("a GDAL subprocess")
        raise AssertionError("a GDAL subprocess reached")

    def _rasterio_open(*args, **kwargs):
        reached.append("rasterio.open")
        raise AssertionError("rasterio.open reached")

    monkeypatch.setattr(
        "app.processing.ingest.ogr.asyncio.create_subprocess_exec", _subprocess
    )
    monkeypatch.setattr("rasterio.open", _rasterio_open)
    yield reached


def _quota(cap: int):
    return patch(
        "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
        new=AsyncMock(return_value=cap),
    )


# --- The import ----------------------------------------------------------


@pytest.mark.parametrize("storage", ["local", "s3"])
async def test_a_tileset_archive_imports_by_url_and_publishes(
    request,
    client: AsyncClient,
    test_db_session,
    uploader,
    deferred,
    monkeypatch,
    storage,
) -> None:
    """A URL import previews like the upload door's and publishes without GDAL."""
    if storage == "s3":
        request.getfixturevalue("s3_storage")
    headers, _ = uploader
    origin = Origin(monkeypatch, serve(campus_zip()))

    with _gdal_unreachable(monkeypatch) as reached:
        job_id = await import_url(client, headers, deferred)
        staged = await load_job(test_db_session, job_id)
        assert staged.status == "pending", staged.error_message
        staged_metadata = staged.user_metadata
        uploaded = await upload(client, headers, campus_zip())
        assert uploaded.status_code == 201, uploaded.text
        upload_job_id = uploaded.json()["job_id"]
        upload_metadata = (await load_job(test_db_session, upload_job_id)).user_metadata
        assert staged_metadata["file_type"] == "tiles3d"
        assert (
            staged_metadata[TILESET_UNPACKED_BYTES_FIELD]
            == upload_metadata[TILESET_UNPACKED_BYTES_FIELD]
        )

        previewed = await client.post(f"/ingest/preview/{job_id}", headers=headers)
        upload_preview = await client.post(
            f"/ingest/preview/{upload_job_id}", headers=headers
        )
        assert previewed.status_code == 200, previewed.text
        assert {**previewed.json(), "job_id": None} == {
            **upload_preview.json(),
            "job_id": None,
        }

        committed = await commit(client, headers, job_id)
        assert committed.status_code == 202, committed.text
        await ingest_tileset.func(**take(deferred, ingest_tileset))

    assert reached == []
    assert origin.connections == [(ORIGIN_IP, ORIGIN)]
    job = await load_job(test_db_session, job_id)
    assert job.status == "complete", job.error_message
    attempt = tileset_attempt_prefix(job.dataset_id, job.attempt_id)
    stored = storage_provider.get_storage()
    assert sorted(await stored.list(tileset_prefix(job.dataset_id))) == [
        f"{attempt}0/0.glb",
        f"{attempt}0/1.b3dm",
        f"{attempt}tileset.json",
    ]
    assert await stored.get(f"{attempt}0/0.glb") == _GLB
    if storage == "s3":
        assert await stored.list(f"staging/{job_id}/") == []
    assert not Path(settings.upload_staging_dir, f"{job_id}_campus.zip").exists()


@pytest.mark.parametrize(
    "case",
    [
        "zip_slip",
        "no_tileset_json",
        "content_outside",
        "truncated",
        "over_unpacked_cap",
    ],
)
async def test_a_refused_archive_fails_with_the_upload_doors_reason(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch, case
) -> None:
    """The job stores the multipart door's refusal and keeps no staged bytes."""
    if case == "over_unpacked_cap":
        monkeypatch.setattr(settings, "max_tileset_unpacked_mb", 0)
    headers, user_id = uploader
    data = refused_archive(case)

    uploaded = await upload(client, headers, data)
    assert uploaded.status_code == 422, uploaded.text
    (upload_job_id,) = await job_ids_of(test_db_session, user_id)
    upload_reason = (await load_job(test_db_session, upload_job_id)).error_message

    Origin(monkeypatch, serve(data))
    job = await load_job(test_db_session, await import_url(client, headers, deferred))

    assert job.status == "failed"
    assert job.error_message == upload_reason
    assert job.error_message != INTERNAL_FAILURE_REASON
    assert TILESET_UNPACKED_BYTES_FIELD not in job.user_metadata
    assert staged_files() == []
    assert await storage_provider.get_storage().list("tiles3d/") == []


async def test_a_refused_archive_is_never_copied_to_object_storage(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch, s3_storage
) -> None:
    """On S3 staging the checks run before the staging put, which only a passing archive gets."""
    headers, _ = uploader
    puts: list[str] = []
    real_put = tasks_url_fetch._put_staging_object

    async def _recording_put(s3_key, local_dest):
        puts.append(s3_key)
        await real_put(s3_key, local_dest)

    monkeypatch.setattr(tasks_url_fetch, "_put_staging_object", _recording_put)

    Origin(monkeypatch, serve(refused_archive("zip_slip")))
    refused = await load_job(
        test_db_session, await import_url(client, headers, deferred)
    )
    assert (refused.status, puts) == ("failed", [])
    assert await s3_storage.list(f"staging/{refused.id}/") == []

    Origin(monkeypatch, serve(campus_zip()))
    staged = await load_job(
        test_db_session, await import_url(client, headers, deferred)
    )
    assert staged.status == "pending", staged.error_message
    assert puts == [f"staging/{staged.id}/campus.zip"]


@pytest.mark.parametrize(
    ("url", "filename"),
    [
        (f"https://{ORIGIN}/tiles/tileset.json", None),
        (f"https://{ORIGIN}/tiles/campus.gpkg", None),
        (f"https://{ORIGIN}/download?id=7", "tileset.json"),
    ],
)
async def test_a_tileset_url_must_name_an_archive(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch, url, filename
) -> None:
    """A name that is not an archive gets the upload door's 422, before DNS or a job."""
    headers, user_id = uploader
    origin = Origin(monkeypatch, serve(b""))
    fields = {"filename": filename} if filename else {}

    refused = await submit(client, headers, url, **fields)
    name = filename or url.rsplit("/", 1)[1]
    uploaded = await upload(client, headers, b"{}", filename=name)

    assert refused.status_code == 422, refused.text
    assert refused.json() == uploaded.json()
    assert origin.resolved == []
    assert await job_ids_of(test_db_session, user_id) == []
    assert deferred == []


async def test_a_3tz_url_without_the_tileset_kind_is_refused(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch
) -> None:
    """A .3tz named without kind=tiles3d gets the upload door's 422, before DNS or a job."""
    headers, user_id = uploader
    origin = Origin(monkeypatch, serve(campus_zip()))

    refused = await client.post(
        "/ingest/upload/url",
        json={"url": f"https://{ORIGIN}/exports/campus.3tz"},
        headers=headers,
    )
    uploaded = await client.post(
        "/ingest/upload",
        files={"file": ("campus.3tz", campus_zip(), "application/zip")},
        headers=headers,
    )

    assert refused.status_code == 422, refused.text
    assert refused.json() == uploaded.json()
    assert origin.resolved == []
    assert await job_ids_of(test_db_session, user_id) == []
    assert deferred == []


async def test_a_3tz_url_with_the_tileset_kind_stages_as_a_tileset(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch
) -> None:
    """A .3tz named with kind=tiles3d stages as a tileset, as a .zip does."""
    headers, _ = uploader
    Origin(monkeypatch, serve(campus_zip()))

    job_id = await import_url(
        client, headers, deferred, f"https://{ORIGIN}/exports/campus.3tz"
    )

    job = await load_job(test_db_session, job_id)
    assert job.status == "pending", job.error_message
    assert job.user_metadata["file_type"] == "tiles3d"
    assert TILESET_UNPACKED_BYTES_FIELD in job.user_metadata


# --- Rule 2: every hop through the safe client ---------------------------


async def test_a_redirect_to_a_private_address_fails_the_import(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch
) -> None:
    """The redirect hook refuses the hop, so nothing connects to the private host."""
    headers, _ = uploader

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == ORIGIN:
            location = f"http://{PRIVATE_HOST}/latest/campus.zip"
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200, stream=_Body([campus_zip()]))

    origin = Origin(monkeypatch, respond, hosts={PRIVATE_HOST: "169.254.169.254"})
    job = await load_job(test_db_session, await import_url(client, headers, deferred))

    assert origin.connections == [(ORIGIN_IP, ORIGIN)]
    assert job.status == "failed"
    assert (
        job.error_message == "URLs targeting private/internal networks are not allowed"
    )
    assert staged_files() == []


async def test_the_door_refuses_a_private_tileset_url_before_any_job(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch
) -> None:
    """The submission gate still runs for a tileset URL."""
    headers, user_id = uploader
    origin = Origin(monkeypatch, serve(campus_zip()), hosts={PRIVATE_HOST: "10.0.0.7"})

    refused = await submit(client, headers, f"https://{PRIVATE_HOST}/campus.zip")

    assert refused.status_code == 400, refused.text
    assert await job_ids_of(test_db_session, user_id) == []
    assert (deferred, origin.connections) == ([], [])


# --- Credentials in the URL ----------------------------------------------


class _Lines(logging.Handler):
    """Every line the production pipeline renders for the root logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@contextmanager
def captured_logs():
    """Yield the raw structlog events and the lines the production pipeline renders."""
    events: list[str] = []

    def _record(logger, method_name, event_dict):
        events.append(json.dumps(event_dict, default=str))
        return event_dict

    with configured_logging(json_logs=True, log_level="DEBUG", production=True):
        structlog.configure(processors=[_record, *structlog.get_config()["processors"]])
        root = logging.getLogger()
        lines = _Lines()
        lines.setFormatter(root.handlers[0].formatter)
        root.addHandler(lines)
        try:
            yield events, lines.lines
        finally:
            root.removeHandler(lines)


_ROW_QUERIES = {
    "job": "SELECT row_to_json(t)::text FROM catalog.ingest_jobs t WHERE t.id = :id",
    "dataset": "SELECT row_to_json(t)::text FROM catalog.datasets t WHERE t.id = :id",
    "record": "SELECT row_to_json(t)::text FROM catalog.records t WHERE t.id = :id",
    "assets": (
        "SELECT coalesce(json_agg(t)::text, '') FROM catalog.dataset_assets t "
        "WHERE t.dataset_id = :id"
    ),
}


async def _row_text(session, query: str, row_id) -> str:
    return (
        await session.execute(text(_ROW_QUERIES[query]), {"id": row_id})
    ).scalar_one()


@pytest.mark.parametrize("outcome", ["published", "refused"])
async def test_url_credentials_reach_no_row_log_or_dataset(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch, outcome
) -> None:
    """Userinfo and a presigned signature never land in a row or a log line."""
    headers, _ = uploader
    user, password, credential, token, signature = (uuid.uuid4().hex for _ in range(5))
    basic = base64.b64encode(f"{user}:{password}".encode()).decode()
    url = (
        f"https://{user}:{password}@{ORIGIN}/exports/campus.zip"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        f"&X-Amz-Credential={credential}%2F20260924%2Fus-east-1%2Fs3%2Faws4_request"
        "&X-Amz-Date=20260924T000000Z&X-Amz-Expires=900&X-Amz-SignedHeaders=host"
        f"&X-Amz-Security-Token={token}&X-Amz-Signature={signature}"
    )
    body = campus_zip() if outcome == "published" else refused_archive("zip_slip")
    fetched: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        fetched.append(request)
        return httpx.Response(200, stream=_Body([body]))

    Origin(monkeypatch, respond)
    with captured_logs() as (events, lines):
        submitted = await submit(client, headers, url)
        assert submitted.status_code == 201, submitted.text
        job_id = submitted.json()["job_id"]
        # The queued download's arguments are the URL's one carrier.
        assert deferred[0][1]["url"] == url
        await download(deferred)
        if outcome == "published":
            assert (await commit(client, headers, job_id)).status_code == 202
            await ingest_tileset.func(**take(deferred, ingest_tileset))

    # The download itself carried every credential.
    assert signature in str(fetched[0].url)
    assert fetched[0].headers["authorization"] == f"Basic {basic}"
    job = await load_job(test_db_session, job_id)
    assert job.status == ("complete" if outcome == "published" else "failed")
    rows = [await _row_text(test_db_session, "job", job.id)]
    if outcome == "published":
        dataset = await _row_text(test_db_session, "dataset", job.dataset_id)
        rows += [
            dataset,
            await _row_text(
                test_db_session, "record", json.loads(dataset)["record_id"]
            ),
            await _row_text(test_db_session, "assets", job.dataset_id),
        ]
    assert events and lines
    for secret in (user, password, basic, credential, token, signature):
        assert not [row for row in rows if secret in row]
        assert not [event for event in events if secret in event]
        assert not [line for line in lines if secret in line]


# --- Size -----------------------------------------------------------------


def _repeat(total: int):
    chunk = b"\x00" * _CHUNK
    for _ in range(total // _CHUNK):
        yield chunk


@pytest.mark.parametrize("shape", ["lying_length", "no_length", "declared_over"])
async def test_an_origin_past_the_download_cap_is_cut_off(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch, shape
) -> None:
    """A dishonest or endless body stops at the cap, and nothing stays staged."""
    headers, _ = uploader
    monkeypatch.setattr(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
    body = _Body(_repeat(16 * _MiB))
    declared = {"lying_length": "100", "declared_over": str(2 * _MiB)}.get(shape)

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": declared} if declared else {},
            stream=body,
        )

    Origin(monkeypatch, respond)
    job = await load_job(test_db_session, await import_url(client, headers, deferred))

    assert job.status == "failed"
    assert "exceeds the maximum allowed size" in job.error_message
    if shape == "declared_over":
        assert body.pulled == 0
    else:
        assert _MiB < body.pulled <= _MiB + 2 * _CHUNK
    assert staged_files() == []


@pytest.mark.parametrize("storage", ["local", "s3"])
async def test_the_unpacked_total_is_charged_against_the_quota(
    request,
    client: AsyncClient,
    test_db_session,
    uploader,
    deferred,
    monkeypatch,
    storage,
) -> None:
    """An archive under the quota that unpacks past it fails, its staged copies gone."""
    s3 = request.getfixturevalue("s3_storage") if storage == "s3" else None
    headers, _ = uploader
    data = compressible_zip()
    Origin(monkeypatch, serve(data))

    with _quota(400_000):
        job_id = await import_url(client, headers, deferred)

    assert len(data) < 400_000
    job = await load_job(test_db_session, job_id)
    assert job.status == "failed"
    assert job.error_message.startswith("Storage quota exceeded")
    assert staged_files() == []
    if s3 is not None:
        assert await s3.list(f"staging/{job_id}/") == []


# --- Cancel and access control -------------------------------------------


async def test_a_cancel_during_the_download_keeps_the_job_cancelled(
    client: AsyncClient, test_db_session, uploader, deferred, monkeypatch
) -> None:
    """The owner's cancel mid-transfer stands, with no tileset facts and nothing staged."""
    headers, _ = uploader
    data = campus_zip()
    cancelled: list[int] = []

    class _CancelMidway(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield data[: len(data) // 2]
            response = await client.post(f"/jobs/{job_id}/cancel", headers=headers)
            cancelled.append(response.status_code)
            yield data[len(data) // 2 :]

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CancelMidway())

    Origin(monkeypatch, respond)
    submitted = await submit(client, headers, ARCHIVE_URL)
    assert submitted.status_code == 201, submitted.text
    job_id = submitted.json()["job_id"]
    await download(deferred)

    job = await load_job(test_db_session, job_id)
    assert cancelled == [200]
    assert (job.status, job.error_message) == ("cancelled", "Cancelled by user")
    assert TILESET_UNPACKED_BYTES_FIELD not in job.user_metadata
    assert staged_files() == []


async def test_the_door_keeps_its_permission_and_ownership_checks(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    uploader,
    deferred,
    monkeypatch,
) -> None:
    """A viewer cannot submit a tileset URL, and another editor cannot reach the job."""
    headers, _ = uploader
    Origin(monkeypatch, serve(campus_zip()))
    viewer_headers, viewer_id = await create_user(client, admin_auth_header, "viewer")

    refused = await submit(client, viewer_headers, ARCHIVE_URL)

    assert refused.status_code == 403, refused.text
    assert await job_ids_of(test_db_session, uuid.UUID(viewer_id)) == []
    assert deferred == []

    job_id = await import_url(client, headers, deferred)
    other_headers, _ = await create_user(client, admin_auth_header, "editor")
    previewed = await client.post(f"/ingest/preview/{job_id}", headers=other_headers)
    committed = await commit(client, other_headers, job_id)

    assert (previewed.status_code, committed.status_code) == (403, 403)
    assert (await load_job(test_db_session, job_id)).status == "pending"
