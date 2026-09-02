"""feat(#1746) lane B2b: how a service credential actually travels.

The contract tests next door assert what the doors ACCEPT. These assert what
leaves the process once a door has accepted it, which is where this change can
fail quietly:

- the GDAL header file holds exactly one composed line, whatever the method,
  and never the double prefix a writer that kept its own
  ``Authorization: Bearer `` would have produced;
- a bearer import writes the byte-identical file it wrote before the prefix
  moved into the shared builder;
- an input carrying CR, LF or a non-ASCII character is refused at the door,
  before a single-use credential can be spent, and the refusal echoes nothing;
- no composed ArcGIS URL contains the string ``Authorization``, which is plan
  D9's invariant at the place it would actually do damage;
- a cross-origin redirect cannot carry a service-chosen credential header off
  the origin it was given to, on each of the three httpx paths that send one;
- the GDAL envs that carry a header file pin the Authorization redirect rule.

Every credential value here is generated per call, so an assertion that a
value is absent from a response, a file or a job row cannot pass by
coincidence, and no literal password is written down anywhere (Rule 3).
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.service_tokens import (
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
)
from app.modules.catalog.sources import preview as preview_mod
from app.modules.catalog.sources.adapters import arcgis as arcgis_mod
from app.modules.catalog.sources.adapters.ogcapi import probe_ogcapi
from app.modules.catalog.sources.adapters.wfs import probe_wfs
from app.platform import security
from app.platform.security import SSRFError, make_safe_client
from app.processing.ingest import tasks_vector
from app.processing.ingest import ogr as ogr_mod
from app.processing.ingest.ogr import run_ogr2ogr_service

# fix(#1746 codex r2): autouse where imported — the credential header lands in
# gdal_header_dir(), so without this the suite writes into the real /tmp.
from tests.test_ogr_subprocess_env import gdal_header_tmpdir  # noqa: F401

pytestmark = pytest.mark.anyio

_WFS_URL = "https://services.example.test/geoserver/wfs"
_ARCGIS_BASE = "https://services.example.test/rest/services/Parcels/FeatureServer"
_REDIRECT_PIN = "CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT"
_DOUBLE_PREFIX = "Authorization: Bearer Authorization:"


def _value() -> str:
    """A credential value with no literal spelled anywhere in this file."""
    return uuid.uuid4().hex


def _basic() -> tuple[ServiceCredential, str, str]:
    username = "u" + _value()
    password = "p" + _value()
    return (
        ServiceCredential(
            method=CredentialMethod.BASIC,
            service_format="wfs",
            username=username,
            password=password,
        ),
        username,
        password,
    )


def _header_key() -> tuple[ServiceCredential, str]:
    value = _value()
    return (
        ServiceCredential(
            method=CredentialMethod.HEADER_KEY,
            service_format="wfs",
            header_name="X-Api-Key",
            header_value=value,
        ),
        value,
    )


def _bearer(token: str | None = None) -> ServiceCredential:
    return ServiceCredential(
        method=CredentialMethod.BEARER,
        service_format="wfs",
        token=token or ("tok" + _value()),
    )


# ---------------------------------------------------------------------------
# The header file: one line, composed once
# ---------------------------------------------------------------------------


class _CapturedRun:
    """What the ogrinfo/ogr2ogr subprocess would have been given."""

    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.header_bytes: bytes | None = None


def _capture_subprocess(monkeypatch, capture: _CapturedRun, *, payload: dict | None):
    async def _fake_exec(*cmd, **kwargs):
        capture.env = dict(kwargs.get("env") or {})
        path = capture.env.get("GDAL_HTTP_HEADER_FILE")
        if path and os.path.exists(path):
            with open(path, "rb") as handle:
                capture.header_bytes = handle.read()
        proc = MagicMock()
        proc.returncode = 0

        async def _communicate():
            return (json.dumps(payload or {}).encode(), b"")

        proc.communicate = _communicate
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


_EMPTY_LAYER = {
    "layers": [
        {"name": "topp:parcels", "fields": [], "features": [], "geometryFields": []}
    ]
}


async def _preview_with(monkeypatch, credential) -> _CapturedRun:
    capture = _CapturedRun()
    _capture_subprocess(monkeypatch, capture, payload=_EMPTY_LAYER)
    await preview_mod.run_service_preview(
        f"WFS:{_WFS_URL}", "topp:parcels", credential=credential
    )
    return capture


async def _commit_with(monkeypatch, token: str) -> _CapturedRun:
    capture = _CapturedRun()
    _capture_subprocess(monkeypatch, capture, payload=None)

    async def _fake_communicate(proc, timeout, tool_name):
        return (b"", b"")

    monkeypatch.setattr(
        "app.processing.ingest.ogr._communicate_with_timeout", _fake_communicate
    )
    await run_ogr2ogr_service(
        gdal_source=f"WFS:{_WFS_URL}",
        layer_name="topp:parcels",
        table_name="t",
        db_conn_str="PG:dummy",
        service_type="wfs",
        token=token,
        schema="data",
    )
    return capture


class TestTheHeaderFileHoldsOneComposedLine:
    async def test_a_basic_credential_writes_one_authorization_line(
        self, monkeypatch
    ) -> None:
        """The whole point of moving the prefix into the builder.

        A writer that kept its own ``Authorization: Bearer `` and was handed a
        finished line would emit
        ``Authorization: Bearer Authorization: Basic <blob>`` — a
        working-looking string that 401s at the origin and reads in a log like
        a credential problem rather than a bug.
        """
        credential, username, password = _basic()
        capture = await _preview_with(monkeypatch, credential)

        assert capture.header_bytes is not None
        text = capture.header_bytes.decode("ascii")
        assert text.count("\n") == 1 and text.endswith("\n")
        line = text.rstrip("\n")
        name, _, value = line.partition(": ")
        assert name == "Authorization"
        assert value.startswith("Basic ")
        assert _DOUBLE_PREFIX not in text
        # The blob really is this username and password, encoded server side.
        blob = base64.b64decode(value.removeprefix("Basic ")).decode("ascii")
        assert blob == f"{username}:{password}"

    async def test_a_named_api_key_writes_its_own_header_name(
        self, monkeypatch
    ) -> None:
        credential, value = _header_key()
        capture = await _preview_with(monkeypatch, credential)

        assert capture.header_bytes == f"X-Api-Key: {value}\n".encode("ascii")
        assert _DOUBLE_PREFIX not in capture.header_bytes.decode("ascii")

    async def test_a_bearer_preview_is_byte_identical_to_the_shipping_path(
        self, monkeypatch
    ) -> None:
        """The parity guard: moving the prefix changed nothing that ships."""
        credential = _bearer()
        capture = await _preview_with(monkeypatch, credential)

        assert capture.header_bytes == (
            f"Authorization: Bearer {credential.token}\n".encode("ascii")
        )

    async def test_a_bearer_commit_is_byte_identical_to_the_shipping_path(
        self, monkeypatch
    ) -> None:
        token = "tok" + _value()
        capture = await _commit_with(monkeypatch, f"Authorization: Bearer {token}")

        assert capture.header_bytes == (
            f"Authorization: Bearer {token}\n".encode("ascii")
        )

    async def test_a_basic_commit_writes_the_line_it_was_given(
        self, monkeypatch
    ) -> None:
        credential, username, password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        line = f"{pair[0]}: {pair[1]}"

        capture = await _commit_with(monkeypatch, line)

        assert capture.header_bytes == f"{line}\n".encode("ascii")
        assert password not in capture.header_bytes.decode("ascii")
        assert _DOUBLE_PREFIX not in capture.header_bytes.decode("ascii")

    @pytest.mark.parametrize("path", ["preview", "commit"])
    async def test_the_redirect_pin_is_on_every_env_that_carries_a_header_file(
        self, monkeypatch, path
    ) -> None:
        """Plan rule A, on both GDAL paths.

        GDAL strips ``Authorization`` on a cross-host redirect by default and
        forwards every other header name verbatim, so a service-chosen API key
        is redirect-exposed here and cannot be protected from inside. Pinning
        NO tightens the half that can be.
        """
        if path == "preview":
            capture = await _preview_with(monkeypatch, _bearer())
        else:
            capture = await _commit_with(
                monkeypatch, "Authorization: Bearer tok" + _value()
            )

        assert capture.env[_REDIRECT_PIN] == "NO"
        # And never the option that reads as a defense and is a no-op (#937).
        assert "GDAL_HTTP_FOLLOWLOCATION" not in capture.env

    async def test_no_env_carries_the_credential_itself(self, monkeypatch) -> None:
        """IA-P1-06: the env var holds the file path, not the secret."""
        credential, _username, password = _basic()
        capture = await _preview_with(monkeypatch, credential)

        assert "GDAL_HTTP_HEADERS" not in capture.env
        assert password not in str(capture.env)


# ---------------------------------------------------------------------------
# The doors judge inputs, and refuse before anything is spent
# ---------------------------------------------------------------------------


_REFUSED_INPUTS = {
    "carriage_return": "abc\rdef",
    "line_feed": "abc\ndef",
    "non_ascii": "abcdéfgh",
    "space": "abc def",
    "empty": "",
}


class TestUnusableInputsAreRefusedAtTheDoor:
    """fix(#1746): before the composition, and before the credential is spent.

    Non-ASCII is the one worth naming. RFC 7617 makes UTF-8 the default charset
    for basic authentication, so refusing an accented letter reads like a bug
    until you look at the writer: both header files are written with
    ``.encode("ascii")``, so the alternative is a UnicodeEncodeError inside the
    worker, AFTER the single-use credential has been claimed — unrecoverable
    without re-entering it, and reported as an encoding bug rather than as the
    field the user typed.
    """

    async def _preview(self, client, headers, auth: dict):
        spawned: list = []

        async def _fake_exec(*cmd, **kwargs):
            spawned.append(cmd)
            raise AssertionError("ogrinfo must not be spawned for a refused input")

        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch.object(asyncio, "create_subprocess_exec", _fake_exec),
        ):
            resp = await client.post(
                "/services/preview",
                json={
                    "url": _WFS_URL,
                    "service_type": "WFS 2.0.0",
                    "layer_name": "topp:parcels",
                    "auth": auth,
                },
                headers=headers,
            )
        return resp, spawned

    @pytest.mark.parametrize("kind", sorted(_REFUSED_INPUTS))
    async def test_a_password_that_cannot_be_written_is_refused(
        self, client, admin_auth_header: dict, kind
    ) -> None:
        password = _REFUSED_INPUTS[kind]
        resp, spawned = await self._preview(
            client,
            admin_auth_header,
            {"method": "basic", "username": "u" + _value(), "password": password},
        )

        assert resp.status_code == 422, resp.text
        assert spawned == []
        if password.strip():
            assert password not in resp.text

    @pytest.mark.parametrize("kind", sorted(_REFUSED_INPUTS))
    async def test_a_header_value_that_cannot_be_written_is_refused(
        self, client, admin_auth_header: dict, kind
    ) -> None:
        value = _REFUSED_INPUTS[kind]
        resp, spawned = await self._preview(
            client,
            admin_auth_header,
            {"method": "header", "header_name": "X-Api-Key", "header_value": value},
        )

        assert resp.status_code == 422, resp.text
        assert spawned == []
        if value.strip():
            assert value not in resp.text

    @pytest.mark.parametrize(
        "header_name", ["Authorization", "AUTHORIZATION", "X Api Key", ":authority"]
    )
    async def test_a_header_name_this_build_sets_itself_is_refused(
        self, client, admin_auth_header: dict, header_name
    ) -> None:
        """The denylist is case-insensitive, and a pseudo-header is not a field."""
        value = _value()
        resp, spawned = await self._preview(
            client,
            admin_auth_header,
            {"method": "header", "header_name": header_name, "header_value": value},
        )

        assert resp.status_code == 422, resp.text
        assert spawned == []
        assert value not in resp.text

    async def test_the_probe_judges_the_same_inputs_as_the_preview(
        self, client, admin_auth_header: dict
    ) -> None:
        """fix(#1755 item 2): the two doors agreed on nothing before this.

        A credential the preview refuses used to probe cleanly, so the user
        learned at the next step rather than at the one they were on.
        """
        probe = AsyncMock()
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", probe),
        ):
            resp = await client.post(
                "/services/probe",
                json={
                    "url": _WFS_URL,
                    "auth": {
                        "method": "basic",
                        "username": "u" + _value(),
                        "password": "abc\rdef",
                    },
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        probe.assert_not_awaited()

    async def test_a_wfs_bearer_token_outside_the_charset_is_refused_at_the_probe(
        self, client, admin_auth_header: dict
    ) -> None:
        """The same rule the preview and the two commit doors already applied.

        The probe has no service type yet, so the URL shape is its selector.
        An ArcGIS-shaped URL keeps the wider vocabulary its query-parameter
        transport legitimately has; this one does not.
        """
        probe = AsyncMock()
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", probe),
        ):
            resp = await client.post(
                "/services/probe",
                json={"url": _WFS_URL, "token": "tok+slash/" + _value()},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        probe.assert_not_awaited()

    async def test_an_arcgis_url_keeps_its_wider_token_vocabulary(
        self, client, admin_auth_header: dict
    ) -> None:
        """An ArcGIS token is urlencoded into a query, so it is not a header."""
        from app.modules.catalog.sources.schemas import ProbeResponse

        probe = AsyncMock(
            return_value=ProbeResponse(
                service_type="ArcGIS FeatureServer", url=_ARCGIS_BASE, layers=[]
            )
        )
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", probe),
        ):
            resp = await client.post(
                "/services/probe",
                json={"url": _ARCGIS_BASE, "token": "tok+slash/" + _value()},
                headers=admin_auth_header,
            )

        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Plan D9's invariant: an ArcGIS URL never carries a header
# ---------------------------------------------------------------------------


class TestNoArcgisUrlCarriesAnAuthorizationHeader:
    """The builder answers None for ArcGIS, so nothing can compose one there.

    An ArcGIS credential is percent-encoded straight into a URL query
    (``build_gdal_source``, ``build_arcgis_count_query_url``, the paged import
    path), so a builder that ever returned a line for an ArcGIS credential
    would put ``Authorization: Basic ...`` inside a query string.
    """

    @pytest.mark.parametrize(
        "method",
        [
            CredentialMethod.BEARER,
            CredentialMethod.BASIC,
            CredentialMethod.HEADER_KEY,
        ],
    )
    def test_the_builder_composes_nothing_for_an_arcgis_credential(self, method):
        credential = ServiceCredential(
            method=method,
            service_format="arcgis_featureserver",
            token="tok" + _value(),
            username="u" + _value(),
            password="p" + _value(),
            header_name="X-Api-Key",
            header_value=_value(),
        )
        assert build_credential_header(credential) is None

    def test_no_composed_arcgis_url_contains_the_string(self):
        """Every ArcGIS URL this codebase composes, with a token in it."""
        from app.modules.catalog.sources.preview import build_gdal_source

        token = "tok" + _value()
        source, _layer = build_gdal_source(
            "ArcGIS FeatureServer", _ARCGIS_BASE, "Parcels", 0, token=token
        )
        count_url = arcgis_mod.build_arcgis_count_query_url(f"{_ARCGIS_BASE}/0", token)

        for url in (source, count_url):
            assert "Authorization" not in url
            assert token in url

    def test_neither_arcgis_module_composes_a_credential_header(self):
        """The positive control names the string it is looking for.

        A source-text assertion, because the ArcGIS transport is C2's lane and
        this is the invariant that lane must not break: an adapter that grew a
        header would pass every behavioural test here while putting a
        credential where the query goes.
        """
        adapter_source = inspect.getsource(arcgis_mod)
        paged_source = inspect.getsource(tasks_vector._fetch_arcgis_import_page_info)
        assert "token" in adapter_source, "positive control: the file was read"
        for source in (adapter_source, paged_source):
            # The only mention either module may make of the header is the
            # comment saying it composes none.
            assert "Authorization:" not in source
            assert "build_credential_header(" not in source


# ---------------------------------------------------------------------------
# Rule A, httpx half: a credential header stays on its origin
# ---------------------------------------------------------------------------


class TestACrossOriginRedirectCannotCarryTheKey:
    """Per adapter, because each builds its own request off one client.

    ``make_safe_client`` is what refuses, and B1 pinned that mechanism. What
    these add is that the adapters are actually reached through a client that
    declared the header, so a future adapter that builds its own client is a
    failure here rather than a silent leak.
    """

    @pytest.fixture
    def transport(self, monkeypatch):
        def install(location: str) -> list[httpx.Request]:
            recorded: list[httpx.Request] = []

            def handle(request: httpx.Request) -> httpx.Response:
                recorded.append(request)
                if len(recorded) == 1:
                    return httpx.Response(302, headers={"Location": location})
                return httpx.Response(200, json={})

            monkeypatch.setattr(
                security, "make_safe_transport", lambda: httpx.MockTransport(handle)
            )
            monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
            return recorded

        return install

    @pytest.mark.parametrize("probe", [probe_wfs, probe_ogcapi])
    async def test_a_probe_adapter_issues_no_second_request(self, transport, probe):
        recorded = transport("https://elsewhere.example/collect")
        credential, value = _header_key()

        async with make_safe_client(credential_header="X-Api-Key") as client:
            with pytest.raises(SSRFError) as raised:
                await probe(_WFS_URL, client, credential=credential)

        assert len(recorded) == 1
        assert value not in str(raised.value)

    async def test_the_collection_crs_fallback_issues_no_second_request(
        self, transport
    ):
        """It builds its own client, so it declares its own header name."""
        from app.modules.catalog.sources.router import _fetch_ogcapi_collection_srid

        recorded = transport("https://elsewhere.example/collect")
        credential, _value = _header_key()

        srid = await _fetch_ogcapi_collection_srid(
            "https://services.example.test/oapif",
            "parcels",
            ServiceCredential(
                method=credential.method,
                service_format="ogcapi_features",
                header_name=credential.header_name,
                header_value=credential.header_value,
            ),
        )

        # Degrades to no CRS rather than raising, and never issues the hop.
        assert srid is None
        assert len(recorded) == 1

    @pytest.mark.parametrize("probe", [probe_wfs, probe_ogcapi])
    async def test_a_same_origin_redirect_still_carries_it(self, transport, probe):
        """The ordinary case a service moving its own path produces."""
        recorded = transport("https://services.example.test/geoserver/moved")
        credential, value = _header_key()

        async with make_safe_client(credential_header="X-Api-Key") as client:
            await probe(_WFS_URL, client, credential=credential)

        assert len(recorded) == 2
        assert recorded[1].headers.get("X-Api-Key") == value


# ---------------------------------------------------------------------------
# A failed dispatch leaves nothing behind
# ---------------------------------------------------------------------------


class TestAFailedDispatchLeavesNoCredentialBehind:
    """The durable surfaces, for a credential that is no longer a bare token.

    Plan D9 keeps them all working by keeping the kwarg NAME: the queued-row
    purge is ``args - 'token'``, the terminal-row sweep reads the same key, and
    the log scrubber's regex is a word-boundary match on ``token``. What D9
    does not close on its own is the exact-value scrub: with a header line as
    the value, an origin that echoed back only the credential half would have
    survived it.
    """

    async def test_the_queued_row_purge_strips_a_composed_line(
        self, test_db_session
    ) -> None:
        from app.processing.ingest.tasks_common import purge_queued_job_token
        from tests.test_failed_job_token_purge_1746 import (
            _drop_queue,
            _queue_row,
            _read_args,
        )

        credential, _username, password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        line = f"{pair[0]}: {pair[1]}"
        blob = pair[1].removeprefix("Basic ")

        queue = f"b2b-purge-{uuid.uuid4().hex[:12]}"
        try:
            row_id = await _queue_row(
                test_db_session,
                status="failed",
                queue_name=queue,
                args={"job_id": str(uuid.uuid4()), "token": line},
            )
            context = SimpleNamespace(job=SimpleNamespace(id=row_id))
            await purge_queued_job_token(context)
            args = await _read_args(test_db_session, row_id)
        finally:
            await _drop_queue(test_db_session, queue)

        assert "token" not in args
        assert blob not in json.dumps(args)
        assert password not in json.dumps(args)

    def test_an_echo_of_the_credential_half_is_scrubbed_too(self) -> None:
        """The residual D9 does not close on its own.

        ``scrub_secret_from_exception`` scrubs the exact value it is handed.
        With the line as that value, an origin that quotes back the encoded
        credential without the header name it arrived under would have gone
        through untouched into ``IngestJob.error_message``, a log record, a
        notification reason and the exception the queue records.
        """
        from app.core.url_redaction import scrub_secret_from_exception

        credential, _username, _password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        line = f"{pair[0]}: {pair[1]}"
        blob = pair[1].removeprefix("Basic ")

        for echo in (line, pair[1], blob):
            error = ValueError(f"upstream said: {echo} was rejected")
            scrub_secret_from_exception(error, line)
            assert echo not in str(error)
            assert blob not in str(error)

    def test_a_bearer_echo_is_still_scrubbed_by_its_bare_token(self) -> None:
        """The parity half: this is exactly what was scrubbed before D9."""
        from app.core.url_redaction import scrub_secret_from_exception

        token = "tok" + _value()
        error = ValueError(f"upstream said: {token} was rejected")
        scrub_secret_from_exception(error, f"Authorization: Bearer {token}")
        assert token not in str(error)

    async def test_the_worker_error_carries_no_credential_after_the_scrub(
        self, monkeypatch
    ) -> None:
        """The chain, end to end, on the path an origin actually echoes.

        ogr2ogr prints the request it failed on, so a credential can reach
        stderr; ``redact_url_credentials`` is pattern-based and does not see a
        header. The exact-value scrub in the task is what closes it, and it can
        only close it because the value the task holds is the same string.
        """
        from app.core.url_redaction import scrub_secret_from_exception
        from app.processing.ingest.ogr import IngestionError

        credential, _username, _password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        line = f"{pair[0]}: {pair[1]}"
        blob = pair[1].removeprefix("Basic ")

        async def _fake_exec(*cmd, **kwargs):
            proc = MagicMock()
            proc.returncode = 1
            return proc

        async def _fake_communicate(proc, timeout, tool_name):
            return (b"", f"ERROR 1: HTTP error, sent {blob}".encode())

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        monkeypatch.setattr(
            "app.processing.ingest.ogr._communicate_with_timeout", _fake_communicate
        )

        with pytest.raises(IngestionError) as raised:
            await run_ogr2ogr_service(
                gdal_source=f"WFS:{_WFS_URL}",
                layer_name="topp:parcels",
                table_name="t",
                db_conn_str="PG:dummy",
                service_type="wfs",
                token=line,
                schema="data",
            )

        scrub_secret_from_exception(raised.value, line)
        assert blob not in str(raised.value)


# ---------------------------------------------------------------------------
# The preview path's own failure text
# ---------------------------------------------------------------------------


class TestAPreviewFailureCarriesNoCredential:
    """fix(#1746 B2b review r2): the door path needed the worker's scrub too.

    GDAL prints the request it failed on, so an origin that rejects a
    credential can put the header line, or the encoded credential on its own,
    into ogrinfo's stderr. Neither `redact_url_credentials`, which matches URL
    shapes, nor the stdlib log processor, which matches key NAMES, can see a
    credential arriving as prose under a `stderr` key. The exact-value scrub
    can, because it holds the value, and it runs before the log line and
    before the exception is built, so every downstream reader gets the same
    text: the API log, the 502 the router raises, and the response body.
    """

    async def _failing_preview(self, monkeypatch, credential, stderr_text: str):
        """Run a preview whose ogrinfo exits 1 with *stderr_text*."""
        import structlog

        async def _fake_exec(*cmd, **kwargs):
            proc = MagicMock()
            proc.returncode = 1

            async def _communicate():
                return (b"", stderr_text.encode())

            proc.communicate = _communicate
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with structlog.testing.capture_logs() as captured:
            with pytest.raises(Exception) as raised:  # noqa: PT011 - IngestionError is resolved through the port
                await preview_mod.run_service_preview(
                    f"WFS:{_WFS_URL}", "topp:parcels", credential=credential
                )
        return raised.value, captured

    async def test_a_basic_credential_echoed_in_stderr_is_scrubbed(
        self, monkeypatch
    ) -> None:
        credential, _username, password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        line = f"{pair[0]}: {pair[1]}"
        blob = pair[1].removeprefix("Basic ")

        # Every shape an origin can echo: the whole line, the scheme-prefixed
        # value, and the encoded credential on its own.
        stderr_text = (
            f"ERROR 1: HTTP error code 401 - sent '{line}' "
            f"(header value '{pair[1]}', credential '{blob}')"
        )
        error, captured = await self._failing_preview(
            monkeypatch, credential, stderr_text
        )

        for secret in (line, pair[1], blob, password):
            assert secret not in str(error), secret
            assert secret not in str(captured), secret

    async def test_a_named_api_key_echoed_in_stderr_is_scrubbed(
        self, monkeypatch
    ) -> None:
        credential, value = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        line = f"{pair[0]}: {pair[1]}"

        error, captured = await self._failing_preview(
            monkeypatch, credential, f"ERROR 1: rejected '{line}' / bare '{value}'"
        )

        for secret in (line, value):
            assert secret not in str(error), secret
            assert secret not in str(captured), secret

    async def test_a_bearer_token_echoed_in_stderr_is_scrubbed(
        self, monkeypatch
    ) -> None:
        """The shipping path keeps the guarantee the other two just gained."""
        credential = _bearer()
        token = credential.token
        error, captured = await self._failing_preview(
            monkeypatch,
            credential,
            f"ERROR 1: HTTP 401 for 'Authorization: Bearer {token}' / '{token}'",
        )

        assert token not in str(error)
        assert token not in str(captured)

    async def test_the_counterfactual(self, monkeypatch) -> None:
        """The assertions above pass because of the scrub, not by accident.

        Without a positive control an absence assertion is satisfied by a
        preview that never reached the failure block at all. This drives the
        same path with the scrub disabled and requires the credential to come
        through, so the three tests above cannot be green for the wrong
        reason.
        """
        monkeypatch.setattr(
            preview_mod, "scrub_secret_value", lambda text, secret: text
        )
        credential, _username, _password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        blob = pair[1].removeprefix("Basic ")

        error, captured = await self._failing_preview(
            monkeypatch, credential, f"ERROR 1: sent '{blob}'"
        )

        assert blob in str(error)
        assert blob in str(captured)

    async def test_unreadable_stdout_names_none_of_it(self, monkeypatch) -> None:
        """An exit-0 run whose stdout is not JSON used to raise the decoder's.

        A `JSONDecodeError` carries the document it could not parse, and that
        document is GDAL output like any other.
        """
        import structlog

        credential, _username, _password = _basic()
        pair = build_credential_header(credential)
        assert pair is not None
        blob = pair[1].removeprefix("Basic ")

        async def _fake_exec(*cmd, **kwargs):
            proc = MagicMock()
            proc.returncode = 0

            async def _communicate():
                return (f"not json, and it quotes {blob}".encode(), b"")

            proc.communicate = _communicate
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with structlog.testing.capture_logs() as captured:
            with pytest.raises(Exception) as raised:  # noqa: PT011
                await preview_mod.run_service_preview(
                    f"WFS:{_WFS_URL}", "topp:parcels", credential=credential
                )

        assert blob not in str(raised.value)
        assert blob not in str(captured)
        # And the chained original cannot carry it either.
        assert raised.value.__cause__ is None


# ---------------------------------------------------------------------------
# The queue this worker inherits from the version before it
# ---------------------------------------------------------------------------


class TestALegacyQueuedTokenStillImports:
    """fix(#1746 B2b review r3): a deploy must not fail the jobs already in flight.

    Plan D9 changed what travels under the `token` kwarg from a bare bearer
    token to a finished header line. A worker that starts while authenticated
    WFS or OGC API jobs are already queued reads the OLD shape, out of
    `procrastinate_jobs.args` or out of the credential store behind a reference
    the previous door stashed. Refusing it would fail every one of those
    deterministically at the next deploy or restart, and would spend the
    single-use credential before ogr2ogr started, which is worse than the skew
    #1689 accepted here: that one degraded to a 401 the operator could retry.

    The compatibility branch is exactly as wide as the old door was, and the
    line it produces comes from the same builder as every other line.
    """

    @pytest.mark.parametrize("service_type", ["wfs", "ogcapi_features"])
    async def test_a_bare_token_reaches_ogr2ogr_as_the_composed_line(
        self, monkeypatch, service_type
    ) -> None:
        token = "tok" + _value()
        capture = _CapturedRun()
        _capture_subprocess(monkeypatch, capture, payload=None)

        async def _fake_communicate(proc, timeout, tool_name):
            return (b"", b"")

        monkeypatch.setattr(
            "app.processing.ingest.ogr._communicate_with_timeout", _fake_communicate
        )
        await run_ogr2ogr_service(
            gdal_source=f"WFS:{_WFS_URL}",
            layer_name="topp:parcels",
            table_name="t",
            db_conn_str="PG:dummy",
            service_type=service_type,
            # The pre-#1770 wire value, exactly as the old door dispatched it.
            token=token,
            schema="data",
        )

        assert capture.header_bytes == (
            f"Authorization: Bearer {token}\n".encode("ascii")
        )
        assert _DOUBLE_PREFIX not in capture.header_bytes.decode("ascii")
        assert capture.env[_REDIRECT_PIN] == "NO"

    async def test_a_value_that_is_neither_shape_still_refuses(
        self, monkeypatch
    ) -> None:
        """The branch widens compatibility, not what may reach libcurl."""
        from app.processing.ingest.ogr import HEADER_LINE_SHAPE_POLICY

        spawned: list = []

        async def _fake_exec(*cmd, **kwargs):
            spawned.append(cmd)
            raise AssertionError("ogr2ogr must not be spawned for a refused value")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(ValueError) as raised:
            await run_ogr2ogr_service(
                gdal_source=f"WFS:{_WFS_URL}",
                layer_name="topp:parcels",
                table_name="t",
                db_conn_str="PG:dummy",
                service_type="wfs",
                # Not a line, and outside the charset the old door enforced.
                token="plus+slash/" + _value(),
                schema="data",
            )

        assert str(raised.value) == HEADER_LINE_SHAPE_POLICY
        assert spawned == []

    def test_the_compatibility_branch_composes_nothing_of_its_own(self) -> None:
        """The single-producer rule holds through the legacy path.

        A prefix written here would be a second producer in the module the
        whole gate exists to keep clean, and it would be invisible to the AST
        rule because this module's write site is allowlisted for a different
        reason (the line arrives as a task argument).
        """
        source = inspect.getsource(ogr_mod._legacy_bearer_line)
        assert "build_credential_header(" in source
        assert "credential_header_line(" in source
        assert "Bearer" not in source
