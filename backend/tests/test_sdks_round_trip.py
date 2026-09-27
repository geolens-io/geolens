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
import re
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
from geolens.models.stac_item_summary import StacItemSummary  # noqa: E402
from geolens.types import UNSET  # noqa: E402

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
            headers={"X-Custom-Header": secrets["header"]},
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
    def test_storage_redirects_are_followed_without_credentials(
        self, storage: _Storage, mode: str
    ) -> None:
        mirror = "https://mirror.test/cog.tif"
        storage.respond = lambda request: (
            httpx.Response(307, headers={"Location": mirror})
            if request.url.host == "storage.test"
            else httpx.Response(200, content=self._BODY)
        )
        client, _ = self._client(self._redirect_to(self._STORAGE_URL))

        assert self._download(mode, client).payload.read() == self._BODY
        assert [str(request.url) for request in storage.seen] == [
            self._STORAGE_URL,
            mirror,
        ]
        assert all("X-API-Key" not in request.headers for request in storage.seen)

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
    """fix(#1277 review): an omitted body must not reach httpx as UNSET.

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

        # fix(#1666): this used to need an explicit body=None. The endpoint
        # declared `keywords` as an optional list BODY on a GET, so the generated
        # _get_kwargs unconditionally set _kwargs["json"] = body and httpx could
        # not serialize the SDK's UNSET sentinel. `keywords` is a query parameter
        # now, the generated function takes no body at all, and the call is
        # simply the call.
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
    async def test_a_tileset_upload_body_carries_its_kind(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The generated multipart body sends kind, and the upload door takes it."""
        from sqlalchemy import select, text

        from app.platform.jobs.models import IngestJob
        from geolens.models.body_upload_file_ingest_upload_post import (
            BodyUploadFileIngestUploadPost,
        )
        from tests.tiles3d_archives import tileset_json, zip_bytes

        parts = BodyUploadFileIngestUploadPost(file="", kind="tiles3d").to_multipart()
        kind = [part for part in parts if part[0] == "kind"]
        assert [(name, value[1]) for name, value in kind] == [("kind", b"tiles3d")]

        # The generator sends `file` as a text field, so a named .zip part
        # stands in for it; the kind part goes as the SDK built it.
        archive = zip_bytes([("tileset.json", tileset_json()), ("0/0.glb", b"glb")])
        resp = await client.post(
            "/ingest/upload",
            files=[("file", ("campus.zip", archive, "application/zip")), *kind],
            headers=admin_auth_header,
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
