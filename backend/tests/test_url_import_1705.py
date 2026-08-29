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
        )

        assert EDGE_PROXY_READ_TIMEOUT_SECONDS == 600
        assert FETCH_MAX_SECONDS + 120 <= EDGE_PROXY_READ_TIMEOUT_SECONDS

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
