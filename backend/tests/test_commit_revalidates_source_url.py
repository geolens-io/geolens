"""Unit tests for IA-P0-03: commit-time + worker-time SSRF revalidation.

Pins the preview→commit DNS-rebinding TOCTOU closure (route layer) and the
manifest-path defense-in-depth (worker layer).

Requirement: IA-P0-03
Phase: 1066
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.catalog.sources.security import SSRFError


# ---------------------------------------------------------------------------
# Route layer: commit_import re-validates job.source_url
# ---------------------------------------------------------------------------


class TestCommitImportRevalidatesSourceUrl:
    """`commit_import` calls validate_url_for_ssrf for service jobs."""

    @pytest.mark.asyncio
    async def test_service_commit_raises_400_on_ssrf_at_commit_time(self):
        """SSRF error at commit time → 400, even when preview succeeded."""
        # Import inside the test to keep import-cost flat for the test
        # collection phase; the function reads the security module at
        # call time via the inner `from ... import` so we can patch the
        # module-level name.
        from app.processing.ingest.router import commit_import

        # Build a minimal `job` stand-in: source_url set, no file_path
        # (service job), status pending.
        job = MagicMock()
        job.id = uuid.uuid4()
        job.source_url = "https://example.test/wfs"
        job.file_path = None
        job.status = "pending"
        job.user_metadata = {"service_type": "WFS 2.0.0", "layer_name": "roads"}

        async def _ssrf_raise(url: str) -> None:
            raise SSRFError(f"private IP after rebinding: {url}")

        with patch(
            "app.processing.ingest.router.get_job_or_404",
            new=AsyncMock(return_value=job),
        ), patch(
            "app.modules.catalog.sources.security.validate_url_for_ssrf",
            side_effect=_ssrf_raise,
        ):
            with pytest.raises(HTTPException) as exc:
                # `request`, `user`, `db` are mocked to bare minimum since
                # the SSRF gate fires before any of them are used.
                await commit_import(
                    job_id=job.id,
                    request=MagicMock(),
                    user=MagicMock(),
                    db=MagicMock(),
                )

        assert exc.value.status_code == 400
        assert "safety check" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_file_job_skips_ssrf_revalidation(self):
        """File jobs (file_path set, source_url None) skip the SSRF check."""
        from app.processing.ingest.router import commit_import

        job = MagicMock()
        job.id = uuid.uuid4()
        job.source_url = None
        job.file_path = "/tmp/staging/abc.geojson"
        job.status = "pending"
        job.user_metadata = {}

        ssrf_mock = AsyncMock()

        with patch(
            "app.processing.ingest.router.get_job_or_404",
            new=AsyncMock(return_value=job),
        ), patch(
            "app.modules.catalog.sources.security.validate_url_for_ssrf",
            new=ssrf_mock,
        ), patch(
            "app.processing.ingest.router._pick_commit_subclass",
            return_value=MagicMock(model_validate=lambda d: MagicMock()),
        ), patch(
            "app.processing.ingest.router.queue_ingest_job",
            new=AsyncMock(),
        ):
            try:
                await commit_import(
                    job_id=job.id,
                    request=MagicMock(model_dump=lambda: {}),
                    user=MagicMock(),
                    db=AsyncMock(),
                )
            except (TypeError, AttributeError):
                # The mock for Subclass.model_validate may not match the
                # actual call signature; we only care that SSRF gate did
                # not fire.
                pass

        # SSRF validator MUST NOT have been called for a file job.
        ssrf_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Worker layer: ingest_service / reupload_service revalidate at fetch time
# ---------------------------------------------------------------------------


class TestIngestServiceWorkerRevalidatesSourceUrl:
    """`ingest_service` worker task re-validates source_url before fetch."""

    @pytest.mark.asyncio
    async def test_worker_raises_runtime_error_on_ssrf(self):
        """SSRFError from worker-side validator → RuntimeError (Procrastinate
        retries are gated by retry=0 on the task; failure surfaces in the
        job status)."""
        from app.processing.ingest.tasks_vector import ingest_service

        async def _ssrf_raise(url: str) -> None:
            raise SSRFError(f"rebinding at fetch: {url}")

        with patch(
            "app.modules.catalog.sources.security.validate_url_for_ssrf",
            side_effect=_ssrf_raise,
        ):
            with pytest.raises(RuntimeError) as exc:
                # The task function: when invoked directly (not through
                # the Procrastinate wrapper), it runs as a plain coroutine.
                await ingest_service.__wrapped__(  # type: ignore[attr-defined]
                    job_id=str(uuid.uuid4()),
                    source_url="https://example.test/wfs",
                    source_layer="roads",
                    user_id=str(uuid.uuid4()),
                )

        assert "safety check at worker fetch time" in str(exc.value)


class TestReuploadServiceWorkerRevalidatesSourceUrl:
    """`reupload_service` worker also re-validates source_url."""

    @pytest.mark.asyncio
    async def test_reupload_worker_raises_runtime_error_on_ssrf(self):
        from app.processing.ingest.tasks_reupload import reupload_service

        async def _ssrf_raise(url: str) -> None:
            raise SSRFError(f"rebinding at reupload fetch: {url}")

        with patch(
            "app.modules.catalog.sources.security.validate_url_for_ssrf",
            side_effect=_ssrf_raise,
        ):
            with pytest.raises(RuntimeError) as exc:
                await reupload_service.__wrapped__(  # type: ignore[attr-defined]
                    job_id=str(uuid.uuid4()),
                    dataset_id=str(uuid.uuid4()),
                    source_url="https://example.test/wfs",
                    source_layer="roads",
                    user_id=str(uuid.uuid4()),
                )

        assert "safety check at worker fetch time" in str(exc.value)
