"""fix(#1528): a real GDAL client must be able to open the COG over HTTP.

Every other test for this route asserts on headers through
``httpx.ASGITransport``, which never builds an HTTP message — it hands ASGI
dicts straight to the app. That proves the route's intent and proves nothing
about the wire. The failure this issue is about lives on the wire: whether
uvicorn frames the response with a Content-Length or with
``transfer-encoding: chunked``, and whether GDAL's /vsicurl/ can therefore
learn the object's size.

So this one boots the real app on a real socket (the ``uvicorn_url`` pattern
from ``test_cli_round_trip.py`` / ``test_sdks_round_trip.py``), writes a real
COG, and opens it with rasterio through ``/vsicurl/``. rasterio rather than the
``gdalinfo`` CLI because it is a hard backend dependency and is therefore
present wherever these tests run.

MEASURED, GDAL 3.13.0 CLI and rasterio 1.5.1 / GDAL 3.12.4, against this same
harness on a bare uvicorn — no nginx, no production edge:

  before (main)   HEAD -> 405 allow: GET, and the GET is a StreamingResponse
                  with no length, so uvicorn frames it chunked. vsicurl logs
                  ``HEAD not allowed. Retrying with GET``, the fallback GET
                  teaches it nothing either, and it concludes ``Request at
                  offset 0, after end of file``. gdalinfo exits 1 with
                  ``ERROR 4: ... not recognized as a supported dataset name``;
                  rasterio raises OpenFailedError. The COG cannot be opened AT
                  ALL.

  after           HEAD -> 200 with content-length and accept-ranges. vsicurl
                  logs ``GetFileSize``, then ``Downloading 0-16383`` ->
                  ``Got response_code=206``, and opens the file. gdalinfo exits
                  0; rasterio reports the overviews and reads a window.

Worth recording because it corrects the premise this issue was filed with:
#1513 found that a 405 alone does not break GDAL, because the fallback GET
still carries a Content-Length on a bare uvicorn and only the production edge
strips it. That reasoning does not transfer here. This route's GET was a
``StreamingResponse`` with no Content-Length, so uvicorn *itself* frames it
chunked — the second ingredient was already inside the route, and no edge was
needed to reproduce the failure.

Requirements:
  - Docker database must be running (docker compose up db)
  - Run with: set -a && source ../.env.test && set +a
              uv run pytest tests/test_cog_vsicurl_1528.py -v
"""

import asyncio
import socket
import uuid

import pytest
from sqlalchemy import select

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.storage import get_storage
from app.processing.raster.models import RasterAsset

from tests.factories import get_user_id

rasterio = pytest.importorskip("rasterio", reason="rasterio (GDAL) not installed")


def _build_cog(path: str) -> bytes:
    """Write a genuine tiled, overviewed COG and hand back its bytes.

    Tiled with overviews on purpose: an untiled GeoTIFF would be readable in
    one sequential pass, so it could not distinguish a client that ranges from
    one that downloads everything. 1024x1024 at 256 blocks gives GDAL real
    overviews to discover, which is the access pattern the format exists for.
    """
    import numpy as np
    from rasterio.transform import from_origin

    data = (np.random.default_rng(1528).random((1024, 1024)) * 255).astype("uint8")
    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=1024,
        width=1024,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(-100, 40, 0.001, 0.001),
        blocksize=256,
    ) as dst:
        dst.write(data, 1)
    with open(path, "rb") as fh:
        return fh.read()


@pytest.fixture
async def vsicurl_cog(client, test_db_session, tmp_path):
    """A public raster dataset with real COG bytes, plus a download token."""
    from datetime import UTC, datetime, timedelta

    import jwt as _jwt

    from app.core.config import settings

    admin_id = await get_user_id(test_db_session, "admin")
    record = Record(
        title=f"VsiCurl COG {uuid.uuid4().hex[:6]}",
        summary="COG for the #1528 /vsicurl/ round trip",
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
        table_name=f"vsicurl_cog_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="probe.tif",
    )
    test_db_session.add(dataset)
    await test_db_session.flush()
    # No "/vsicurl/" segment in the key: resolve_storage_key's
    # _validate_asset_uri rejects that pattern outright (GDAL path injection),
    # and it does so before this route is reached.
    asset_uri = f"rasters/{dataset.id}/cogread/src.cog.tif"
    test_db_session.add(
        RasterAsset(dataset_id=dataset.id, asset_uri=asset_uri, storage_backend="local")
    )
    await test_db_session.flush()
    await test_db_session.commit()

    cog_bytes = _build_cog(str(tmp_path / "probe.cog.tif"))
    await get_storage().put(asset_uri, cog_bytes)

    # A download-scoped token on ?token=, the lane a GDAL client can actually
    # use: vsicurl takes a URL, not an Authorization header.
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
    return dataset.id, token, len(cog_bytes)


@pytest.fixture
async def uvicorn_url(client):
    """The real app on a real free port.

    Verbatim shape of ``test_cli_round_trip.py``'s fixture: the ``client``
    fixture has already installed the DB override, the admin user and the local
    storage provider, and uvicorn re-uses that same wired ``app``.
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


def _open_and_read(url: str) -> dict:
    """Open through /vsicurl/ and read one block. Blocking — call in a thread.

    ``GDAL_DISABLE_READDIR_ON_OPEN`` because this URL's path ends in
    ``/download/cog`` with the token in the query string: with no file
    extension to go on, vsicurl otherwise probes the parent path as a directory
    listing, which this API has no concept of.
    """
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(f"/vsicurl/{url}") as ds:
            window = ds.read(1, window=((0, 256), (0, 256)))
            return {
                "width": ds.width,
                "height": ds.height,
                "count": ds.count,
                "overviews": ds.overviews(1),
                "window_shape": window.shape,
            }


async def test_gdal_vsicurl_opens_the_cog_over_http(
    uvicorn_url, vsicurl_cog, test_db_session
):
    """The end-to-end claim: a GDAL client opens this endpoint and reads a tile.

    On main this raises OpenFailedError — see the module docstring for the
    measured before/after. It is the one assertion in this change that a header
    check cannot stand in for.
    """
    from app.modules.audit.models import AuditLog

    dataset_id, token, total_size = vsicurl_cog
    url = f"{uvicorn_url}/datasets/{dataset_id}/download/cog?token={token}"

    info = await asyncio.to_thread(_open_and_read, url)

    assert info["width"] == 1024 and info["height"] == 1024
    assert info["count"] == 1
    assert info["window_shape"] == (256, 256)
    assert info["overviews"], (
        "GDAL opened the file but found no overviews; the COG's pyramid is the "
        "part a range-reading client navigates by."
    )

    # The efficiency claim, checked server-side rather than asserted. Every GET
    # on this route writes an audit row carrying its Range header, so the log
    # is a complete record of how GDAL fetched the object. If any row has a
    # null range, GDAL pulled the whole COG down and the ranges bought nothing.
    rows = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "dataset.download_cog",
                    AuditLog.resource_id == dataset_id,
                )
            )
        )
        .scalars()
        .all()
    )

    assert rows, "no download was recorded; the open cannot have gone over HTTP"
    full_body_gets = [r for r in rows if not (r.details or {}).get("range")]
    assert full_body_gets == [], (
        f"GDAL issued {len(full_body_gets)} full-object GET(s) against a "
        f"{total_size}-byte COG. Opening a COG is supposed to cost a header "
        f"read and the tiles actually wanted, not the whole file."
    )


async def test_head_on_the_wire_carries_the_size(uvicorn_url, vsicurl_cog):
    """The framing itself, over a real socket rather than through ASGI.

    ``ASGITransport`` cannot show this: uvicorn is what decides between a
    Content-Length and ``transfer-encoding: chunked``, and that decision is the
    whole reason /vsicurl/ could not open this endpoint.
    """
    import httpx

    dataset_id, token, total_size = vsicurl_cog
    url = f"{uvicorn_url}/datasets/{dataset_id}/download/cog?token={token}"

    async with httpx.AsyncClient() as raw:
        head = await raw.head(url)
        ranged = await raw.get(url, headers={"Range": "bytes=0-16383"})

    assert head.status_code == 200, (
        f"HEAD on the wire returned {head.status_code} "
        f"(allow: {head.headers.get('allow')!r})"
    )
    assert head.headers.get("content-length") == str(total_size)
    assert head.headers.get("accept-ranges") == "bytes"

    # 16 KiB is the window vsicurl actually asks for first; measured above as
    # "Downloading 0-16383 ... Got response_code=206".
    assert ranged.status_code == 206
    assert ranged.headers.get("content-range") == f"bytes 0-16383/{total_size}"
    assert len(ranged.content) == 16384
