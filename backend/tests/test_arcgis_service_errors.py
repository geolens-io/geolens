"""An ArcGIS service's own error reaches a failed import's reason, redacted."""

from __future__ import annotations

import contextvars
import json
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.service_tokens import register_credential_secret
from app.modules.catalog.sources.preview import build_gdal_source
from app.platform import egress_proxy, security
from app.processing.ingest.arcgis_errors import MAX_DETAIL_CHARS, arcgis_error_detail
from app.processing.ingest.ogr import IngestionError, run_ogr2ogr_service

_TOKEN = "fake-token-fake-token-SECRET"
_HOST = "arcgis.example.test"


def _envelope(message: object, details: object = None, code: object = 400) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def test_an_envelope_gives_its_code_message_and_details():
    detail = arcgis_error_detail(
        _envelope(
            "Cannot perform query. Invalid query parameters.",
            ["'OBJECTID ASC' parameter is invalid"],
        ),
        None,
    )

    assert detail == (
        "ArcGIS error 400: Cannot perform query. Invalid query parameters. "
        "'OBJECTID ASC' parameter is invalid"
    )


@pytest.mark.parametrize(
    "data",
    [
        {"features": []},
        [],
        "error",
        {"error": "Service not started"},
        _envelope(None),
        _envelope(["not", "text"]),
        _envelope(" \n\t"),
    ],
)
def test_anything_but_an_envelope_with_a_message_gives_nothing(data):
    assert arcgis_error_detail(data, None) is None


@pytest.mark.parametrize("code", [True, "400", 10_000, -1, None])
def test_a_code_that_is_not_a_small_integer_is_left_out(code):
    assert arcgis_error_detail(_envelope("Failed", code=code), None) == (
        "ArcGIS error: Failed"
    )


@pytest.mark.parametrize(
    ("message", "secrets"),
    [
        (
            f"Bad request https://svc.example/q?f=json&token={_TOKEN}",
            [_TOKEN],
        ),
        (
            "Bad request https://svc.example/q?access_token=AT-9f8e7d&api_key=K-1a2b",
            ["AT-9f8e7d", "K-1a2b"],
        ),
        ("See https://alice:pa55-w0rd@svc.example/rest", ["pa55-w0rd", "alice"]),
        (f"Invalid token {_TOKEN} supplied", [_TOKEN]),
        ("Invalid token Tok-en_0123456789abcdef%2FSECRET", ["Tok-en_0123456789"]),
        ("X-Esri-Authorization: Bearer someone-elses-token", ["someone-elses-token"]),
        ("Rejected authorization: Basic YWxpY2U6c2VjcmV0", ["YWxpY2U6c2VjcmV0"]),
        ("Rejected credential registered-secret-4242 here", ["registered-secret-4242"]),
    ],
    ids=[
        "arcgis-query-token",
        "other-query-credentials",
        "userinfo",
        "exact-token",
        "percent-encoded-token",
        "x-esri-authorization",
        "authorization-header",
        "registered-credential",
    ],
)
def test_every_credential_class_is_redacted(message, secrets):
    token = "Tok-en_0123456789abcdef/SECRET" if "%2F" in message else _TOKEN

    def run() -> str | None:
        register_credential_secret("registered-secret-4242")
        return arcgis_error_detail(_envelope(message), token)

    detail = contextvars.copy_context().run(run)

    assert detail is not None
    for secret in secrets:
        assert secret not in detail


def test_control_format_and_separator_characters_become_single_spaces():
    detail = arcgis_error_detail(
        _envelope("line one\r\nline\x1b[31m two‮​ three\x00"), None
    )

    assert detail == "ArcGIS error 400: line one line [31m two three"


def test_a_long_message_is_cut_after_redaction():
    # The token starts a few characters before the cut, so cutting first
    # would leave a prefix of it that exact-value scrubbing can't match.
    filler = "x" * (MAX_DETAIL_CHARS - 30)
    detail = arcgis_error_detail(_envelope(f"{filler} {_TOKEN} {'y' * 5000}"), _TOKEN)

    assert detail is not None
    assert len(detail) == MAX_DETAIL_CHARS
    assert detail.endswith("...")
    assert "fake-t" not in detail


needs_ogr = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None, reason="needs the GDAL command line tools"
)


@contextmanager
def _arcgis_error_service(status: int) -> Iterator[tuple[int, list[str]]]:
    """A loopback ArcGIS layer whose query answers with an error envelope."""
    requests: list[str] = []
    body = json.dumps(
        _envelope(
            "Cannot perform query. Invalid query parameters.",
            [
                "'OBJECTID ASC' parameter is invalid",
                f"https://{_HOST}/q?token={_TOKEN}",
            ],
        )
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            requests.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
def loopback_service_host(monkeypatch) -> None:
    """Resolve the test host to loopback on both outbound paths."""
    real_all = egress_proxy._resolve_all_and_validate
    real_one = security._resolve_and_validate

    async def resolve_all(host: str, port: int | None) -> list[str]:
        if host == _HOST:
            return ["127.0.0.1"]
        return await real_all(host, port)

    async def resolve_one(host: str, port: int | None) -> str:
        if host == _HOST:
            return "127.0.0.1"
        return await real_one(host, port)

    monkeypatch.setattr(egress_proxy, "_resolve_all_and_validate", resolve_all)
    monkeypatch.setattr(security, "_resolve_and_validate", resolve_one)


@needs_ogr
@pytest.mark.anyio
@pytest.mark.usefixtures("loopback_service_host")
@pytest.mark.parametrize(
    ("status", "gdal_reason"),
    [
        (200, "the source service returned an error instead of features"),
        (400, "the source service answered HTTP 400"),
    ],
)
async def test_a_failed_import_reports_the_services_own_error(status, gdal_reason):
    with _arcgis_error_service(status) as (port, requests):
        source, layer = build_gdal_source(
            "ArcGIS FeatureServer",
            f"http://{_HOST}:{port}/arcgis/rest/services/Parcels/FeatureServer",
            "",
            layer_id=0,
            token=_TOKEN,
            order_field="OBJECTID",
        )
        with pytest.raises(IngestionError) as failure:
            await run_ogr2ogr_service(
                source,
                layer,
                "never_created",
                "PG:dbname=never_opened",
                "arcgis_featureserver",
                timeout=60.0,
                token=_TOKEN,
                is_non_spatial=True,
                schema="data",
            )

    assert str(failure.value) == (
        f"ogr2ogr failed (exit 1): {gdal_reason}. ArcGIS error 400: Cannot "
        "perform query. Invalid query parameters. 'OBJECTID ASC' parameter is "
        f"invalid https://{_HOST}/q?token=%3Credacted%3E"
    )
    assert _TOKEN not in str(failure.value)
    assert len(requests) == 2
    assert requests[0] == requests[1]
