"""Titiler reads a remote raster only through the pinned API relay, and only as a TIFF.

The origins and the relay listen on loopback. The address policy refuses
loopback, so the one origin a test treats as public is mapped to it by name in
the pinned client's resolver; every other address keeps the real policy.
GDAL opens the relay address directly, standing in for Titiler.
"""

from __future__ import annotations

import ast
import secrets
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
import uvicorn
from fastapi import FastAPI
from rasterio.transform import from_origin

from app.platform import security
from app.platform.http import remote_raster
from app.platform.storage import raster_relay
from app.platform.storage.raster_relay import (
    is_relay_url,
    issue_relay_token,
    read_relay_token,
    relay_url,
)
from app.platform.storage.titiler_url import (
    RemoteRasterPathError,
    build_titiler_cog_url,
    resolve_open_path,
    resolve_titiler_source,
)
from app.processing.raster.validation import validate_sources
from app.processing.raster.vrt import resolve_vrt_source_path
from app.processing.tiles.raster_relay import router as relay_router

_APP_ROOT = Path(__file__).resolve().parent.parent / "app"
_PUBLIC_HOST = "origin.example.test"
# What the Titiler service sets for GDAL in both Compose files.
_TITILER_GDAL_ENV = {
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.cog,.vrt",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_VRT_ENABLE_RAWRASTERBAND": "NO",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "VSI_CACHE": "TRUE",
    "GDAL_HTTP_MAX_RETRY": "0",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Origin:
    """A loopback HTTP origin with Range support that records every request."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.redirects: dict[str, str] = {}
        # Misbehaviours, by path: a false Content-Range start, a full body for
        # any Range, and a body sent one byte at a time.
        self.claimed_starts: dict[str, int] = {}
        self.ignore_range: set[str] = set()
        self.trickle: set[str] = set()
        self.overrun: set[str] = set()
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.port = 0

    def url(self, path: str, host: str = _PUBLIC_HOST) -> str:
        return f"http://{host}:{self.port}{path}"


@contextmanager
def _origin() -> Iterator[_Origin]:
    origin = _Origin()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _serve(self, with_body: bool) -> None:
            origin.requests.append((self.command, self.path, dict(self.headers)))
            if self.path in origin.redirects:
                self.send_response(302)
                self.send_header("Location", origin.redirects[self.path])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = origin.files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            status, start, end = 200, 0, len(body) - 1
            requested = self.headers.get("Range", "")
            if requested.startswith("bytes=") and self.path not in origin.ignore_range:
                first, _, last = requested[len("bytes=") :].partition("-")
                start = int(first)
                end = min(int(last) if last else end, len(body) - 1)
                status = 206
            chunk = body[start : end + 1]
            self.send_response(status)
            if self.path in origin.overrun:
                # No length, and the whole rest of the file after the span.
                claimed_end = end
                chunk = body[start:]
            else:
                claimed_end = None
                self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                claimed = origin.claimed_starts.get(self.path, start)
                last = (
                    claimed_end if claimed_end is not None else claimed + len(chunk) - 1
                )
                self.send_header("Content-Range", f"bytes {claimed}-{last}/{len(body)}")
            self.end_headers()
            if with_body and self.path in origin.trickle:
                for index in range(len(chunk)):
                    self.wfile.write(chunk[index : index + 1])
                    self.wfile.flush()
                    time.sleep(0.2)
            elif with_body:
                self.wfile.write(chunk)

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler contract
            self._serve(False)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            self._serve(True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    origin.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def public_origin(monkeypatch) -> Iterator[_Origin]:
    """An origin the pinned client treats as public; nothing else changes."""
    real = security._resolve_all_and_validate

    async def resolve(host, port):
        if host == _PUBLIC_HOST:
            return ["127.0.0.1"]
        return await real(host, port)

    monkeypatch.setattr(security, "_resolve_all_and_validate", resolve)
    with _origin() as origin:
        yield origin


@pytest.fixture
def private_origin() -> Iterator[_Origin]:
    with _origin() as origin:
        yield origin


@pytest.fixture
def relay_base(monkeypatch) -> Iterator[str]:
    """The relay route served over real HTTP, so GDAL can open it."""
    app = FastAPI()
    app.include_router(relay_router)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "relay server did not start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    from app.core.config import settings

    monkeypatch.setattr(settings, "remote_raster_relay_base_url", base)
    try:
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _cog_bytes(tmp_path: Path, value: int) -> bytes:
    path = tmp_path / f"cog-{value}.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 64, 1, 1),
        tiled=True,
        blockxsize=32,
        blockysize=32,
    ) as dataset:
        dataset.write(np.full((1, 64, 64), value, dtype="uint8"))
    return path.read_bytes()


def _gdal_read(address: str):
    with rasterio.Env(**_TITILER_GDAL_ENV), rasterio.open(address) as dataset:
        return dataset.driver, dataset.read(1)


# ---------------------------------------------------------------------------
# GDAL through the relay
# ---------------------------------------------------------------------------


def test_a_remote_cog_renders_through_the_relay(public_origin, relay_base, tmp_path):
    public_origin.files["/scene.tif"] = _cog_bytes(tmp_path, 42)

    driver, pixels = _gdal_read(relay_url(public_origin.url("/scene.tif"), None))

    assert driver == "GTiff"
    assert (pixels == 42).all()
    assert public_origin.requests
    assert all(path == "/scene.tif" for _, path, _ in public_origin.requests)


def test_a_remote_file_holding_vrt_xml_is_refused(
    public_origin, private_origin, relay_base, tmp_path
):
    secret = tmp_path / "secret.tif"
    secret.write_bytes(_cog_bytes(tmp_path, 77))
    private_origin.files["/inner.tif"] = _cog_bytes(tmp_path, 1)
    public_origin.files[
        "/entry.tif"
    ] = f"""<VRTDataset rasterXSize="64" rasterYSize="64">
<VRTRasterBand dataType="Byte" band="1">
<SimpleSource><SourceFilename>{secret}</SourceFilename><SourceBand>1</SourceBand></SimpleSource>
<SimpleSource><SourceFilename>/vsicurl/{private_origin.url("/inner.tif", "127.0.0.1")}</SourceFilename><SourceBand>1</SourceBand></SimpleSource>
</VRTRasterBand></VRTDataset>""".encode()

    with pytest.raises(rasterio.errors.RasterioIOError):
        _gdal_read(relay_url(public_origin.url("/entry.tif"), None))

    assert private_origin.requests == []


def test_a_redirect_to_a_private_address_is_refused(
    public_origin, private_origin, relay_base, tmp_path
):
    private_origin.files["/internal.tif"] = _cog_bytes(tmp_path, 9)
    public_origin.redirects["/moved.tif"] = private_origin.url(
        "/internal.tif", "127.0.0.1"
    )
    address = relay_url(public_origin.url("/moved.tif"), None)

    with pytest.raises(rasterio.errors.RasterioIOError):
        _gdal_read(address)
    assert httpx.get(address, headers={"Range": "bytes=0-15"}).status_code == 403

    assert private_origin.requests == []


def test_a_private_origin_is_refused_at_the_first_hop(private_origin, relay_base):
    private_origin.files["/internal.tif"] = b"II*\x00" + b"\x00" * 60
    address = relay_url(private_origin.url("/internal.tif", "127.0.0.1"), None)

    assert httpx.get(address, headers={"Range": "bytes=0-15"}).status_code == 403
    assert private_origin.requests == []


# ---------------------------------------------------------------------------
# The relay's request and response shape
# ---------------------------------------------------------------------------


def test_only_the_range_reaches_the_origin(public_origin, relay_base, tmp_path):
    body = _cog_bytes(tmp_path, 5)
    public_origin.files["/scene.tif"] = body

    response = httpx.get(
        relay_url(public_origin.url("/scene.tif"), uuid.uuid4()),
        headers={
            "Range": "bytes=0-15",
            "Authorization": "Bearer caller-secret",
            "Cookie": "session=caller-secret",
            "X-Esri-Authorization": "Bearer caller-secret",
        },
    )

    assert response.status_code == 206
    assert response.content == body[:16]
    assert response.headers["content-range"] == f"bytes 0-15/{len(body)}"
    [(_, _, sent)] = public_origin.requests
    assert sent["Range"] == "bytes=0-15"
    assert "caller-secret" not in repr(sent)


def test_head_reports_the_size(public_origin, relay_base, tmp_path):
    body = _cog_bytes(tmp_path, 5)
    public_origin.files["/scene.tif"] = body

    response = httpx.head(relay_url(public_origin.url("/scene.tif"), None))

    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(body))
    [(method, _, sent)] = public_origin.requests
    assert (method, sent["Range"]) == ("GET", "bytes=0-0")


def test_a_later_range_is_served_without_a_signature_check(
    public_origin, relay_base, tmp_path
):
    body = _cog_bytes(tmp_path, 5)
    public_origin.files["/scene.tif"] = body

    response = httpx.get(
        relay_url(public_origin.url("/scene.tif"), None),
        headers={"Range": "bytes=100-199"},
    )

    assert response.status_code == 206
    assert response.content == body[100:200]


@pytest.mark.parametrize("header", ["bytes=-16", "bytes=0-1,4-5", "items=0-1"])
def test_other_range_forms_are_refused(public_origin, relay_base, header):
    public_origin.files["/scene.tif"] = b"II*\x00" + b"\x00" * 60

    response = httpx.get(
        relay_url(public_origin.url("/scene.tif"), None), headers={"Range": header}
    )

    assert response.status_code == 416
    assert public_origin.requests == []


def test_a_response_past_the_size_cap_is_refused(
    public_origin, relay_base, tmp_path, monkeypatch
):
    monkeypatch.setattr(remote_raster, "MAX_RELAY_RESPONSE_BYTES", 1024)
    public_origin.files["/scene.tif"] = _cog_bytes(tmp_path, 5)

    response = httpx.get(relay_url(public_origin.url("/scene.tif"), None))

    assert response.status_code == 403


def test_an_unsigned_or_expired_token_is_not_served(public_origin, relay_base):
    public_origin.files["/scene.tif"] = b"II*\x00" + b"\x00" * 60
    url = public_origin.url("/scene.tif")
    expired = issue_relay_token(url, None, now=time.time() - 3 * 3600)
    forged = issue_relay_token(url, None)[:-4] + "AAAA"

    for token in (expired, forged, "not-a-token"):
        response = httpx.get(f"{relay_base}/internal/raster-relay/{token}/raster.tif")
        assert response.status_code == 404
    response = httpx.get(
        f"{relay_base}/internal/raster-relay/{issue_relay_token(url, None)}/x.tif.ovr"
    )
    assert response.status_code == 404
    assert public_origin.requests == []


# ---------------------------------------------------------------------------
# Tokens and the Titiler URL seam
# ---------------------------------------------------------------------------


def test_a_token_carries_its_claims_without_the_url_in_plaintext():
    url = "https://stac.example.com/a.tif?X-Amz-Signature=presigned"
    dataset_id = uuid.uuid4()
    now = 1_800_000_000

    token = issue_relay_token(url, dataset_id, now=now)

    assert read_relay_token(token, now=now) == (url, dataset_id)
    assert "stac.example.com" not in token and "presigned" not in token
    assert issue_relay_token(url, dataset_id, now=now + 60) == token
    assert issue_relay_token(url + "&x", dataset_id, now=now) != token
    assert read_relay_token(token, now=now + 2 * 3600) is None


def test_a_token_from_another_secret_is_refused(monkeypatch):
    from app.core.config import settings

    token = issue_relay_token("https://stac.example.com/a.tif", None)
    monkeypatch.setattr(
        settings, "jwt_secret_key", type(settings.jwt_secret_key)(secrets.token_hex(32))
    )

    assert read_relay_token(token) is None


@pytest.mark.parametrize(
    "remote",
    [
        "https://stac.example.com/a.tif",
        "HTTP://stac.example.com/a.tif",
        "/vsicurl/https://stac.example.com/a.tif",
        "/vsicurl_streaming/https://stac.example.com/a.tif",
    ],
)
def test_titiler_is_never_handed_a_remote_url(remote):
    with pytest.raises(RemoteRasterPathError):
        build_titiler_cog_url("info", query={"url": remote})


def test_a_source_url_may_not_ride_in_the_raw_suffix():
    with pytest.raises(RemoteRasterPathError):
        build_titiler_cog_url(
            "info",
            query={"url": "/vsis3/bucket/a.tif"},
            raw_query_suffix="bidx=1&URL=https%3A%2F%2Fstac.example.com%2Fa.tif",
        )


def test_a_remote_asset_becomes_a_relay_address():
    url = "https://stac.example.com/a.tif"

    source = resolve_titiler_source(url, dataset_id=uuid.uuid4())

    assert is_relay_url(source)
    assert "stac.example.com" not in source
    assert build_titiler_cog_url("info", query={"url": source})


@pytest.mark.parametrize(
    ("provider", "extra"),
    [
        ("local", {}),
        ("s3", {"s3_bucket": "bkt"}),
        ("azure", {"azure_storage_container": "c"}),
    ],
)
def test_managed_assets_keep_their_storage_path(monkeypatch, provider, extra):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_provider", provider)
    for name, value in extra.items():
        monkeypatch.setattr(settings, name, value)
    key = "rasters/abc/cog.tif"

    source = resolve_titiler_source(key, dataset_id=uuid.uuid4())

    assert source == resolve_open_path(key)
    assert not is_relay_url(source)
    assert build_titiler_cog_url("info", query={"url": source})


def _calls_to(name: str) -> list[Path]:
    callers = []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                called = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else getattr(func, "id", None)
                )
                if called == name:
                    callers.append(path.relative_to(_APP_ROOT))
                    break
    return callers


def test_only_the_seam_builds_titiler_urls():
    """Titiler URLs come from build_titiler_cog_url, which refuses remote sources."""
    readers, cog_paths = [], []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "titiler_base_url":
                readers.append(path.relative_to(_APP_ROOT))
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "/cog/" in node.value
                and "\n" not in node.value
            ):
                cog_paths.append(path.relative_to(_APP_ROOT))
    seam = Path("platform/storage/titiler_url.py")

    assert set(readers) == {seam}
    assert set(cog_paths) == {seam}
    assert len(_calls_to("build_titiler_cog_url")) >= 2  # positive control


def test_only_the_seam_the_vrt_builder_and_the_mosaic_check_resolve_open_paths():
    """Any other caller could hand GDAL a path without the relay deciding."""
    assert set(_calls_to("resolve_open_path")) == {
        Path("platform/storage/titiler_url.py"),
        Path("processing/raster/vrt.py"),
        # Resolves a stored mosaic's relative source names; opens nothing.
        Path("processing/tiles/remote_sources.py"),
    }


# ---------------------------------------------------------------------------
# VRT members
# ---------------------------------------------------------------------------


class _Source:
    def __init__(self, storage_backend: str) -> None:
        self.id = uuid.uuid4()
        self.storage_backend = storage_backend


def test_a_remote_raster_is_refused_as_a_vrt_member():
    remote, managed = _Source("remote"), _Source("local")

    errors = validate_sources("mosaic", [remote], {})

    assert [(e.source_id, e.code) for e in errors] == [(remote.id, "remote_source")]
    assert validate_sources("mosaic", [managed], {}) == []


def test_a_vrt_build_refuses_a_remote_member():
    with pytest.raises(ValueError, match="can't be a VRT member"):
        resolve_vrt_source_path("https://stac.example.com/a.tif")


def test_relay_addresses_use_the_configured_base(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "remote_raster_relay_base_url", "http://api.internal:9000/"
    )

    address = relay_url("https://stac.example.com/a.tif", None)

    assert address.startswith("http://api.internal:9000/internal/raster-relay/")
    assert address.endswith("/raster.tif")
    assert raster_relay.is_relay_url(address)
    assert not raster_relay.is_relay_url(address.replace("raster.tif", "x.tif"))


# ---------------------------------------------------------------------------
# Probing an asset through Titiler
# ---------------------------------------------------------------------------


def _titiler_answers(monkeypatch, status: int, seen: list[str]) -> None:
    from types import SimpleNamespace

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, json={"count": 1, "dtype": "uint8"})

    monkeypatch.setattr(
        "app.modules.catalog.sources.cog_info.httpx",
        SimpleNamespace(
            AsyncClient=lambda *a, **k: httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
            Timeout=httpx.Timeout,
        ),
    )


@pytest.mark.anyio
async def test_titiler_is_asked_for_the_relay_address(monkeypatch):
    from app.modules.catalog.sources.cog_info import fetch_cog_info

    seen: list[str] = []
    _titiler_answers(monkeypatch, 200, seen)

    assert (await fetch_cog_info("https://stac.example.com/a.tif"))["dtype"] == "uint8"
    assert seen and all("stac.example.com" not in url for url in seen)
    assert all("raster-relay" in httpx.URL(url).params["url"] for url in seen)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (remote_raster.RemoteRasterFormat.OTHER, {"not_geotiff": True}),
        (remote_raster.RemoteRasterFormat.UNREACHABLE, None),
    ],
)
async def test_a_failed_read_says_whether_the_asset_is_a_tiff(
    monkeypatch, verdict, expected
):
    from app.modules.catalog.sources import cog_info

    _titiler_answers(monkeypatch, 500, [])

    async def format_of(url):
        return verdict

    monkeypatch.setattr(cog_info, "remote_raster_format", format_of)

    assert await cog_info.fetch_cog_info("https://stac.example.com/a.tif") == expected


@pytest.mark.anyio
async def test_a_remote_vrt_is_refused_without_a_read(monkeypatch):
    from app.modules.catalog.sources.cog_info import fetch_cog_info, import_refusal

    seen: list[str] = []
    _titiler_answers(monkeypatch, 200, seen)

    probed = await fetch_cog_info("https://stac.example.com/mosaic.VRT?sig=1")

    assert probed == {"not_geotiff": True}
    assert "GeoTIFF or COG" in import_refusal(probed)
    assert seen == []


@pytest.mark.anyio
async def test_the_format_probe_reads_four_bytes(public_origin, tmp_path):
    public_origin.files["/scene.tif"] = _cog_bytes(tmp_path, 5)
    public_origin.files["/page.tif"] = b"<html>not a raster</html>"

    tiff = await remote_raster.remote_raster_format(public_origin.url("/scene.tif"))
    other = await remote_raster.remote_raster_format(public_origin.url("/page.tif"))
    gone = await remote_raster.remote_raster_format(public_origin.url("/none.tif"))

    assert (tiff, other, gone) == (
        remote_raster.RemoteRasterFormat.TIFF,
        remote_raster.RemoteRasterFormat.OTHER,
        remote_raster.RemoteRasterFormat.UNREACHABLE,
    )
    assert {headers["Range"] for _, _, headers in public_origin.requests} == {
        "bytes=0-3"
    }


def test_the_public_edge_does_not_reach_internal_routes():
    """nginx answers /api/internal/ itself, ahead of the /api/ proxy and its regex
    locations."""
    import re

    from tests.repo_paths import repo_root

    conf = (repo_root(__file__) / "frontend" / "nginx.conf").read_text()
    lines = [line for line in conf.splitlines() if not line.lstrip().startswith("#")]
    match = re.search(
        r"location\s+\^~\s+/api/internal/\s*\{\s*return\s+404;\s*\}", "\n".join(lines)
    )

    assert match is not None
    assert raster_relay.RELAY_ROUTE_PREFIX.startswith("/internal/")


# ---------------------------------------------------------------------------
# What the origin says about its own response
# ---------------------------------------------------------------------------


def _vrt_xml_naming(private_origin: _Origin, secret: Path) -> bytes:
    return f"""<VRTDataset rasterXSize="64" rasterYSize="64">
<VRTRasterBand dataType="Byte" band="1">
<SimpleSource><SourceFilename>{secret}</SourceFilename><SourceBand>1</SourceBand></SimpleSource>
<SimpleSource><SourceFilename>/vsicurl/{private_origin.url("/inner.tif", "127.0.0.1")}</SourceFilename><SourceBand>1</SourceBand></SimpleSource>
</VRTRasterBand></VRTDataset>""".encode()


def test_a_range_answered_from_a_later_start_is_refused(
    public_origin, private_origin, relay_base, tmp_path
):
    secret = tmp_path / "secret.tif"
    secret.write_bytes(_cog_bytes(tmp_path, 77))
    private_origin.files["/inner.tif"] = _cog_bytes(tmp_path, 1)
    public_origin.files["/entry.tif"] = b"II*\x00" + _vrt_xml_naming(
        private_origin, secret
    )
    # Every 206 claims to start four bytes on, past the signature, while its
    # body still begins at byte 0.
    public_origin.claimed_starts["/entry.tif"] = 4
    address = relay_url(public_origin.url("/entry.tif"), None)

    response = httpx.get(address, headers={"Range": "bytes=0-16383"})
    with pytest.raises(rasterio.errors.RasterioIOError):
        _gdal_read(address)

    assert response.status_code == 403
    assert private_origin.requests == []


@pytest.mark.parametrize(
    ("requested", "status", "content_range", "allowed"),
    [
        ((0, 15), 206, "bytes 0-15/64", 16),
        ((8, 9), 206, "bytes 8-9/64", 2),
        ((8, 9), 206, "bytes 8-12/64", None),
        ((8, 9), 206, "bytes 9-9/64", None),
        ((8, None), 206, "bytes 8-63/64", 56),
        ((8, None), 200, None, None),
        (None, 206, "bytes 0-63/64", None),
        (None, 200, None, remote_raster.MAX_RELAY_RESPONSE_BYTES),
        ((0, 15), 206, "bytes */64", None),
    ],
)
def test_a_response_must_answer_the_range_asked_for(
    requested, status, content_range, allowed
):
    asked = remote_raster.ByteRange(*requested) if requested else None
    headers = {"Content-Range": content_range} if content_range else {}
    response = httpx.Response(status, headers=headers)

    if allowed is None:
        with pytest.raises(remote_raster.RemoteRasterRefused):
            remote_raster.check_range_response(response, asked)
    else:
        assert remote_raster.check_range_response(response, asked) == allowed


def test_a_full_body_for_a_later_range_is_refused(public_origin, relay_base, tmp_path):
    public_origin.files["/scene.tif"] = _cog_bytes(tmp_path, 5)
    public_origin.ignore_range.add("/scene.tif")

    later = httpx.get(
        relay_url(public_origin.url("/scene.tif"), None),
        headers={"Range": "bytes=100-199"},
    )
    first = httpx.get(
        relay_url(public_origin.url("/scene.tif"), None),
        headers={"Range": "bytes=0-99"},
    )

    assert later.status_code == 403
    assert first.status_code == 200


def test_a_trickling_origin_is_cut_off_at_the_deadline(
    public_origin, relay_base, monkeypatch
):
    monkeypatch.setattr(remote_raster, "RELAY_DEADLINE_SECONDS", 1.0)
    public_origin.files["/scene.tif"] = b"II*\x00" + b"\x00" * 60
    public_origin.trickle.add("/scene.tif")
    started = time.monotonic()

    with pytest.raises(httpx.HTTPError):
        httpx.get(
            relay_url(public_origin.url("/scene.tif"), None),
            headers={"Range": "bytes=0-63"},
            timeout=10,
        ).raise_for_status()

    assert time.monotonic() - started < 5


def test_a_proxied_request_is_not_served(public_origin, relay_base):
    public_origin.files["/scene.tif"] = b"II*\x00" + b"\x00" * 60
    address = relay_url(public_origin.url("/scene.tif"), None)

    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
        response = httpx.get(address, headers={header: "203.0.113.9"})
        assert response.status_code == 404
    assert public_origin.requests == []


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/vsis3/another-bucket/rasters/a.tif",
        "/app/staging-other/a.tif",
        "rasters/a.tif",
    ],
)
def test_titiler_opens_only_the_managed_prefix(monkeypatch, path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(settings, "upload_staging_dir", "/app/staging")
    for value in (path, f"/app/staging/../{path.lstrip('/')}"):
        with pytest.raises(RemoteRasterPathError):
            build_titiler_cog_url("info", query={"url": value})
    assert build_titiler_cog_url("info", query={"url": "/app/staging/rasters/a.tif"})


def test_no_module_names_titiler_outside_the_seam():
    """A hard-coded Titiler host or an environment read would bypass the seam."""
    allowed = {Path("platform/storage/titiler_url.py"), Path("core/config.py")}
    offenders = []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        relative = path.relative_to(_APP_ROOT)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            text = node.value
            if "\n" in text:
                continue
            if "titiler:" in text.lower() or "TITILER" in text:
                if relative not in allowed:
                    offenders.append((str(relative), text))
    assert offenders == []


def test_a_body_without_a_length_is_cut_at_the_checked_span(
    public_origin, relay_base, tmp_path
):
    body = _cog_bytes(tmp_path, 5)
    public_origin.files["/scene.tif"] = body
    public_origin.overrun.add("/scene.tif")

    with httpx.stream(
        "GET",
        relay_url(public_origin.url("/scene.tif"), None),
        headers={"Range": "bytes=0-15"},
    ) as response:
        received = b""
        try:
            for chunk in response.iter_raw():
                received += chunk
        except httpx.HTTPError:
            pass

    assert response.status_code == 206
    assert received == body[:16]
