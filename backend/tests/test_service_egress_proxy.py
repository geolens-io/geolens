"""A service import connects only to the hosts the URL checks allow.

GDAL resolves host names and follows redirects itself, so a service import or
preview runs its subprocess with every HTTP request routed through
``service_egress_proxy``. The proxy resolves each connection once, applies the
address policy ``validate_url_for_ssrf`` applies, and connects to the address
it checked, redirect hops included. A failed service import reports the
failure class and keeps GDAL's own text, which can quote the service, in the
log.

The fixture services listen on loopback, which the policy refuses, so tests
that need an allowed service map one test host name to loopback in the
proxy's resolver and leave every other name to the real policy.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import structlog
from sqlalchemy import select, text

from app.modules.catalog.sources.preview import run_service_preview
from app.platform import egress_proxy
from app.platform.egress_proxy import ServiceEgress, service_egress_proxy
from app.platform.gdal_env import gdal_service_safe_env
from app.platform.jobs.models import IngestJob
from app.processing.ingest.ogr import (
    SERVICE_ADDRESS_REFUSED,
    IngestionError,
    build_pg_conn_str,
    run_ogr2ogr_service,
)
from app.platform.security import _SSRFGuardTransport, make_safe_client
from app.processing.ingest.tasks import reupload_service
from app.processing.ingest.tasks_common import _run_service_import_with_wfs_fallback
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

needs_ogr = pytest.mark.skipif(
    shutil.which("ogrinfo") is None or shutil.which("ogr2ogr") is None,
    reason="needs the GDAL command line tools",
)

_HOST = "wfs.example.test"
_LAYER = "app:parcels"

_CAPABILITIES = """<?xml version="1.0" encoding="UTF-8"?>
<wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1">
 <wfs:FeatureTypeList><wfs:FeatureType>
  <wfs:Name xmlns:app="http://example.test/app">app:parcels</wfs:Name>
  <wfs:Title>{title}</wfs:Title>
  <wfs:DefaultCRS>urn:ogc:def:crs:EPSG::4326</wfs:DefaultCRS>
  <ows:WGS84BoundingBox><ows:LowerCorner>0 0</ows:LowerCorner>
  <ows:UpperCorner>2 2</ows:UpperCorner></ows:WGS84BoundingBox>
 </wfs:FeatureType></wfs:FeatureTypeList>
</wfs:WFS_Capabilities>"""

_SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:app="http://example.test/app"
 targetNamespace="http://example.test/app" elementFormDefault="qualified">
 <xsd:import namespace="http://www.opengis.net/gml/3.2"
  schemaLocation="http://schemas.opengis.net/gml/3.2.1/gml.xsd"/>
 <xsd:element name="parcels" type="app:parcelsType"
  substitutionGroup="gml:AbstractFeature"/>
 <xsd:complexType name="parcelsType"><xsd:complexContent>
  <xsd:extension base="gml:AbstractFeatureType"><xsd:sequence>
   <xsd:element name="name" type="xsd:string" minOccurs="0"/>
   <xsd:element name="geom" type="gml:PointPropertyType" minOccurs="0"/>
  </xsd:sequence></xsd:extension>
 </xsd:complexContent></xsd:complexType>
</xsd:schema>"""

_FEATURES = """<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:app="http://example.test/app"
 numberMatched="1" numberReturned="1">
 <wfs:member><app:parcels gml:id="parcels.1"><app:name>one</app:name>
  <app:geom><gml:Point srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>1 2</gml:pos>
  </gml:Point></app:geom>
 </app:parcels></wfs:member>
</wfs:FeatureCollection>"""

_HITS = """<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
 numberMatched="1" numberReturned="0"/>"""

_EXCEPTION_REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">
 <ows:Exception exceptionCode="NoApplicableCode">
  <ows:ExceptionText>{text}</ows:ExceptionText>
 </ows:Exception>
</ows:ExceptionReport>"""


@contextmanager
def _wfs_service(
    *,
    title: str = "Parcels",
    redirect_to: str | None = None,
    exception_text: str | None = None,
    status: int | None = None,
) -> Iterator[tuple[int, list[str]]]:
    """A WFS 2.0 service on loopback; yields its port and the requests it got."""
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            query = parse_qs(urlsplit(self.path).query)
            params = {key.lower(): values[0] for key, values in query.items()}
            operation = params.get("request", "").lower()
            requests.append(operation)
            if status is not None:
                self.send_error(status)
                return
            if redirect_to is not None:
                self.send_response(302)
                self.send_header("Location", redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if exception_text is not None:
                body = _EXCEPTION_REPORT.format(text=exception_text)
            elif operation == "getcapabilities":
                body = _CAPABILITIES.format(title=title)
            elif operation == "describefeaturetype":
                body = _SCHEMA
            elif operation == "getfeature":
                body = _HITS if params.get("resulttype") == "hits" else _FEATURES
            else:
                self.send_error(400)
                return
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def resolver_calls(monkeypatch) -> list[str]:
    """Map the test host to loopback; every other name meets the real policy."""
    calls: list[str] = []
    real = egress_proxy._resolve_and_validate

    async def resolve(host: str, port: int | None) -> str:
        calls.append(host)
        if host == _HOST:
            return "127.0.0.1"
        return await real(host, port)

    monkeypatch.setattr(egress_proxy, "_resolve_and_validate", resolve)
    return calls


async def _exchange(egress: ServiceEgress, raw: bytes) -> bytes:
    """Send ``raw`` to the proxy and read until it closes the connection."""
    address = urlsplit(egress.address)
    reader, writer = await asyncio.open_connection(address.hostname, address.port)
    try:
        writer.write(raw)
        await writer.drain()
        return await asyncio.wait_for(reader.read(), 10)
    finally:
        writer.close()


async def _open(
    egress: ServiceEgress,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    address = urlsplit(egress.address)
    return await asyncio.open_connection(address.hostname, address.port)


@contextmanager
def _silent_upstream() -> Iterator[tuple[int, asyncio.Event]]:
    """A loopback server that accepts and never answers; the event is set
    when the proxy closes its side."""
    listener = socket.create_server(("127.0.0.1", 0))
    closed = asyncio.Event()
    loop = asyncio.get_running_loop()

    def accept() -> None:
        conn, _ = listener.accept()
        with conn:
            while conn.recv(4096):
                pass
        loop.call_soon_threadsafe(closed.set)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], closed
    finally:
        listener.close()


def _get(url: str, host: str) -> bytes:
    return (
        f"GET {url} HTTP/1.1\r\nHost: {host}\r\nProxy-Connection: Keep-Alive\r\n"
        "Accept: */*\r\n\r\n"
    ).encode()


class TestTheProxyRelaysOnlyToCheckedAddresses:
    async def test_an_allowed_host_is_relayed_in_origin_form(self, resolver_calls):
        """The origin asks to keep its connection open; libcurl is told to
        close, and closing ends the relay without waiting on the origin."""
        seen: list[tuple[str, str | None, str | None]] = []
        released = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                seen.append(
                    (
                        self.path,
                        self.headers.get("Host"),
                        self.headers.get("Proxy-Connection"),
                    )
                )
                self.send_response(200)
                self.send_header("Content-Length", "6")
                self.send_header("Connection", "keep-alive")
                self.send_header("Keep-Alive", "timeout=60")
                self.end_headers()
                self.wfile.write(b"origin")

            def finish(self) -> None:
                super().finish()
                released.set()

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_port
            async with service_egress_proxy(idle_seconds=60) as egress:
                reader, writer = await _open(egress)
                writer.write(
                    _get(f"http://{_HOST}:{port}/wfs?REQUEST=x", f"{_HOST}:{port}")
                )
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
                body = await asyncio.wait_for(reader.readexactly(6), 10)
                writer.close()
                assert await asyncio.to_thread(released.wait, 5)
        finally:
            server.shutdown()
            server.server_close()

        assert b" 200 " in head.split(b"\r\n", 1)[0], head
        assert body == b"origin"
        assert b"\r\nconnection: close" in head.lower()
        assert b"keep-alive" not in head.lower()
        assert seen == [("/wfs?REQUEST=x", f"{_HOST}:{port}", None)]
        assert resolver_calls == [_HOST]
        assert egress.refused is False

    @pytest.mark.parametrize(
        "request_head",
        [
            "GET http://127.0.0.1:{port}/wfs HTTP/1.1\r\nHost: x\r\n\r\n",
            "GET http://localhost:{port}/wfs HTTP/1.1\r\nHost: x\r\n\r\n",
            "CONNECT 127.0.0.1:{port} HTTP/1.1\r\nHost: x\r\n\r\n",
            "CONNECT [::1]:{port} HTTP/1.1\r\nHost: x\r\n\r\n",
            "GET http://169.254.169.254/latest HTTP/1.1\r\nHost: x\r\n\r\n",
            "CONNECT 10.0.0.1:443 HTTP/1.1\r\nHost: x\r\n\r\n",
            "GET http://[fd00::1]/ HTTP/1.1\r\nHost: x\r\n\r\n",
        ],
    )
    async def test_the_address_policy_refuses_before_any_connection(self, request_head):
        with _wfs_service() as (port, requests):
            async with service_egress_proxy(idle_seconds=30) as egress:
                response = await _exchange(
                    egress, request_head.format(port=port).encode()
                )

        assert response.startswith(b"HTTP/1.1 403"), response
        assert egress.refused is True
        assert requests == []

    async def test_a_name_that_resolves_to_a_private_address_is_refused(
        self, monkeypatch
    ):
        real_getaddrinfo = socket.getaddrinfo

        def getaddrinfo(host, port, *args, **kwargs):
            if host == "internal.example.test":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
            return real_getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        async with service_egress_proxy(idle_seconds=30) as egress:
            response = await _exchange(
                egress,
                _get("http://internal.example.test/wfs", "internal.example.test"),
            )

        assert response.startswith(b"HTTP/1.1 403"), response
        assert egress.refused is True

    async def test_each_connection_is_checked_once_and_made_to_that_address(
        self, monkeypatch, resolver_calls
    ):
        """A name whose DNS answer changes after the check still reaches the
        address that was checked: the proxy never looks the name up again."""
        real_getaddrinfo = socket.getaddrinfo

        def getaddrinfo(host, port, *args, **kwargs):
            if host == _HOST:
                return [
                    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0))
                ]
            return real_getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        with _wfs_service() as (port, requests):
            async with service_egress_proxy(idle_seconds=30) as egress:
                for _ in range(2):
                    response = await _exchange(
                        egress,
                        _get(
                            f"http://{_HOST}:{port}/wfs?REQUEST=GetCapabilities",
                            _HOST,
                        ),
                    )
                    assert b" 200 " in response.split(b"\r\n", 1)[0], response

        assert requests == ["getcapabilities", "getcapabilities"]
        assert resolver_calls == [_HOST, _HOST]

    async def test_https_is_tunnelled_to_the_checked_address(self, resolver_calls):
        async def echo(reader, writer):
            writer.write(await reader.read(4))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            async with service_egress_proxy(idle_seconds=30) as egress:
                address = urlsplit(egress.address)
                reader, writer = await asyncio.open_connection(
                    address.hostname, address.port
                )
                writer.write(f"CONNECT {_HOST}:{port} HTTP/1.1\r\n\r\n".encode())
                established = await reader.readuntil(b"\r\n\r\n")
                writer.write(b"ping")
                echoed = await asyncio.wait_for(reader.read(), 10)
                writer.close()
        finally:
            server.close()
            await server.wait_closed()

        assert established.startswith(b"HTTP/1.1 200")
        assert echoed == b"ping"
        assert resolver_calls == [_HOST]

    @pytest.mark.parametrize(
        "request_head",
        [
            b"GET /wfs HTTP/1.1\r\nHost: wfs.example.test\r\n\r\n",
            b"GET ftp://wfs.example.test/x HTTP/1.1\r\n\r\n",
            b"CONNECT wfs.example.test HTTP/1.1\r\n\r\n",
            b"GET http://wfs.example.test/ HTTP/1.1\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n",
            b"not a request\r\n\r\n",
        ],
    )
    async def test_a_request_it_cannot_route_is_refused_unresolved(
        self, request_head, resolver_calls
    ):
        async with service_egress_proxy(idle_seconds=30) as egress:
            response = await _exchange(egress, request_head)

        assert response.startswith(b"HTTP/1.1 400"), response
        assert resolver_calls == []

    async def test_a_connection_carries_one_request(self, resolver_calls):
        """libcurl reuses a proxy connection across hosts; a second request
        on it must not reach the first host's address."""
        with _wfs_service() as (port, requests):
            async with service_egress_proxy(idle_seconds=30) as egress:
                await _exchange(
                    egress,
                    _get(f"http://{_HOST}:{port}/wfs?REQUEST=first", _HOST)
                    + _get(f"http://other.example.test:{port}/?REQUEST=second", "o"),
                )

        assert requests == ["first"]

    async def test_an_idle_tunnel_is_closed(self, resolver_calls):
        with _silent_upstream() as (port, upstream_closed):
            async with service_egress_proxy(idle_seconds=0.5) as egress:
                reader, writer = await _open(egress)
                writer.write(f"CONNECT {_HOST}:{port} HTTP/1.1\r\n\r\n".encode())
                await reader.readuntil(b"\r\n\r\n")
                assert await asyncio.wait_for(reader.read(), 5) == b""
                writer.close()
                await asyncio.wait_for(upstream_closed.wait(), 5)

    async def test_a_response_that_never_starts_is_closed(self, resolver_calls):
        with _silent_upstream() as (port, _upstream_closed):
            async with service_egress_proxy(idle_seconds=0.5) as egress:
                response = await _exchange(egress, _get(f"http://{_HOST}:{port}/", "x"))

        assert response.startswith(b"HTTP/1.1 502"), response

    async def test_a_slow_relay_that_keeps_moving_is_not_cut(self, resolver_calls):
        async def trickle(reader, writer):
            for _ in range(6):
                writer.write(b"x")
                await writer.drain()
                await asyncio.sleep(0.2)
            writer.close()

        server = await asyncio.start_server(trickle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            async with service_egress_proxy(idle_seconds=0.5) as egress:
                reader, writer = await _open(egress)
                writer.write(f"CONNECT {_HOST}:{port} HTTP/1.1\r\n\r\n".encode())
                await reader.readuntil(b"\r\n\r\n")
                received = await asyncio.wait_for(reader.read(), 10)
                writer.close()
        finally:
            server.close()
            await server.wait_closed()

        assert received == b"x" * 6

    async def test_leaving_the_block_closes_open_relays(self, resolver_calls):
        with _silent_upstream() as (port, upstream_closed):
            async with service_egress_proxy(idle_seconds=60) as egress:
                reader, writer = await _open(egress)
                writer.write(f"CONNECT {_HOST}:{port} HTTP/1.1\r\n\r\n".encode())
                await reader.readuntil(b"\r\n\r\n")

            assert await asyncio.wait_for(reader.read(), 5) == b""
            await asyncio.wait_for(upstream_closed.wait(), 5)
            writer.close()

    async def test_leaving_the_block_stops_a_relay_still_resolving(self, monkeypatch):
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def resolve_forever(host: str, port: int | None) -> str:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return "127.0.0.1"

        monkeypatch.setattr(egress_proxy, "_resolve_and_validate", resolve_forever)

        async def request_then_leave() -> asyncio.StreamWriter:
            async with service_egress_proxy(idle_seconds=60) as egress:
                _reader, writer = await _open(egress)
                writer.write(_get(f"http://{_HOST}/wfs", _HOST))
                await asyncio.wait_for(entered.wait(), 5)
            return writer

        writer = await asyncio.wait_for(request_then_leave(), 10)
        writer.close()

        assert cancelled.is_set()

    async def test_it_stops_listening_when_its_block_exits(self):
        async with service_egress_proxy(idle_seconds=30) as egress:
            address = urlsplit(egress.address)

        assert address.hostname == "127.0.0.1"
        with pytest.raises(OSError):
            await asyncio.open_connection(address.hostname, address.port)


def test_the_service_env_sends_every_request_through_the_proxy(monkeypatch):
    """libcurl honours NO_PROXY even with a proxy set, and GDAL_HTTPS_PROXY
    takes precedence for https, so no inherited proxy setting survives."""
    for key in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, "*")
    for key in ("HTTPS_PROXY", "http_proxy", "ALL_PROXY", "GDAL_HTTPS_PROXY"):
        monkeypatch.setenv(key, "http://elsewhere:1")
    monkeypatch.setenv("GDAL_CONFIG_FILE", "/etc/gdalrc-elsewhere")
    egress = ServiceEgress("http://127.0.0.1:4321")

    env = gdal_service_safe_env(egress)

    assert env["GDAL_HTTP_PROXY"] == env["GDAL_HTTPS_PROXY"] == egress.address
    assert env["GDAL_CONFIG_FILE"] == os.devnull
    stray = {k for k in env if "proxy" in k.lower()} - {
        "GDAL_HTTP_PROXY",
        "GDAL_HTTPS_PROXY",
    }
    assert stray == set()


async def test_environment_proxy_settings_route_neither_outbound_path(monkeypatch):
    """httpx ignores the environment's proxies when it is handed a transport,
    which make_safe_client always does, and the GDAL service env drops them, so
    an operator's proxy settings apply to neither path."""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "https_proxy"):
        monkeypatch.setenv(key, "http://outbound.example.test:3128")

    client = make_safe_client()
    try:
        transport = client._transport_for_url(httpx.URL("https://svc.example.test/"))
    finally:
        await client.aclose()
    env = gdal_service_safe_env(ServiceEgress("http://127.0.0.1:4321"))

    assert isinstance(transport, _SSRFGuardTransport)
    assert "outbound.example.test" not in " ".join(env.values())


_AUTH_HINT = "The service needs a credential."


def _importer(source: str):
    async def run(layer: str) -> None:
        await run_ogr2ogr_service(
            source,
            layer,
            "never_created",
            "PG:dbname=never_opened",
            "wfs",
            timeout=60.0,
            schema="data",
        )

    return run


@needs_ogr
class TestGdalReachesOnlyAllowedHosts:
    @pytest.mark.parametrize("status", [401, 403])
    async def test_an_auth_refusal_still_gets_the_credential_hint(
        self, resolver_calls, status
    ):
        """The job error keeps the HTTP status, which is what tells the import
        to suggest a credential."""
        with _wfs_service(status=status) as (port, requests):
            with pytest.raises(IngestionError) as error:
                await _run_service_import_with_wfs_fallback(
                    _importer(f"WFS:http://{_HOST}:{port}/wfs"),
                    _LAYER,
                    token=None,
                    auth_error_message=_AUTH_HINT,
                )

        assert requests
        assert str(error.value) == _AUTH_HINT

    async def test_a_refused_address_is_not_reported_as_an_auth_refusal(
        self, resolver_calls
    ):
        with _wfs_service() as (internal_port, internal_requests):
            target = f"http://127.0.0.1:{internal_port}/wfs?REQUEST=GetCapabilities"
            with _wfs_service(redirect_to=target) as (port, _requests):
                with pytest.raises(IngestionError) as error:
                    await _run_service_import_with_wfs_fallback(
                        _importer(f"WFS:http://{_HOST}:{port}/wfs"),
                        _LAYER,
                        token=None,
                        auth_error_message=_AUTH_HINT,
                    )

        assert internal_requests == []
        assert str(error.value) == (
            f"ogr2ogr failed (exit 1): {SERVICE_ADDRESS_REFUSED}"
        )

    async def test_a_wfs_preview_reads_an_allowed_service_through_the_proxy(
        self, resolver_calls
    ):
        with _wfs_service() as (port, requests):
            preview = await run_service_preview(
                f"WFS:http://{_HOST}:{port}/wfs", _LAYER, timeout=60.0
            )

        assert [row["name"] for row in preview["sample_rows"]] == ["one"]
        assert "getfeature" in requests
        assert set(resolver_calls) == {_HOST}

    async def test_an_inherited_no_proxy_does_not_route_around_it(
        self, monkeypatch, resolver_calls
    ):
        monkeypatch.setenv("NO_PROXY", "*")
        monkeypatch.setenv("no_proxy", "*")
        with _wfs_service() as (port, requests):
            preview = await run_service_preview(
                f"WFS:http://{_HOST}:{port}/wfs", _LAYER, timeout=60.0
            )

        # The test host exists only in the proxy's resolver, so a request that
        # skipped the proxy could not have reached the service at all.
        assert [row["name"] for row in preview["sample_rows"]] == ["one"]
        assert "getcapabilities" in requests

    async def test_a_redirect_to_a_refused_address_never_reaches_it(
        self, resolver_calls
    ):
        marker = f"internal-{uuid.uuid4().hex}"
        with _wfs_service(title=marker) as (internal_port, internal_requests):
            target = (
                f"http://127.0.0.1:{internal_port}/wfs"
                "?SERVICE=WFS&REQUEST=GetCapabilities"
            )
            with _wfs_service(redirect_to=target) as (port, requests):
                source = f"WFS:http://{_HOST}:{port}/wfs"
                with pytest.raises(IngestionError) as preview_error:
                    await run_service_preview(source, _LAYER, timeout=60.0)
                with pytest.raises(IngestionError) as import_error:
                    await run_ogr2ogr_service(
                        source,
                        _LAYER,
                        "never_created",
                        "PG:dbname=never_opened",
                        "wfs",
                        timeout=60.0,
                        schema="data",
                    )

        assert requests, "the allowed service was asked first"
        assert internal_requests == []
        assert marker not in str(preview_error.value)
        assert str(import_error.value) == (
            f"ogr2ogr failed (exit 1): {SERVICE_ADDRESS_REFUSED}"
        )

    @pytest.mark.parametrize(
        ("setting", "content"),
        [
            ("GDAL_CONFIG_FILE", "[directives]\nignore-env-vars=yes\n"),
            ("GDAL_CONFIG_FILE", "[configoptions]\nGDAL_HTTP_PROXY=\n"),
            ("HOME", "[directives]\nignore-env-vars=yes\n"),
        ],
        ids=["ignore-env-vars", "empty-proxy-option", "home-gdalrc"],
    )
    async def test_a_gdal_config_file_does_not_route_around_it(
        self, resolver_calls, monkeypatch, tmp_path, setting, content
    ):
        """GDAL reads $GDAL_CONFIG_FILE, or else ~/.gdal/gdalrc, and either can
        tell it to ignore the environment the proxy is set in. The test host
        resolves only in the proxy, so going direct fails without the refusal."""
        if setting == "HOME":
            (tmp_path / ".gdal").mkdir()
            (tmp_path / ".gdal" / "gdalrc").write_text(content)
            monkeypatch.setenv("HOME", str(tmp_path))
        else:
            (tmp_path / "gdalrc").write_text(content)
            monkeypatch.setenv("GDAL_CONFIG_FILE", str(tmp_path / "gdalrc"))

        with _wfs_service() as (internal_port, internal_requests):
            target = f"http://127.0.0.1:{internal_port}/wfs?REQUEST=GetCapabilities"
            with _wfs_service(redirect_to=target) as (port, requests):
                with pytest.raises(IngestionError) as error:
                    await _importer(f"WFS:http://{_HOST}:{port}/wfs")(_LAYER)

        assert requests
        assert internal_requests == []
        assert str(error.value) == (
            f"ogr2ogr failed (exit 1): {SERVICE_ADDRESS_REFUSED}"
        )

    async def test_a_failed_import_reports_its_class_and_logs_the_service_text(
        self, resolver_calls
    ):
        marker = f"echoed-{uuid.uuid4().hex}"
        with _wfs_service(exception_text=marker) as (port, _requests):
            with structlog.testing.capture_logs() as logs:
                with pytest.raises(IngestionError) as error:
                    await run_ogr2ogr_service(
                        f"WFS:http://{_HOST}:{port}/wfs",
                        _LAYER,
                        "never_created",
                        "PG:dbname=never_opened",
                        "wfs",
                        timeout=60.0,
                        schema="data",
                    )

        assert str(error.value) == "ogr2ogr failed (exit 1)"
        logged = [entry.get("stderr", "") for entry in logs]
        assert any(marker in text for text in logged), logs


@pytest.fixture
def ogr_writes_the_test_database(monkeypatch) -> None:
    """ogr2ogr connects with the app database settings, not the test engine's."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "postgres_db", settings.postgres_db_test)


@needs_ogr
@pytest.mark.usefixtures("ogr_writes_the_test_database")
class TestAServiceImportJobError:
    async def test_the_job_error_names_the_class_not_the_service_text(
        self, test_db_session, resolver_calls
    ):
        marker = f"echoed-{uuid.uuid4().hex}"
        user_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session, created_by=user_id, source_format="wfs"
        )
        with _wfs_service(exception_text=marker) as (port, requests):
            source_url = f"http://{_HOST}:{port}/wfs"
            job = IngestJob(
                dataset_id=dataset.id,
                source_filename="Parcels",
                source_url=source_url,
                source_layer=_LAYER,
                created_by=user_id,
                status="pending",
                user_metadata={
                    "reupload": True,
                    "dataset_id": str(dataset.id),
                    "service_type": "WFS",
                    "layer_id": None,
                    "source_type": "service_url",
                },
            )
            test_db_session.add(job)
            await test_db_session.commit()
            await test_db_session.refresh(job)

            # The submitted URL is checked with the real resolver, which has
            # never heard of the test host.
            with patch("app.platform.security.validate_url_for_ssrf", AsyncMock()):
                with pytest.raises(Exception):
                    await reupload_service(
                        job_id=str(job.id),
                        attempt_id=str(job.attempt_id),
                        dataset_id=str(dataset.id),
                        source_url=source_url,
                        source_layer=_LAYER,
                        user_id=str(user_id),
                        token=None,
                    )

        refreshed = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job.id)
            )
        ).scalar_one()
        await test_db_session.refresh(refreshed)

        assert requests, "GDAL reached the service"
        assert refreshed.status == "failed"
        assert refreshed.error_message.startswith("ogr2ogr failed (exit 1)")
        assert marker not in refreshed.error_message

    async def test_an_allowed_service_imports_through_the_proxy(
        self, test_db_session, resolver_calls
    ):
        table = f"egress_{uuid.uuid4().hex[:12]}"
        try:
            with _wfs_service() as (port, requests):
                await run_ogr2ogr_service(
                    f"WFS:http://{_HOST}:{port}/wfs",
                    _LAYER,
                    table,
                    build_pg_conn_str(),
                    "wfs",
                    timeout=120.0,
                    schema="data",
                )
            count = await test_db_session.scalar(
                text(f'SELECT count(*) FROM data."{table}"')
            )
        finally:
            await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{table}"'))
            await test_db_session.commit()

        assert count == 1
        assert "getfeature" in requests
