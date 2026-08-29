"""Tests for feat(#1705) — POST /ingest/upload/url, the URL variant of upload.

Covers the Rule 2 posture end to end without touching the network:

- SSRF rejection at submission time (private/link-local/loopback/scheme),
  driven by IP-literal URLs so no DNS resolution is required.
- The fetch path via a mocked ``make_safe_client`` (httpx.MockTransport),
  including per-hop redirect revalidation, the streamed size cap with and
  without a Content-Length header, staged-file content sniffing, and origin
  HTTP failures mapping to 502.
- The staged result entering the normal upload pipeline: an IngestJob row in
  'pending', the file on local staging, and the raster stamp for .tif.
"""

import asyncio
import inspect
import time
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
            return result

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


async def _get_job(test_db_session, job_id: str) -> IngestJob | None:
    result = await test_db_session.execute(
        select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
    )
    return result.scalar_one_or_none()


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
# Filename / extension validation (all fail before any fetch)
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
# The fetch path (mocked transport; no network)
# ---------------------------------------------------------------------------


class TestUrlImportFetch:
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
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/roads.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "pending"

        job = await _get_job(test_db_session, data["job_id"])
        assert job is not None
        assert job.status == "pending"
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
        resp = await client.post(
            "/ingest/upload/url",
            json={
                "url": "https://files.example.test/download?id=7",
                # Path components must be stripped, not staged.
                "filename": "../points.geojson",
            },
            headers=admin_auth_header,
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
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/dem.tif"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert (job.user_metadata or {}).get("file_type") == "raster"

    async def test_declared_content_length_over_cap_is_413_without_reading_body(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
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
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/big.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 413
        assert body.iterated is False
        assert _staged_files() == []

    async def test_streamed_bytes_over_cap_is_413_and_partial_file_removed(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ):
        monkeypatch.setattr(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
        # No Content-Length: three chunks totalling 1.5 MB against a 1 MB cap,
        # so the refusal can only come from counting what actually arrives.
        chunks = [b"x" * (512 * 1024)] * 3
        _install_transport(
            monkeypatch,
            lambda request: httpx.Response(200, stream=_StreamingBody(*chunks)),
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/big.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 413
        assert _staged_files() == []

    async def test_content_mismatch_is_422_and_staged_file_removed(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ):
        # Null bytes fail the text heuristic for .geojson; the sniff runs on
        # the STAGED file, after the download completed.
        _install_transport(
            monkeypatch,
            lambda request: httpx.Response(200, content=b"\x00\x01\x02\x03PK"),
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/fake.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "extension" in resp.json()["detail"]
        assert _staged_files() == []

    async def test_origin_http_error_maps_to_502(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ):
        _install_transport(
            monkeypatch, lambda request: httpx.Response(404, content=b"nope")
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/gone.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 502
        assert "404" in resp.json()["detail"]
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
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/start.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert Path(job.file_path).read_bytes() == GEOJSON

    async def test_redirect_to_private_target_is_blocked_per_hop(
        self, client: AsyncClient, admin_auth_header: dict, monkeypatch
    ):
        """The submission URL passes; the 302 hop to a private IP must not.

        ``validate`` refuses only the redirect target, so the 400 here can
        only have come from ``_revalidate_redirect`` — the per-hop guard
        ``make_safe_client`` installs — not from the submission-time gate.
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
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/start.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]
        # The blocked hop was never fetched.
        assert all(r.url.host != "169.254.169.254" for r in recorded)
        assert _staged_files() == []

    async def test_job_row_committed_before_fetch_releases_connection(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex P1): the transaction ends before the fetch awaits.

        The transport handler runs in the middle of the fetch. It opens its
        OWN session (a separate pool connection) and looks for the job row:
        visible there means the request's transaction was committed — and
        with it the request's pool connection released — before the remote
        download started. Before the fix the row was only flushed, so an
        independent session could not see it.
        """
        seen: dict[str, bool] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            import app.core.db as db_module

            async with db_module.async_session() as s:
                result = await s.execute(
                    select(IngestJob).where(
                        IngestJob.source_filename == "visible.geojson"
                    )
                )
                row = result.scalar_one_or_none()
            seen["committed_mid_fetch"] = row is not None
            # fix(#1708 codex r2): mid-fetch the row rides the RUNNING lease,
            # which the stale-pending sweep's status clause excludes.
            seen["running_mid_fetch"] = row is not None and row.status == "running"
            seen["lease_stamped"] = row is not None and row.started_at is not None
            seen["no_file_mid_fetch"] = row is not None and not row.file_path
            return httpx.Response(200, content=GEOJSON)

        _install_transport(monkeypatch, handler)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/visible.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        assert seen == {
            "committed_mid_fetch": True,
            "running_mid_fetch": True,
            "lease_stamped": True,
            # Mid-fetch the row has no file_path yet, which is exactly the
            # state preview and commit already refuse with a 400.
            "no_file_mid_fetch": True,
        }
        # And the finished job is previewable: back to 'pending', file bound.
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "pending"
        assert job.file_path

    async def test_failed_fetch_stamps_the_committed_job_failed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex P1): the pre-fetch commit means a failed fetch can
        no longer roll the job row away — it must be stamped 'failed' with the
        refusal instead of sitting 'pending' until the stale reaper."""
        _install_transport(
            monkeypatch, lambda request: httpx.Response(404, content=b"nope")
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/stamped.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 502
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename == "stamped.geojson")
        )
        job = result.scalar_one()
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
        open() with ENAMETOOLONG as a 500."""
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        override = "a" * 247 + ".geojson"  # 255 chars, the schema max
        resp = await client.post(
            "/ingest/upload/url",
            json={
                "url": "https://files.example.test/download?id=1",
                "filename": override,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
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
        resp = await client.post(
            "/ingest/upload/url",
            json={
                "url": "https://files.example.test/download?id=2",
                "filename": override,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        job = await _get_job(test_db_session, resp.json()["job_id"])
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
        """The design premise of riding the RUNNING lease with one started_at
        stamp: the fetch's own hard wall-clock bound (plus generous margin for
        connect/validation/S3 hand-off) must stay inside JOB_TIMEOUT_SECONDS,
        or a legitimate fetch could be lease-reaped mid-download. If this
        fails, the URL-import path needs periodic heartbeats instead."""
        from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS
        from app.processing.ingest.url_fetch import FETCH_MAX_SECONDS

        assert FETCH_MAX_SECONDS + 300 < JOB_TIMEOUT_SECONDS

    def test_fetch_deadline_fits_the_edge_proxy_budget(self):
        """fix(#1708 codex r3): the endpoint sends nothing until fetch AND
        post-work finish, and frontend/nginx.conf's `location /api/` severs
        any response at proxy_read_timeout 600s. The fetch bound must leave
        real post-work margin inside that deadline — 120s covers the only
        size-scaled step (the S3 staging copy: seconds to same-network
        MinIO, ~84s at a conservative 50 Mbps to remote S3 for a 500 MB
        file) plus the header/footer sniff and single-row quota/commit
        queries. EDGE_PROXY_READ_TIMEOUT_SECONDS documents the nginx value;
        if the nginx budget ever changes, change the constant WITH it."""
        from app.processing.ingest.url_fetch import (
            EDGE_PROXY_READ_TIMEOUT_SECONDS,
            FETCH_MAX_SECONDS,
            STAGE_TOTAL_BUDGET_SECONDS,
        )

        assert EDGE_PROXY_READ_TIMEOUT_SECONDS == 600
        assert FETCH_MAX_SECONDS + 120 <= EDGE_PROXY_READ_TIMEOUT_SECONDS
        # fix(#1708 codex r7): the JOINT budget (fetch + sniff + S3 staging
        # put) also fits, with slack for the two short post-work
        # transactions; and the fetch bound runs inside the joint budget.
        assert STAGE_TOTAL_BUDGET_SECONDS + 60 <= EDGE_PROXY_READ_TIMEOUT_SECONDS
        assert FETCH_MAX_SECONDS < STAGE_TOTAL_BUDGET_SECONDS
        # fix(#1708 codex r8): the preflight DNS bound joined the budget —
        # it now starts the clock, so a max-length resolution must still
        # leave the fetch its full cap inside the joint budget.
        from app.processing.ingest.url_fetch import PREFLIGHT_DNS_MAX_SECONDS

        assert (
            PREFLIGHT_DNS_MAX_SECONDS + FETCH_MAX_SECONDS <= STAGE_TOTAL_BUDGET_SECONDS
        )

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
        running->pending CAS then matches zero rows, and the endpoint must
        surface that (409), delete the staged bytes, and leave the external
        verdict untouched rather than part-updating a dead row.
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
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/flip.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        assert "cancelled or timed out" in resp.json()["detail"]
        assert _staged_files() == []
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename == "flip.geojson")
        )
        job = result.scalar_one()
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
        (patched) deadline — the request must still fail cleanly inside the
        budget, with the job stamped failed and nothing left in staging."""
        monkeypatch.setattr("app.processing.ingest.url_fetch.FETCH_MAX_SECONDS", 1)

        async def stalled(request: httpx.Request) -> httpx.Response:
            import asyncio

            # Models an origin stalling before headers: nothing is produced
            # until far beyond the wall clock.
            await asyncio.sleep(10)
            return httpx.Response(200, content=GEOJSON)  # pragma: no cover

        _install_transport(monkeypatch, stalled)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/stall.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 502
        assert "did not finish" in resp.json()["detail"]
        assert _staged_files() == []
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename == "stall.geojson")
        )
        job = result.scalar_one()
        assert job.status == "failed"


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
        refusal (not a cleanup artifact) while the client gets the 502."""
        original_unlink = Path.unlink

        def raising_unlink(self, *args, **kwargs):
            if "cleanupboom" in self.name:
                raise OSError("simulated cleanup failure")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", raising_unlink)
        _install_transport(
            monkeypatch, lambda request: httpx.Response(404, content=b"nope")
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/cleanupboom.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 502
        assert "404" in resp.json()["detail"]
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename == "cleanupboom.geojson")
        )
        job = result.scalar_one()
        assert job.status == "failed"
        assert "404" in (job.error_message or "")


# ---------------------------------------------------------------------------
# Round-7 review findings (#1708): the S3-mode completions of the two
# families — no connection held across the staging put, and the put bounded
# inside the joint stage budget
# ---------------------------------------------------------------------------


class TestUrlImportS3Staging:
    async def test_s3_success_path_stages_and_cas_transitions(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """S3 mode end to end with the provider stubbed: the bounded put
        succeeds, the CAS lands the staging key, and the job is previewable."""
        monkeypatch.setattr(settings, "storage_provider", "s3")
        put_calls: list[tuple[str, str]] = []

        async def fake_put(s3_key: str, local_dest: Path) -> None:
            put_calls.append((s3_key, str(local_dest)))

        monkeypatch.setattr(
            "app.processing.ingest.router._put_staging_object", fake_put
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/s3ok.geojson"},
            headers=admin_auth_header,
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
        monkeypatch,
    ):
        """fix(#1708 codex r7 P1-A): pins the reorder. The byte-quota check
        now runs AFTER the staging put, in the same short transaction as the
        CAS — so no transaction is open across the provider upload. A put
        that fails must therefore short-circuit before any byte-charged
        quota call: only the pre-fetch count-cap call (0 bytes) may exist."""
        monkeypatch.setattr(settings, "storage_provider", "s3")

        async def failing_put(s3_key: str, local_dest: Path) -> None:
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(
            "app.processing.ingest.router._put_staging_object", failing_put
        )
        monkeypatch.setattr(
            "app.processing.ingest.router._cleanup_saved_upload", AsyncMock()
        )
        quota_spy = AsyncMock()
        monkeypatch.setattr(
            "app.processing.ingest.router.check_upload_quota", quota_spy
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/quotaorder.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 500  # provider failure -> generic 500
        # Only the pre-fetch count-cap call (incoming_bytes=0) ever ran; the
        # byte-charged call sits behind the put and was never reached.
        assert all(c.args[2] == 0 for c in quota_spy.await_args_list)

    async def test_put_exceeding_the_stage_budget_is_a_clean_502(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r7 P1-B): a put that cannot finish inside what
        remains of the joint stage budget is abandoned — clean 502 inside
        the proxy deadline, job stamped failed, local staging cleaned, and
        the late task handed to the reaper (its cleanup is invoked once the
        put actually ends)."""
        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setattr(
            "app.processing.ingest.router.STAGE_TOTAL_BUDGET_SECONDS", 1
        )
        release = asyncio.Event()
        started = asyncio.Event()

        async def slow_put(s3_key: str, local_dest: Path) -> None:
            started.set()
            await release.wait()

        monkeypatch.setattr(
            "app.processing.ingest.router._put_staging_object", slow_put
        )
        reaper_cleanup = AsyncMock()
        monkeypatch.setattr(
            "app.processing.ingest.router._cleanup_saved_upload", reaper_cleanup
        )
        _install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=GEOJSON)
        )
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/slowput.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 502
        assert "time" in resp.json()["detail"].lower()
        assert started.is_set()
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.source_filename == "slowput.geojson")
        )
        job = result.scalar_one()
        assert job.status == "failed"
        # Let the abandoned task finish; the reaper then re-deletes the key.
        settle_calls = len(reaper_cleanup.await_args_list)
        release.set()
        await asyncio.sleep(0.05)
        assert len(reaper_cleanup.await_args_list) == settle_calls + 1


# ---------------------------------------------------------------------------
# Round-8 review findings (#1708): the preflight DNS bound, and the reaper
# existing from the moment the put task does
# ---------------------------------------------------------------------------


class TestUrlImportPreflightDnsBound:
    async def test_stalled_preflight_dns_fails_inside_a_bound(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1708 codex r8): the submission-time getaddrinfo was the one
        long operation outside every deadline. A validator that never
        returns must now fail cleanly at the (patched) preflight bound, name
        DNS as the cause, and leave no job row — the gate runs before any
        job exists."""
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


class TestUrlImportPutReaperOnCancel:
    async def test_cancelled_wait_still_installs_the_reaper(self, monkeypatch):
        """fix(#1708 codex r8): a request cancelled while the put wait is
        pending (forced worker shutdown) used to escape before the timeout
        branch installed the reaper — the settle path then deleted the key
        mid-upload and the late-landing object had no deleter. Unit-level:
        cancel the waiter while the put is in flight, let the put land late,
        and the reaper must still re-delete the key."""
        from app.processing.ingest import router as router_module

        release = asyncio.Event()
        started = asyncio.Event()

        async def slow_put(s3_key: str, local_dest: Path) -> None:
            started.set()
            await release.wait()

        monkeypatch.setattr(router_module, "_put_staging_object", slow_put)
        cleanup = AsyncMock()
        monkeypatch.setattr(router_module, "_cleanup_saved_upload", cleanup)

        waiter = asyncio.create_task(
            router_module._stage_put_bounded(
                "staging/jid/late.geojson",
                Path("/tmp/lane2-nonexistent"),
                # A generous deadline: the failure mode under test is
                # cancellation DURING the wait, not the timeout branch.
                time.monotonic() + 30,
                "jid",
            )
        )
        await started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        # The put is still running (asyncio.wait never cancels it) and no
        # cleanup has run yet.
        cleanup.assert_not_awaited()
        release.set()
        await asyncio.sleep(0.05)
        cleanup.assert_awaited_once_with("staging/jid/late.geojson", "jid")
