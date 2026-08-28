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
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/notes.txt"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

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
            seen["pending_mid_fetch"] = row is not None and row.status == "pending"
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
            "pending_mid_fetch": True,
            # Mid-fetch the row has no file_path yet, which is exactly the
            # state preview and commit already refuse with a 400.
            "no_file_mid_fetch": True,
        }

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
