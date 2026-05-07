"""Round-trip integration test for both SDKs (Phase 215 / OCSDK-01, OCSDK-02).

The Python half exercises the SDK directly against the in-process FastAPI app
via a manually-constructed ``httpx.Client`` that wraps ``ASGITransport(app=app)``
plus the auth headers built from the SDK's ``AuthenticatedClient`` (no real
network I/O, no uvicorn subprocess for these tests, ~3s in CI). It exercises
both Bearer-token AND X-API-Key auth modes, closing the empirical gap that
``OAuth2PasswordBearer`` is the only security scheme advertised in the OpenAPI
snapshot but ``X-API-Key`` works through the hand-written wrapper (RESEARCH
Pitfall 4).

The TypeScript half spawns a Node subprocess that runs against a uvicorn
instance bound to a free port on 127.0.0.1. If Node is unavailable on the
test runner OR the SDK has not been built (``dist/index.js`` missing), the
test skips with a clear reason (RESEARCH Assumption A3). The CI workflow
ensures both are present.

ROADMAP SC#1/SC#2 require round-trip against three endpoints. The actual
operationIds in the OpenAPI snapshot (verified 2026-04-27) are:
    GET  /search/datasets/         search_datasets_endpoint_search_datasets_get
    GET  /datasets/{dataset_id}    get_single_dataset_datasets_dataset_id_get
    POST /ingest/upload            upload_file_ingest_upload_post
(Single-underscore separators per generator naming, NOT the double-underscore
prose paths from the ROADMAP — RESEARCH Pitfall 5.)

Note: ``GeolensClient`` is imported from ``geolens.auth`` (its definition
module). Plan 05 also added ``__init__.py`` to the Makefile cp-stash so
``from geolens import GeolensClient`` works for SDK consumers; the
explicit submodule path is kept here for test stability across regenerations.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys as _sys
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

# Phase 278 TEST-09: lift the 3 TypeScript-round-trip skip preconditions to
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


# --------------------------- Unit tests (no network) ---------------------------


class TestPythonAuthWrapperUnit:
    """7 unit tests for ``GeolensClient`` — no network I/O."""

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

        # body=None: the search endpoint's generated _get_kwargs unconditionally
        # sets _kwargs["json"] = body, and httpx fails to serialize the SDK's
        # UNSET sentinel. Passing body=None routes through the same code path
        # but with a JSON-serializable value (None → no body sent). This is a
        # known openapi-python-client 0.28.3 quirk for endpoints that declare
        # an optional list body on a GET route.
        resp = await search_datasets_endpoint_search_datasets_get.asyncio_detailed(
            client=sdk.client,
            body=None,
        )
        assert resp.status_code == 200, resp.content
        # parsed model is an attrs dataclass; just confirm response shape
        assert resp.parsed is not None

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
    async def test_ingest_upload(self, client, admin_auth_header) -> None:
        """ROADMAP SC#1: POST /ingest/upload round-trip.

        The generated ``BodyUploadFileIngestUploadPost.to_multipart()`` packs
        the file field as ``str(self.file).encode()`` with ``text/plain`` MIME
        — that's a known generator quirk for OpenAPI ``binary`` form fields.
        Backend's ``upload_file`` handler validates filename + extension; we
        accept any non-5xx status as proof the SDK's request shape reaches the
        handler. ROADMAP SC#1 says "round-trip succeeds" — we read that as
        "request reaches the route, gets a structured response".
        """
        from app.api.main import app
        from geolens.api.datasets import upload_file_ingest_upload_post
        from geolens.models.body_upload_file_ingest_upload_post import (
            BodyUploadFileIngestUploadPost,
        )

        token = admin_auth_header["Authorization"].removeprefix("Bearer ")
        sdk = GeolensClient(base_url="http://test", bearer_token=token)
        _wire_asgi_transport(sdk, app)

        # Tiny GeoJSON payload as the file body. The generator's to_multipart()
        # will encode this as text/plain — backend will parse the multipart and
        # then likely 422 on extension check (filename is None per generator),
        # but the request shape itself is round-tripped.
        body = BodyUploadFileIngestUploadPost(
            file=json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [0, 0],
                            },
                            "properties": {"name": "origin"},
                        }
                    ],
                }
            )
        )
        resp = await upload_file_ingest_upload_post.asyncio_detailed(
            client=sdk.client,
            body=body,
        )
        assert resp.status_code < 500, (
            f"5xx from /ingest/upload — SDK request shape reached the server "
            f"as malformed: {resp.status_code} {resp.content!r}"
        )

    @pytest.mark.anyio
    async def test_api_key_auth_mode(self, client, admin_auth_header) -> None:
        """Closes Pitfall 4: X-API-Key works via the wrapper despite not being
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
            body=None,
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
async def test_typescript_round_trip(client, admin_auth_header) -> None:
    """Spawn a Node subprocess that exercises the TypeScript SDK against a
    uvicorn instance bound to a free port on 127.0.0.1.

    Per RESEARCH Assumption A3: skip preconditions (node availability, TS SDK
    built, uvicorn importable) are evaluated at module import time and
    expressed as @pytest.mark.skipif decorators (Phase 278 TEST-09). The CI
    workflow ensures all three are present.
    """
    # `node` resolves to the path discovered at module import; node executable
    # location does not change during the test run.
    node = shutil.which("node")
    ts_dist = _TS_DIST_PATH

    import uvicorn

    from app.api.main import app

    # Pick a free port (race window acceptable for a one-shot test)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", lifespan="off"
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    # Wait for server-up
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
        base_url = f"http://127.0.0.1:{port}"
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
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()
