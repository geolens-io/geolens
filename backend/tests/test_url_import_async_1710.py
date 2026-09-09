"""Tests for feat(#1710) — the URL-import download as a background job.

What this file pins, beyond the two-phase coverage in
``test_url_import_1705.py``:

- the endpoint answers inside the request even when the origin never sends a
  byte, which is the whole point of the change;
- the worker keeps the Rule 2 posture: a connect-time private address is
  refused there, not just at submission;
- the size cap, the byte-quota recheck and the running -> pending transition
  all happen on the worker, and each failure settles the row;
- a worker that dies mid-download leaves a row the stale sweep settles, with
  the partial file gone.
"""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS, fail_stale_jobs
from app.platform.security import SSRFError
from app.processing.ingest import tasks_url_fetch
from app.processing.ingest.url_fetch import fetch_url_to_path

GEOJSON = b'{"type":"FeatureCollection","features":[]}'


def _capture_defer(monkeypatch) -> list[dict]:
    """Record what the door hands the queue instead of enqueueing it."""
    captured: list[dict] = []

    async def _fake_defer(task, /, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(
        "app.core.db.tenant_session.defer_async_with_tenant", _fake_defer
    )
    return captured


async def _run_task(kwargs: dict) -> None:
    payload = {k: v for k, v in kwargs.items() if k != "tenant_id"}
    await tasks_url_fetch.fetch_url.func(**payload)


async def _get_job(session, job_id) -> IngestJob | None:
    result = await session.execute(
        select(IngestJob).where(
            IngestJob.id
            == (job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(job_id))
        )
    )
    return result.scalar_one_or_none()


def _staged_files() -> list[Path]:
    return [p for p in Path(settings.upload_staging_dir).iterdir() if p.is_file()]


class TestEndpointReturnsBeforeTheDownload:
    async def test_slow_origin_does_not_delay_the_response(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """The response arrives while the origin is still stalled.

        Counterfactual: on the synchronous shape the request could not
        complete until the transport handler returned, so a handler that
        never returns held the response open. Here the transport is never
        even reached: nothing calls it during the request.
        """
        touched = asyncio.Event()

        def factory(timeout=None, **_kwargs):
            async def _handle(request: httpx.Request) -> httpx.Response:
                touched.set()
                await asyncio.sleep(3600)
                raise AssertionError("unreachable")

            return httpx.AsyncClient(transport=httpx.MockTransport(_handle))

        monkeypatch.setattr("app.processing.ingest.url_fetch.make_safe_client", factory)
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf",
            _accept_any_url(),
        )
        _capture_defer(monkeypatch)

        resp = await asyncio.wait_for(
            client.post(
                "/ingest/upload/url",
                json={"url": "https://slow.example.test/roads.geojson"},
                headers=admin_auth_header,
            ),
            timeout=20,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "running"
        assert not touched.is_set()

        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert job.status == "running"
        assert job.current_step == "downloading"
        assert job.started_at is not None

    async def test_the_url_never_lands_on_the_job_row(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A submitted URL reaches the worker as a task argument only.

        `user_metadata` is served by GET /jobs/{id} and a URL can carry
        userinfo credentials, so it must not be stored there.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        url = "https://files.example.test/roads.geojson"
        resp = await client.post(
            "/ingest/upload/url", json={"url": url}, headers=admin_auth_header
        )
        assert resp.status_code == 201, resp.text
        assert captured[0]["url"] == url

        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert url not in str(job.user_metadata or {})
        assert job.source_url is None
        assert not job.file_path


class TestWorkerKeepsTheSsrfPosture:
    async def test_connect_time_private_address_is_refused_on_the_worker(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A URL that only resolves privately at connect time fails the job.

        Counterfactual: with the safe client replaced by a plain
        `httpx.AsyncClient`, the same run stages the body and the job reaches
        'pending' instead of settling failed.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://rebind.example.test/roads.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        def factory(timeout=None, **_kwargs):
            async def _handle(request: httpx.Request) -> httpx.Response:
                raise SSRFError("URL resolves to a private address: 169.254.169.254")

            return httpx.AsyncClient(transport=httpx.MockTransport(_handle))

        monkeypatch.setattr("app.processing.ingest.url_fetch.make_safe_client", factory)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "private address" in job.error_message
        assert _staged_files() == []


class TestWorkerCapsAndQuota:
    async def test_streamed_bytes_over_the_cap_settle_the_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A body larger than the instance cap fails the job, partial removed.

        Counterfactual: raising UPLOAD_MAX_SIZE_MB above the body size on the
        same run stages the file and the job reaches 'pending'.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/big.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        _install_body(monkeypatch, b"x" * 4096)
        from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

        async def _tiny_cap(_db):
            return 0

        monkeypatch.setattr(UPLOAD_MAX_SIZE_MB, "get", _tiny_cap)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "maximum allowed size" in job.error_message
        assert _staged_files() == []

    async def test_byte_quota_is_recharged_with_what_landed(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """The post-download quota check settles the job when it refuses.

        Counterfactual: with the quota seam left alone the same run reaches
        'pending'; only the recheck turns it into a failure.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/quota.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        _install_body(monkeypatch, GEOJSON)
        charged: list[int] = []

        # Patch the door's own check, so the worker seam's HTTP-to-domain
        # translation runs rather than being stubbed over.
        async def _refuse(db, user_id, incoming_bytes, request):
            charged.append(incoming_bytes)
            raise _quota_refusal(incoming_bytes)

        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.check_upload_quota", _refuse
        )
        await _run_task(captured[0])

        assert charged == [len(GEOJSON)]
        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Storage quota exceeded" in job.error_message
        assert _staged_files() == []


class TestWorkerTransition:
    async def test_success_moves_running_to_pending_and_binds_the_file(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """The task publishes the staged file and clears the download step.

        Counterfactual: without running the task the row stays 'running' with
        no file_path, which is what the poll shows as "downloading".
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/roads.geojson"},
            headers=admin_auth_header,
        )
        job_id = resp.json()["job_id"]
        job = await _get_job(test_db_session, job_id)
        assert (job.status, job.file_path, job.current_step) == (
            "running",
            "",
            "downloading",
        )

        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])

        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert job.current_step is None
        assert Path(job.file_path).read_bytes() == GEOJSON
        assert (job.user_metadata or {}).get("staged_at")

    async def test_a_cancel_during_the_download_is_not_overwritten(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A row cancelled mid-download stays cancelled and stages nothing.

        Counterfactual: without the attempt-fenced CAS the task's own
        transition would move the cancelled row to 'pending' and hand the
        user a previewable job they had just cancelled.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/cancelme.geojson"},
            headers=admin_auth_header,
        )
        job_id = uuid.UUID(resp.json()["job_id"])

        async def _cancelling_body(request: httpx.Request) -> httpx.Response:
            await test_db_session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(status="cancelled")
            )
            await test_db_session.commit()
            return httpx.Response(200, content=GEOJSON)

        _install_handler(monkeypatch, _cancelling_body)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, job_id)
        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert not job.file_path
        assert _staged_files() == []


class TestEveryFailureSettles:
    """fix(#1710): no raise after the row is adopted may leave it running."""

    async def test_a_failure_in_the_adoption_block_settles_the_row(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A raise before the staging block still stamps the job failed.

        Counterfactual: with the outer handler only logging, the same run
        leaves the row running with no error_message until the lease reaper.
        The reason is generic because RuntimeError is not this tree's text.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/adopt.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("driver dump for https://user:pw@origin.test/a.geojson")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_url_fetch._adopt_running_lease", _boom
        )
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "URL import failed"
        assert "pw@origin.test" not in job.error_message

    async def test_a_composed_refusal_keeps_its_text_with_the_url_redacted(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A refusal this tree wrote survives, minus any userinfo it quotes.

        Counterfactual: dropping the redaction from `_settlement_message`
        stores the credential verbatim in a field the job owner's status
        poll returns.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/wrapped.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        from app.processing.ingest.url_fetch import UrlFetchError

        async def _boom(*_args, **_kwargs):
            raise UrlFetchError(
                "Could not download the file: no route to "
                "https://user:pw@origin.test/a.geojson"
            )

        monkeypatch.setattr(
            "app.processing.ingest.tasks_url_fetch.fetch_url_to_path", _boom
        )
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message.startswith("Could not download the file:")
        assert "pw@origin.test" not in job.error_message
        assert "origin.test" in job.error_message

    async def test_the_worker_raises_no_http_exception(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """An at-cap quota refusal settles as a domain failure, not an HTTP one.

        Counterfactual: with the refusal left as HTTPException, the stored
        reason falls to the generic string because fastapi is not this
        tree's module.
        """
        from app.processing.ingest.url_import_staging import UrlImportRefused

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        monkeypatch.setattr(
            "app.processing.ingest.url_import_staging.get_user_quota_usage",
            _usage_at_cap(),
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/atcap2.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Storage quota exceeded" in job.error_message
        assert issubclass(UrlImportRefused, ValueError)
        assert UrlImportRefused.__module__.startswith("app.")


class TestCrashRecovery:
    async def test_a_killed_download_is_settled_by_the_stale_sweep(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A row abandoned mid-download is failed once its lease expires.

        Counterfactual: with the row's heartbeat left fresh the same sweep
        leaves it running, which is what keeps a live download alive.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/crash.geojson"},
            headers=admin_auth_header,
        )
        job_id = uuid.UUID(resp.json()["job_id"])

        await fail_stale_jobs(test_db_session)
        job = await _get_job(test_db_session, job_id)
        assert job.status == "running"

        from datetime import datetime, timedelta, timezone

        expired = datetime.now(timezone.utc) - timedelta(
            seconds=JOB_TIMEOUT_SECONDS + 60
        )
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(started_at=expired, heartbeat_at=expired)
        )
        await test_db_session.commit()

        await fail_stale_jobs(test_db_session)
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Stale: running" in job.error_message

    async def test_a_cancelled_fetch_removes_its_partial_file(self, tmp_path):
        """Cancelling the download deletes the bytes it had written.

        Counterfactual: the same run without the helper's cleanup leaves the
        partial file behind for the staging volume to accumulate.
        """
        dest = tmp_path / "partial.geojson"
        started = asyncio.Event()

        def factory(timeout=None, **_kwargs):
            async def _handle(request: httpx.Request) -> httpx.Response:
                started.set()
                await asyncio.sleep(3600)
                raise AssertionError("unreachable")

            return httpx.AsyncClient(transport=httpx.MockTransport(_handle))

        import app.processing.ingest.url_fetch as url_fetch_module

        original = url_fetch_module.make_safe_client
        url_fetch_module.make_safe_client = factory
        try:
            task = asyncio.create_task(
                fetch_url_to_path("https://x.example.test/a.geojson", dest, 1024)
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            url_fetch_module.make_safe_client = original
        assert not dest.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _usage_at_cap():
    from unittest.mock import AsyncMock

    return AsyncMock(
        return_value=SimpleNamespace(
            bytes_used=1000, storage_cap=1000, dataset_count=0, count_cap=0
        )
    )


def _accept_any_url():
    async def _validate(url):
        return None

    return _validate


def _install_handler(monkeypatch, handler):
    """Install a mock safe client whose transport runs ``handler``."""

    def factory(timeout=None, **_kwargs):
        async def _handle(request: httpx.Request) -> httpx.Response:
            result = await handler(request)
            # The fetch reads aiter_raw, and a Response built with content=
            # has its stream pre-consumed, so rebuild it as a live stream.
            return httpx.Response(
                result.status_code,
                headers=result.headers,
                stream=_Body(result.content),
            )

        return httpx.AsyncClient(transport=httpx.MockTransport(_handle))

    monkeypatch.setattr("app.processing.ingest.url_fetch.make_safe_client", factory)


def _install_body(monkeypatch, body: bytes) -> None:
    async def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _install_handler(monkeypatch, _handler)


class _Body(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def __aiter__(self):
        yield self._payload


def _quota_refusal(actual_size: int):
    from fastapi import HTTPException

    return HTTPException(
        status_code=413,
        detail=f"Storage quota exceeded: used 0 of 1 bytes (adding {actual_size} bytes)",
    )
