"""Tests for POST /ingest/upload/url — the two-phase URL import (#1705, #1710).

The endpoint validates and answers immediately; the ``fetch_url`` Procrastinate
task does the download. The tests split along that seam:

- Submission scope, asserted on the HTTP response: auth, the SSRF and scheme
  refusals, filename derivation/override/clamping, the extension allowlist,
  standalone VRT, control characters, and the dataset-count quota. Success is
  201 with status 'running' and a job row that stays 'running' until the task
  runs.
- Task scope, asserted on the IngestJob row and the staged files: the download
  through a mocked ``make_safe_client`` (httpx.MockTransport), the streamed
  size cap, per-hop redirect revalidation, compression refusal, the staged
  content sniff, S3 staging, the running -> pending CAS, and every failure
  settlement.

``_run_url_import`` POSTs and then runs the deferred task inline, so one call
still drives a whole import end to end.
"""

import asyncio
import inspect
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import AsyncByteStream, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
from app.platform.jobs.models import IngestJob
from app.platform.security import SSRFError, _revalidate_redirect
from app.processing.ingest.url_fetch import clamp_filename_bytes, filename_from_url

GEOJSON = b'{"type":"FeatureCollection","features":[]}'


class _StreamingBody(AsyncByteStream):
    """Chunked response body that records whether it was ever iterated."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks
        self.iterated = False

    async def __aiter__(self):
        self.iterated = True
        for chunk in self._chunks:
            yield chunk


def _install_transport(monkeypatch, handler, *, validate=None):
    """Patch the safe-client factory with a MockTransport-backed client.

    The mock client keeps ``follow_redirects`` and the REAL
    ``_revalidate_redirect`` event hook, so redirect tests exercise the
    per-hop revalidation exactly as ``make_safe_client`` wires it.

    ``validate`` replaces ``validate_url_for_ssrf`` for both the router's
    submission-time gate and the redirect hook (they resolve the same module
    attribute); the default accepts everything, since mock hostnames do not
    resolve in DNS.
    """
    recorded: list[httpx.Request] = []

    def factory(timeout=None, **_kwargs) -> httpx.AsyncClient:
        async def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            result = handler(request)
            if inspect.isawaitable(result):
                result = await result
            # fix(#1708 codex r11): the fetch reads aiter_raw (compression-
            # bomb hardening), and a Response built with content=... has its
            # stream pre-consumed — aiter_raw then raises StreamConsumed.
            # Real network responses are always live streams, so rebuild
            # content-shaped mock responses as streaming ones to keep the
            # harness faithful to the wire.
            try:
                body = result.content
            except httpx.ResponseNotRead:
                return result  # already a streaming body
            return httpx.Response(
                result.status_code,
                headers=result.headers,
                stream=_StreamingBody(body),
            )

        return httpx.AsyncClient(
            transport=httpx.MockTransport(_handle),
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"response": [_revalidate_redirect]},
        )

    monkeypatch.setattr("app.processing.ingest.url_fetch.make_safe_client", factory)
    monkeypatch.setattr(
        "app.platform.security.validate_url_for_ssrf",
        validate if validate is not None else AsyncMock(),
    )
    return recorded


def _capture_deferred_fetch(monkeypatch) -> dict:
    """Patch the queue hand-off so the fetch task's kwargs land in a dict.

    fix(#1710): the handler imports ``defer_async_with_tenant`` INSIDE its
    body, so the module attribute is the binding it resolves; patching it
    keeps the whole test suite off Procrastinate's queue.
    """
    captured: dict[str, dict] = {}

    async def _fake_defer(task, /, **kwargs):
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "app.core.db.tenant_session.defer_async_with_tenant", _fake_defer
    )
    return captured


async def _run_fetch_task(deferred_kwargs: dict) -> None:
    """Run the deferred ``fetch_url`` delivery in-process."""
    from app.processing.ingest.tasks_url_fetch import fetch_url

    # `Task.func` is the coroutine function a worker awaits; `tenant_id` is
    # threaded in by the real defer helper and popped by `tenant_task`.
    await fetch_url.func(
        **{k: v for k, v in deferred_kwargs.items() if k != "tenant_id"}
    )


async def _submit_url_import(client, monkeypatch, headers, json_body):
    """POST the URL. Returns ``(response, deferred_kwargs_or_None)``."""
    captured = _capture_deferred_fetch(monkeypatch)
    resp = await client.post("/ingest/upload/url", json=json_body, headers=headers)
    return resp, captured.get("kwargs")


async def _run_url_import(client, monkeypatch, headers, json_body):
    """POST the URL, then run the deferred fetch task inline.

    Returns ``(response, deferred_kwargs_or_None)``; the kwargs are None when
    the submission was refused before the queue hand-off.
    """
    resp, deferred = await _submit_url_import(client, monkeypatch, headers, json_body)
    if deferred is not None:
        await _run_fetch_task(deferred)
    return resp, deferred


async def _get_job(test_db_session, job_id: str) -> IngestJob | None:
    test_db_session.expire_all()
    result = await test_db_session.execute(
        select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
    )
    return result.scalar_one_or_none()


async def _job_by_name(test_db_session, source_filename: str) -> IngestJob:
    test_db_session.expire_all()
    result = await test_db_session.execute(
        select(IngestJob).where(IngestJob.source_filename == source_filename)
    )
    return result.scalar_one()


def _staged_files() -> list[Path]:
    return [p for p in Path(settings.upload_staging_dir).iterdir() if p.is_file()]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestUrlImportAuth:
    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/roads.geojson"},
        )
        assert resp.status_code == 401

    async def test_requires_upload_permission(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/roads.geojson"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# SSRF rejection at submission time (no transport installed: every one of
# these must be refused before any connection is attempted)
# ---------------------------------------------------------------------------


class TestUrlImportSsrf:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/data.geojson",  # loopback
            "http://10.0.0.5/data.geojson",  # RFC 1918
            "http://192.168.1.10/data.geojson",  # RFC 1918
            "http://169.254.169.254/latest.geojson",  # link-local / IMDS
            "http://100.64.0.1/data.geojson",  # CGNAT (SEC-013)
            "http://[::1]/data.geojson",  # IPv6 loopback
        ],
    )
    async def test_private_targets_rejected(
        self, client: AsyncClient, admin_auth_header: dict, url: str
    ):
        resp = await client.post(
            "/ingest/upload/url", json={"url": url}, headers=admin_auth_header
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://files.example.test/data.geojson",
            "file:///etc/passwd.geojson",
        ],
    )
    async def test_non_http_schemes_rejected(
        self, client: AsyncClient, admin_auth_header: dict, url: str
    ):
        resp = await client.post(
            "/ingest/upload/url", json={"url": url}, headers=admin_auth_header
        )
        assert resp.status_code == 400
        assert "http" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Filename / extension validation (all fail before anything is queued)
# ---------------------------------------------------------------------------


class TestUrlImportFilename:
    async def test_no_derivable_filename_needs_override(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "filename" in resp.json()["detail"]

    async def test_extensionless_path_needs_override(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/download"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_disallowed_extension_rejected(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ):
        # fix(#1708 codex r4): the SSRF gate now runs BEFORE the allowlist
        # check (so its unbounded DNS never overlaps a checked-out
        # connection); stub it so this unresolvable mock host reaches the
        # extension refusal it is testing.
        monkeypatch.setattr("app.platform.security.validate_url_for_ssrf", AsyncMock())
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/notes.txt"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    async def test_ssrf_gate_runs_before_any_handler_db_work(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ):
        """fix(#1708 codex r4): pins the reorder. The SSRF gate (with its
        unbounded getaddrinfo) must run before the handler's first DB call,
        so a DNS stall holds no pool connection. A refused URL must
        therefore never reach the allowlist fetch — if someone reorders the
        DB work back above the gate, the spy fires and this fails."""
        gate = AsyncMock(
            side_effect=SSRFError(
                "URLs targeting private/internal networks are not allowed"
            )
        )
        monkeypatch.setattr("app.platform.security.validate_url_for_ssrf", gate)
        spy = AsyncMock(return_value=[".geojson"])
        monkeypatch.setattr(
            "app.processing.ingest.router._get_allowed_extensions_safely", spy
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/x.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        gate.assert_awaited_once()
        spy.assert_not_awaited()

    async def test_standalone_vrt_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/mosaic.vrt"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "VRT" in resp.json()["detail"]

    def test_filename_from_url_shapes(self):
        assert filename_from_url("https://h/x/roads.geojson") == "roads.geojson"
        # Percent-encoding decodes to the real name.
        assert filename_from_url("https://h/my%20file.fgb") == "my file.fgb"
        # Query strings are not part of the name.
        assert filename_from_url("https://h/a.parquet?sig=abc") == "a.parquet"
        # No path name -> empty (router then requires an explicit override).
        assert filename_from_url("https://h/") == ""
        assert filename_from_url("https://h") == ""
        # Over-long names are trimmed at the stem, never the suffix.
        long = filename_from_url(f"https://h/{'a' * 400}.geojson")
        assert len(long.encode("utf-8")) <= 160
        assert long.endswith(".geojson")

    def test_clamp_filename_bytes_shapes(self):
        """fix(#1708 codex P2): the clamp counts encoded BYTES, not chars."""
        # Under the cap: untouched.
        assert clamp_filename_bytes("roads.geojson") == "roads.geojson"
        # ASCII at the schema max (255 chars): stem trimmed, suffix kept.
        ascii_long = clamp_filename_bytes("a" * 247 + ".geojson")
        assert len(ascii_long.encode("utf-8")) <= 160
        assert ascii_long.endswith(".geojson")
        # Multibyte: short in CHARACTERS but far over 255 bytes with the
        # 37-byte job-id prefix — the character-count bug's exact shape.
        cjk = clamp_filename_bytes("京" * 80 + ".geojson")
        assert len(cjk.encode("utf-8")) <= 160
        assert cjk.endswith(".geojson")
        # No split codepoint: the result must round-trip UTF-8 exactly.
        assert cjk.encode("utf-8").decode("utf-8") == cjk
        # 4-byte codepoints too.
        emoji = clamp_filename_bytes("🌍" * 70 + ".parquet")
        assert len(emoji.encode("utf-8")) <= 160
        assert emoji.endswith(".parquet")
        assert emoji.encode("utf-8").decode("utf-8") == emoji


# ---------------------------------------------------------------------------
# The fetch task (mocked transport; no network)
# ---------------------------------------------------------------------------


class TestUrlImportFetch:
    async def test_submission_answers_running_and_defers_the_url(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """The door commits a 'running', file-less row and hands the URL to
        the task as an argument rather than storing it on the job."""
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, deferred = await _submit_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/deferred.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "running"
        assert resp.json()["message"] == "Downloading the file"

        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "running"
        assert job.started_at is not None
        assert job.current_step == "downloading"
        # Not previewable yet, which is the state preview and commit refuse.
        assert not job.file_path

        assert deferred["url"] == "https://files.example.test/deferred.geojson"
        assert deferred["attempt_id"] == str(job.attempt_id)
        assert deferred["filename"] == "deferred.geojson"
        # fix(#1710): a URL can carry userinfo credentials and user_metadata
        # is served by GET /jobs/{id}, so the URL must not reach the row.
        assert "deferred.geojson" not in str(job.user_metadata or {})

    async def test_success_stages_file_and_creates_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/roads.geojson"},
        )
        assert resp.status_code == 201, resp.text

        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job is not None
        assert job.status == "pending"
        assert job.current_step is None
        assert job.source_filename == "roads.geojson"
        staged = Path(job.file_path)
        assert staged.exists()
        assert staged.read_bytes() == GEOJSON
        # No raster stamp for a vector file.
        assert (job.user_metadata or {}).get("file_type") is None
        # fix(#1708 codex r6): staging completion restarts the pending
        # review window; the stamp the sweep's coalesce reads must exist.
        assert (job.user_metadata or {}).get("staged_at")

    async def test_filename_override_for_query_style_urls(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {
                "url": "https://files.example.test/download?id=7",
                # Path components must be stripped, not staged.
                "filename": "../points.geojson",
            },
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.source_filename == "points.geojson"
        assert Path(job.file_path).name.endswith("points.geojson")

    async def test_raster_url_gets_file_type_stamp(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        tiff = b"II*\x00" + b"\x00" * 128
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=tiff)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/dem.tif"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert (job.user_metadata or {}).get("file_type") == "raster"

    async def test_declared_content_length_over_cap_settles_failed_unread(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        monkeypatch.setattr(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
        body = _StreamingBody(b"x" * 1024)
        _install_transport(
            monkeypatch,
            lambda request: httpx.Response(
                200,
                headers={"Content-Length": str(2 * 1024 * 1024)},
                stream=body,
            ),
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/big.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "failed"
        assert "exceeds the maximum allowed size" in (job.error_message or "")
        assert body.iterated is False
        assert _staged_files() == []

    async def test_streamed_bytes_over_cap_settle_failed_and_partial_removed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        monkeypatch.setattr(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
        # No Content-Length: three chunks totalling 1.5 MB against a 1 MB cap,
        # so the refusal can only come from counting what actually arrives.
        chunks = [b"x" * (512 * 1024)] * 3
        _install_transport(
            monkeypatch,
            lambda request: httpx.Response(200, stream=_StreamingBody(*chunks)),
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/streamedbig.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "failed"
        assert "exceeds the maximum allowed size" in (job.error_message or "")
        assert _staged_files() == []

    async def test_content_mismatch_settles_failed_and_staged_file_removed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        # Null bytes fail the text heuristic for .geojson; the sniff runs on
        # the STAGED file, after the download completed.
        _install_transport(
            monkeypatch,
            lambda request: httpx.Response(200, content=b"\x00\x01\x02\x03PK"),
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/fake.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "failed"
        assert "extension" in (job.error_message or "")
        assert _staged_files() == []

    async def test_origin_http_error_settles_the_job_failed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        _install_transport(
            monkeypatch, lambda request: httpx.Response(404, content=b"nope")
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/gone.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "failed"
        assert "404" in (job.error_message or "")
        assert job.completed_at is not None
        assert _staged_files() == []

    async def test_redirect_to_public_target_is_followed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/start.geojson":
                return httpx.Response(
                    302,
                    headers={"Location": "https://files.example.test/final.geojson"},
                )
            return httpx.Response(200, content=GEOJSON)

        _install_transport(monkeypatch, handler)
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/start.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert Path(job.file_path).read_bytes() == GEOJSON

    async def test_redirect_to_private_target_is_blocked_per_hop(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """The submission URL passes; the 302 hop to a private IP must not.

        ``validate`` refuses only the redirect target, so the settled failure
        here can only have come from ``_revalidate_redirect`` — the per-hop
        guard ``make_safe_client`` installs — not from the submission gate.
        """

        async def validate(url: str) -> None:
            if "169.254.169.254" in url:
                raise SSRFError(
                    "URLs targeting private/internal networks are not allowed"
                )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "169.254.169.254":  # pragma: no cover
                return httpx.Response(200, content=b"IMDS")
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest.geojson"},
            )

        recorded = _install_transport(monkeypatch, handler, validate=validate)
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/redirstart.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "failed"
        assert "not allowed" in (job.error_message or "")
        # The blocked hop was never fetched.
        assert all(r.url.host != "169.254.169.254" for r in recorded)
        assert _staged_files() == []

    async def test_failed_fetch_stamps_the_committed_job_failed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex P1): the door commits the row before the download,
        so a failed fetch cannot roll it away — it must be stamped 'failed'
        with the refusal instead of sitting 'running' until the lease reaper."""
        _install_transport(
            monkeypatch, lambda request: httpx.Response(404, content=b"nope")
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/stamped.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _job_by_name(test_db_session, "stamped.geojson")
        assert job.status == "failed"
        assert "404" in (job.error_message or "")

    async def test_ascii_255_char_override_is_clamped_and_staged(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex P2): a 255-char ASCII override used to build a
        292-byte staging component (37-byte job-id prefix + name) and die in
        open() with ENAMETOOLONG."""
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        override = "a" * 247 + ".geojson"  # 255 chars, the schema max
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {
                "url": "https://files.example.test/download?id=1",
                "filename": override,
            },
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "pending"
        staged = Path(job.file_path)
        assert staged.exists()
        assert staged.name.endswith(".geojson")
        # Whole component (prefix + clamped name) stays under NAME_MAX.
        assert len(staged.name.encode("utf-8")) <= 255

    async def test_multibyte_override_is_clamped_by_bytes_and_staged(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex P2): 88 CHARACTERS but 285 bytes with the prefix —
        short enough for the schema and any character-count cap, over
        NAME_MAX in bytes."""
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        override = "京" * 80 + ".geojson"
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {
                "url": "https://files.example.test/download?id=2",
                "filename": override,
            },
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "pending"
        staged = Path(job.file_path)
        assert staged.exists()
        assert staged.name.endswith(".geojson")
        assert len(staged.name.encode("utf-8")) <= 255
        # The clamp never splits a codepoint.
        assert staged.name.encode("utf-8").decode("utf-8") == staged.name


# ---------------------------------------------------------------------------
# Round-2 review findings (#1708): malformed URLs, and the running lease
# that keeps the stale-pending sweep off an in-progress fetch
# ---------------------------------------------------------------------------


class TestUrlImportMalformedUrl:
    async def test_malformed_authority_is_400_not_500(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """fix(#1708 codex r2): urlparse raises ValueError on 'http://[/...';
        derivation ran before the guarded block, so this exact payload 500ed."""
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "http://[/roads.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    async def test_malformed_authority_with_override_is_400(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """With an override the derivation skips urlparse, but the SSRF gate
        hits it — its ValueError must land in the endpoint's 400 family too."""
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "http://[/x", "filename": "roads.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400


class TestUrlImportReaperInteraction:
    def test_fetch_deadline_fits_the_running_lease(self):
        """The download's wall clock is operator-bounded, and the heartbeat
        renews the lease many times over inside the reaper's cutoff.

        feat(#1710): the download rides a worker lease rather than a request,
        so the fetch ceiling may legally exceed JOB_TIMEOUT_SECONDS; what has
        to hold is that the renewal interval is far under it, or a long
        download would be reaped mid-transfer.
        """
        from app.platform.jobs.heartbeat import HEARTBEAT_INTERVAL_SECONDS
        from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS

        assert 0 < settings.url_import_fetch_max_seconds <= 86400
        assert HEARTBEAT_INTERVAL_SECONDS * 10 < JOB_TIMEOUT_SECONDS

    async def test_mid_fetch_row_shape_is_invisible_to_the_pending_sweep(
        self, client, test_db_session
    ):
        """fix(#1708 codex r2): the sweep-exclusion claim, tested against the
        sweep's OWN clause set rather than a paraphrase of it.

        Two rows aged past any legal pending_job_timeout_seconds (backdated a
        full day): one shaped exactly like a mid-fetch URL import ('running',
        fresh started_at, empty file_path), one a bare abandoned 'pending'
        row. stale_pending_clauses must select the pending twin — proving the
        query bites — and must NOT select the mid-fetch row. The running
        sweep's lease predicate must also exclude it while started_at is
        fresh. (`client` is requested only to point app.core.db at the test
        engine; the queries here use test_db_session directly.)
        """
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import update as sa_update

        from app.platform.jobs.sweep import (
            JOB_TIMEOUT_SECONDS,
            stale_pending_clauses,
        )

        now = datetime.now(timezone.utc)
        mid_fetch = IngestJob(
            source_filename="sweepshape-a.geojson",
            file_path="",
            status="running",
            started_at=now,
        )
        abandoned = IngestJob(
            source_filename="sweepshape-b.geojson",
            file_path="",
            status="pending",
        )
        test_db_session.add_all([mid_fetch, abandoned])
        await test_db_session.flush()
        # created_at is server-stamped; backdate both past any legal cutoff.
        await test_db_session.execute(
            sa_update(IngestJob)
            .where(IngestJob.id.in_([mid_fetch.id, abandoned.id]))
            .values(created_at=now - timedelta(days=1))
        )

        swept = (
            (
                await test_db_session.execute(
                    select(IngestJob.id).where(
                        *stale_pending_clauses(now, completion_bound=False)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert abandoned.id in swept  # the clause set does bite...
        assert mid_fetch.id not in swept  # ...but not on the running row

        # The running sweep judges by the lease, and started_at is fresh.
        from sqlalchemy import func as sa_func

        running_swept = (
            (
                await test_db_session.execute(
                    select(IngestJob.id).where(
                        IngestJob.status == "running",
                        sa_func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                        < now - timedelta(seconds=JOB_TIMEOUT_SECONDS),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert mid_fetch.id not in running_swept
        await test_db_session.rollback()

    async def test_external_flip_mid_fetch_is_surfaced_not_part_updated(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r2): the post-fetch transition is a guarded CAS.

        The transport handler plays the reaper: it flips the row to 'failed'
        mid-download through an independent session. The completion's
        running->pending CAS then matches zero rows, so the task must delete
        the staged bytes and leave the external verdict untouched rather than
        part-updating a dead row.
        """
        from sqlalchemy import update as sa_update

        async def handler(request: httpx.Request) -> httpx.Response:
            import app.core.db as db_module

            async with db_module.async_session() as s:
                await s.execute(
                    sa_update(IngestJob)
                    .where(IngestJob.source_filename == "flip.geojson")
                    .values(
                        status="failed",
                        error_message="Stale: reaped by test",
                    )
                )
                await s.commit()
            return httpx.Response(200, content=GEOJSON)

        _install_transport(monkeypatch, handler)
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/flip.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "flip.geojson")
        # The external verdict survives — not overwritten by the completion
        # or by the failure-path stamp (both CAS from 'running' only).
        assert job.status == "failed"
        assert job.error_message == "Stale: reaped by test"

    async def test_staged_pending_row_gets_a_fresh_review_window(
        self, client, test_db_session
    ):
        """fix(#1708 codex r6): the running lease covers the fetch, but the
        completion CAS used to return the row to 'pending' with created_at
        unchanged — at the 61s floor of pending_job_timeout_seconds the sweep
        could reap the freshly staged local-mode import while the user was
        mid-preview. Tested against the sweep's OWN clause set: pending age
        is now measured from coalesce(staged_at, created_at). Three rows, all
        with created_at backdated a day: a staged import with a fresh
        staged_at keeps its window; one whose staged_at also aged out is
        still reaped (a restart, not an exemption); a pre-fetch abandoned
        twin without the key still ages from creation, unweakened."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import update as sa_update

        from app.platform.jobs.sweep import stale_pending_clauses

        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        staged_fresh = IngestJob(
            source_filename="freshwindow-a.geojson",
            # Local-mode staging binds an ABSOLUTE path -> the unbound half,
            # i.e. the short configurable cutoff (S3 mode binds 'staging/%'
            # and already sat under the 24h backstop).
            file_path="/tmp/urlimport/freshwindow-a.geojson",
            status="pending",
            user_metadata={"staged_at": now.isoformat()},
        )
        staged_stale = IngestJob(
            source_filename="freshwindow-b.geojson",
            file_path="/tmp/urlimport/freshwindow-b.geojson",
            status="pending",
            user_metadata={"staged_at": day_ago.isoformat()},
        )
        abandoned = IngestJob(
            source_filename="freshwindow-c.geojson",
            file_path="",
            status="pending",
        )
        test_db_session.add_all([staged_fresh, staged_stale, abandoned])
        await test_db_session.flush()
        await test_db_session.execute(
            sa_update(IngestJob)
            .where(IngestJob.id.in_([staged_fresh.id, staged_stale.id, abandoned.id]))
            .values(created_at=day_ago)
        )

        swept = (
            (
                await test_db_session.execute(
                    select(IngestJob.id).where(
                        *stale_pending_clauses(now, completion_bound=False)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert staged_fresh.id not in swept  # full review window from staging
        assert staged_stale.id in swept  # the window restarts, it doesn't exempt
        assert abandoned.id in swept  # pre-fetch abandonment still ages from creation
        await test_db_session.rollback()


# ---------------------------------------------------------------------------
# Round-5 review findings (#1708): filesystem-invalid names refused before a
# job exists; the wall clock covering connect/headers; cleanup that can never
# preempt the failure stamp
# ---------------------------------------------------------------------------


class TestUrlImportControlCharacters:
    async def test_nul_in_url_path_rejected_before_job_creation(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """fix(#1708 codex r5): '/roads%00.geojson' decodes to a NUL-bearing
        basename that passes the suffix/allowlist checks and blows up only at
        open() — after the running-commit, with the cleanup unlink raising
        again on the same path before the failure CAS. Exact payload; the
        refusal must come before any job row exists (and before DNS — the
        mock host does not resolve, so a 422 here proves the ordering)."""
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/nulname%00.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "control characters" in resp.json()["detail"]
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename.like("nulname%"))
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.parametrize(
        "override",
        [
            "roads\x00.geojson",  # embedded NUL, the reported payload
            "roads\n.geojson",  # newline — C0 range
            "roads\x7f.geojson",  # DEL
        ],
    )
    async def test_control_chars_in_override_rejected(
        self, client: AsyncClient, admin_auth_header: dict, override: str
    ):
        resp = await client.post(
            "/ingest/upload/url",
            json={
                "url": "https://files.example.test/download?id=9",
                "filename": override,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "control characters" in resp.json()["detail"]


class TestUrlImportWallClock:
    async def test_stalled_connect_fails_inside_the_wall_clock(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r5): the deadline used to be polled only between
        body chunks, so a stall during connect/DNS/headers ran outside it.
        The transport here never yields a response until well past the
        (patched) deadline — the download must still fail cleanly inside the
        budget, with the job stamped failed and nothing left in staging."""
        monkeypatch.setattr(settings, "url_import_fetch_max_seconds", 1)

        async def stalled(request: httpx.Request) -> httpx.Response:
            # Models an origin stalling before headers: nothing is produced
            # until far beyond the wall clock.
            await asyncio.sleep(10)
            return httpx.Response(200, content=GEOJSON)  # pragma: no cover

        _install_transport(monkeypatch, stalled)
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/stall.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "stall.geojson")
        assert job.status == "failed"
        assert "did not finish" in (job.error_message or "")


class TestUrlImportCleanupHardening:
    async def test_raising_cleanup_cannot_prevent_the_failure_stamp(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r5): the stuck-running SHAPE, not just the NUL
        instance. Whatever makes a cleanup step raise, the failure CAS must
        still run — here every unlink of this job's staged file throws, the
        origin 404s, and the row must still land 'failed' with the real
        refusal rather than a cleanup artifact."""
        original_unlink = Path.unlink

        def raising_unlink(self, *args, **kwargs):
            if "cleanupboom" in self.name:
                raise OSError("simulated cleanup failure")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", raising_unlink)
        _install_transport(
            monkeypatch, lambda request: httpx.Response(404, content=b"nope")
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/cleanupboom.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _job_by_name(test_db_session, "cleanupboom.geojson")
        assert job.status == "failed"
        assert "404" in (job.error_message or "")


# ---------------------------------------------------------------------------
# Round-7 review findings (#1708): the S3-mode completions of the two
# families — the CAS lands the staging key, and the byte quota is charged
# only once the object exists
# ---------------------------------------------------------------------------


class TestUrlImportS3Staging:
    async def test_s3_success_path_stages_and_cas_transitions(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """S3 mode end to end with the provider stubbed: the put succeeds,
        the CAS lands the staging key, and the job is previewable."""
        monkeypatch.setattr(settings, "storage_provider", "s3")
        put_calls: list[tuple[str, str]] = []

        async def fake_put(s3_key: str, local_dest: Path) -> None:
            put_calls.append((s3_key, str(local_dest)))

        monkeypatch.setattr(
            "app.processing.ingest.tasks_url_fetch._put_staging_object", fake_put
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/s3ok.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "pending"
        assert job.file_path == f"staging/{job.id}/s3ok.geojson"
        assert (job.user_metadata or {}).get("staged_at")
        assert len(put_calls) == 1
        # The local validation copy is deleted once S3 holds the bytes.
        assert _staged_files() == []

    async def test_put_runs_before_the_byte_quota_check(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r7 P1-A): pins the ordering. The byte-quota check
        runs AFTER the staging put, in the same short transaction as the CAS,
        so a put that fails must short-circuit before any byte-charged quota
        call — and the job must still settle failed."""
        monkeypatch.setattr(settings, "storage_provider", "s3")

        async def failing_put(s3_key: str, local_dest: Path) -> None:
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_url_fetch._put_staging_object", failing_put
        )
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._cleanup_saved_upload",
            AsyncMock(),
        )
        quota_spy = AsyncMock()
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.check_upload_quota", quota_spy
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/quotaorder.geojson"},
        )
        assert resp.status_code == 201, resp.text
        quota_spy.assert_not_awaited()
        job = await _job_by_name(test_db_session, "quotaorder.geojson")
        assert job.status == "failed"
        # An internal provider error is not user-authored text.
        assert job.error_message == "URL import failed"


# ---------------------------------------------------------------------------
# Round-8 review finding (#1708): the preflight DNS bound
# ---------------------------------------------------------------------------


class TestUrlImportPreflightDnsBound:
    async def test_stalled_preflight_dns_fails_inside_a_bound(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r8): submission-time getaddrinfo has no bound of
        its own. A validator that never returns must fail cleanly at the
        (patched) preflight bound, name DNS as the cause, and leave no job
        row — the gate runs before any job exists."""
        monkeypatch.setattr("app.processing.ingest.router.PREFLIGHT_DNS_MAX_SECONDS", 1)

        async def stalled_resolve(url: str) -> None:
            await asyncio.sleep(30)  # cancelled by wait_for at the bound

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", stalled_resolve
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/dnsstall.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 502
        assert "DNS" in resp.json()["detail"]
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename == "dnsstall.geojson")
        )
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Round-9 review finding (#1708): staging-path setup can never strand a
# running row
# ---------------------------------------------------------------------------


class TestUrlImportStagingDirFailure:
    async def test_unwritable_staging_parent_settles_the_job_failed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        tmp_path,
        monkeypatch,
    ):
        """fix(#1708 codex r9): mkdir of upload_staging_dir used to run
        outside the settlement guard, so a read-only parent left the job
        stranded 'running' for the full lease. feat(#1710) moved it into the
        task's guarded block: the same failure must now settle the row."""
        import os

        monkeypatch.setattr("app.platform.security.validate_url_for_ssrf", AsyncMock())
        ro_parent = tmp_path / "ro-parent"
        ro_parent.mkdir()
        os.chmod(ro_parent, 0o500)  # read+execute, no write: mkdir below fails
        try:
            monkeypatch.setattr(
                settings, "upload_staging_dir", str(ro_parent / "staging")
            )
            resp, _ = await _run_url_import(
                client,
                monkeypatch,
                admin_auth_header,
                {"url": "https://files.example.test/roparent.geojson"},
            )
        finally:
            os.chmod(ro_parent, 0o700)  # let pytest clean tmp_path up

        assert resp.status_code == 201, resp.text
        job = await _job_by_name(test_db_session, "roparent.geojson")
        assert job.status == "failed"
        assert not job.file_path


# ---------------------------------------------------------------------------
# Round-10 review finding (#1708): the stream cap honors the caller's
# remaining byte quota, not just the instance upload max
# ---------------------------------------------------------------------------


def _usage(bytes_used: int, storage_cap: int):
    from app.modules.quota.schemas import UserQuotaUsage

    return UserQuotaUsage(
        bytes_used=bytes_used,
        dataset_count=0,
        storage_cap=storage_cap,
        count_cap=0,
    )


class TestUrlImportQuotaCappedStream:
    async def test_at_cap_user_refused_before_any_origin_contact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """Zero remaining quota refuses before any origin contact.

        fix(#1708 codex r10): no bandwidth spent and nothing staged.
        fix(#1710): the refusal runs inside the task's settlement, so the
        row is stamped failed rather than left running for the lease.
        """
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.get_user_quota_usage",
            AsyncMock(return_value=_usage(bytes_used=1000, storage_cap=1000)),
        )
        recorded = _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/atcap.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert recorded == []  # the origin was never contacted
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "atcap.geojson")
        assert job.status == "failed"
        assert "Storage quota exceeded" in job.error_message
        assert not job.file_path

    async def test_near_cap_stream_cut_at_remaining_quota(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r10): the mid-stream cap is min(instance max,
        remaining quota). 100 KB of quota left against a 192 KB body with no
        Content-Length: the stream must be cut at the quota, with the
        settled failure naming the quota rather than the instance limit."""
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.get_user_quota_usage",
            AsyncMock(
                return_value=_usage(bytes_used=900 * 1024, storage_cap=1000 * 1024)
            ),
        )
        chunks = [b"x" * (64 * 1024)] * 3  # 192 KB, no Content-Length
        recorded = _install_transport(
            monkeypatch,
            lambda request: httpx.Response(200, stream=_StreamingBody(*chunks)),
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/nearcap.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert len(recorded) == 1  # the fetch started, then was cut
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "nearcap.geojson")
        assert job.status == "failed"
        assert "remaining storage quota" in (job.error_message or "")

    async def test_unlimited_quota_streams_under_the_instance_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """storage_cap == 0 means unlimited: the instance cap applies alone
        and a normal import is untouched by the preflight derivation."""
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.get_user_quota_usage",
            AsyncMock(return_value=_usage(bytes_used=10**12, storage_cap=0)),
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/unlimited.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "pending"

    async def test_post_download_check_still_authoritative_on_a_race(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r10): the preflight cap is advisory admission
        control; the post-stage check stays authoritative and is charged the
        bytes that actually landed. Quota consumed by a concurrent actor
        DURING the fetch must still be caught, with the staged bytes gone."""
        from fastapi import HTTPException

        charged: list[int] = []

        async def racing_quota(db_, user_id, incoming_bytes, request_):
            charged.append(incoming_bytes)
            raise HTTPException(
                status_code=413,
                detail="Storage quota exceeded: raced during fetch",
            )

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.check_upload_quota", racing_quota
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/raced.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert charged == [len(GEOJSON)]
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "raced.geojson")
        assert job.status == "failed"
        assert "raced" in (job.error_message or "")


# ---------------------------------------------------------------------------
# Round-11 review findings (#1708): compression bombs never reach a
# decompressor, and an ambiguous final commit never deletes live bytes
# ---------------------------------------------------------------------------


class TestUrlImportCompressionRefusal:
    async def test_compressed_response_refused_without_decoding(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r11): a Content-Encoding response is refused by
        design, before any body handling. The body here is NOT valid gzip —
        anything that routed it through a decompressor would raise
        DecodingError instead of our deterministic refusal — and the request
        must have asked for identity in the first place."""
        # Built as a STREAM: httpx.Response(content=..., headers={CE: gzip})
        # decodes at construction — inside the test handler, before any
        # production code — which is itself a nice demonstration of the
        # bomb surface. A real origin delivers a stream, so the mock does.
        recorded = _install_transport(
            monkeypatch,
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=_StreamingBody(b"\x00\x01not-gzip-at-all" * 64),
            ),
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/bomb.geojson"},
        )
        assert resp.status_code == 201, resp.text
        # Belt: the request asked the origin for an uncompressed transfer.
        assert recorded[0].headers.get("Accept-Encoding") == "identity"
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "bomb.geojson")
        assert job.status == "failed"
        assert "transport-compressed" in (job.error_message or "")


class TestUrlImportAmbiguousCommit:
    async def test_ambiguous_commit_landed_stands_down(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r11): the final commit was durably applied but the
        acknowledgement raised. Settlement must probe on a fresh session,
        see the pending row bound to the staged path, and stand down — the
        staged bytes survive and the row stays coherent."""

        async def ack_lost(db) -> None:
            await db.commit()  # durable on the server...
            raise ConnectionError("ack lost after durable commit")

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._commit_staged_transition",
            ack_lost,
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/acklost.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _job_by_name(test_db_session, "acklost.geojson")
        assert job.status == "pending"  # NOT flipped to failed
        assert job.error_message is None
        staged = Path(job.file_path)
        assert staged.exists()  # the bytes were NOT deleted
        assert staged.read_bytes() == GEOJSON

    async def test_genuine_commit_failure_settles_normally(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """The control: a commit that genuinely failed (rolled back server-
        side) must settle exactly as before — staged bytes deleted, job
        CAS-stamped failed."""

        async def commit_failed(db) -> None:
            await db.rollback()  # the server never applied it
            raise ConnectionError("commit failed")

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._commit_staged_transition",
            commit_failed,
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/commitfail.geojson"},
        )
        assert resp.status_code == 201, resp.text
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "commitfail.geojson")
        assert job.status == "failed"
        assert job.error_message == "URL import failed"


# ---------------------------------------------------------------------------
# Round-14 review findings (#1708): the ambiguous-commit probe fires ONLY for
# a genuinely ambiguous commit, and settlement releases its connection first
# ---------------------------------------------------------------------------


class TestUrlImportSettlementScope:
    async def test_post_stage_rejection_never_probes_and_rolls_back_first(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r14): an ordinary post-stage failure (quota race)
        has a KNOWN outcome, so it must not open the probe's fresh session —
        which, held alongside its own still-open transaction, is what could
        exhaust the pool. It must also roll back BEFORE any settlement work,
        and settle normally: artifact cleaned, job failed."""
        from fastapi import HTTPException
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, deferred = await _submit_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/probescope.geojson"},
        )
        assert resp.status_code == 201, resp.text

        # Installed after submission so `order` records the task's sequence
        # only, not the request teardown's rollback.
        order: list[str] = []

        probe_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._url_import_transition_landed",
            probe_spy,
        )

        real_rollback = _AsyncSession.rollback

        async def recording_rollback(self):
            order.append("rollback")
            return await real_rollback(self)

        monkeypatch.setattr(_AsyncSession, "rollback", recording_rollback)

        real_unlink = Path.unlink

        def recording_unlink(self, *args, **kwargs):
            if "probescope" in self.name:
                order.append("cleanup")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", recording_unlink)

        async def racing_quota(db_, user_id, incoming_bytes, request_):
            raise HTTPException(status_code=413, detail="quota raced")

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.check_upload_quota", racing_quota
        )

        await _run_fetch_task(deferred)

        # The probe — and its fresh session — was never reached.
        probe_spy.assert_not_awaited()
        # The connection was released before any settlement work.
        assert "rollback" in order and "cleanup" in order
        assert order.index("rollback") < order.index("cleanup")
        # And the failure settled normally.
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "probescope.geojson")
        assert job.status == "failed"

    async def test_ambiguous_commit_still_probes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """The narrowing must not disarm the r11 protection: an exception
        out of the final commit still reaches the probe and stands down."""

        async def ack_lost(db) -> None:
            await db.commit()
            raise ConnectionError("ack lost after durable commit")

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._commit_staged_transition",
            ack_lost,
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/stillprobes.geojson"},
        )
        assert resp.status_code == 201, resp.text
        job = await _job_by_name(test_db_session, "stillprobes.geojson")
        assert job.status == "pending"  # stood down, not stamped failed
        assert Path(job.file_path).exists()  # bytes preserved

    def test_only_the_commit_seam_marks_its_exception(self):
        """The marker is acquired by the commit seam alone — an exception
        merely passing through settlement never gains it."""
        from app.processing.ingest.url_import_staging import _COMMIT_AMBIGUOUS_ATTR

        assert getattr(ValueError("plain"), _COMMIT_AMBIGUOUS_ATTR, False) is False


# ---------------------------------------------------------------------------
# Round-15 review finding (#1708): the landed stand-down keeps the artifact
# the ROW references and drops the copy nothing references
# ---------------------------------------------------------------------------


class TestUrlImportLandedStandDownCleanup:
    async def test_s3_landed_stand_down_drops_the_local_copy(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r15): under S3 the pending row records only the
        staging key, so the local file is a redundant sniff copy that NO
        reaper can discover — the stand-down's early return used to leak one
        per ambiguous commit. The S3 object must survive (the row points at
        it); the local copy must not."""
        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setattr(
            "app.processing.ingest.tasks_url_fetch._put_staging_object", AsyncMock()
        )
        delete_spy = AsyncMock()
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._cleanup_saved_upload", delete_spy
        )

        async def ack_lost(db) -> None:
            await db.commit()
            raise ConnectionError("ack lost after durable commit")

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._commit_staged_transition",
            ack_lost,
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/s3landed.geojson"},
        )
        assert resp.status_code == 201, resp.text

        job = await _job_by_name(test_db_session, "s3landed.geojson")
        assert job.status == "pending"
        assert job.file_path == f"staging/{job.id}/s3landed.geojson"
        # The referenced S3 object was NOT deleted...
        delete_spy.assert_not_awaited()
        # ...and the unreferenced local copy is gone.
        assert _staged_files() == []

    async def test_local_landed_stand_down_keeps_the_artifact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """The other half of the distinction, pinned: under local storage
        `local_dest` IS the artifact the pending row references, so the same
        branch must NOT delete it — doing so would recreate the exact
        pending-row-pointing-at-nothing failure the stand-down prevents."""

        async def ack_lost(db) -> None:
            await db.commit()
            raise ConnectionError("ack lost after durable commit")

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging._commit_staged_transition",
            ack_lost,
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, _ = await _run_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/locallanded.geojson"},
        )
        assert resp.status_code == 201, resp.text

        job = await _job_by_name(test_db_session, "locallanded.geojson")
        assert job.status == "pending"
        staged = Path(job.file_path)
        assert staged.exists()
        assert staged.read_bytes() == GEOJSON


# ---------------------------------------------------------------------------
# feat(#1710): the delivery fence — a token-less or already-settled delivery
# touches nothing
# ---------------------------------------------------------------------------


class TestUrlImportDeliveryFence:
    async def test_delivery_without_an_attempt_token_touches_nothing(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """A delivery carrying no attempt token must not adopt the lease: it
        returns without contacting the origin or moving the row."""
        recorded = _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, deferred = await _submit_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/notoken.geojson"},
        )
        assert resp.status_code == 201, resp.text
        await _run_fetch_task({**deferred, "attempt_id": None})

        assert recorded == []
        job = await _job_by_name(test_db_session, "notoken.geojson")
        assert job.status == "running"
        assert not job.file_path

    async def test_delivery_after_an_external_settlement_stands_down(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1710): a cancel, retry or stale sweep that settles the row
        before the delivery lands wins — the adoption CAS misses and the task
        must not download anything or revive the job."""
        from sqlalchemy import update as sa_update

        recorded = _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp, deferred = await _submit_url_import(
            client,
            monkeypatch,
            admin_auth_header,
            {"url": "https://files.example.test/settled.geojson"},
        )
        assert resp.status_code == 201, resp.text

        import app.core.db as db_module

        async with db_module.async_session() as s:
            await s.execute(
                sa_update(IngestJob)
                .where(IngestJob.source_filename == "settled.geojson")
                .values(status="cancelled", error_message="Cancelled by test")
            )
            await s.commit()

        await _run_fetch_task(deferred)

        assert recorded == []
        assert _staged_files() == []
        job = await _job_by_name(test_db_session, "settled.geojson")
        assert job.status == "cancelled"
        assert job.error_message == "Cancelled by test"
