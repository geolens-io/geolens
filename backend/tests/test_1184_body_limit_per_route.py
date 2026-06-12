"""Regression tests for Phase 1184 — GAP-001: per-route body cap.

GAP-001: Non-upload routes must enforce a small default cap (10 MB);
         upload/reupload routes must allow up to the configured upload max.

Design:
  - The middleware grants the large UPLOAD_MAX_SIZE_MB limit to exactly the two
    multipart file endpoints (/ingest/upload, /datasets/{id}/reupload) and the
    small DEFAULT_BODY_LIMIT_BYTES (10 MB) to everything else.
  - We verify the RED case (non-upload with 11 MB → 413) and the GREEN case
    (upload path with 11 MB → NOT 413) without needing a real file upload.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.api.middleware.body_limit import (
    DEFAULT_BODY_LIMIT_BYTES,
    _get_upload_limit,
    _is_upload_route,
)

_11MB = 11 * 1024 * 1024  # 11 MB — over the 10 MB default cap


# ---------------------------------------------------------------------------
# Unit tests: _is_upload_route path classifier
# ---------------------------------------------------------------------------


class TestIsUploadRoute:
    """_is_upload_route matches ONLY the two multipart file-byte endpoints.

    POST /ingest/upload and POST /datasets/{id}/reupload stream file bytes and get
    the large cap; the JSON-only presigned/commit/preview sub-routes of those
    flows — and everything else — stay on the default 10 MB cap (PR #249 review).
    """

    # --- the two real file-upload endpoints get the large cap ---
    def test_ingest_upload_is_upload(self):
        assert _is_upload_route("/api/ingest/upload") is True

    def test_datasets_reupload_is_upload(self):
        assert _is_upload_route("/api/datasets/abc123/reupload") is True

    def test_trailing_slash_ignored(self):
        assert _is_upload_route("/api/ingest/upload/") is True
        assert _is_upload_route("/api/datasets/abc123/reupload/") is True

    def test_case_insensitive(self):
        assert _is_upload_route("/API/INGEST/UPLOAD") is True
        assert _is_upload_route("/API/DATASETS/ABC/REUPLOAD") is True

    # --- the upload endpoints are POST-only; a non-POST request to the same path
    # is NOT a file upload and must fall back to the default cap (PR #249 review,
    # else a large body slips past the cap before the 405). ---
    def test_non_post_method_is_not_upload(self):
        assert _is_upload_route("/api/ingest/upload", "GET") is False
        assert _is_upload_route("/api/ingest/upload", "PUT") is False
        assert _is_upload_route("/api/datasets/abc123/reupload", "GET") is False
        assert _is_upload_route("/api/datasets/abc123/reupload", "HEAD") is False

    def test_post_method_is_upload(self):
        assert _is_upload_route("/api/ingest/upload", "POST") is True
        assert _is_upload_route("/api/datasets/abc123/reupload", "POST") is True
        assert (
            _is_upload_route("/api/ingest/upload", "post") is True
        )  # case-insensitive

    # --- JSON-only sub-routes of the upload/reupload flows are NOT file uploads
    # (PR #249 review): the bytes go straight to object storage, so a large JSON
    # body on these routes must be stopped by the default cap. ---
    def test_ingest_upload_presigned_is_not_upload(self):
        assert _is_upload_route("/api/ingest/upload/presigned") is False

    def test_ingest_upload_presigned_complete_is_not_upload(self):
        assert (
            _is_upload_route("/api/ingest/upload/presigned/some-job-id/complete")
            is False
        )

    def test_datasets_reupload_presigned_is_not_upload(self):
        assert _is_upload_route("/api/datasets/abc123/reupload/presigned") is False

    def test_datasets_reupload_commit_is_not_upload(self):
        assert _is_upload_route("/api/datasets/abc123/reupload/job-id/commit") is False

    def test_datasets_reupload_service_preview_is_not_upload(self):
        assert (
            _is_upload_route("/api/datasets/abc123/reupload/service/preview") is False
        )

    # --- other non-upload routes ---
    def test_health_is_not_upload(self):
        assert _is_upload_route("/health") is False

    def test_api_datasets_list_is_not_upload(self):
        # /api/datasets/ without /reupload is NOT an upload route
        assert _is_upload_route("/api/datasets/") is False

    def test_api_datasets_detail_is_not_upload(self):
        assert _is_upload_route("/api/datasets/abc123") is False

    def test_api_maps_is_not_upload(self):
        assert _is_upload_route("/api/maps") is False

    def test_api_ingest_non_upload_is_not_upload(self):
        # /api/ingest/commit is not an upload route
        assert _is_upload_route("/api/ingest/commit/some-job-id") is False


class TestIsUploadRouteProxyStripped:
    """The /api prefix is stripped by both proxies before the app sees the path.

    Regression for the GAP-001 fix: prod nginx (`rewrite ^/api/(.*) /$1`) and the
    dev Vite proxy (`rewrite: p.replace(/^\\/api/, '')`) both remove `/api`, so
    in every real deployment scope["path"] is the un-prefixed form. Matching only
    the `/api/...` prefix never fired, silently capping uploads at 10 MB. The
    classifier must recognise the stripped form too — for the file endpoints only.
    """

    # --- the two file endpoints, stripped, get the large cap ---
    def test_stripped_ingest_upload_is_upload(self):
        assert _is_upload_route("/ingest/upload") is True

    def test_stripped_datasets_reupload_is_upload(self):
        assert _is_upload_route("/datasets/abc123/reupload") is True

    def test_stripped_trailing_slash_ignored(self):
        assert _is_upload_route("/ingest/upload/") is True
        assert _is_upload_route("/datasets/abc123/reupload/") is True

    def test_stripped_case_insensitive(self):
        assert _is_upload_route("/INGEST/UPLOAD") is True
        assert _is_upload_route("/DATASETS/ABC/REUPLOAD") is True

    def test_stripped_non_post_method_is_not_upload(self):
        assert _is_upload_route("/ingest/upload", "GET") is False
        assert _is_upload_route("/ingest/upload", "PUT") is False
        assert _is_upload_route("/datasets/abc123/reupload", "DELETE") is False

    # --- stripped JSON sub-routes must NOT get the large cap (PR #249 review) ---
    def test_stripped_ingest_upload_presigned_is_not_upload(self):
        assert _is_upload_route("/ingest/upload/presigned") is False

    def test_stripped_ingest_upload_complete_is_not_upload(self):
        assert (
            _is_upload_route("/ingest/upload/presigned/some-job-id/complete") is False
        )

    def test_stripped_datasets_reupload_presigned_is_not_upload(self):
        assert _is_upload_route("/datasets/abc123/reupload/presigned") is False

    def test_stripped_datasets_reupload_commit_is_not_upload(self):
        assert _is_upload_route("/datasets/abc123/reupload/job-id/commit") is False

    # --- stripped non-upload paths must NOT over-match (still get the 10 MB cap) ---
    def test_stripped_datasets_list_is_not_upload(self):
        assert _is_upload_route("/datasets/") is False

    def test_stripped_datasets_detail_is_not_upload(self):
        assert _is_upload_route("/datasets/abc123") is False

    def test_stripped_maps_is_not_upload(self):
        assert _is_upload_route("/maps") is False

    def test_stripped_ingest_non_upload_is_not_upload(self):
        assert _is_upload_route("/ingest/commit/some-job-id") is False


# ---------------------------------------------------------------------------
# Unit tests: _get_upload_limit with route_override
# ---------------------------------------------------------------------------


class TestGetUploadLimitRouteOverride:
    """_get_upload_limit(route_override=N) must return N regardless of cache."""

    def test_route_override_wins(self):
        assert (
            _get_upload_limit(route_override=DEFAULT_BODY_LIMIT_BYTES)
            == DEFAULT_BODY_LIMIT_BYTES
        )

    def test_no_override_returns_cache_or_fallback(self):
        # Without override, returns cached value or fallback
        result = _get_upload_limit()
        assert result > 0


# ---------------------------------------------------------------------------
# Integration tests: middleware enforces per-route limits
# ---------------------------------------------------------------------------


class TestGap001PerRouteBodyCap:
    """GAP-001: non-upload POST over 10 MB → 413; upload path → allowed.

    Pre-fix (uniform 500 MB limit): an 11 MB body to /health passed through.
    Post-fix (10 MB default + per-route override): 11 MB to /health → 413.
    """

    @pytest.mark.anyio
    async def test_non_upload_over_10mb_is_413(self, client: AsyncClient):
        """An 11 MB POST to a non-upload route must return 413.

        GAP-001 RED case: previously this passed through (500 MB global limit).
        """
        resp = await client.post(
            "/health",
            content=b"x",
            headers={"Content-Length": str(_11MB)},
        )
        assert resp.status_code == 413, (
            "GAP-001: non-upload POST with 11 MB body must return 413 "
            f"(default 10 MB cap); got {resp.status_code}"
        )

    @pytest.mark.anyio
    async def test_upload_route_over_10mb_is_not_413(self, client: AsyncClient):
        """An 11 MB body to an upload route must NOT be blocked by the 10 MB cap.

        GAP-001 GREEN case: upload routes use UPLOAD_MAX_SIZE_MB (500 MB),
        so an 11 MB upload body passes the middleware (downstream may still reject
        it for auth/other reasons, but not 413 from the body limit).

        We patch _get_upload_limit to return a high limit so the test is
        independent of the actual configured UPLOAD_MAX_SIZE_MB value.
        """
        high_limit = 500 * 1024 * 1024  # 500 MB

        # Patch the limit cache to return a high value for upload routes.
        # The middleware calls _get_upload_limit() (no route_override) for upload
        # routes, so we patch the module-level cache to return 500 MB.
        with patch(
            "app.api.middleware.body_limit._limit_cache",
            (float("inf"), high_limit),
        ):
            resp = await client.post(
                "/api/ingest/upload",
                content=b"x",
                headers={"Content-Length": str(_11MB)},
            )
        # Must NOT be 413 from the body limit middleware
        # (may be 401/403/422/etc. from auth — those are expected)
        assert resp.status_code != 413, (
            "GAP-001: upload route with 11 MB body must not be 413 from body limit; "
            f"got {resp.status_code}. Upload routes use UPLOAD_MAX_SIZE_MB (500 MB)."
        )

    @pytest.mark.anyio
    async def test_proxy_stripped_upload_route_over_10mb_is_not_413(
        self, client: AsyncClient
    ):
        """The /api-stripped upload path must ALSO get the large upload limit.

        Deployment regression for the GAP-001 fix: both the prod nginx and the
        dev Vite proxy strip /api, so the app receives /ingest/upload (not
        /api/ingest/upload). Before the fix this missed the upload allowlist and
        an 11 MB body → 413, silently capping every real-deployment upload at
        10 MB. It must now pass the body limit (downstream auth may still reject
        with 401/422 — but not 413). This test FAILS pre-fix, PASSES post-fix.
        """
        high_limit = 500 * 1024 * 1024  # 500 MB
        with patch(
            "app.api.middleware.body_limit._limit_cache",
            (float("inf"), high_limit),
        ):
            resp = await client.post(
                "/ingest/upload",
                content=b"x",
                headers={"Content-Length": str(_11MB)},
            )
        assert resp.status_code != 413, (
            "GAP-001 fix: proxy-stripped upload path (/ingest/upload) with 11 MB "
            f"body must not be 413; got {resp.status_code}. Both proxies strip "
            "/api, so this is the path real deployments actually produce."
        )

    @pytest.mark.anyio
    async def test_non_post_to_upload_path_over_10mb_is_413(self, client: AsyncClient):
        """A non-POST request to an upload PATH must hit the 10 MB default cap.

        PR #249 review: the upload endpoints are POST-only. Before the method
        gate, PUT /ingest/upload with 11 MB got the 500 MB cap and was rejected
        only as 405 *after* the body was allowed through; now it falls back to the
        10 MB default and is stopped at the body limit. FAILS pre-fix (405),
        PASSES post-fix (413).
        """
        resp = await client.put(
            "/ingest/upload",
            content=b"x",
            headers={"Content-Length": str(_11MB)},
        )
        assert resp.status_code == 413, (
            "PR #249: non-POST to an upload path with 11 MB must hit the 10 MB "
            f"default cap (413), not the large upload cap; got {resp.status_code}"
        )

    @pytest.mark.anyio
    async def test_non_upload_under_10mb_is_not_413(self, client: AsyncClient):
        """A 5 MB POST to a non-upload route must NOT be blocked by the 10 MB cap."""
        five_mb = 5 * 1024 * 1024
        resp = await client.post(
            "/health",
            content=b"x",
            headers={"Content-Length": str(five_mb)},
        )
        assert resp.status_code != 413, (
            "GAP-001: 5 MB body to non-upload route must not be 413 "
            f"(default cap is 10 MB); got {resp.status_code}"
        )
