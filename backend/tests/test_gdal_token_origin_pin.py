"""A GDAL service run that carries a credential connects only to its source's origin.

The ArcGIS token rides in the ESRIJSON query and libcurl repeats it on every
redirect it follows, while the egress proxy sees an https hop only as
``CONNECT host:port``. These tests run real GDAL over TLS through the proxy.
"""

from __future__ import annotations

import datetime
import json
import ssl
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.modules.catalog.sources.preview import run_service_preview
from app.platform import egress_proxy
from app.platform.egress_proxy import pinned_origin, service_egress_proxy
from app.processing.ingest.ogr import (
    SERVICE_ADDRESS_REFUSED,
    IngestionError,
    run_ogr2ogr_service,
)
from tests.test_service_egress_proxy import _exchange, needs_ogr, needs_preview_ogrinfo

pytestmark = pytest.mark.anyio

_ORIGIN = "arcgis.example.test"
_OTHER = "other.example.test"
_QUERY_PATH = "/arcgis/rest/services/Parcels/FeatureServer/0/query"

_FEATURES = json.dumps(
    {
        "objectIdFieldName": "OBJECTID",
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 4326},
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "name", "type": "esriFieldTypeString"},
        ],
        "features": [
            {"attributes": {"OBJECTID": 1, "name": "one"}, "geometry": {"x": 1, "y": 2}}
        ],
    }
).encode()


@pytest.fixture(scope="module")
def tls_context(tmp_path_factory) -> ssl.SSLContext:
    """A server context with a self-signed certificate for both test hosts."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _ORIGIN)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(_ORIGIN), x509.DNSName(_OTHER)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    folder: Path = tmp_path_factory.mktemp("tls")
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "cert.pem", folder / "key.pem")
    return context


@pytest.fixture
def gdal_trusts_the_test_certificate(monkeypatch) -> None:
    # The subprocess env is copied from os.environ, so GDAL accepts the
    # self-signed certificate; the proxy, not TLS, is what is under test.
    monkeypatch.setenv("GDAL_HTTP_UNSAFESSL", "YES")


@pytest.fixture
def both_hosts_resolve(monkeypatch) -> None:
    async def resolve(host: str, port: int | None) -> list[str]:
        if host in (_ORIGIN, _OTHER):
            return ["127.0.0.1"]
        raise AssertionError(f"unexpected host {host!r}")

    monkeypatch.setattr(egress_proxy, "_resolve_all_and_validate", resolve)


@contextmanager
def _https_service(
    context: ssl.SSLContext, *, redirect_to: str | None = None
) -> Iterator[tuple[int, list[str]]]:
    """An HTTPS ArcGIS query endpoint; yields its port and the paths it got.

    With ``redirect_to``, a request outside the query path is sent there;
    ``{port}`` in it is this server's port.
    """
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            requests.append(self.path)
            if redirect_to is not None and not self.path.startswith(_QUERY_PATH):
                self.send_response(302)
                location = redirect_to.replace("{port}", str(self.server.server_port))
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_FEATURES)))
            self.end_headers()
            self.wfile.write(_FEATURES)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _query(host: str, port: int | str, token: str, path: str = _QUERY_PATH) -> str:
    return f"https://{host}:{port}{path}?f=json&where=1%3D1&outFields=%2A&token={token}"


@needs_ogr
@pytest.mark.usefixtures("gdal_trusts_the_test_certificate", "both_hosts_resolve")
class TestATokenRunStaysOnItsOrigin:
    @needs_preview_ogrinfo
    async def test_a_preview_never_sends_the_token_to_another_origin(self, tls_context):
        token = f"tok-{uuid.uuid4().hex}"
        with _https_service(tls_context) as (other_port, other_requests):
            stolen = _query(_OTHER, other_port, token)
            with _https_service(tls_context, redirect_to=stolen) as (port, requests):
                source = "ESRIJSON:" + _query(_ORIGIN, port, token, path="/moved")
                with pytest.raises(IngestionError, match="does not connect to"):
                    await run_service_preview(source, "", timeout=60.0)

        assert requests, "the origin was asked first"
        assert other_requests == []

    async def test_an_import_never_sends_the_token_to_another_origin(self, tls_context):
        token = f"tok-{uuid.uuid4().hex}"
        with _https_service(tls_context) as (other_port, other_requests):
            stolen = _query(_OTHER, other_port, token)
            with _https_service(tls_context, redirect_to=stolen) as (port, requests):
                with pytest.raises(IngestionError) as error:
                    await run_ogr2ogr_service(
                        "ESRIJSON:" + _query(_ORIGIN, port, token, path="/moved"),
                        "",
                        "never_created",
                        "PG:dbname=never_opened",
                        "arcgis_featureserver",
                        token=token,
                        timeout=60.0,
                        schema="data",
                    )

        assert requests
        assert other_requests == []
        assert str(error.value).endswith(SERVICE_ADDRESS_REFUSED)
        assert token not in str(error.value)

    @needs_preview_ogrinfo
    async def test_a_same_origin_redirect_is_still_followed(self, tls_context):
        token = f"tok-{uuid.uuid4().hex}"
        target = _query(_ORIGIN, "{port}", token)
        with _https_service(tls_context, redirect_to=target) as (port, requests):
            source = "ESRIJSON:" + _query(_ORIGIN, port, token, path="/moved")
            preview = await run_service_preview(source, "", timeout=60.0)

        assert [row["name"] for row in preview["sample_rows"]] == ["one"]
        assert requests[0].startswith("/moved?")
        assert any(path.startswith(_QUERY_PATH) for path in requests[1:])


class TestTheProxyPin:
    @pytest.mark.parametrize(
        ("origin", "request_head", "allowed"),
        [
            ("https://a.test/x", "CONNECT a.test:443 HTTP/1.1\r\n\r\n", True),
            ("https://A.test:443/x", "CONNECT a.test:443 HTTP/1.1\r\n\r\n", True),
            ("https://[::1]:8443/x", "CONNECT [::1]:8443 HTTP/1.1\r\n\r\n", True),
            (
                "https://b\u00fccher.test/x",
                "CONNECT xn--bcher-kva.test:443 HTTP/1.1\r\n\r\n",
                True,
            ),
            ("https://a.test/x", "CONNECT b.test:443 HTTP/1.1\r\n\r\n", False),
            ("https://a.test/x", "CONNECT a.test:8443 HTTP/1.1\r\n\r\n", False),
            ("https://a.test/x", "GET http://a.test:443/ HTTP/1.1\r\n\r\n", False),
            ("https://a.test/x", "GET http://a.test/ HTTP/1.1\r\n\r\n", False),
            ("http://a.test/x", "GET http://a.test/y HTTP/1.1\r\n\r\n", True),
            ("http://a.test/x", "CONNECT a.test:80 HTTP/1.1\r\n\r\n", False),
            ("http://a.test/x", "GET http://b.test/y HTTP/1.1\r\n\r\n", False),
        ],
    )
    async def test_only_the_origins_scheme_host_and_port_pass(
        self, monkeypatch, origin, request_head, allowed
    ):
        async def resolve(host: str, port: int | None) -> list[str]:
            return ["127.0.0.1"]

        # Past the pin nothing answers, which the proxy reports as a 502.
        async def connect_nowhere(addresses, port):
            return None

        monkeypatch.setattr(egress_proxy, "_resolve_all_and_validate", resolve)

        monkeypatch.setattr(egress_proxy, "_connect_first", connect_nowhere)
        async with service_egress_proxy(idle_seconds=30, origin=origin) as egress:
            response = await _exchange(egress, request_head.encode())

        if allowed:
            assert response.startswith(b"HTTP/1.1 502"), response
            assert egress.refused is False
        else:
            assert response.startswith(b"HTTP/1.1 403"), response
            assert egress.refused is True


@pytest.mark.parametrize(
    ("source", "credential", "expected"),
    [
        ("WFS:https://h.test/wfs", True, "https://h.test/wfs"),
        ("WFS:https://h.test/wfs", False, None),
        (
            "ESRIJSON:https://h.test/q?f=json&token=t",
            False,
            "https://h.test/q?f=json&token=t",
        ),
        ("ESRIJSON:https://h.test/q?Token=t", False, "https://h.test/q?Token=t"),
        ("ESRIJSON:https://h.test/q?f=json", False, None),
        ("https://h.test/q?token=t", False, "https://h.test/q?token=t"),
        ("/staging/items.json", True, None),
    ],
)
def test_a_run_is_pinned_exactly_when_it_carries_a_credential(
    source, credential, expected
):
    assert pinned_origin(source, credential=credential) == expected
