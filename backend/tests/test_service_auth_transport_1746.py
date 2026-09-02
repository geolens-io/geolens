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
import pathlib
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from dataclasses import replace

from app.core.service_tokens import (
    HEADER_TOKEN_POLICY,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
)
from app.modules.catalog.sources import preview as preview_mod
from app.modules.catalog.sources.adapters import arcgis as arcgis_mod
from app.modules.catalog.sources.adapters import ogcapi as ogcapi_mod
from app.modules.catalog.sources.adapters.ogcapi import probe_ogcapi
from app.modules.catalog.sources.adapters.wfs import probe_wfs
from app.platform import security
from app.platform.security import SSRFError, make_safe_client
from app.processing.ingest import tasks_vector
from app.processing.ingest import ogr as ogr_mod
from app.platform.service_items import ItemFetchFailedError, materialise_oapif_items
from app.processing.ingest.ogr import run_ogr2ogr_service

# fix(#1746 codex r2): autouse where imported — the credential header lands in
# gdal_header_dir(), so without this the suite writes into the real /tmp.
from tests.test_ogr_subprocess_env import gdal_header_tmpdir  # noqa: F401

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _staging_dir(tmp_path, monkeypatch):
    """Keep the materialised-items extract out of the real staging volume.

    fix(#1746 B2b review r16): a protected OGC API collection is streamed to a
    file under the staging dir, which on a developer host is the unwritable
    container path.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))


_WFS_URL = "https://services.example.test/geoserver/wfs"
_ARCGIS_BASE = "https://services.example.test/rest/services/Parcels/FeatureServer"
_REDIRECT_PIN = "CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT"
_REDIRECT_PIN_VALUE = "IF_SAME_HOST"
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
        self.cmd: tuple = ()


def _capture_subprocess(monkeypatch, capture: _CapturedRun, *, payload: dict | None):
    async def _fake_exec(*cmd, **kwargs):
        capture.cmd = cmd
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

        GDAL forwards ``Authorization`` only to the host it was given to, and
        forwards every other header name verbatim even across hosts, so a
        service-chosen API key is redirect-exposed here and cannot be protected
        from inside; that residual is bounded operationally, which is why the
        httpx probe path refuses the cross-origin hop outright instead.

        The value is asserted rather than left to GDAL's default so a later
        change to that default cannot silently widen what this credential
        follows. What it must NOT be is asserted too: see the test below.
        """
        if path == "preview":
            capture = await _preview_with(monkeypatch, _bearer())
        else:
            capture = await _commit_with(
                monkeypatch, "Authorization: Bearer tok" + _value()
            )

        assert capture.env[_REDIRECT_PIN] == _REDIRECT_PIN_VALUE
        # And never the option that reads as a defense and is a no-op (#937).
        assert "GDAL_HTTP_FOLLOWLOCATION" not in capture.env

    @pytest.mark.parametrize("path", ["preview", "commit"])
    async def test_the_pin_does_not_drop_the_header_on_a_same_host_redirect(
        self, monkeypatch, path
    ) -> None:
        """fix(#1746 B2b review r4): NO would have regressed working imports.

        ``NO`` blocks forwarding after ANY redirect, not only a cross-host one,
        so a protected WFS or OAPIF endpoint that redirects to its own
        canonical path -- adding a trailing slash is the common one -- would
        lose the credential and answer 401. Bearer imports that work today go
        through exactly that.

        This asserts the value, not the behaviour. The harness stubs the
        subprocess, so no libcurl runs and no redirect is followed here; what
        can be pinned is that this build asks GDAL for the same-host rule and
        not the total one.
        """
        if path == "preview":
            capture = await _preview_with(monkeypatch, _bearer())
        else:
            capture = await _commit_with(
                monkeypatch, "Authorization: Bearer tok" + _value()
            )

        assert capture.env[_REDIRECT_PIN] == "IF_SAME_HOST"
        assert capture.env[_REDIRECT_PIN] != "NO"

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

    async def test_a_bearer_token_is_not_charset_judged_before_detection(
        self, client, admin_auth_header: dict
    ) -> None:
        """fix(#1746 B2b review r7): the probe is what determines the service.

        A bearer token reaches detection whatever the URL looks like, because
        the transport that would constrain it is not known yet. The refusal,
        when it comes, comes from `TestABearerTokenIsJudgedAfterDetection`
        below, after every adapter has had its turn.
        """
        from app.modules.catalog.sources.schemas import ProbeResponse

        probe = AsyncMock(
            return_value=ProbeResponse(
                service_type="ArcGIS FeatureServer", url=_ARCGIS_BASE, layers=[]
            )
        )
        for url in (_WFS_URL, _ARCGIS_BASE):
            with (
                patch(
                    "app.modules.catalog.sources.router.validate_url_for_ssrf",
                    new_callable=AsyncMock,
                ),
                patch("app.modules.catalog.sources.router.detect_service_type", probe),
            ):
                resp = await client.post(
                    "/services/probe",
                    json={"url": url, "token": "tok+slash/" + _value()},
                    headers=admin_auth_header,
                )

            assert resp.status_code == 200, (url, resp.text)


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

    async def test_a_bare_token_reaches_ogr2ogr_as_the_composed_line(
        self, monkeypatch
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
            service_type="wfs",
            # The pre-#1770 wire value, exactly as the old door dispatched it.
            token=token,
            schema="data",
        )

        assert capture.header_bytes == (
            f"Authorization: Bearer {token}\n".encode("ascii")
        )
        assert _DOUBLE_PREFIX not in capture.header_bytes.decode("ascii")
        assert capture.env[_REDIRECT_PIN] == _REDIRECT_PIN_VALUE

    async def test_a_bare_token_reaches_the_ogcapi_reader_as_the_line(
        self, monkeypatch, tmp_path
    ) -> None:
        """The same conversion, on the driver that no longer sees a header file.

        A protected OGC API collection is read in-process now, so the legacy
        value has to arrive at that reader already composed, and nothing may be
        written for GDAL to pick up (fix #1746 B2b review r16).
        """
        token = "tok" + _value()
        capture = _CapturedRun()
        _capture_subprocess(monkeypatch, capture, payload=None)
        seen: dict = {}

        async def _fake_communicate(proc, timeout, tool_name):
            return (b"", b"")

        async def _fake_materialise(url, collection, **kwargs):
            seen.update(url=url, collection=collection, **kwargs)
            local = tmp_path / "items.geojson"
            local.write_text('{"type": "FeatureCollection", "features": []}')
            return str(local)

        monkeypatch.setattr(
            "app.processing.ingest.ogr._communicate_with_timeout", _fake_communicate
        )
        monkeypatch.setattr(
            "app.processing.ingest.ogr.materialise_oapif_items", _fake_materialise
        )
        await run_ogr2ogr_service(
            gdal_source=f"OAPIF:{_SVC_OAPIF}",
            layer_name="c0",
            table_name="t",
            db_conn_str="PG:dummy",
            service_type="ogcapi_features",
            token=token,
            schema="data",
        )

        assert seen["credential_line"] == f"Authorization: Bearer {token}"
        assert seen["url"] == _SVC_OAPIF
        assert seen["collection"] == "c0"
        # Nothing left for GDAL to read: no header file, and a local extract in
        # place of the service URL.
        assert capture.header_bytes is None
        assert str(tmp_path / "items.geojson") in capture.cmd
        assert not any(str(part).startswith("OAPIF:") for part in capture.cmd)

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


# ---------------------------------------------------------------------------
# A link the DOCUMENT chose is not a redirect, and nothing else guards it
# ---------------------------------------------------------------------------


_SERVICE_ORIGIN = "https://service.example"
_OTHER_ORIGIN = "https://elsewhere.example"


class TestTheConformanceLinkStaysOnTheServiceOrigin:
    """fix(#1746 B2b review r5): the second way a credential leaves its origin.

    `make_safe_client` refuses a cross-origin REDIRECT, and that covers every
    hop httpx follows. It cannot cover this one: when an OGC API landing page
    omits `conformsTo`, the adapter follows the `conformance` link the document
    named, and that is a fresh request. A landing page that points its
    conformance link at another origin would have been handed the credential
    built for the service.

    The rule is the same one, asked by the adapter instead of by the hook, and
    it uses the same `same_origin` definition so the two cannot drift.
    """

    def _landing(self, conformance_href: str) -> dict:
        """A landing page with no `conformsTo`, so the link must be followed."""
        return {
            "links": [
                {"rel": "data", "href": f"{_SERVICE_ORIGIN}/oapif/collections"},
                {"rel": "conformance", "href": conformance_href},
            ]
        }

    async def _probe(self, monkeypatch, credential, conformance_href, *, blocked=()):
        recorded: list[httpx.Request] = []
        landing = self._landing(conformance_href)

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if request.url.path.endswith("/collections"):
                return httpx.Response(200, json={"collections": [{"id": "parcels"}]})
            if "conformance" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "conformsTo": [
                            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
                        ]
                    },
                )
            return httpx.Response(200, json=landing)

        async def _validate(target: str) -> None:
            # The real validator has its own suite; what matters here is that
            # this adapter asks it BEFORE the fetch and honours the refusal.
            if any(target.startswith(prefix) for prefix in blocked):
                raise SSRFError("blocked")

        monkeypatch.setattr(
            "app.modules.catalog.sources.adapters.ogcapi.validate_url_for_ssrf",
            _validate,
        )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await probe_ogcapi(
                f"{_SERVICE_ORIGIN}/oapif", client, credential=credential
            )
        return recorded, result

    async def test_a_cross_origin_link_is_not_followed_with_a_credential(
        self, monkeypatch
    ) -> None:
        credential, value = _header_key()
        recorded, result = await self._probe(
            monkeypatch,
            replace(credential, service_format="ogcapi_features"),
            f"{_OTHER_ORIGIN}/conformance",
        )

        # Not a single request reached the other origin, so the key could not
        # have been disclosed to it.
        assert all(str(r.url).startswith(_SERVICE_ORIGIN) for r in recorded), recorded
        assert not [r for r in recorded if "conformance" in r.url.path]
        # And the credential still goes to the service itself, so this is a
        # refusal to follow one link and not a probe quietly stripped of its
        # credential.
        assert [r for r in recorded if r.headers.get("X-Api-Key") == value]
        # The service is still classified, by its `data` link, exactly as a
        # landing page advertising no conformance link at all would be.
        assert result is not None
        assert result["service_type"] == "OGC API Features"

    async def test_a_same_origin_link_keeps_the_credential(self, monkeypatch) -> None:
        """The ordinary shape, which must keep working.

        A service that publishes its conformance document under its own origin
        and requires a credential for it is the case this whole path exists
        for.
        """
        credential, value = _header_key()
        recorded, result = await self._probe(
            monkeypatch,
            replace(credential, service_format="ogcapi_features"),
            f"{_SERVICE_ORIGIN}/oapif/conformance",
        )

        conformance = [r for r in recorded if "conformance" in r.url.path]
        assert len(conformance) == 1
        assert conformance[0].headers.get("X-Api-Key") == value
        assert result is not None

    async def test_a_default_port_spelling_is_the_same_origin(
        self, monkeypatch
    ) -> None:
        """`https://host` and `https://host:443` are one origin, not two.

        Comparing the port as written would refuse a real service over a
        spelling difference, which is the failure `same_origin` fills the
        default port to avoid.
        """
        credential, value = _header_key()
        recorded, _result = await self._probe(
            monkeypatch,
            replace(credential, service_format="ogcapi_features"),
            "https://service.example:443/oapif/conformance",
        )

        conformance = [r for r in recorded if "conformance" in r.url.path]
        assert len(conformance) == 1
        assert conformance[0].headers.get("X-Api-Key") == value

    async def test_an_anonymous_probe_still_follows_a_cross_origin_link(
        self, monkeypatch
    ) -> None:
        """The refusal is about the credential, not about the link.

        With nothing to disclose there is nothing to protect, and refusing here
        would classify fewer public services for no gain. Recorded as a test so
        the asymmetry is deliberate rather than incidental.
        """
        recorded, result = await self._probe(
            monkeypatch, None, f"{_OTHER_ORIGIN}/conformance"
        )

        followed = [r for r in recorded if str(r.url).startswith(_OTHER_ORIGIN)]
        assert len(followed) == 1
        assert "x-api-key" not in {name.lower() for name in followed[0].headers}
        assert result is not None

    async def test_a_private_address_link_is_refused_before_any_request(
        self, monkeypatch
    ) -> None:
        """The SSRF gate is in front of this fetch, and its refusal is honoured.

        Driven anonymously on purpose. A private address is a different origin,
        so a credentialed probe is already refused by the rule above and this
        gate would never be reached; running it with no credential isolates the
        gate and proves it is the thing doing the refusing.
        """
        recorded, result = await self._probe(
            monkeypatch,
            None,
            "http://127.0.0.1:9/conformance",
            blocked=("http://127.0.0.1",),
        )

        assert "127.0.0.1" not in {r.url.host for r in recorded}, recorded
        assert result is not None

    async def test_a_syntactically_invalid_link_is_unusable_not_a_crash(
        self, monkeypatch
    ) -> None:
        """fix(#1746 B2b review r6): the origin question must be answerable.

        `httpx.URL` raises on something like `http://example.com:notaport/`,
        and the landing document chooses this URL, so asking whether it is the
        same origin used to turn a probe into a 500 where the old path
        degraded. An unparseable link is not the same origin as anything, so
        it is simply not followed.
        """
        credential, value = _header_key()
        recorded, result = await self._probe(
            monkeypatch,
            replace(credential, service_format="ogcapi_features"),
            "http://example.com:notaport/conformance",
        )

        assert not [r for r in recorded if "conformance" in r.url.path]
        assert all(str(r.url).startswith(_SERVICE_ORIGIN) for r in recorded), recorded
        assert [r for r in recorded if r.headers.get("X-Api-Key") == value]
        assert result is not None
        assert result["service_type"] == "OGC API Features"

    async def test_a_syntactically_invalid_link_degrades_anonymously_too(
        self, monkeypatch
    ) -> None:
        """The path with no credential never reaches the origin rule.

        It still has to degrade rather than raise, which is what the guarded
        block around the fetch is for, and what the old code did before this
        branch added an origin comparison in front of it.
        """
        recorded, result = await self._probe(
            monkeypatch, None, "http://example.com:notaport/conformance"
        )

        assert all(str(r.url).startswith(_SERVICE_ORIGIN) for r in recorded), recorded
        assert result is not None
        assert result["service_type"] == "OGC API Features"

    def test_the_origin_rule_is_total(self) -> None:
        """Asked directly, because both callers depend on it never raising."""
        from app.platform.security import same_origin

        assert same_origin("https://a.example/x", "https://a.example/y") is True
        assert same_origin("https://a.example", "https://a.example:443") is True
        assert same_origin("https://a.example", "https://b.example") is False
        # Unparseable on either side, and unparseable against itself.
        broken = "http://example.com:notaport/conformance"
        assert same_origin("https://a.example", broken) is False
        assert same_origin(broken, "https://a.example") is False
        assert same_origin(broken, broken) is False

    async def test_the_adapter_asks_the_shared_origin_rule(self) -> None:
        """One definition of same-origin, shared with the redirect refusal.

        A second one here would drift from the hook's, and the two are meant to
        answer the same question about the same credential.
        """
        source = inspect.getsource(ogcapi_mod._resolve_conformance)
        assert "same_origin(" in source
        assert "validate_url_for_ssrf(" in source


# ---------------------------------------------------------------------------
# The probe is what determines the service, so it judges the token afterwards
# ---------------------------------------------------------------------------


class TestABearerTokenIsJudgedAfterDetection:
    """fix(#1746 B2b review r7): restores the probe's pre-#1770 acceptance.

    The first cut of #1755 item 2 chose the credential policy from the URL
    shape, and that rejected a working import. `detect_service_type`'s slow
    path deliberately probes ArcGIS for a URL naming neither FeatureServer nor
    MapServer, and `probe_arcgis_service` classifies such an endpoint by what
    its response contains, so a vanity or rewritten ArcGIS URL is ordinary.
    Its token is percent-encoded into a query and legitimately holds `+` or
    `/`, which the header charset refuses.

    Only ArcGIS gets that acceptance back. A token no adapter can use is still
    refused, with the same code and the same policy-only message the preview
    and commit doors return; it just happens after detection rather than
    instead of it.
    """

    async def _probe(self, client, headers, url, body, handle):
        recorded: list[httpx.Request] = []

        def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return handle(request)

        with (
            patch.object(
                security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
            ),
            patch.object(security, "validate_url_for_ssrf", AsyncMock()),
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.catalog.sources.adapters.ogcapi.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.post(
                "/services/probe", json={"url": url, **body}, headers=headers
            )
        return resp, recorded

    async def test_a_keyword_free_arcgis_url_keeps_its_token_vocabulary(
        self, client, admin_auth_header: dict
    ) -> None:
        """The regression, end to end through the real adapters.

        No FeatureServer or MapServer in the URL, so the fast path does not
        fire and the two header-auth adapters are tried first. Neither can
        compose this token; that ends those two probes and nothing else, and
        the ArcGIS probe then classifies the endpoint by its response.
        """
        token = "tok+slash/" + _value()
        vanity = "https://gis.example/maps/data"

        def handle(request: httpx.Request) -> httpx.Response:
            if "f=json" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "currentVersion": 10.91,
                        "layers": [{"id": 0, "name": "Parcels"}],
                    },
                )
            return httpx.Response(404)

        resp, recorded = await self._probe(
            client, admin_auth_header, vanity, {"token": token}, handle
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["service_type"] == "ArcGIS FeatureServer"
        # The token reached the service the way that transport carries one,
        # percent-encoded into the query, and never as a header.
        arcgis = [r for r in recorded if "f=json" in r.url.query.decode()]
        assert arcgis
        assert "tok%2Bslash%2F" in str(arcgis[0].url)
        assert all(
            "authorization" not in {n.lower() for n in r.headers} for r in recorded
        )

    async def test_a_token_no_adapter_can_use_is_refused_after_detection(
        self, client, admin_auth_header: dict
    ) -> None:
        """The other half: the policy still applies, just not prematurely.

        Nothing claims this URL. The header-auth adapters could not compose the
        token, so the answer is the policy that explains why rather than
        "service not recognized", which would send the caller off to check
        their URL.
        """
        token = "tok+slash/" + _value()

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        resp, recorded = await self._probe(
            client, admin_auth_header, _WFS_URL, {"token": token}, handle
        )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "invalid_service_token"
        assert detail["message"] == HEADER_TOKEN_POLICY
        assert token not in resp.text
        # No credential left the process under a header, on any hop.
        assert all(
            "authorization" not in {n.lower() for n in r.headers} for r in recorded
        )

    async def test_an_unrecognized_service_still_says_so(
        self, client, admin_auth_header: dict
    ) -> None:
        """The policy answer must not swallow the ordinary one.

        With a token every adapter can use, a URL nothing claims is still a 400
        about the URL, which is the advice that caller needs.
        """

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        resp, _recorded = await self._probe(
            client,
            admin_auth_header,
            _WFS_URL,
            {"token": "tok" + _value()},
            handle,
        )

        assert resp.status_code == 400, resp.text

    @pytest.mark.parametrize("method", ["basic", "header"])
    async def test_the_header_only_methods_are_still_judged_up_front(
        self, client, admin_auth_header: dict, method
    ) -> None:
        """No detection outcome makes these sendable to ArcGIS.

        So their inputs are judged before anything is requested, exactly as
        before: the deferral is for the one method ArcGIS can carry.
        """
        secrets = [_value()]
        auth = (
            {"method": "basic", "username": secrets[0], "password": "bad\rvalue"}
            if method == "basic"
            else {
                "method": "header",
                "header_name": "X-Api-Key",
                "header_value": "bad\rvalue",
            }
        )

        def handle(request: httpx.Request) -> httpx.Response:
            raise AssertionError("nothing may be requested for a refused credential")

        resp, recorded = await self._probe(
            client, admin_auth_header, _WFS_URL, {"auth": auth}, handle
        )

        assert resp.status_code == 422, resp.text
        assert recorded == []
        for secret in secrets:
            assert secret not in resp.text

    async def test_a_fallback_detected_arcgis_refuses_a_method_it_cannot_carry(
        self, client, admin_auth_header: dict
    ) -> None:
        """fix(#1746 B2b review r9): the probe must answer what preview will.

        `url_query_token` answers None for basic and for a named API key,
        because neither fits in a query parameter. On this path that silently
        became an ANONYMOUS ArcGIS probe: the vanity endpoint answered 200 and
        the caller was told their credential worked, and then preview refused
        the same credential with `unsupported_auth_method`. The probe now
        gives that answer itself, once the fallback has established that
        ArcGIS is what this is.
        """
        secret = _value()
        vanity = "https://gis.example/maps/data"

        def handle(request: httpx.Request) -> httpx.Response:
            if "f=json" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "currentVersion": 10.91,
                        "layers": [{"id": 0, "name": "Parcels"}],
                    },
                )
            return httpx.Response(404)

        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            vanity,
            {
                "auth": {
                    "method": "basic",
                    "username": "u" + _value(),
                    "password": secret,
                }
            },
            handle,
        )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "unsupported_auth_method"
        assert secret not in resp.text
        # The ArcGIS request is the one that identified the service, and it is
        # the anonymous one: a basic credential has no query spelling, which
        # is the whole reason this refusal exists. The header-auth probes that
        # ran before it did carry the credential, to the service's own origin,
        # which is what they are for.
        arcgis = [r for r in recorded if "f=json" in r.url.query.decode()]
        assert arcgis
        assert all(secret not in str(r.url) for r in recorded)
        assert all(
            "authorization" not in {n.lower() for n in r.headers} for r in arcgis
        )

    async def test_the_same_fallback_still_succeeds_for_a_bearer_token(
        self, client, admin_auth_header: dict
    ) -> None:
        """The twin, so the refusal is about the method and not the path."""
        token = "tok" + _value()
        vanity = "https://gis.example/maps/data"

        def handle(request: httpx.Request) -> httpx.Response:
            if "f=json" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "currentVersion": 10.91,
                        "layers": [{"id": 0, "name": "Parcels"}],
                    },
                )
            return httpx.Response(404)

        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            vanity,
            {"auth": {"method": "bearer", "token": token}},
            handle,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["service_type"] == "ArcGIS FeatureServer"
        assert [r for r in recorded if token in str(r.url)]

    async def test_the_anonymous_fallback_is_untouched(
        self, client, admin_auth_header: dict
    ) -> None:
        """No credential, nothing to refuse: a public vanity endpoint probes."""
        vanity = "https://gis.example/maps/data"

        def handle(request: httpx.Request) -> httpx.Response:
            if "f=json" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "currentVersion": 10.91,
                        "layers": [{"id": 0, "name": "Parcels"}],
                    },
                )
            return httpx.Response(404)

        resp, _recorded = await self._probe(
            client, admin_auth_header, vanity, {}, handle
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["service_type"] == "ArcGIS FeatureServer"

    @staticmethod
    def _challenging_arcgis(request: httpx.Request) -> httpx.Response:
        """A protected keyword-free endpoint: ArcGIS 499 in a 200 body."""
        if "f=json" in str(request.url):
            return httpx.Response(
                200,
                json={"error": {"code": 499, "message": "Token Required"}},
            )
        return httpx.Response(404)

    async def test_a_challenged_fallback_refuses_a_method_it_cannot_carry(
        self, client, admin_auth_header: dict
    ) -> None:
        """fix(#1746 B2b review r10): the third sub-branch of one question.

        ArcGIS answers 499 in the BODY of a 200, which `probe_arcgis_service`
        turns into `ArcGISTokenError`. That challenge identifies the service
        just as surely as a layer list does, so it used to report the generic
        403 "provide a valid ArcGIS token" to a caller whose problem was the
        METHOD and not the token: advice they cannot act on, and a different
        answer from the two sibling branches.
        """
        secret = _value()
        vanity = "https://gis.example/maps/data"

        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            vanity,
            {
                "auth": {
                    "method": "basic",
                    "username": "u" + _value(),
                    "password": secret,
                }
            },
            self._challenging_arcgis,
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "unsupported_auth_method"
        assert secret not in resp.text
        arcgis = [r for r in recorded if "f=json" in r.url.query.decode()]
        assert arcgis
        assert all(secret not in str(r.url) for r in arcgis)

    async def test_a_challenged_fallback_still_challenges_an_anonymous_caller(
        self, client, admin_auth_header: dict
    ) -> None:
        """The challenge is true advice for the callers it is true for.

        With no credential, "this service requires authentication" is exactly
        what the caller needs to hear, and it is the answer this door has
        always given.
        """
        resp, _recorded = await self._probe(
            client,
            admin_auth_header,
            "https://gis.example/maps/data",
            {},
            self._challenging_arcgis,
        )

        assert resp.status_code == 403, resp.text

    async def test_a_challenged_fallback_still_challenges_a_bearer_caller(
        self, client, admin_auth_header: dict
    ) -> None:
        """A bearer token IS presentable here, so a rejection is about the token."""
        token = "tok" + _value()

        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            "https://gis.example/maps/data",
            {"auth": {"method": "bearer", "token": token}},
            self._challenging_arcgis,
        )

        assert resp.status_code == 403, resp.text
        # And it was actually presented, the way that transport presents one.
        assert [r for r in recorded if token in str(r.url)]


# ---------------------------------------------------------------------------
# The credential an ORIGIN knows is a username and a password
# ---------------------------------------------------------------------------


class TestTheCleartextHalvesOfABasicCredentialAreScrubbed:
    """fix(#1746 B2b review r11): base64 matches none of what a service says.

    A basic credential travels encoded, so every spelling scrubbed until now
    was an encoded one. The origin does not know that spelling: it knows a
    username and a password, and its own error text says so. GDAL propagates
    that body to stderr, the preview path logs it, and the worker paths carry
    it into `IngestJob.error_message`, the notification reason and the
    exception the queue records.

    The values here carry the characters #1749's review classes named --
    quotes, `#`, `&`, a path delimiter, a percent -- because the variants feed
    `str.replace`, which is literal. Nothing is compiled, so no value can
    change what matches; asserting that is what keeps a future rewrite from
    reaching for a regex.
    """

    @staticmethod
    def _awkward_basic() -> tuple[ServiceCredential, str, str, str]:
        """A credential whose halves exercise the redaction review classes."""
        username = "al'ice#" + _value()
        password = 'p&ss/"word%' + _value()
        credential = ServiceCredential(
            method=CredentialMethod.BASIC,
            service_format="wfs",
            username=username,
            password=password,
        )
        pair = build_credential_header(credential)
        assert pair is not None
        return credential, username, password, f"{pair[0]}: {pair[1]}"

    async def test_the_preview_path_scrubs_both_halves(self, monkeypatch) -> None:
        """The reported case, on the door path that logs stderr."""
        credential, username, password, line = self._awkward_basic()
        blob = line.rsplit(" ", 1)[1]

        (
            error,
            captured,
        ) = await TestAPreviewFailureCarriesNoCredential()._failing_preview(
            monkeypatch,
            credential,
            # What a service actually says, in the words it knows.
            f"ERROR 1: HTTP 401 authentication failed for user '{username}' "
            f"(password '{password}')",
        )

        for secret in (username, password, blob, line):
            assert secret not in str(error), secret
            assert secret not in str(captured), secret

    async def test_the_worker_failure_detail_scrubs_both_halves(
        self, monkeypatch
    ) -> None:
        """The same echo on the path that PERSISTS it.

        `scrub_secret_from_exception` mutates in place precisely so the job
        row, the log record, the notification reason and the re-raise all read
        the same text, so proving it once at that call proves it for all four.
        """
        from app.core.url_redaction import scrub_secret_from_exception
        from app.processing.ingest.ogr import IngestionError

        credential, username, password, line = self._awkward_basic()

        async def _fake_exec(*cmd, **kwargs):
            proc = MagicMock()
            proc.returncode = 1
            return proc

        async def _fake_communicate(proc, timeout, tool_name):
            return (
                b"",
                f"ERROR 1: rejected credentials for {username} / {password}".encode(),
            )

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

        # Before the scrub the worker's own message still carries it: the
        # pattern-based redactor cannot see a credential in prose, which is
        # why the exact-value scrub exists at all.
        scrub_secret_from_exception(raised.value, line)
        assert username not in str(raised.value)
        assert password not in str(raised.value)

    def test_a_blob_that_cannot_be_decoded_scrubs_what_it_can(self) -> None:
        """Never raise: the value reaching the scrub is whatever was handed over.

        A truncated, re-encoded or simply non-base64 blob has to degrade to
        "nothing extra to scrub" rather than replacing a failure message with a
        decoder traceback, and the line itself must still be scrubbed.
        """
        from app.core.url_redaction import scrub_secret_value

        for blob in ("!!! not base64 !!!", "dXNlcg", "", "=", "AAAA"):
            line = f"Authorization: Basic {blob}"
            scrubbed = scrub_secret_value(f"ERROR 1: sent {line}", line)
            assert line not in scrubbed
            assert "***" in scrubbed

    def test_the_halves_are_matched_literally_not_as_a_pattern(self) -> None:
        """#1749's review classes, asked directly.

        `scrub_secret_value` replaces with `str.replace`, so a credential
        containing regex metacharacters, quotes or a path delimiter is matched
        as itself. A future rewrite to a compiled pattern would fail here
        rather than in production.
        """
        from app.core.url_redaction import scrub_secret_value

        _credential, username, password, line = self._awkward_basic()
        for secret in (username, password):
            assert (
                scrub_secret_value(f"said {secret} loudly", line) == "said *** loudly"
            )
        # A metacharacter-only neighbour is untouched, which a pattern built
        # from these values would not manage.
        assert scrub_secret_value("a.*b", line) == "a.*b"

    def test_the_counterfactual_on_the_decode_step(self, monkeypatch) -> None:
        """The assertions above pass because of the decode, not by accident."""
        from app.core import url_redaction

        _credential, username, password, line = self._awkward_basic()
        monkeypatch.setattr(url_redaction, "_basic_cleartext", lambda blob: set())

        scrubbed = url_redaction.scrub_secret_value(
            f"user {username} pw {password}", line
        )
        assert username in scrubbed
        assert password in scrubbed


# ---------------------------------------------------------------------------
# Where a service says its own operations live
# ---------------------------------------------------------------------------


_SVC_ORIGIN = "https://service.example"
_SVC_WFS = f"{_SVC_ORIGIN}/geoserver/wfs"
_SVC_OAPIF = f"{_SVC_ORIGIN}/oapif"
_FOREIGN = "https://collector.example"


def _hosts(requests) -> set[str]:
    """The hosts a recorded run actually contacted.

    fix(#1746 B2b review r16): comparing parsed hosts rather than testing a
    substring of the URL. CodeQL flags the substring form, and it is right to:
    `"collector.example" in url` also matches
    `https://collector.example.attacker.test/`, so the assertion was weaker
    than it read.
    """
    return {request.url.host for request in requests}


def _capabilities(get_href: str) -> str:
    """A WFS 2.0 capabilities document advertising *get_href* for GetFeature."""
    return f"""<?xml version="1.0"?>
<WFS_Capabilities version="2.0.0"
    xmlns="http://www.opengis.net/wfs/2.0"
    xmlns:ows="http://www.opengis.net/ows/1.1"
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <ows:OperationsMetadata>
    <ows:Operation name="GetFeature">
      <ows:DCP><ows:HTTP>
        <ows:Get xlink:href="{get_href}"/>
      </ows:HTTP></ows:DCP>
    </ows:Operation>
  </ows:OperationsMetadata>
  <FeatureTypeList>
    <FeatureType><Name>topp:parcels</Name><Title>Parcels</Title>
      <DefaultCRS>urn:ogc:def:crs:EPSG::4326</DefaultCRS></FeatureType>
  </FeatureTypeList>
</WFS_Capabilities>"""


class TestAServiceCannotPointTheCredentialSomewhereElse:
    """fix(#1746 B2b review r13/r14): the document GDAL reads, not the one we do.

    GDAL applies `GDAL_HTTP_HEADER_FILE` to every request it makes, and for
    these two formats it does not only fetch the URL it was given: it reads the
    service's own description and fetches the operation endpoints that
    description advertises. Those are fresh requests, so
    `CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT` never applies and
    would not cover a service-chosen header name if it did.

    Two properties, and r14 is why the first one matters as much as the second.
    The description is read WITH the credential, because the services this
    protects are exactly the ones that answer an anonymous read with a 401; and
    a description that cannot be read is a refusal rather than a pass, because
    "could not read it" was the normal answer for those same services.
    """

    # The one class that drives the real check; every other suite gets the
    # autouse stub, so nothing reaches for a service description by accident.
    uses_the_real_endpoint_check = True

    def _transport(self, monkeypatch, handler):
        recorded: list[httpx.Request] = []

        def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return handler(request)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
        )
        monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
        monkeypatch.setattr(
            "app.platform.service_endpoints.validate_url_for_ssrf", AsyncMock()
        )
        # The adapter imported it by name, so patching the definition alone
        # leaves its own binding pointing at the real resolver.
        monkeypatch.setattr(
            "app.modules.catalog.sources.adapters.ogcapi.validate_url_for_ssrf",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "app.platform.service_items.validate_url_for_ssrf", AsyncMock()
        )
        return recorded

    @staticmethod
    def _wfs_handler(get_href: str, *, protected: bool = False):
        """A WFS whose capabilities advertise *get_href*.

        ``protected`` makes it answer 401 to an unauthenticated read, which is
        the shape that made an anonymous check worse than none: it learned
        nothing and approved the source.
        """

        def handle(request: httpx.Request) -> httpx.Response:
            if protected and "x-api-key" not in {
                name.lower() for name in request.headers
            }:
                return httpx.Response(401)
            if "GetCapabilities" in str(request.url):
                return httpx.Response(200, text=_capabilities(get_href))
            return httpx.Response(404)

        return handle

    @staticmethod
    def _oapif_handler(items_href: str, *, collection_count: int = 1):
        """An OGC API whose collection number ``collection_count - 1`` is foreign.

        The listing is paginated one page per collection so the probe has to
        follow `next`, and the last one carries the cross-origin items link.
        """
        ids = [f"c{index}" for index in range(collection_count)]

        def _collection(index: int) -> dict:
            href = (
                items_href
                if index == collection_count - 1
                else (f"{_SVC_OAPIF}/collections/{ids[index]}/items")
            )
            return {"id": ids[index], "links": [{"rel": "items", "href": href}]}

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/collections"):
                page = int(request.url.params.get("page", 0))
                body: dict = {"collections": [_collection(page)]}
                if page + 1 < collection_count:
                    body["links"] = [
                        {
                            "rel": "next",
                            "href": f"{_SVC_OAPIF}/collections?page={page + 1}",
                        }
                    ]
                return httpx.Response(200, json=body)
            if path.endswith("/items"):
                return httpx.Response(
                    200, json={"type": "FeatureCollection", "features": [], "links": []}
                )
            if "/collections/" in path:
                index = ids.index(path.rsplit("/", 1)[1])
                return httpx.Response(200, json=_collection(index))
            return httpx.Response(
                200,
                json={
                    "conformsTo": [
                        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
                    ],
                    "links": [{"rel": "data", "href": f"{_SVC_OAPIF}/collections"}],
                },
            )

        return handle

    async def _probe(self, client, headers, url, body, handler, monkeypatch):
        recorded = self._transport(monkeypatch, handler)
        with patch(
            "app.modules.catalog.sources.router.validate_url_for_ssrf",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                "/services/probe", json={"url": url, **body}, headers=headers
            )
        return resp, recorded

    @staticmethod
    def _key_auth(value: str) -> dict:
        return {"method": "header", "header_name": "X-Api-Key", "header_value": value}

    # -- the door -----------------------------------------------------------

    @pytest.mark.parametrize(
        ("href", "refused"),
        [
            (f"{_SVC_ORIGIN}/geoserver/wfs", False),
            ("/geoserver/wfs", False),
            ("wfs", False),
            (f"{_FOREIGN}/wfs", True),
        ],
        ids=["absolute_same", "root_relative", "relative", "cross_origin"],
    )
    async def test_the_probe_refuses_a_cross_origin_operation_endpoint(
        self, client, admin_auth_header: dict, monkeypatch, href, refused
    ) -> None:
        """Relative hrefs describe the service itself and must keep working."""
        value = _value()
        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {"auth": self._key_auth(value)},
            self._wfs_handler(href),
            monkeypatch,
        )

        if refused:
            assert resp.status_code == 422, resp.text
            detail = resp.json()["detail"]
            assert detail["code"] == "cross_origin_endpoint"
            assert detail["field"] == "url"
            assert value not in resp.text
        else:
            assert resp.status_code == 200, resp.text
        assert "collector.example" not in _hosts(recorded)

    async def test_a_protected_service_is_read_with_the_credential(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        """fix(#1746 B2b review r14): the reported hole, end to end.

        A protected origin answers an anonymous read with 401. The check used
        to take that as "nothing to see" and approve the source, and GDAL then
        authenticated, received the real document, and followed the
        cross-origin endpoint it advertised.
        """
        value = _value()
        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {"auth": self._key_auth(value)},
            self._wfs_handler(f"{_FOREIGN}/wfs", protected=True),
            monkeypatch,
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "cross_origin_endpoint"
        # The credential went to the submitted origin, which is what made the
        # real document readable, and nowhere else.
        authenticated = [r for r in recorded if r.headers.get("X-Api-Key") == value]
        assert authenticated
        assert all(str(r.url).startswith(_SVC_ORIGIN) for r in authenticated)
        assert "collector.example" not in _hosts(recorded)

    async def test_a_protected_same_origin_service_proceeds(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        """The half that must keep working: authentication is not the problem."""
        resp, _recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {"auth": self._key_auth(_value())},
            self._wfs_handler(f"{_SVC_ORIGIN}/geoserver/wfs", protected=True),
            monkeypatch,
        )

        assert resp.status_code == 200, resp.text

    async def test_a_description_that_stops_answering_is_not_approved(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        """A read that fails says nothing, so it cannot say yes.

        Shaped as the service answering the probe and then refusing the
        check's own read, which is the reachable form of it: a service that
        refuses every read is never detected at all and the door answers 400
        about the URL, before any of this. It is also the case the worker's
        second check exists for, since the document can change between two
        reads that are minutes apart.
        """
        value = _value()
        reads: list[int] = []

        def handle(request: httpx.Request) -> httpx.Response:
            if "GetCapabilities" not in str(request.url):
                return httpx.Response(404)
            reads.append(1)
            if len(reads) == 1:
                return httpx.Response(
                    200, text=_capabilities(f"{_SVC_ORIGIN}/geoserver/wfs")
                )
            return httpx.Response(503)

        resp, _recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {"auth": self._key_auth(value)},
            handle,
            monkeypatch,
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "endpoint_check_failed"
        assert value not in resp.text

    async def test_a_credential_free_probe_is_unaffected(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        """A public federated service is ordinary; the credential is the problem."""
        resp, _recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {},
            self._wfs_handler(f"{_FOREIGN}/wfs"),
            monkeypatch,
        )

        assert resp.status_code == 200, resp.text

    async def test_a_late_collection_is_refused_at_the_probe(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        """Within the page bound, the probe still sees a later collection."""
        value = _value()
        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_OAPIF,
            {"auth": self._key_auth(value)},
            self._oapif_handler(
                f"{_FOREIGN}/oapif/collections/c9/items", collection_count=10
            ),
            monkeypatch,
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "cross_origin_endpoint"
        assert "collector.example" not in _hosts(recorded)

    # -- the preview door ---------------------------------------------------

    async def test_the_preview_refuses_before_writing_the_header_file(
        self, monkeypatch
    ) -> None:
        credential, value = _header_key()
        recorded = self._transport(
            monkeypatch, self._wfs_handler(f"{_FOREIGN}/wfs", protected=True)
        )

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogrinfo must not be spawned for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(Exception) as raised:  # noqa: PT011 - HTTPException
            await preview_mod.run_service_preview(
                f"WFS:{_SVC_WFS}", "topp:parcels", credential=credential
            )

        assert raised.value.detail["code"] == "cross_origin_endpoint"
        assert value not in str(raised.value.detail)
        assert "collector.example" not in _hosts(recorded)

    async def test_the_preview_never_follows_an_advertised_items_link(
        self, monkeypatch
    ) -> None:
        """fix(#1746 B2b review r16): the link is not refused, it is not read.

        A protected collection is read in-process now, from the items path
        under the URL the caller submitted. What the service advertises for
        `rel=items` is never consulted, so pointing it at another origin buys
        nothing: that origin is simply never contacted.
        """
        credential, _value_ = _header_key()
        recorded = self._transport(
            monkeypatch,
            self._oapif_handler(
                f"{_FOREIGN}/oapif/collections/c54/items", collection_count=55
            ),
        )
        spawned: list = []

        async def _fake_exec(*cmd, **kwargs):
            spawned.append(cmd)
            proc = MagicMock()
            proc.returncode = 0

            async def _communicate():
                return (json.dumps(_EMPTY_LAYER).encode(), b"")

            proc.communicate = _communicate
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        await preview_mod.run_service_preview(
            f"OAPIF:{_SVC_OAPIF}", "c54", credential=credential
        )

        assert "collector.example" not in _hosts(recorded)
        # Read from the submitted origin's own items path, and ogrinfo was
        # handed a local file rather than the service.
        assert [r.url.path for r in recorded] == ["/oapif/collections/c54/items"]
        assert spawned
        assert not any(str(part).startswith("OAPIF:") for part in spawned[0])

    # -- the worker ---------------------------------------------------------

    async def _run_worker(self, monkeypatch, gdal_source: str, layer: str):
        credential, value = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogr2ogr must not be spawned for a refused source")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        await run_ogr2ogr_service(
            gdal_source=gdal_source,
            layer_name=layer,
            table_name="t",
            db_conn_str="PG:dummy",
            service_type="wfs" if gdal_source.startswith("WFS:") else "ogcapi_features",
            token=f"{pair[0]}: {pair[1]}",
            schema="data",
        )
        return value

    async def test_the_worker_refuses_the_same_source(self, monkeypatch) -> None:
        """Checked again here because the document can change in between.

        This is also the side that actually spends the credential, so a
        refusal that only ran at the door would be one an attacker could wait
        out.
        """
        from app.platform.service_endpoints import CrossOriginEndpointError

        recorded = self._transport(
            monkeypatch, self._wfs_handler(f"{_FOREIGN}/wfs", protected=True)
        )

        with pytest.raises(CrossOriginEndpointError):
            await self._run_worker(monkeypatch, f"WFS:{_SVC_WFS}", "topp:parcels")

        assert "collector.example" not in _hosts(recorded)

    async def test_an_endpoint_href_that_will_not_parse_is_refused(
        self, monkeypatch
    ) -> None:
        """fix(#1746 B2b review r16): the href comes out of a distrusted document.

        An address the parser cannot read cannot be shown to stay on the
        origin, so it gets the same coded refusal, and nothing of what the
        service wrote reaches the message.
        """
        from app.platform.service_endpoints import (
            CrossOriginEndpointError,
            assert_endpoints_stay_on_origin,
        )

        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        self._transport(monkeypatch, self._wfs_handler("http://[", protected=True))

        with pytest.raises(CrossOriginEndpointError) as raised:
            await assert_endpoints_stay_on_origin(
                _SVC_WFS,
                service_format="wfs",
                credential_line=f"{pair[0]}: {pair[1]}",
            )

        assert "[" not in raised.value.policy

    async def test_a_listing_next_that_will_not_parse_stops_the_walk(
        self, monkeypatch
    ) -> None:
        """The sibling site. The walk already stops for an off-origin `next`."""
        from app.platform.service_endpoints import assert_endpoints_stay_on_origin

        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/collections"):
                return httpx.Response(
                    200,
                    json={
                        "collections": [
                            {
                                "id": "c0",
                                "links": [
                                    {
                                        "rel": "items",
                                        "href": f"{_SVC_OAPIF}/collections/c0/items",
                                    }
                                ],
                            }
                        ],
                        "links": [{"rel": "next", "href": "http://["}],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "conformsTo": [
                        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
                    ],
                    "links": [{"rel": "data", "href": f"{_SVC_OAPIF}/collections"}],
                },
            )

        self._transport(monkeypatch, handle)

        await assert_endpoints_stay_on_origin(
            _SVC_OAPIF,
            service_format="ogcapi_features",
            credential_line=f"{pair[0]}: {pair[1]}",
        )

    async def test_the_worker_never_follows_an_advertised_items_link(
        self, monkeypatch
    ) -> None:
        """The same property on the side that actually spends the credential."""
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        recorded = self._transport(
            monkeypatch,
            self._oapif_handler(
                f"{_FOREIGN}/oapif/collections/c54/items", collection_count=55
            ),
        )
        spawned: list = []

        async def _fake_exec(*cmd, **kwargs):
            spawned.append((cmd, dict(kwargs.get("env") or {})))
            proc = MagicMock()
            proc.returncode = 0
            return proc

        async def _fake_communicate(proc, timeout, tool_name):
            return (b"", b"")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        monkeypatch.setattr(
            "app.processing.ingest.ogr._communicate_with_timeout", _fake_communicate
        )

        await run_ogr2ogr_service(
            gdal_source=f"OAPIF:{_SVC_OAPIF}",
            layer_name="c54",
            table_name="t",
            db_conn_str="PG:dummy",
            service_type="ogcapi_features",
            token=f"{pair[0]}: {pair[1]}",
            schema="data",
        )

        assert "collector.example" not in _hosts(recorded)
        assert [r.url.path for r in recorded] == ["/oapif/collections/c54/items"]
        argv, env = spawned[0]
        # ogr2ogr got a local file and no credential of any kind.
        assert not any(str(part).startswith("OAPIF:") for part in argv)
        assert "GDAL_HTTP_HEADER_FILE" not in env

    async def test_the_worker_proceeds_for_a_same_origin_service(
        self, monkeypatch
    ) -> None:
        """The counterfactual's other half: the guard is not refusing everything."""
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        self._transport(
            monkeypatch,
            self._wfs_handler(f"{_SVC_ORIGIN}/geoserver/wfs", protected=True),
        )

        spawned: list = []

        async def _fake_exec(*cmd, **kwargs):
            spawned.append(cmd)
            proc = MagicMock()
            proc.returncode = 0
            return proc

        async def _fake_communicate(proc, timeout, tool_name):
            return (b"", b"")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        monkeypatch.setattr(
            "app.processing.ingest.ogr._communicate_with_timeout", _fake_communicate
        )

        await run_ogr2ogr_service(
            gdal_source=f"WFS:{_SVC_WFS}",
            layer_name="topp:parcels",
            table_name="t",
            db_conn_str="PG:dummy",
            service_type="wfs",
            token=f"{pair[0]}: {pair[1]}",
            schema="data",
        )

        assert spawned

    # -- the validator itself -----------------------------------------------

    async def test_an_unreadable_document_refuses(self, monkeypatch) -> None:
        """fix(#1746 B2b review r14): fail closed, and this is why.

        The previous revision failed OPEN here, reasoning that one request
        against a third party should not refuse an import. That reasoning was
        wrong for this check specifically: the services it protects are the
        ones that refuse an unauthenticated description, so "could not read it"
        was their normal answer and it approved every one of them.
        """
        from app.platform.service_endpoints import (
            EndpointCheckFailedError,
            assert_endpoints_stay_on_origin,
        )

        self._transport(monkeypatch, lambda request: httpx.Response(500))

        with pytest.raises(EndpointCheckFailedError) as raised:
            await assert_endpoints_stay_on_origin(
                _SVC_WFS,
                service_format="wfs",
                credential_line=f"X-Api-Key: {_value()}",
            )

        assert raised.value.code == "endpoint_check_failed"
        assert raised.value.field == "url"

    async def test_a_malformed_capabilities_document_refuses(self, monkeypatch) -> None:
        from app.platform.service_endpoints import (
            EndpointCheckFailedError,
            assert_endpoints_stay_on_origin,
        )

        self._transport(
            monkeypatch, lambda request: httpx.Response(200, text="<not xml")
        )

        with pytest.raises(EndpointCheckFailedError):
            await assert_endpoints_stay_on_origin(
                _SVC_WFS,
                service_format="wfs",
                credential_line=f"X-Api-Key: {_value()}",
            )

    async def test_an_arcgis_source_is_not_checked(self, monkeypatch) -> None:
        """Its credential is a query parameter, so there is no header to leak."""
        from app.platform.service_endpoints import assert_endpoints_stay_on_origin

        recorded = self._transport(monkeypatch, self._wfs_handler(f"{_FOREIGN}/wfs"))

        await assert_endpoints_stay_on_origin(
            _SVC_WFS,
            service_format="arcgis_featureserver",
            credential_line=f"Authorization: Bearer tok{_value()}",
        )

        assert recorded == []

    async def test_a_credential_free_call_is_not_checked(self, monkeypatch) -> None:
        from app.platform.service_endpoints import assert_endpoints_stay_on_origin

        recorded = self._transport(monkeypatch, self._wfs_handler(f"{_FOREIGN}/wfs"))

        await assert_endpoints_stay_on_origin(
            _SVC_WFS, service_format="wfs", credential_line=None
        )

        assert recorded == []

    # -- the three WFS spellings, together ----------------------------------

    @staticmethod
    def _capabilities_10(online_resource: str) -> str:
        """WFS 1.0: `DCPType/HTTP/Get @onlineResource`, and no xlink at all.

        fix(#1746 B2b review r15): reading only `href` let a 1.0 service
        advertise a cross-origin GetFeature and pass the guard, which is
        exactly what this check exists to catch.
        """
        return f"""<?xml version="1.0"?>
<WFS_Capabilities version="1.0.0" xmlns="http://www.opengis.net/wfs">
  <Capability><Request>
    <GetFeature>
      <DCPType><HTTP><Get onlineResource="{online_resource}"/></HTTP></DCPType>
      <DCPType><HTTP><Post onlineResource="{online_resource}"/></HTTP></DCPType>
    </GetFeature>
  </Request></Capability>
  <FeatureTypeList>
    <FeatureType><Name>topp:parcels</Name><Title>Parcels</Title>
      <SRS>EPSG:4326</SRS></FeatureType>
  </FeatureTypeList>
</WFS_Capabilities>"""

    @pytest.mark.parametrize(
        ("version", "foreign"),
        [("1.0", True), ("1.0", False), ("2.0", True), ("2.0", False)],
        ids=["v1_0_cross", "v1_0_same", "v2_0_cross", "v2_0_same"],
    )
    async def test_every_wfs_spelling_of_an_operation_endpoint_is_read(
        self, client, admin_auth_header: dict, monkeypatch, version, foreign
    ) -> None:
        """The two attribute spellings, refused and allowed, in one place.

        1.1 and 2.0 name the endpoint with `xlink:href` under `ows:DCP`; 1.0
        uses `onlineResource` under `DCPType` and binds no xlink namespace.
        Both are compared by local name, because the namespaces and the
        prefixes bound to them differ across the three versions.
        """
        endpoint = f"{_FOREIGN}/wfs" if foreign else f"{_SVC_ORIGIN}/geoserver/wfs"
        document = (
            self._capabilities_10(endpoint)
            if version == "1.0"
            else _capabilities(endpoint)
        )

        def handle(request: httpx.Request) -> httpx.Response:
            if "GetCapabilities" in str(request.url):
                return httpx.Response(200, text=document)
            return httpx.Response(404)

        value = _value()
        resp, recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {"auth": self._key_auth(value)},
            handle,
            monkeypatch,
        )

        if foreign:
            assert resp.status_code == 422, resp.text
            assert resp.json()["detail"]["code"] == "cross_origin_endpoint"
            assert value not in resp.text
        else:
            assert resp.status_code == 200, resp.text
        assert "collector.example" not in _hosts(recorded)

    async def test_a_malformed_port_is_refused_without_raising(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        """fix(#1746 B2b review r15): the refusal must survive being built.

        `same_origin` already answered False for `http://example.com:notaport/`,
        which is correct. Reporting it then read `parsed.port`, which
        `urlparse` defers and raises ValueError on, so the clean 422 became a
        500. The port is dropped rather than echoed: the URL is
        provider-controlled and the raw value does not belong in a message or
        a log line.
        """
        value = _value()
        resp, _recorded = await self._probe(
            client,
            admin_auth_header,
            _SVC_WFS,
            {"auth": self._key_auth(value)},
            self._wfs_handler("http://example.com:notaport/wfs"),
            monkeypatch,
        )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "cross_origin_endpoint"
        assert detail["message"].endswith("Advertised origin: http://example.com")
        assert "notaport" not in resp.text
        assert value not in resp.text

    def test_the_validator_has_exactly_one_request_site(self) -> None:
        """fix(#1746 B2b review r15): one site, one marker, both counted.

        Every document this module reads goes through one `_fetch`, so the
        SSRF revalidation cannot be forgotten at a new call site and there is
        exactly one suppression marker to keep correct. A second request added
        beside it fails here rather than in a scan weeks later.
        """
        import inspect as _inspect

        from app.platform import service_endpoints

        source = _inspect.getsource(service_endpoints)
        requests = sum(
            source.count(f"client.{verb}(")
            for verb in ("get", "post", "put", "patch", "delete", "request", "stream")
        )
        assert requests == 1, requests
        assert source.count("# codeql[py/full-ssrf]") == 1
        # And the marker binds to the call: the suppression query reads the
        # line that FOLLOWS it, so prose between the two silently disarms it.
        lines = source.splitlines()
        marker = next(
            index
            for index, line in enumerate(lines)
            if "# codeql[py/full-ssrf]" in line
        )
        assert "client.get(" in lines[marker + 1]
        # The revalidation is in the same function, above the call.
        assert "validate_url_for_ssrf(url)" in "\n".join(lines[marker - 12 : marker])


class TestAPagedCollectionCannotWalkOffTheOrigin:
    """fix(#1746 B2b review r16): the page chain is bounded where it is read.

    An OGC API items response names its own successor. GDAL follows that link
    and applies `GDAL_HTTP_HEADER_FILE` to every request the process makes, and
    GDAL 3.10.3 has no way to scope a header to one origin; that was measured
    against a two-server rig before this module was written, and the command
    and result are in `app/platform/service_items.py`. So the pages are read
    here instead, and `next` is judged before it is followed.
    """

    def _transport(self, monkeypatch, handler):
        recorded: list[httpx.Request] = []

        def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return handler(request)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
        )
        monkeypatch.setattr(
            "app.platform.service_items.validate_url_for_ssrf", AsyncMock()
        )
        return recorded

    @staticmethod
    def _pages(*nexts: str | None):
        """A handler serving one feature per page, each naming the next."""

        def handle(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params.get("page", 0))
            body: dict = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": f"f{page}",
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                        "properties": {"page": page},
                    }
                ],
                "links": [],
            }
            if page < len(nexts) and nexts[page] is not None:
                body["links"] = [{"rel": "next", "href": nexts[page]}]
            return httpx.Response(200, json=body)

        return handle

    async def test_a_same_origin_chain_is_followed_to_the_end(
        self, monkeypatch, tmp_path
    ) -> None:
        credential, value = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        base = f"{_SVC_OAPIF}/collections/c1/items"
        recorded = self._transport(
            monkeypatch, self._pages(f"{base}?page=1", f"{base}?page=2", None)
        )

        path = await materialise_oapif_items(
            _SVC_OAPIF,
            "c1",
            credential_line=f"{pair[0]}: {pair[1]}",
            staging_dir=tmp_path,
        )

        document = json.loads(pathlib.Path(path).read_text())
        assert [f["properties"]["page"] for f in document["features"]] == [0, 1, 2]
        assert len(recorded) == 3
        # The credential went to the service, and only to the service.
        assert {r.url.host for r in recorded} == {httpx.URL(_SVC_OAPIF).host}
        assert all(r.headers.get(pair[0]) == value for r in recorded)

    async def test_a_cross_origin_next_is_refused_before_it_is_fetched(
        self, monkeypatch, tmp_path
    ) -> None:
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        recorded = self._transport(
            monkeypatch, self._pages(f"{_FOREIGN}/oapif/collections/c1/items")
        )

        with pytest.raises(ItemFetchFailedError):
            await materialise_oapif_items(
                _SVC_OAPIF,
                "c1",
                credential_line=f"{pair[0]}: {pair[1]}",
                staging_dir=tmp_path,
            )

        assert "collector.example" not in {r.url.host for r in recorded}
        # And the partial extract is gone: it is data read with somebody's
        # credential, and nothing downstream would know it was short.
        assert list(tmp_path.iterdir()) == []

    async def test_without_the_origin_check_the_foreign_page_is_fetched(
        self, monkeypatch, tmp_path
    ) -> None:
        """The counterfactual. Neuter `same_origin` and the leak comes back."""
        credential, value = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        recorded = self._transport(
            monkeypatch, self._pages(f"{_FOREIGN}/oapif/collections/c1/items", None)
        )
        monkeypatch.setattr(
            "app.platform.service_items.same_origin", lambda *args: True
        )

        await materialise_oapif_items(
            _SVC_OAPIF,
            "c1",
            credential_line=f"{pair[0]}: {pair[1]}",
            staging_dir=tmp_path,
        )

        foreign = [r for r in recorded if r.url.host == httpx.URL(_FOREIGN).host]
        assert foreign
        assert foreign[0].headers.get(pair[0]) == value

    async def test_a_preview_stops_at_its_sample_size(
        self, monkeypatch, tmp_path
    ) -> None:
        """A preview wants a handful of rows, not the collection."""
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        base = f"{_SVC_OAPIF}/collections/c1/items"
        recorded = self._transport(
            monkeypatch, self._pages(*[f"{base}?page={n}" for n in range(1, 20)])
        )

        path = await materialise_oapif_items(
            _SVC_OAPIF,
            "c1",
            credential_line=f"{pair[0]}: {pair[1]}",
            staging_dir=tmp_path,
            feature_limit=2,
        )

        document = json.loads(pathlib.Path(path).read_text())
        assert len(document["features"]) == 2
        assert len(recorded) == 2

    async def test_an_endless_chain_is_bounded(self, monkeypatch, tmp_path) -> None:
        """A service that always answers `next` is a fetch loop holding a key."""
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        base = f"{_SVC_OAPIF}/collections/c1/items"

        def handle(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params.get("page", 0))
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [],
                    "links": [{"rel": "next", "href": f"{base}?page={page + 1}"}],
                },
            )

        recorded = self._transport(monkeypatch, handle)
        monkeypatch.setattr("app.platform.service_items.MAX_PAGES", 4)

        path = await materialise_oapif_items(
            _SVC_OAPIF,
            "c1",
            credential_line=f"{pair[0]}: {pair[1]}",
            staging_dir=tmp_path,
        )

        assert len(recorded) == 4
        assert json.loads(pathlib.Path(path).read_text())["features"] == []

    async def test_a_next_that_will_not_parse_is_refused(
        self, monkeypatch, tmp_path
    ) -> None:
        """fix(#1746 B2b review r16): `urljoin` raises on some references.

        Refused rather than read as the end of the chain, so a short extract is
        never mistaken for a complete collection.
        """
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        self._transport(monkeypatch, self._pages("http://[", None))

        with pytest.raises(ItemFetchFailedError):
            await materialise_oapif_items(
                _SVC_OAPIF,
                "c1",
                credential_line=f"{pair[0]}: {pair[1]}",
                staging_dir=tmp_path,
            )

        assert list(tmp_path.iterdir()) == []

    async def test_a_page_that_cannot_be_read_leaves_nothing_behind(
        self, monkeypatch, tmp_path
    ) -> None:
        credential, _value_ = _header_key()
        pair = build_credential_header(credential)
        assert pair is not None
        self._transport(monkeypatch, lambda request: httpx.Response(500))

        with pytest.raises(ItemFetchFailedError):
            await materialise_oapif_items(
                _SVC_OAPIF,
                "c1",
                credential_line=f"{pair[0]}: {pair[1]}",
                staging_dir=tmp_path,
            )

        assert list(tmp_path.iterdir()) == []
