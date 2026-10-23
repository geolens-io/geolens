"""Round-trip integration test for both SDKs.

The Python half exercises the SDK directly against the in-process FastAPI app
via a manually-constructed ``httpx.Client`` that wraps ``ASGITransport(app=app)``
plus the auth headers built from the SDK's ``AuthenticatedClient`` (no real
network I/O, no uvicorn subprocess for these tests, ~3s in CI). It exercises
both Bearer-token AND X-API-Key auth modes, closing the empirical gap that
``OAuth2PasswordBearer`` is the only security scheme advertised in the OpenAPI
snapshot but ``X-API-Key`` works through the hand-written wrapper.

The TypeScript half spawns a Node subprocess that runs against a uvicorn
instance bound to a free port on 127.0.0.1. If Node is unavailable on the
test runner OR the SDK has not been built (``dist/index.js`` missing), the
test skips with a clear reason. The CI workflow
ensures both are present.

The round-trip covers three endpoints. The actual
operationIds in the OpenAPI snapshot (verified 2026-04-27) are:
    GET  /search/datasets/         search_datasets_endpoint_search_datasets_get
    GET  /datasets/{dataset_id}    get_single_dataset_datasets_dataset_id_get
    POST /ingest/upload            upload_file_ingest_upload_post
(Single-underscore separators per generator naming, NOT the double-underscore
prose paths in earlier notes.)

Note: ``GeolensClient`` is imported from ``geolens.auth`` (its definition
module). The Makefile cp-stash also carries ``__init__.py`` so
``from geolens import GeolensClient`` works for SDK consumers; the
explicit submodule path is kept here for test stability across regenerations.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys as _sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

# Make the in-repo geolens package importable without `pip install -e`.
# The sdks/python tree is NOT a uv workspace member; it's a sibling distribution
# whose contents are committed for consumer inspection. Adding it to sys.path
# is the smallest mechanism to import it from a backend test.
#
# Skip the entire module gracefully when sdks/python is not available on the
# filesystem. This is the case inside the docker `api` container — its volume
# mounts include backend/{app,alembic,tests} but NOT sdks/. The host pytest
# (and any CI runner that checks out the full repo) finds the SDK and runs
# all tests; container runs see "skipped: SDK source tree not present", and
# CI's dedicated `sdks-check` job catches generation drift independently.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SDK_PY_PATH = _REPO_ROOT / "sdks" / "python"
# pytest.skip kept inline: allow_module_level=True is required at module scope
# (no test function exists yet to decorate); the `if` runs at import time
# to abort the rest of the module load when the SDK tree is absent.
if not (_SDK_PY_PATH / "geolens" / "auth.py").is_file():
    pytest.skip(
        "geolens source tree not present at "
        f"{_SDK_PY_PATH} (expected when running inside the api container; "
        "host pytest and full-checkout CI runners exercise this module)",
        allow_module_level=True,
    )
if str(_SDK_PY_PATH) not in _sys.path:
    _sys.path.insert(0, str(_SDK_PY_PATH))

from geolens.auth import GeolensClient  # noqa: E402
from geolens.client import AuthenticatedClient, Client  # noqa: E402
from geolens.models.reupload_commit_request import ReuploadCommitRequest  # noqa: E402
from geolens.models.service_auth_request import ServiceAuthRequest  # noqa: E402
from geolens.models.stac_item_summary import StacItemSummary  # noqa: E402
from geolens.types import UNSET  # noqa: E402

# Lift the 3 TypeScript-round-trip skip preconditions to
# module-level constants so the conditional skips become @pytest.mark.skipif
# decorators (collected at gather-time). All three checks are pure (no
# side effects, no network).
_TS_DIST_PATH = _REPO_ROOT / "sdks" / "typescript" / "dist" / "index.js"
_NODE_AVAILABLE: bool = shutil.which("node") is not None
_TS_SDK_BUILT: bool = _TS_DIST_PATH.exists()
try:
    import uvicorn as _uvicorn_check  # noqa: F401

    _UVICORN_AVAILABLE: bool = True
except ImportError:
    _UVICORN_AVAILABLE = False


# --------------------------- Helpers ---------------------------


def _wire_asgi_transport(sdk: GeolensClient, app) -> None:
    """Wire the SDK's underlying client to an in-process ASGITransport.

    ``ASGITransport`` only implements ``handle_async_request`` — there is no
    sync counterpart, so the SDK's ``sync_detailed`` calls cannot use this
    transport. The round-trip tests therefore use the SDK's ``asyncio_detailed``
    entrypoints, which call ``client.get_async_httpx_client()``.

    The generated ``AuthenticatedClient.set_async_httpx_client()`` replaces
    the internal httpx.AsyncClient outright — bypassing the lazy auth-header
    injection in ``get_async_httpx_client()``. So we read ``auth_header_name``,
    ``prefix``, and ``token`` off the SDK's underlying client and construct an
    ``httpx.AsyncClient(transport=ASGITransport(app=app), headers=...)``
    ourselves that includes the auth header up front.
    """
    transport = ASGITransport(app=app)
    headers: dict[str, str] = {}
    underlying = sdk.client
    if isinstance(underlying, AuthenticatedClient):
        token = underlying.token
        prefix = underlying.prefix
        header_name = underlying.auth_header_name
        headers[header_name] = f"{prefix} {token}" if prefix else token
    async_httpx_client = httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
        headers=headers,
    )
    underlying.set_async_httpx_client(async_httpx_client)


@contextlib.asynccontextmanager
async def _serving_over_http(app):
    """Serve ``app`` on a free 127.0.0.1 port and yield its base URL.

    The sync SDK calls and the TypeScript SDK need a real socket: httpx's
    ASGITransport has no sync counterpart.
    """
    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error", lifespan="off"
        )
    )
    serve_task = asyncio.create_task(server.serve())
    try:
        for _ in range(50):
            await asyncio.sleep(0.1)
            if server.started:
                break
        else:
            pytest.fail("uvicorn server did not start within 5s")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()


def _collection(names: list[str]) -> bytes:
    """A point FeatureCollection with one feature per name.

    Compact and in the key order ``JSON.stringify`` gives the TypeScript
    script's copy, so both SDKs' uploads compare byte for byte.
    """
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [i, i]},
                    "properties": {"name": name},
                }
                for i, name in enumerate(names)
            ],
        },
        separators=(",", ":"),
    ).encode()


def _png(width: int = 8, height: int = 8) -> bytes:
    """A valid solid-colour RGBA PNG."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xff\x00\x00\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class _InlineWorker:
    """Runs a queued ingest or reupload task in the test process.

    GDAL is replaced by a loader that reads the staged file itself, so the
    rows that land are the rows the SDK uploaded; ``received`` keeps the bytes
    the worker was handed.
    """

    def __init__(self, session) -> None:
        self.session = session
        self.received: list[bytes] = []

    async def _fake_ogrinfo(self, file_path, *args, **kwargs):
        features = json.loads(Path(file_path).read_bytes())["features"]
        return {
            "srid": 4326,
            "geometry_type": "Point",
            "layer_name": "rt",
            "feature_count": len(features),
            "columns": [{"name": "name", "type": "String"}],
        }

    async def _fake_ogr2ogr(self, file_path, table_name, db_conn_str, *, schema, **kw):
        from sqlalchemy import text

        import app.core.db as db_module

        raw = Path(file_path).read_bytes()
        self.received.append(raw)
        async with db_module.async_session() as session:
            await session.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table_name}" '
                    "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
                )
            )
            for feature in json.loads(raw)["features"]:
                x, y = feature["geometry"]["coordinates"]
                await session.execute(
                    text(
                        f'INSERT INTO "{schema}"."{table_name}" (geom, name) '
                        "VALUES (ST_SetSRID(ST_MakePoint(:x, :y), 4326), :name)"
                    ),
                    {"x": x, "y": y, "name": feature["properties"]["name"]},
                )
            await session.commit()

    async def run(self, task, job_id, **extra) -> None:
        from unittest.mock import AsyncMock, patch

        from sqlalchemy import select

        from app.platform.jobs.models import IngestJob

        self.session.expire_all()
        job = (
            await self.session.execute(select(IngestJob).where(IngestJob.id == job_id))
        ).scalar_one()
        with (
            patch("app.processing.ingest.ogr.run_ogrinfo", new=self._fake_ogrinfo),
            patch("app.processing.ingest.ogr.run_ogr2ogr", new=self._fake_ogr2ogr),
            patch(
                "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.publish_followups.invalidate_catalog_cache",
                new=AsyncMock(),
            ),
            patch("app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()),
        ):
            await task.func(
                job_id=str(job.id),
                file_path=job.file_path,
                user_id=str(job.created_by),
                attempt_id=str(job.attempt_id),
                **extra,
            )


@contextlib.contextmanager
def _commits_stay_queued():
    """Lets the import and reupload commit routes run without a task queue."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.catalog.datasets.api import router_reupload

    queued = MagicMock()
    queued.defer_async = AsyncMock()
    queued.configure.return_value.defer_async = AsyncMock()
    port = router_reupload.get_catalog_port()
    with (
        patch("app.processing.ingest.router.queue_ingest_job", new=AsyncMock()),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
        patch.object(port, "reupload_file_task", return_value=queued),
    ):
        yield


@pytest.fixture
async def ingested_datasets(client, admin_auth_header):
    """Dataset ids a test created; each is deleted with its table afterwards."""
    from sqlalchemy import select

    from app.core.db import async_session
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    ids: list = []
    yield ids
    for dataset_id in ids:
        async with async_session() as session:
            title = (
                await session.execute(
                    select(Record.title)
                    .join(Dataset, Dataset.record_id == Record.id)
                    .where(Dataset.id == dataset_id)
                )
            ).scalar_one_or_none()
        if title is not None:
            await client.request(
                "DELETE",
                f"/datasets/{dataset_id}",
                json={"confirm_title": title},
                headers=admin_auth_header,
            )


# --------------------------- Unit tests (no network) ---------------------------


class TestPythonAuthWrapperUnit:
    """Unit tests for ``GeolensClient`` — no network I/O."""

    def test_construct_with_bearer(self) -> None:
        c = GeolensClient(base_url="http://x", bearer_token="abc")
        assert isinstance(c._client, AuthenticatedClient)
        assert c._client.token == "abc"
        assert c._client.prefix == "Bearer"
        assert c._client.auth_header_name == "Authorization"

    def test_construct_with_api_key(self) -> None:
        c = GeolensClient(base_url="http://x", api_key="key123")
        assert isinstance(c._client, AuthenticatedClient)
        assert c._client.token == "key123"
        assert c._client.prefix == ""
        assert c._client.auth_header_name == "X-API-Key"

    def test_construct_anonymous(self) -> None:
        c = GeolensClient(base_url="http://x")
        # Anonymous mode — Client (parent), NOT AuthenticatedClient (subclass-like)
        assert isinstance(c._client, Client)
        assert not isinstance(c._client, AuthenticatedClient)

    def test_both_auth_modes_raises(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            GeolensClient(base_url="http://x", bearer_token="a", api_key="b")

    def test_set_bearer_token(self) -> None:
        c = GeolensClient(base_url="http://x")
        c.set_bearer_token("xyz")
        assert isinstance(c._client, AuthenticatedClient)
        assert c._client.token == "xyz"
        assert c._client.auth_header_name == "Authorization"

    def test_set_api_key(self) -> None:
        c = GeolensClient(base_url="http://x")
        c.set_api_key("k")
        assert isinstance(c._client, AuthenticatedClient)
        assert c._client.token == "k"
        assert c._client.auth_header_name == "X-API-Key"

    def test_client_property(self) -> None:
        c = GeolensClient(base_url="http://x", bearer_token="abc")
        assert c.client is c._client

    @pytest.mark.parametrize(
        "auth", [{}, {"bearer_token": "abc"}, {"api_key": "key123"}]
    )
    def test_client_options_reach_the_generated_client(self, auth: dict) -> None:
        import httpx

        timeout = httpx.Timeout(7.0)
        c = GeolensClient(
            base_url="http://x", timeout=timeout, headers={"X-Probe": "1"}, **auth
        )
        assert c.client.get_httpx_client().timeout == timeout
        assert c.client.get_httpx_client().headers["X-Probe"] == "1"

    def test_a_credential_swap_does_not_carry_the_old_credential_over(self) -> None:
        c = GeolensClient(
            base_url="http://x", api_key="key123", headers={"X-Probe": "1"}
        )
        c.client.get_httpx_client()
        c.set_bearer_token("tok")
        for headers in (
            c.client.get_httpx_client().headers,
            c.client.get_async_httpx_client().headers,
        ):
            assert headers["Authorization"] == "Bearer tok"
            assert "X-API-Key" not in headers
            assert headers["X-Probe"] == "1"

    @pytest.mark.parametrize("auth", ["bearer_token", "api_key"])
    def test_the_callers_options_are_not_mutated(self, auth: str) -> None:
        headers = {"X-Probe": "1"}
        httpx_args = {"trust_env": False}
        c = GeolensClient(
            base_url="http://x", headers=headers, httpx_args=httpx_args, **{auth: "k"}
        )
        c.client.get_httpx_client()
        c.set_api_key("k2")
        c.client.get_httpx_client()
        c.set_bearer_token("t2")
        c.client.get_async_httpx_client()
        assert headers == {"X-Probe": "1"}
        assert httpx_args == {"trust_env": False}

    @pytest.mark.parametrize(
        "auth", [{}, {"bearer_token": "abc"}, {"api_key": "key123"}]
    )
    def test_every_client_reads_restricted_map_visibility(self, auth: dict) -> None:
        c = GeolensClient(base_url="http://x", **auth)
        clients = [c.client]
        c.set_api_key("k2")
        clients.append(c.client)
        for client in clients:
            for http in (client.get_httpx_client(), client.get_async_httpx_client()):
                assert http.headers["X-GeoLens-Map-Visibility"] == "restricted"

    @pytest.mark.parametrize("setter", ["set_bearer_token", "set_api_key"])
    def test_client_options_survive_a_credential_swap(self, setter: str) -> None:
        import httpx

        timeout = httpx.Timeout(7.0)
        c = GeolensClient(base_url="http://x", timeout=timeout)
        getattr(c, setter)("secret")
        assert c.client.get_httpx_client().timeout == timeout


# ------------------- Model field compatibility (older server) -------------------


class TestPythonModelOptionalFieldCompatibility:
    """A Python SDK version can run a version ahead of the GeoLens server it
    talks to — unlike the web app, which always ships bundled with its own
    API. A field the SDK knows about but an older server never sent must
    come back ``UNSET``, not raise ``KeyError``; that only holds if the
    generated model's own field stays optional (a ``default=None`` on the
    backend schema, not just nullable) once it exists."""

    def test_stac_item_summary_from_dict_tolerates_a_missing_optional_field(
        self,
    ) -> None:
        # Shaped like an older server's /services/stac/search response:
        # every required field present, data_asset_import_refusal simply
        # doesn't exist yet.
        raw = {"id": "item-1", "title": "Item 1", "asset_count": 1}
        item = StacItemSummary.from_dict(raw)
        assert item.data_asset_import_refusal is UNSET


class TestPythonModelPositionalSlots:
    """A field added to a request model never takes a slot a caller already fills."""

    def test_a_positional_auth_on_a_reupload_commit_stays_auth(self) -> None:
        auth = ServiceAuthRequest(method="bearer", token="t")
        request = ReuploadCommitRequest(None, None, None, None, auth)
        assert request.auth is auth
        assert request.to_dict()["auth"]["method"] == "bearer"
        assert "review_fingerprint" not in request.to_dict()


# ------------------- Binary downloads -------------------


class TestPointCloudDownload:
    """The convenience calls return a point cloud file's bytes, whole or ranged."""

    @pytest.mark.parametrize("status", [200, 206])
    def test_sync_and_asyncio_return_the_file(self, status: int) -> None:
        from geolens.api.datasets import (
            get_pointcloud_file_datasets_dataset_id_copc_attempt_id_name_copc_laz_get as download,
        )
        from geolens.types import File

        body = b"LASF" + bytes(range(64))

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status,
                content=body,
                headers={"Content-Type": "application/vnd.laszip+copc"},
            )

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        ids = {"dataset_id": uuid4(), "attempt_id": uuid4(), "name": "data"}

        synced = download.sync(**ids, client=client)
        awaited = asyncio.run(download.asyncio(**ids, client=client))

        for result in (synced, awaited):
            assert isinstance(result, File)
            assert result.payload.read() == body


class TestFeaturesGeojsonDownload:
    """The convenience calls return the parsed FeatureCollection, not None."""

    def test_sync_and_asyncio_return_the_collection(self) -> None:
        from geolens.api.features import (
            get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get as fetch,
        )

        body = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": 1,
                    "geometry": {"type": "Point", "coordinates": [1.0, 2.0, 3.0]},
                    "properties": {"name": "a"},
                },
                {"type": "Feature", "id": 2, "geometry": None, "properties": {}},
            ],
            "truncated": False,
            "total_count": 2,
        }

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=body, headers={"Content-Type": "application/geo+json"}
            )

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        dataset_id = uuid4()

        synced = fetch.sync(dataset_id, client=client)
        awaited = asyncio.run(fetch.asyncio(dataset_id, client=client))

        for result in (synced, awaited):
            assert result is not None
            payload = result.to_dict()
            assert payload["features"][0]["geometry"]["coordinates"] == [1.0, 2.0, 3.0]
            assert payload["truncated"] is False
            assert payload["features"][1]["geometry"] is None
            assert payload["total_count"] == 2


class TestCogDownload:
    """sync() and asyncio() return the COG download's bytes for 200 and 206."""

    @pytest.mark.parametrize("status", [200, 206])
    def test_sync_and_asyncio_return_the_file(self, status: int) -> None:
        from geolens.api.datasets_export import (
            download_cog_datasets_dataset_id_download_cog_get as download,
        )
        from geolens.types import File

        body = b"II*\x00" + bytes(range(64))  # a TIFF byte-order marker + filler

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status, content=body, headers={"Content-Type": "image/tiff"}
            )

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        dataset_id = uuid4()

        synced = download.sync(dataset_id=dataset_id, client=client)
        awaited = asyncio.run(download.asyncio(dataset_id=dataset_id, client=client))

        for result in (synced, awaited):
            assert isinstance(result, File)
            assert result.payload.read() == body


class TestExportDownload:
    """sync() and asyncio() return the export's bytes.

    One format stands in for the whole set here (schemas.ExportFormat) —
    every format is declared with the identical binary schema
    (_EXPORT_BODY), so the generated parse code is the same for all of them.
    """

    @pytest.mark.parametrize("status", [200, 206])
    def test_sync_and_asyncio_return_the_file(self, status: int) -> None:
        from geolens.api.datasets import (
            export_dataset_endpoint_datasets_dataset_id_export_get as download,
        )
        from geolens.types import File

        body = b"GPKG-bytes-not-real-sqlite" + bytes(range(32))

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status,
                content=body,
                headers={"Content-Type": "application/geopackage+sqlite3"},
            )

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        dataset_id = uuid4()

        synced = download.sync(dataset_id=dataset_id, client=client)
        awaited = asyncio.run(download.asyncio(dataset_id=dataset_id, client=client))

        for result in (synced, awaited):
            assert isinstance(result, File)
            assert result.payload.read() == body


class TestTiles3dFileDownload:
    """sync() and asyncio() return a 3D Tiles file's bytes.

    Parametrized across a JSON file (tileset.json) and a binary one (a GLB
    tile) — both must come back as bytes, not a parsed dict, which is the
    failure mode _TILES3D_BODY's exclusion of "application/json" guards
    against (see the router's comment).
    """

    @pytest.mark.parametrize("content_type", ["application/json", "model/gltf-binary"])
    def test_sync_and_asyncio_return_the_file(self, content_type: str) -> None:
        from geolens.api.datasets import (
            get_tileset_file_datasets_dataset_id_tiles3d_path_get as download,
        )
        from geolens.types import File

        body = (
            b'{"asset": {"version": "1.1"}}'
            if "json" in content_type
            else b"glTF" + bytes(range(32))
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=body, headers={"Content-Type": content_type}
            )

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        ids = {"dataset_id": uuid4(), "path": "0/tileset.json"}

        synced = download.sync(**ids, client=client)
        awaited = asyncio.run(download.asyncio(**ids, client=client))

        for result in (synced, awaited):
            assert isinstance(result, File)
            assert result.payload.read() == body


class TestRasterTileForbidden:
    """A refused raster tile parses as a ProblemDetail rather than None."""

    def test_sync_and_detailed_parse_the_403(self) -> None:
        from geolens.api.tiles import (
            raster_tile_proxy_tiles_raster_proxy_dataset_id_z_x_y_fmt_get as tile,
        )
        from geolens.models import ProblemDetail

        problem = {
            "type": "about:blank",
            "title": "Forbidden",
            "status": 403,
            "detail": "Invalid or expired signature",
        }

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403, json=problem, headers={"Content-Type": "application/problem+json"}
            )

        client = Client(
            base_url="http://sdk.test",
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        args = {"dataset_id": uuid4(), "z": 0, "x": 0, "y": 0, "fmt": "png"}

        synced = tile.sync(**args, client=client)
        detailed = tile.sync_detailed(**args, client=client)
        awaited = asyncio.run(tile.asyncio(**args, client=client))

        for result in (synced, detailed.parsed, awaited):
            assert isinstance(result, ProblemDetail)
            assert result.detail == "Invalid or expired signature"


class TestCogAndExportNotModified:
    """A 304 from the COG download or export is a declared status, so
    raise_on_unexpected_status=True doesn't raise on a cache hit.
    """

    def test_cog_304_does_not_raise(self) -> None:
        from geolens.api.datasets_export import (
            download_cog_datasets_dataset_id_download_cog_get as download,
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(304, headers={"ETag": '"abc123"'})

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
            raise_on_unexpected_status=True,
        )

        result = download.sync_detailed(dataset_id=uuid4(), client=client)

        assert result.status_code == 304

    def test_export_304_does_not_raise(self) -> None:
        from geolens.api.datasets import (
            export_dataset_endpoint_datasets_dataset_id_export_get as download,
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(304, headers={"ETag": '"abc123"'})

        client = AuthenticatedClient(
            base_url="http://sdk.test",
            token=uuid4().hex,
            httpx_args={"transport": httpx.MockTransport(respond)},
            raise_on_unexpected_status=True,
        )

        result = download.sync_detailed(dataset_id=uuid4(), client=client)

        assert result.status_code == 304


class _Storage:
    """Stands in for every host reached over a real network transport."""

    def __init__(self, body: bytes) -> None:
        self.seen: list[httpx.Request] = []
        self.respond = lambda request: httpx.Response(200, content=body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return self.respond(request)


class TestCogDownloadRedirect:
    """geolens.cog_download returns the COG on every storage backend.

    The GeoLens client answers through its own MockTransport; the storage
    host is whatever a fresh httpx client reaches, captured by patching the
    real network transports.
    """

    _BODY = b"II*\x00" + bytes(range(64))
    _STORAGE_URL = "https://storage.test/bucket/cog.tif?X-Amz-Signature=abc123"
    _AUTH = {
        "bearer": {},
        "api_key": {"prefix": "", "auth_header_name": "X-API-Key"},
    }

    @pytest.fixture
    def storage(self, monkeypatch: pytest.MonkeyPatch) -> _Storage:
        storage = _Storage(self._BODY)

        async def handle_async(_transport, request: httpx.Request) -> httpx.Response:
            return storage.handle(request)

        monkeypatch.setattr(
            httpx.HTTPTransport,
            "handle_request",
            lambda _transport, request: storage.handle(request),
        )
        monkeypatch.setattr(
            httpx.AsyncHTTPTransport, "handle_async_request", handle_async
        )
        return storage

    def _client(
        self,
        respond,
        *,
        auth: str = "api_key",
        secrets: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs,
    ) -> tuple[AuthenticatedClient, list[httpx.Request]]:
        secrets = secrets or {
            name: uuid4().hex for name in ("token", "header", "cookie")
        }
        sent: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return respond(request)

        client = AuthenticatedClient(
            base_url="http://sdk.test/api",
            token=secrets["token"],
            headers={"X-Custom-Header": secrets["header"], **(headers or {})},
            cookies={"geolens_session": secrets["cookie"]},
            httpx_args={"transport": httpx.MockTransport(record)},
            **self._AUTH[auth],
            **kwargs,
        )
        return client, sent

    def _redirect_to(self, location: str):
        return lambda request: httpx.Response(302, headers={"Location": location})

    def _download(self, mode: str, client: AuthenticatedClient):
        from geolens import cog_download

        if mode == "sync":
            return cog_download.sync(uuid4(), client=client)
        return asyncio.run(cog_download.asyncio(uuid4(), client=client))

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize("auth", ["bearer", "api_key"])
    def test_302_target_gets_the_bytes_and_no_geolens_credentials(
        self, storage: _Storage, auth: str, mode: str
    ) -> None:
        from geolens.types import File

        secrets = {name: uuid4().hex for name in ("token", "header", "cookie")}
        client, sent = self._client(
            self._redirect_to(self._STORAGE_URL), auth=auth, secrets=secrets
        )

        result = self._download(mode, client)

        assert isinstance(result, File)
        assert result.payload.read() == self._BODY
        # The GeoLens request carried every credential, so their absence
        # below is the helper's doing.
        (geolens_request,) = sent
        joined = " ".join(geolens_request.headers.values())
        assert all(secret in joined for secret in secrets.values())
        (fetched,) = storage.seen
        assert fetched.url == self._STORAGE_URL
        for name in ("Authorization", "X-API-Key", "Cookie", "X-Custom-Header"):
            assert name not in fetched.headers
        joined = " ".join(fetched.headers.values())
        assert not any(secret in joined for secret in secrets.values())

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_client_that_follows_redirects_still_sends_no_credentials(
        self, storage: _Storage, mode: str
    ) -> None:
        client, sent = self._client(
            self._redirect_to(self._STORAGE_URL), follow_redirects=True
        )

        assert self._download(mode, client).payload.read() == self._BODY
        assert len(sent) == 1
        (fetched,) = storage.seen
        assert "X-API-Key" not in fetched.headers

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_same_host_storage_redirect_is_followed_without_credentials(
        self, storage: _Storage, mode: str
    ) -> None:
        storage.respond = lambda request: (
            httpx.Response(307, headers={"Location": "/bucket/moved.tif"})
            if request.url.path == "/bucket/cog.tif"
            else httpx.Response(200, content=self._BODY)
        )
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        assert self._download(mode, client).payload.read() == self._BODY
        assert [str(request.url) for request in storage.seen] == [
            self._STORAGE_URL,
            "https://storage.test/bucket/moved.tif",
        ]
        assert all("X-API-Key" not in request.headers for request in storage.seen)

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_storage_redirect_to_another_host_raises(
        self, storage: _Storage, mode: str
    ) -> None:
        from geolens.errors import UnexpectedStatus

        storage.respond = lambda request: (
            httpx.Response(302, headers={"Location": "http://internal.test/meta"})
            if request.url.host == "storage.test"
            else httpx.Response(200, content=b"not the COG")
        )
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        with pytest.raises(UnexpectedStatus) as raised:
            self._download(mode, client)
        assert raised.value.status_code == 302
        assert "internal.test" in str(raised.value)
        assert [request.url.host for request in storage.seen] == ["storage.test"]

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_storage_redirect_from_http_to_https_is_followed(
        self, storage: _Storage, mode: str
    ) -> None:
        storage.respond = lambda request: (
            httpx.Response(301, headers={"Location": "https://storage.test/cog.tif"})
            if request.url.scheme == "http"
            else httpx.Response(200, content=self._BODY)
        )
        client, _ = self._client(self._redirect_to("http://storage.test/cog.tif"))

        assert self._download(mode, client).payload.read() == self._BODY
        assert [request.url.scheme for request in storage.seen] == ["http", "https"]

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_storage_redirect_from_https_to_http_raises(
        self, storage: _Storage, mode: str
    ) -> None:
        from geolens.errors import UnexpectedStatus

        storage.respond = lambda request: (
            httpx.Response(302, headers={"Location": "http://storage.test/cog.tif"})
            if request.url.scheme == "https"
            else httpx.Response(200, content=self._BODY)
        )
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        with pytest.raises(UnexpectedStatus):
            self._download(mode, client)
        assert [request.url.scheme for request in storage.seen] == ["https"]

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_storage_redirects_past_the_limit_raise(
        self, storage: _Storage, mode: str
    ) -> None:
        from geolens import cog_download
        from geolens.errors import UnexpectedStatus

        # Stops redirecting on its own after 20 hops, so a missing limit fails
        # the test instead of hanging it.
        storage.respond = lambda request: (
            httpx.Response(302, headers={"Location": f"/hop/{len(storage.seen)}"})
            if len(storage.seen) <= 20
            else httpx.Response(200, content=self._BODY)
        )
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        with pytest.raises(UnexpectedStatus):
            self._download(mode, client)
        assert len(storage.seen) == cog_download._MAX_STORAGE_REDIRECTS + 1

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_relative_location_resolves_against_the_request_url(
        self, storage: _Storage, mode: str
    ) -> None:
        client, _ = self._client(self._redirect_to("/files/cog.tif"))

        assert self._download(mode, client).payload.read() == self._BODY
        (fetched,) = storage.seen
        assert fetched.url == "http://sdk.test/files/cog.tif"
        assert "X-API-Key" not in fetched.headers

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize(
        "location",
        ["ftp://storage.test/cog.tif", "file:///etc/passwd", "https:/cog.tif"],
    )
    def test_non_http_location_raises(
        self, storage: _Storage, location: str, mode: str
    ) -> None:
        client, _ = self._client(self._redirect_to(location))

        with pytest.raises(ValueError, match="unsupported URL"):
            self._download(mode, client)
        assert storage.seen == []

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize("if_match", ['"v1"', '"v0"'])
    def test_range_and_preconditions_reach_the_target(
        self, storage: _Storage, if_match: str, mode: str
    ) -> None:
        from geolens.errors import UnexpectedStatus
        from geolens.types import File

        def answer(request: httpx.Request) -> httpx.Response:
            if request.headers.get("if-match") != '"v1"':
                return httpx.Response(412)
            return httpx.Response(206, content=self._BODY[2:6])

        storage.respond = answer
        secrets = {name: uuid4().hex for name in ("token", "header", "cookie")}
        client, _ = self._client(
            self._redirect_to(self._STORAGE_URL),
            secrets=secrets,
            headers={"Range": "bytes=2-5", "If-Match": if_match},
        )

        if if_match == '"v1"':
            result = self._download(mode, client)
            assert isinstance(result, File)
            assert result.payload.read() == self._BODY[2:6]
        else:
            with pytest.raises(UnexpectedStatus) as raised:
                self._download(mode, client)
            assert raised.value.status_code == 412
        (fetched,) = storage.seen
        assert fetched.headers["Range"] == "bytes=2-5"
        assert fetched.headers["If-Match"] == if_match
        for name in ("Authorization", "X-API-Key", "Cookie", "X-Custom-Header"):
            assert name not in fetched.headers
        joined = " ".join(fetched.headers.values())
        assert not any(secret in joined for secret in secrets.values())

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize(
        "condition",
        [
            ("If-None-Match", '"remote-etag"'),
            ("If-Modified-Since", "Wed, 01 Jan 2025 00:00:00 GMT"),
        ],
    )
    def test_not_modified_target_returns_none(
        self, storage: _Storage, condition: tuple[str, str], mode: str
    ) -> None:
        name, value = condition
        storage.respond = lambda request: httpx.Response(304)
        client, _ = self._client(
            self._redirect_to(self._STORAGE_URL), headers={name: value}
        )

        assert self._download(mode, client) is None
        assert storage.seen[0].headers[name] == value

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize(
        "status", [304, 302], ids=["unconditional-304", "302-without-location"]
    )
    def test_target_3xx_that_is_not_an_answer_raises(
        self, storage: _Storage, status: int, mode: str
    ) -> None:
        from geolens.errors import UnexpectedStatus

        storage.respond = lambda request: httpx.Response(status)
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        with pytest.raises(UnexpectedStatus) as raised:
            self._download(mode, client)
        assert raised.value.status_code == status

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_failed_storage_fetch_raises(self, storage: _Storage, mode: str) -> None:
        from geolens.errors import UnexpectedStatus

        storage.respond = lambda request: httpx.Response(403, content=b"expired")
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        with pytest.raises(UnexpectedStatus) as raised:
            self._download(mode, client)
        assert raised.value.status_code == 403

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize("status", [200, 206])
    def test_local_storage_returns_the_body(
        self, storage: _Storage, status: int, mode: str
    ) -> None:
        from geolens.types import File

        client, _ = self._client(
            lambda request: httpx.Response(status, content=self._BODY)
        )

        result = self._download(mode, client)

        assert isinstance(result, File)
        assert result.payload.read() == self._BODY
        assert storage.seen == []

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    @pytest.mark.parametrize("route", ["local", "redirected"])
    def test_large_cog_is_spooled_to_disk(
        self, storage: _Storage, route: str, mode: str
    ) -> None:
        import tempfile

        from geolens import cog_download

        body = os.urandom(cog_download.SPOOL_MAX_SIZE + 1024 * 1024)
        if route == "local":
            client, _ = self._client(lambda request: httpx.Response(200, content=body))
        else:
            storage.respond = lambda request: httpx.Response(200, content=body)
            client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        payload = self._download(mode, client).payload

        assert isinstance(payload, tempfile.SpooledTemporaryFile)
        # Rolled over: the bytes are in a file on disk, not held in memory.
        assert payload._rolled
        assert payload.read() == body
        payload.close()

    @pytest.mark.parametrize("mode", ["sync", "asyncio"])
    def test_generated_call_does_not_raise_on_302(self, mode: str) -> None:
        from geolens.api.datasets_export import (
            download_cog_datasets_dataset_id_download_cog_get as download,
        )

        client, _ = self._client(
            self._redirect_to(self._STORAGE_URL), raise_on_unexpected_status=True
        )

        if mode == "sync":
            result = download.sync_detailed(dataset_id=uuid4(), client=client)
        else:
            result = asyncio.run(
                download.asyncio_detailed(dataset_id=uuid4(), client=client)
            )

        assert result.status_code == 302
        assert result.headers["location"] == self._STORAGE_URL


# ------------------- Optional request bodies (regeneration guard) -------------------


class TestOptionalRequestBodyIsOmitted:
    """An omitted body must not reach httpx as UNSET.

    openapi-python-client emits ``else: _kwargs["json"] = body`` for an
    optional request body. The ``else`` is right for an explicit ``None`` — a
    caller asking to send JSON ``null`` — and wrong for the default, because
    ``UNSET`` is a sentinel object rather than data: httpx raises ``TypeError``
    while serializing it and the request never leaves. Every optional-body
    endpoint in the SDK was unusable at its own documented default.

    ``scripts/fix_sdk_optional_body.py`` guards the emission inside ``make
    sdks``, so the corrected form is the only one the tree ever holds. These
    tests are the second line: they fail if somebody regenerates without the
    pipeline step, or if a generator bump changes the shape the script matches.

    Deliberately checks EVERY optional-body endpoint rather than the one that
    surfaced the bug — all five were broken, and #1220 only made it visible.
    """

    def _optional_body_modules(self) -> list[Path]:
        api_root = _SDK_PY_PATH / "geolens" / "api"
        matches: list[Path] = []
        for path in sorted(api_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if re.search(r"^\s*body:\s.*\bUnset\b\s*=\s*UNSET", source, re.MULTILINE):
                matches.append(path)
        return matches

    def test_the_sdk_still_has_optional_body_endpoints_to_guard(self) -> None:
        """Guard the guard: an empty sweep would pass the test below vacuously."""
        assert self._optional_body_modules(), (
            "No optional-body endpoints found in the generated SDK. Either the "
            "API changed or this scan stopped matching — verify before deleting."
        )

    def test_no_optional_body_endpoint_assigns_the_sentinel(self) -> None:
        unguarded = [
            str(path.relative_to(_SDK_PY_PATH))
            for path in self._optional_body_modules()
            if re.search(
                r'^(?P<indent>[ ]+)else:\n(?P=indent)[ ]{4}_kwargs\["json"\] = body$',
                path.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        ]
        assert not unguarded, (
            "These generated endpoints assign the UNSET sentinel to `json`, so "
            "calling them without a body raises TypeError inside httpx. Run "
            "`make sdks` (which applies scripts/fix_sdk_optional_body.py) and "
            "commit the result:\n  " + "\n  ".join(unguarded)
        )

    def test_omitting_the_body_builds_kwargs_with_no_json_key(self) -> None:
        """The behavioural half, against the real generated function.

        The scan above proves the source shape; this proves what the shape
        does. A future generator could reintroduce the defect in a form the
        regex does not match, and this would still catch it.
        """
        from geolens.api.datasets_refresh import (
            refresh_dataset_datasets_dataset_id_refresh_post as refresh_endpoint,
        )

        omitted = refresh_endpoint._get_kwargs(dataset_id=uuid4())
        assert "json" not in omitted

        # An explicit None is a different request and keeps its null body —
        # the one thing the generator's `else` got right.
        explicit_null = refresh_endpoint._get_kwargs(dataset_id=uuid4(), body=None)
        assert explicit_null["json"] is None

    def test_httpx_can_serialize_the_omitted_body_request(self) -> None:
        """The failure mode itself: building the request used to raise.

        Asserting on the kwargs alone would not have caught the original bug
        if the sentinel had been JSON-serializable, so drive httpx the way the
        SDK does.
        """
        from geolens.api.datasets_refresh import (
            refresh_dataset_datasets_dataset_id_refresh_post as refresh_endpoint,
        )

        kwargs = refresh_endpoint._get_kwargs(dataset_id=uuid4())
        with httpx.Client(base_url="http://test") as client:
            request = client.build_request(**kwargs)
        assert request.read() == b""


# ------------------- Anonymous-capable client typing (regeneration guard) -------------------


class TestAnonymousCapableEndpointAcceptsPlainClient:
    """An operation whose security allows anonymous access (one alternative is
    ``{}``) must still accept GeolensClient's plain ``Client``, not only
    ``AuthenticatedClient`` — openapi-python-client types it from
    ``bool(security)`` alone, ignoring the ``{}`` alternative.
    """

    def _anonymous_capable_operations(self) -> set[tuple[str, str]]:
        spec = json.loads(
            (_REPO_ROOT / "backend" / "openapi.json").read_text(encoding="utf-8")
        )
        http_methods = {
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "head",
            "options",
            "trace",
        }
        operations: set[tuple[str, str]] = set()
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method not in http_methods:
                    continue
                security = operation.get("security")
                if security and any(alternative == {} for alternative in security):
                    operations.add((path, method))
        return operations

    def _endpoint_key(self, source: str) -> tuple[str, str] | None:
        """Recover the (path, method) an endpoint module was generated for."""
        method_match = re.search(r'"method":\s*"([a-z]+)"', source)
        url_match = re.search(r'"url":\s*"([^"]*)"', source)
        if not method_match or not url_match:
            return None
        return url_match.group(1), method_match.group(1)

    def test_the_sdk_still_has_anonymous_capable_endpoints_to_guard(self) -> None:
        """Guard the guard: an empty sweep would pass the test below vacuously."""
        assert self._anonymous_capable_operations(), (
            "No anonymous-capable operations found in backend/openapi.json. Either "
            "the API stopped allowing anonymous access anywhere, or this scan "
            "stopped matching — verify before deleting."
        )

    def test_every_anonymous_capable_endpoint_accepts_a_plain_client(self) -> None:
        anonymous = self._anonymous_capable_operations()
        api_root = _SDK_PY_PATH / "geolens" / "api"
        narrow_client = "    client: AuthenticatedClient,\n"

        unmatched = set(anonymous)
        unwidened: list[str] = []
        for path in sorted(api_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            key = self._endpoint_key(source)
            if key is None or key not in anonymous:
                continue
            unmatched.discard(key)
            if narrow_client in source:
                unwidened.append(str(path.relative_to(_SDK_PY_PATH)))

        assert not unmatched, (
            "No generated module found for anonymous-capable operation(s); the "
            "generator may have dropped or renamed them:\n  "
            + "\n  ".join(
                f"{method.upper()} {path}" for path, method in sorted(unmatched)
            )
        )
        assert not unwidened, (
            "These anonymous-capable endpoints still type `client` as "
            "AuthenticatedClient only, so GeolensClient's plain Client (anonymous "
            "mode) fails a type check calling them. Run `make sdks` (which applies "
            "scripts/fix_sdk_anonymous_client.py) and commit the result:\n  "
            + "\n  ".join(unwidened)
        )

    def test_a_plain_client_completes_an_anonymous_capable_call(self) -> None:
        """A plain ``Client`` actually completes the call, against a mocked transport."""
        from geolens.api.search import search_datasets_endpoint_search_datasets_get

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"numberMatched": 0, "numberReturned": 0, "features": []},
            )

        client = Client(
            base_url="http://sdk.test",
            httpx_args={"transport": httpx.MockTransport(respond)},
        )
        resp = search_datasets_endpoint_search_datasets_get.sync_detailed(client=client)
        assert resp.status_code == 200, resp.content


# --------------------------- Round-trip tests (Python) ---------------------------


class TestPythonRoundTrip:
    """ROADMAP SC#1: Python SDK round-trips three endpoints via in-process ASGI.

    Each test constructs a fresh ``GeolensClient`` and wires it to the
    ``ASGITransport(app=app)`` of the FastAPI app the ``client`` fixture has
    already configured (DB overrides, admin user, storage stub). No real
    network I/O.
    """

    @pytest.mark.anyio
    async def test_search_datasets(self, client, admin_auth_header) -> None:
        from app.api.main import app
        from geolens.api.search import (
            search_datasets_endpoint_search_datasets_get,
        )

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        # `keywords` is a query parameter, so the generated function takes no
        # body and needs no explicit body=None (an optional list BODY on a GET
        # would make _get_kwargs set _kwargs["json"] to the UNSET sentinel,
        # which httpx cannot serialize).
        resp = await search_datasets_endpoint_search_datasets_get.asyncio_detailed(
            client=sdk.client,
        )
        assert resp.status_code == 200, resp.content
        # parsed model is an attrs dataclass; just confirm response shape
        assert resp.parsed is not None

        # And the parameter reaches the server as a repeated query value rather
        # than a body the handler never reads — the defect #1666 reported.
        filtered = await search_datasets_endpoint_search_datasets_get.asyncio_detailed(
            client=sdk.client,
            keywords=["zzz-no-such-keyword"],
        )
        assert filtered.status_code == 200, filtered.content
        assert filtered.parsed.number_matched == 0, (
            "keywords did not filter — the SDK is sending it somewhere the "
            "handler does not read."
        )

    @pytest.mark.anyio
    async def test_get_single_dataset_404_for_missing(
        self, client, admin_auth_header
    ) -> None:
        """A non-existent UUID returns 404 — proves the route + auth work."""
        from app.api.main import app
        from geolens.api.datasets import (
            get_single_dataset_datasets_dataset_id_get,
        )

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        resp = await get_single_dataset_datasets_dataset_id_get.asyncio_detailed(
            dataset_id=uuid4(),
            client=sdk.client,
        )
        # 404 (not 401/403) confirms the auth path succeeded and the SDK
        # reached the route handler. We don't need a real dataset for SC.
        assert resp.status_code == 404, resp.content

    @pytest.mark.anyio
    async def test_an_oversized_dry_run_parses_as_a_413_problem(
        self, client, admin_auth_header
    ) -> None:
        """The body limit's 413 is a declared answer, even for a strict client."""
        from app.api.main import app
        from app.api.middleware.body_limit import FEATURE_WRITE_BODY_LIMIT_BYTES
        from geolens.api.features import (
            dry_run_create_feature_datasets_dataset_id_features_dry_run_post as dry_run,
        )
        from geolens.models.feature_create import FeatureCreate
        from geolens.models.problem_detail import ProblemDetail

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(
            base_url="http://test", bearer_token=token, raise_on_unexpected_status=True
        )
        _wire_asgi_transport(sdk, app)
        body = FeatureCreate.from_dict(
            {
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"name": "x" * FEATURE_WRITE_BODY_LIMIT_BYTES},
            }
        )

        parsed = await dry_run.asyncio(dataset_id=uuid4(), client=sdk.client, body=body)

        assert isinstance(parsed, ProblemDetail), parsed
        assert parsed.status == 413

    @pytest.mark.anyio
    async def test_ingest_upload(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """POST /ingest/upload with a real file creates the staged ingest job."""
        from sqlalchemy import select, text

        from app.api.main import app
        from app.platform.jobs.models import IngestJob
        from geolens.api.datasets import upload_file_ingest_upload_post
        from geolens.models.body_upload_file_ingest_upload_post import (
            BodyUploadFileIngestUploadPost,
        )
        from geolens.types import File

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        payload = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                        "properties": {"name": "origin"},
                    }
                ],
            }
        ).encode()
        body = BodyUploadFileIngestUploadPost(
            file=File(
                payload=BytesIO(payload),
                file_name="origin.geojson",
                mime_type="application/geo+json",
            )
        )
        resp = await upload_file_ingest_upload_post.asyncio_detailed(
            client=sdk.client,
            body=body,
        )
        assert resp.status_code == 201, resp.content
        job_id = resp.parsed.job_id
        try:
            job = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert job.source_filename == "origin.geojson"
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_reupload_body_reaches_the_handler(
        self, client, admin_auth_header
    ) -> None:
        """A real file part passes request validation, so an unknown dataset is a 404."""
        from app.api.main import app
        from geolens.api.datasets_reupload import (
            reupload_dataset_datasets_dataset_id_reupload_post,
        )
        from geolens.models.body_reupload_dataset_datasets_dataset_id_reupload_post import (
            BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
        )
        from geolens.types import File

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        resp = (
            await reupload_dataset_datasets_dataset_id_reupload_post.asyncio_detailed(
                dataset_id=uuid4(),
                client=sdk.client,
                body=BodyReuploadDatasetDatasetsDatasetIdReuploadPost(
                    file=File(payload=BytesIO(b"{}"), file_name="new.geojson")
                ),
            )
        )
        assert resp.status_code == 404, resp.content

    @pytest.mark.anyio
    async def test_ingest_and_reupload_reach_a_terminal_state_with_the_rows(
        self, client, admin_auth_header, test_db_session, ingested_datasets
    ) -> None:
        """Both commits run to ``complete``; the dataset holds the uploaded rows."""
        from app.api.main import app
        from app.processing.ingest.tasks_reupload import reupload_file
        from app.processing.ingest.tasks_vector import ingest_file
        from geolens.api.admin import get_job_status_jobs_job_id_get as get_job
        from geolens.api.datasets import (
            commit_import_ingest_commit_job_id_post as commit_import,
        )
        from geolens.api.datasets import (
            get_single_dataset_datasets_dataset_id_get as get_dataset,
        )
        from geolens.api.datasets import upload_file_ingest_upload_post
        from geolens.api.datasets_reupload import (
            reupload_commit_datasets_dataset_id_reupload_job_id_commit_post as commit_reupload,
        )
        from geolens.api.datasets_reupload import (
            reupload_dataset_datasets_dataset_id_reupload_post as reupload,
        )
        from geolens.api.features import (
            get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get as features,
        )
        from geolens.models.body_reupload_dataset_datasets_dataset_id_reupload_post import (
            BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
        )
        from geolens.models.body_upload_file_ingest_upload_post import (
            BodyUploadFileIngestUploadPost,
        )
        from geolens.models.commit_request import CommitRequest
        from geolens.types import File

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)
        worker = _InlineWorker(test_db_session)

        async def assert_complete_with(job_id, names: list[str], sent: bytes):
            job = await get_job.asyncio_detailed(job_id=job_id, client=sdk.client)
            assert job.status_code == 200, job.content
            assert job.parsed.status == "complete", job.parsed.error_message
            dataset_id = job.parsed.dataset_id
            dataset = await get_dataset.asyncio_detailed(
                dataset_id=dataset_id, client=sdk.client
            )
            assert dataset.parsed.feature_count == len(names)
            rows = await features.asyncio_detailed(
                dataset_id=dataset_id, client=sdk.client
            )
            assert rows.status_code == 200, rows.content
            assert sorted(
                f["properties"]["name"] for f in rows.parsed.to_dict()["features"]
            ) == sorted(names)
            assert worker.received[-1] == sent
            return dataset_id

        first = _collection(["a", "b", "c"])
        uploaded = await upload_file_ingest_upload_post.asyncio_detailed(
            client=sdk.client,
            body=BodyUploadFileIngestUploadPost(
                file=File(payload=BytesIO(first), file_name="rt.geojson")
            ),
        )
        assert uploaded.status_code == 201, uploaded.content
        with _commits_stay_queued():
            committed = await commit_import.asyncio_detailed(
                job_id=uploaded.parsed.job_id,
                client=sdk.client,
                body=CommitRequest(title=f"sdk-rt-{uuid4().hex[:8]}"),
            )
        assert committed.status_code == 202, committed.content
        await worker.run(ingest_file, uploaded.parsed.job_id)
        dataset_id = await assert_complete_with(
            uploaded.parsed.job_id, ["a", "b", "c"], first
        )
        ingested_datasets.append(dataset_id)

        second = _collection(["d", "e"])
        replaced = await reupload.asyncio_detailed(
            dataset_id=dataset_id,
            client=sdk.client,
            body=BodyReuploadDatasetDatasetsDatasetIdReuploadPost(
                file=File(payload=BytesIO(second), file_name="rt2.geojson")
            ),
        )
        assert replaced.status_code == 201, replaced.content
        with _commits_stay_queued():
            recommitted = await commit_reupload.asyncio_detailed(
                dataset_id=dataset_id,
                job_id=replaced.parsed.job_id,
                client=sdk.client,
                body=ReuploadCommitRequest(),
            )
        assert recommitted.status_code == 202, recommitted.content
        await worker.run(
            reupload_file, replaced.parsed.job_id, dataset_id=str(dataset_id)
        )
        assert (
            await assert_complete_with(replaced.parsed.job_id, ["d", "e"], second)
            == dataset_id
        )

    @pytest.mark.anyio
    async def test_icon_upload_and_png_endpoints_return_bytes(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """An uploaded icon is served back as bytes, and so is the sprite sheet."""
        from sqlalchemy import text

        from app.api.main import app
        from geolens.api.maps import (
            get_geolens_sprite_png_endpoint_maps_sprites_geolens_png_get as sprite_png,
        )
        from geolens.api.maps import (
            get_map_icon_asset_endpoint_maps_icons_icon_id_asset_get as icon_asset,
        )
        from geolens.api.maps import upload_map_icon_endpoint_maps_icons_post
        from geolens.models.body_upload_map_icon_endpoint_maps_icons_post import (
            BodyUploadMapIconEndpointMapsIconsPost,
        )
        from geolens.types import File

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'
        created = await upload_map_icon_endpoint_maps_icons_post.asyncio_detailed(
            client=sdk.client,
            body=BodyUploadMapIconEndpointMapsIconsPost(
                file=File(
                    payload=BytesIO(svg),
                    file_name="dot.svg",
                    mime_type="image/svg+xml",
                )
            ),
        )
        assert created.status_code == 201, created.content
        icon_id = created.parsed.id
        try:
            served = await icon_asset.asyncio_detailed(
                icon_id=icon_id, client=sdk.client
            )
            assert served.status_code == 200
            assert served.content.startswith(b"<svg")
            assert served.parsed.payload.read() == served.content

            sheet = await sprite_png.asyncio_detailed(client=sdk.client)
            assert sheet.status_code == 200
            assert sheet.content.startswith(b"\x89PNG\r\n\x1a\n")
            assert sheet.parsed.payload.read() == sheet.content
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text("DELETE FROM catalog.map_icon_assets WHERE id = :id"),
                {"id": icon_id},
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    @pytest.mark.skipif(not _UVICORN_AVAILABLE, reason="uvicorn not installed")
    @pytest.mark.parametrize("call", ["asyncio", "sync"])
    async def test_png_icon_and_sprite_bytes_in_both_call_styles(
        self, client, admin_auth_header, test_db_session, call: str
    ) -> None:
        """The icon asset and the sprite come back as the PNG bytes the server sent.

        ``sync`` goes over a real socket: ASGITransport has no sync counterpart.
        """
        from sqlalchemy import text

        from app.api.main import app
        from geolens.api.maps import (
            get_geolens_sprite_png_endpoint_maps_sprites_geolens_png_get as sprite_png,
        )
        from geolens.api.maps import (
            get_map_icon_asset_endpoint_maps_icons_icon_id_asset_get as icon_asset,
        )
        from geolens.api.maps import upload_map_icon_endpoint_maps_icons_post
        from geolens.models.body_upload_map_icon_endpoint_maps_icons_post import (
            BodyUploadMapIconEndpointMapsIconsPost,
        )
        from geolens.types import File

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        icon_png = _png()
        created = await upload_map_icon_endpoint_maps_icons_post.asyncio_detailed(
            client=sdk.client,
            body=BodyUploadMapIconEndpointMapsIconsPost(
                file=File(
                    payload=BytesIO(icon_png),
                    file_name="dot.png",
                    mime_type="image/png",
                )
            ),
        )
        assert created.status_code == 201, created.content
        icon_id = created.parsed.id
        try:
            async with _serving_over_http(app) as base_url:
                if call == "sync":
                    over_http = GeolensClient(base_url=base_url, bearer_token=token)
                    served = await asyncio.to_thread(
                        icon_asset.sync_detailed,
                        icon_id=icon_id,
                        client=over_http.client,
                    )
                    sheet = await asyncio.to_thread(
                        sprite_png.sync_detailed, client=over_http.client
                    )
                else:
                    served = await icon_asset.asyncio_detailed(
                        icon_id=icon_id, client=sdk.client
                    )
                    sheet = await sprite_png.asyncio_detailed(client=sdk.client)

            assert served.status_code == 200
            assert served.content == icon_png
            assert served.parsed.payload.read() == icon_png
            assert sheet.status_code == 200
            assert sheet.content.startswith(b"\x89PNG\r\n\x1a\n")
            assert sheet.parsed.payload.read() == sheet.content
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text("DELETE FROM catalog.map_icon_assets WHERE id = :id"),
                {"id": icon_id},
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_a_tileset_upload_body_carries_its_kind(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The generated multipart body sends a named file and kind, and the door takes them."""
        from sqlalchemy import select, text

        from app.platform.jobs.models import IngestJob
        from geolens.models.body_upload_file_ingest_upload_post import (
            BodyUploadFileIngestUploadPost,
        )
        from geolens.types import File
        from tests.tiles3d_archives import tileset_json, zip_bytes

        archive = zip_bytes([("tileset.json", tileset_json()), ("0/0.glb", b"glb")])
        parts = BodyUploadFileIngestUploadPost(
            file=File(
                payload=BytesIO(archive),
                file_name="campus.zip",
                mime_type="application/zip",
            ),
            kind="tiles3d",
        ).to_multipart()
        resp = await client.post(
            "/ingest/upload", files=parts, headers=admin_auth_header
        )
        assert resp.status_code == 201, resp.text
        job_id = resp.json()["job_id"]
        try:
            job = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert job.user_metadata["file_type"] == "tiles3d"
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_api_key_auth_mode(self, client, admin_auth_header) -> None:
        """X-API-Key works via the wrapper despite not being
        in the OpenAPI spec (only OAuth2PasswordBearer is advertised)."""
        from app.api.main import app
        from geolens.api.search import (
            search_datasets_endpoint_search_datasets_get,
        )

        # Create an API key for the admin user via the self-service endpoint
        create_resp = await client.post(
            "/auth/api-keys/",
            headers=admin_auth_header,
            json={"name": "round-trip-test-key"},
        )
        assert create_resp.status_code in (200, 201), create_resp.text
        api_key = create_resp.json()["key"]

        # Build SDK in api-key mode and route it through the in-process ASGI app
        sdk = GeolensClient(base_url="http://test", api_key=api_key)
        _wire_asgi_transport(sdk, app)

        resp = await search_datasets_endpoint_search_datasets_get.asyncio_detailed(
            client=sdk.client,
        )
        assert resp.status_code == 200, resp.content


# --------------------------- Round-trip test (TypeScript) ---------------------------


@pytest.mark.anyio
@pytest.mark.skipif(not _NODE_AVAILABLE, reason="node not available on this runner")
@pytest.mark.skipif(
    not _TS_SDK_BUILT,
    reason=(
        "TypeScript SDK not built (sdks/typescript/dist/index.js missing). "
        "Run `cd sdks/typescript && npm install && npm run build` first."
    ),
)
@pytest.mark.skipif(
    not _UVICORN_AVAILABLE,
    reason="uvicorn not installed (TS half needs a real HTTP server)",
)
async def test_typescript_round_trip(
    client, admin_auth_header, test_db_session
) -> None:
    """Spawn a Node subprocess that exercises the TypeScript SDK against a
    uvicorn instance bound to a free port on 127.0.0.1.

    Skip preconditions (node availability, TS SDK
    built, uvicorn importable) are evaluated at module import time and
    expressed as @pytest.mark.skipif decorators. The CI
    workflow ensures all three are present.
    """
    node = shutil.which("node")

    from sqlalchemy import text

    from app.api.main import app

    async with _serving_over_http(app) as base_url:
        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        env = os.environ.copy()
        env["GEOLENS_BASE_URL"] = base_url
        env["GEOLENS_TOKEN"] = token

        ts_test = _REPO_ROOT / "sdks" / "typescript" / "test" / "round_trip.test.mjs"
        assert ts_test.exists(), f"TS test script missing at {ts_test}"

        # Run the blocking subprocess in a worker thread so the asyncio event
        # loop can continue serving the uvicorn requests the subprocess makes.
        # subprocess.run blocks the calling thread; without to_thread, the
        # loop pauses, uvicorn stops processing, and the Node script's HTTP
        # calls hang until the timeout fires (deadlock).
        result = await asyncio.to_thread(
            subprocess.run,
            [node, str(ts_test)],
            env=env,
            cwd=_REPO_ROOT / "sdks" / "typescript",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"TS round-trip failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        match = re.search(r"^UPLOAD_JOB_ID=(\S+)$", result.stdout, re.MULTILINE)
        assert match, f"TS upload printed no job id:\n{result.stdout}"
        job_id = match.group(1)
        try:
            row = (
                await test_db_session.execute(
                    text(
                        "SELECT source_filename FROM catalog.ingest_jobs WHERE id = :id"
                    ),
                    {"id": job_id},
                )
            ).one()
            assert row.source_filename == "tiny.geojson"
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
            )
            await test_db_session.commit()


# ------------------- Ingest and PNG round trips (TypeScript) -------------------


@pytest.mark.skipif(
    not os.environ.get("GEOLENS_REQUIRE_TS_SDK"),
    reason="CI sets GEOLENS_REQUIRE_TS_SDK where the TypeScript tests must run",
)
def test_typescript_round_trip_prerequisites_are_present() -> None:
    """Where CI requires the TypeScript tests, a missing prerequisite fails."""
    assert _NODE_AVAILABLE, "node is not on PATH"
    assert _TS_SDK_BUILT, "sdks/typescript/dist/index.js is not built"
    assert _UVICORN_AVAILABLE, "uvicorn is not installed"


def _needs_typescript_sdk(test):
    for mark in (
        pytest.mark.skipif(not _NODE_AVAILABLE, reason="node not available"),
        pytest.mark.skipif(not _TS_SDK_BUILT, reason="TypeScript SDK not built"),
        pytest.mark.skipif(not _UVICORN_AVAILABLE, reason="uvicorn not installed"),
        pytest.mark.anyio,
    ):
        test = mark(test)
    return test


async def _run_ts_phase(base_url: str, token: str, *argv: str) -> str:
    """Run one phase of ingest_round_trip.test.mjs and return its stdout."""
    result = await asyncio.to_thread(
        subprocess.run,
        [
            shutil.which("node"),
            str(
                _REPO_ROOT
                / "sdks"
                / "typescript"
                / "test"
                / "ingest_round_trip.test.mjs"
            ),
            *argv,
        ],
        env={**os.environ, "GEOLENS_BASE_URL": base_url, "GEOLENS_TOKEN": token},
        cwd=_REPO_ROOT / "sdks" / "typescript",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"TS phase {argv} failed (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _printed(stdout: str, key: str) -> str:
    match = re.search(rf"^{key}=(\S+)$", stdout, re.MULTILINE)
    assert match, f"TS phase printed no {key}:\n{stdout}"
    return match.group(1)


@_needs_typescript_sdk
async def test_typescript_ingest_and_reupload_reach_a_terminal_state(
    client, admin_auth_header, test_db_session, ingested_datasets
) -> None:
    from app.api.main import app
    from app.processing.ingest.tasks_reupload import reupload_file
    from app.processing.ingest.tasks_vector import ingest_file

    token = admin_auth_header["Authorization"].removeprefix("Bearer ")
    worker = _InlineWorker(test_db_session)
    async with _serving_over_http(app) as base_url:
        with _commits_stay_queued():
            uploaded = await _run_ts_phase(base_url, token, "upload")
        job_id = _printed(uploaded, "UPLOAD_JOB_ID")
        await worker.run(ingest_file, job_id)
        verified = await _run_ts_phase(base_url, token, "verify", job_id, "a,b,c")
        dataset_id = _printed(verified, "DATASET_ID")
        ingested_datasets.append(dataset_id)
        assert worker.received[-1] == _collection(["a", "b", "c"])

        with _commits_stay_queued():
            replaced = await _run_ts_phase(
                base_url, token, "reupload", dataset_id, "d,e"
            )
        reupload_job_id = _printed(replaced, "REUPLOAD_JOB_ID")
        await worker.run(reupload_file, reupload_job_id, dataset_id=dataset_id)
        await _run_ts_phase(base_url, token, "verify", reupload_job_id, "d,e")
        assert worker.received[-1] == _collection(["d", "e"])


@_needs_typescript_sdk
async def test_typescript_png_icon_and_sprite_bytes(
    client, admin_auth_header, test_db_session
) -> None:
    from sqlalchemy import text

    from app.api.main import app

    token = admin_auth_header["Authorization"].removeprefix("Bearer ")
    icon_png = _png()
    uploaded = await client.post(
        "/maps/icons",
        files={"file": ("dot.png", icon_png, "image/png")},
        headers=admin_auth_header,
    )
    assert uploaded.status_code == 201, uploaded.text
    icon_id = uploaded.json()["id"]
    try:
        async with _serving_over_http(app) as base_url:
            await _run_ts_phase(
                base_url, token, "png", icon_id, base64.b64encode(icon_png).decode()
            )
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.map_icon_assets WHERE id = :id"), {"id": icon_id}
        )
        await test_db_session.commit()
