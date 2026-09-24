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

from app.core.failure_reason import redact_failure_reason
from app.platform.security import SSRFError


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

        with (
            patch(
                "app.processing.ingest.router.get_job_or_404",
                new=AsyncMock(return_value=job),
            ),
            patch(
                "app.platform.security.validate_url_for_ssrf",
                side_effect=_ssrf_raise,
            ),
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

        with (
            patch(
                "app.processing.ingest.router.get_job_or_404",
                new=AsyncMock(return_value=job),
            ),
            patch(
                "app.platform.security.validate_url_for_ssrf",
                new=ssrf_mock,
            ),
            patch(
                "app.processing.ingest.router._pick_commit_subclass",
                return_value=MagicMock(model_validate=lambda d: MagicMock()),
            ),
            patch(
                "app.processing.ingest.router.queue_ingest_job",
                new=AsyncMock(),
            ),
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
            "app.platform.security.validate_url_for_ssrf",
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
                    attempt_id=str(uuid.uuid4()),
                )

        assert "safety check at worker fetch time" in str(exc.value)
        assert redact_failure_reason(exc.value).startswith(
            "source_url failed safety check at worker fetch time: "
        )


async def _queued_service_reupload(session, *, source_url: str, user_metadata: dict):
    """A dataset with a pending service re-upload job and its pending run."""
    from app.platform.jobs.models import IngestJob
    from app.platform.refresh.service import create_pending_run
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        created_by=admin_id,
        source_url=source_url,
        source_layer="roads",
        user_metadata={"reupload": True, **user_metadata},
    )
    session.add(job)
    await session.flush()
    await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=0,
    )
    await session.commit()
    return dataset, job, admin_id


class TestReuploadServiceWorkerRevalidatesSourceUrl:
    """`reupload_service` worker also re-validates source_url."""

    @pytest.mark.anyio
    async def test_reupload_worker_raises_runtime_error_on_ssrf(self, test_db_session):
        """A URL the fetch-time check refuses fails the claimed job before any fetch."""
        from app.processing.ingest.tasks_reupload import reupload_service

        dataset, job, admin_id = await _queued_service_reupload(
            test_db_session,
            source_url="https://example.test/wfs",
            user_metadata={"service_type": "WFS 2.0.0"},
        )

        async def _ssrf_raise(url: str) -> None:
            raise SSRFError(f"rebinding at reupload fetch: {url}")

        with patch(
            "app.platform.security.validate_url_for_ssrf",
            side_effect=_ssrf_raise,
        ):
            with pytest.raises(RuntimeError) as exc:
                await reupload_service.__wrapped__(  # type: ignore[attr-defined]
                    job_id=str(job.id),
                    dataset_id=str(dataset.id),
                    source_url="https://example.test/wfs",
                    source_layer="roads",
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

        assert "safety check at worker fetch time" in str(exc.value)
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message.startswith(
            "source_url failed safety check at worker fetch time: "
        )

    @pytest.fixture
    def network(self, monkeypatch):
        """Answer DNS for listed hosts, and record every request and ogr2ogr spawn."""
        import socket
        from types import SimpleNamespace

        import httpx

        from app.platform import security as security_mod
        from app.processing.ingest import ogr

        seen = SimpleNamespace(
            answers={}, resolved=[], requests=[], spawned=AsyncMock()
        )

        def _resolve(host, port, *args, **kwargs):
            if host not in seen.answers:
                return socket.getaddrinfo(host, port, *args, **kwargs)
            seen.resolved.append(host)
            address = (seen.answers[host], 443)
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", address)
            ]

        def _record(request: httpx.Request) -> httpx.Response:
            seen.requests.append(request)
            return httpx.Response(503)

        # Only the validator and its transport see these answers.
        monkeypatch.setattr(
            security_mod,
            "socket",
            SimpleNamespace(
                getaddrinfo=_resolve,
                IPPROTO_TCP=socket.IPPROTO_TCP,
                gaierror=socket.gaierror,
            ),
        )
        monkeypatch.setattr(
            security_mod, "make_safe_transport", lambda: httpx.MockTransport(_record)
        )
        monkeypatch.setattr(ogr, "run_ogr2ogr_service", seen.spawned)
        return seen

    @staticmethod
    async def _refused(session, *, stored_url: str, argument_url: str):
        """Run a service re-upload that the fetch-time check must refuse."""
        from sqlalchemy import select

        from app.platform.refresh.models import DatasetRefreshRun
        from app.processing.ingest.tasks_reupload import reupload_service

        dataset, job, admin_id = await _queued_service_reupload(
            session,
            source_url=stored_url,
            user_metadata={"service_type": "ArcGIS FeatureServer", "layer_id": 0},
        )
        with pytest.raises(Exception) as raised:
            await reupload_service.__wrapped__(  # type: ignore[attr-defined]
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                source_url=argument_url,
                source_layer="roads",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
        await session.refresh(job)
        run = await session.scalar(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.ingest_job_id == job.id)
            .execution_options(populate_existing=True)
        )
        return raised.value, job.status, run.status

    @pytest.mark.anyio
    async def test_a_host_now_resolving_to_a_private_address_sends_no_request(
        self, test_db_session, network
    ):
        """A host that resolves to a private address at fetch time fails the job before any request."""
        url = "https://rebound.example.test/arcgis/rest/services/Roads/FeatureServer"
        network.answers["rebound.example.test"] = "10.0.0.7"

        error, job_status, run_status = await self._refused(
            test_db_session, stored_url=url, argument_url=url
        )

        assert network.requests == []
        network.spawned.assert_not_awaited()
        assert "safety check at worker fetch time" in str(error)
        assert (job_status, run_status) == ("failed", "failed")

    @pytest.mark.anyio
    async def test_the_url_checked_is_the_url_fetched(self, test_db_session, network):
        """With the job's URL and the task argument differing, the job's URL is checked and nothing is fetched."""
        network.answers["stored.example.test"] = "10.0.0.7"
        network.answers["argument.example.test"] = "93.184.216.34"

        error, job_status, run_status = await self._refused(
            test_db_session,
            stored_url="https://stored.example.test/arcgis/rest/services/Roads/FeatureServer",
            argument_url="https://argument.example.test/arcgis/rest/services/Roads/FeatureServer",
        )

        assert network.requests == []
        assert network.resolved == ["stored.example.test"]
        network.spawned.assert_not_awaited()
        assert "safety check at worker fetch time" in str(error)
        assert (job_status, run_status) == ("failed", "failed")
