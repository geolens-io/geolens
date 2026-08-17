"""fix(#1540) review P1: the S3 HEAD, over a socket, against a real bucket.

``test_cog_head_ranges_1528.py`` proves the route's intent through
``httpx.ASGITransport`` and a moto bucket. Neither can show the defect this
module is about, because moto does not verify SigV4 signatures at all — it
accepts a presigned URL for any HTTP method, so the redirect the route used to
send would have "worked" there.

Real S3 and real MinIO do not. The method is part of the SigV4 canonical
request, so a URL signed for ``get_object`` is not a URL you may HEAD.

MEASURED against MinIO RELEASE.2025-09-07T16-13-09Z, presigning through boto3
exactly as ``S3StorageProvider.generate_presigned_get_url`` does:

  presigned for get_object    GET  -> 200  content-length=4096  accept-ranges=bytes
                              HEAD -> 403  (no body: it is a HEAD)
  presigned for head_object   HEAD -> 200  content-length=4096
                              GET  -> 403  SignatureDoesNotMatch

The GET-on-a-head_object-URL row is the same rejection with a readable payload,
and it is what names the failure: ``SignatureDoesNotMatch``.

End to end through this route on the same MinIO, HEAD with redirects followed
the way curl -L and GDAL's /vsicurl/ follow them:

  before   302 -> 403.  The probe every /vsicurl/ open begins with fails, on
           every deployment that keeps its COGs in a bucket — which is the
           entire population fix(#1528) was written for.
  after    200, content-length = the object's real size, accept-ranges: bytes,
           in one hop with no redirect at all.

Requirements:
  - Docker database must be running (docker compose up db)
  - An S3-compatible endpoint. The compose stack ships one behind the cloud-dev
    profile (``docker compose --profile cloud-dev up -d minio``), or run a
    throwaway::

        docker run -d --name minio-1540 -p 127.0.0.1:9010:9000 \\
          -e MINIO_ROOT_USER=user -e MINIO_ROOT_PASSWORD=secretpw \\
          quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z server /data

  - Run with::

        set -a && source ../.env.test && set +a
        GEOLENS_TEST_S3_ENDPOINT=http://127.0.0.1:9010 \\
        GEOLENS_TEST_S3_ACCESS_KEY=user \\
        GEOLENS_TEST_S3_SECRET_KEY=secretpw \\
        uv run pytest tests/test_cog_s3_head_wire_1540.py -v

The endpoint is opt-in rather than assumed: the ``backend-test`` CI job has no
MinIO service (only ``backup-roundtrip`` does), so requiring one here would turn
a green suite red everywhere it is not provisioned. The always-running guard
against this regression is
``test_head_cog_on_s3_is_answered_from_object_metadata``; this module is how the
claim about real signature enforcement gets re-measured on demand.
"""

import asyncio
import os
import socket
import uuid

import pytest

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset

from tests.factories import get_user_id

_ENDPOINT = os.environ.get("GEOLENS_TEST_S3_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not _ENDPOINT,
    reason="set GEOLENS_TEST_S3_ENDPOINT to an S3-compatible endpoint (see module docstring)",
)

_BUCKET = os.environ.get("GEOLENS_TEST_S3_BUCKET", "geolens-cog-1540")
_COG_BYTES = bytes(range(256)) * 800  # 204_800 bytes


@pytest.fixture
def real_s3_storage(monkeypatch):
    """Point the storage singleton at the real endpoint, bucket created."""
    import app.platform.storage.provider as storage_provider_module
    from app.platform.storage.s3 import S3StorageProvider

    provider = S3StorageProvider(
        bucket=_BUCKET,
        endpoint=_ENDPOINT,
        region="us-east-1",
        access_key_id=os.environ.get("GEOLENS_TEST_S3_ACCESS_KEY"),
        secret_access_key=os.environ.get("GEOLENS_TEST_S3_SECRET_KEY"),
        allow_http=_ENDPOINT.startswith("http://"),
        addressing_style="path",
    )
    try:
        provider.client.create_bucket(Bucket=_BUCKET)
    except provider.client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except provider.client.exceptions.BucketAlreadyExists:
        pass

    monkeypatch.setattr(storage_provider_module, "_storage", provider)
    return provider


@pytest.fixture
async def s3_cog(client, test_db_session, real_s3_storage):
    """A public raster dataset whose COG bytes really live in the bucket."""
    from datetime import UTC, datetime, timedelta

    import jwt as _jwt

    from app.core.config import settings

    admin_id = await get_user_id(test_db_session, "admin")
    record = Record(
        title=f"S3 COG {uuid.uuid4().hex[:6]}",
        summary="COG for the fix(#1540) P1 wire test",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"s3_cog_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="probe.tif",
    )
    test_db_session.add(dataset)
    await test_db_session.flush()
    asset_uri = f"rasters/{dataset.id}/{uuid.uuid4().hex[:8]}/src.cog.tif"
    test_db_session.add(
        RasterAsset(dataset_id=dataset.id, asset_uri=asset_uri, storage_backend="s3")
    )
    await test_db_session.flush()
    await test_db_session.commit()

    await real_s3_storage.put(asset_uri, _COG_BYTES)

    # ?token= rather than a header: it is the lane a GDAL client can use, since
    # /vsicurl/ takes a URL and not an Authorization header.
    token = _jwt.encode(
        {
            "typ": "download",
            "scope": f"dataset:{dataset.id}",
            "exp": datetime.now(UTC) + timedelta(seconds=600),
            "iat": datetime.now(UTC),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return dataset.id, token


@pytest.fixture
async def uvicorn_url(client):
    """The real app on a real free port.

    Same shape as ``test_cog_vsicurl_1528.py``'s fixture: the ``client``
    fixture has already installed the DB override and the admin user, and
    uvicorn re-uses that same wired ``app``.
    """
    import uvicorn

    from app.api.main import app as fastapi_app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=port, log_level="error", lifespan="off"
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    else:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()
        pytest.fail("uvicorn server did not start within 5s")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()


async def test_head_on_an_s3_backed_cog_answers_200_over_the_wire(uvicorn_url, s3_cog):
    """A redirect-following client HEADs the route and gets a usable answer.

    ``follow_redirects=True`` is the point. Before fix(#1540) this returned a
    302, httpx re-issued the HEAD against the presigned URL exactly as curl -L
    and vsicurl do, and MinIO answered 403 because that URL is signed for GET.
    Nothing about that failure is visible without a client that follows and a
    bucket that checks signatures.
    """
    import httpx

    dataset_id, token = s3_cog
    url = f"{uvicorn_url}/datasets/{dataset_id}/download/cog?token={token}"

    async with httpx.AsyncClient(follow_redirects=True) as raw:
        head = await raw.head(url)

    chain = [r.status_code for r in head.history] + [head.status_code]
    assert 403 not in chain, (
        f"the HEAD chain was {chain}: a presigned get_object URL refuses HEAD "
        f"with 403, so this route must answer the probe itself."
    )
    assert head.status_code == 200, f"HEAD chain {chain}, expected a 200"
    assert head.history == [], (
        f"HEAD was redirected to {[r.headers.get('location') for r in head.history]}"
    )
    assert head.headers.get("content-length") == str(len(_COG_BYTES))
    assert head.headers.get("accept-ranges") == "bytes"


async def test_a_presigned_get_url_really_does_reject_head(real_s3_storage):
    """The premise, measured rather than assumed.

    If this ever passes a HEAD on a GET-signed URL, the endpoint under test is
    not enforcing SigV4 and the test above is proving nothing about redirects.
    That makes this the vacuity guard for the whole module.
    """
    import httpx

    key = f"rasters/{uuid.uuid4().hex[:8]}/sigcheck.cog.tif"
    await real_s3_storage.put(key, b"x" * 4096)
    presigned = real_s3_storage.generate_presigned_get_url(key, expiration=600)

    async with httpx.AsyncClient() as raw:
        signed_get = await raw.get(presigned)
        signed_head = await raw.head(presigned)

    assert signed_get.status_code == 200, (
        f"the presigned URL does not even work for the method it was signed "
        f"for ({signed_get.status_code}); the endpoint is misconfigured."
    )
    assert signed_head.status_code == 403, (
        f"HEAD on a get_object-signed URL returned {signed_head.status_code}, "
        f"not 403. This endpoint is not enforcing the SigV4 method binding, so "
        f"it cannot stand in for S3 or MinIO here."
    )
