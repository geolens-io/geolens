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
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.core.config import settings
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS, fail_stale_jobs
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


async def _run_task(kwargs: dict, job_context=None) -> None:
    payload = {k: v for k, v in kwargs.items() if k != "tenant_id"}
    await tasks_url_fetch.fetch_url.func(job_context, **payload)


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


class TestWorkerRunsTheRealSafeClient:
    """The download keeps Rule 2 on the worker: the real `make_safe_client`
    re-resolves and validates at connect time, so a host that answers public
    at submission and private at connect is refused there."""

    async def test_connect_time_private_resolution_fails_the_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A host resolving to link-local at connect time settles the job failed.

        The real client and transport run; only `socket.getaddrinfo` is
        stubbed. The positive control below proves the same wiring reaches a
        200 when resolution is public, so this is the guard refusing rather
        than the harness failing to connect.
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

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda h, p, *a, **k: _addrinfo("169.254.169.254", p),
        )
        # The guard raises BEFORE delegating, so a reached connection means
        # the refusal did not happen and a transport error is standing in for
        # it. Returning 200 here makes that substitution fail the test.
        connected: list[str] = []

        async def _record_connect(self, request):
            connected.append(str(request.url))
            return httpx.Response(200, stream=_Body(GEOJSON))

        monkeypatch.setattr(
            httpx.AsyncHTTPTransport, "handle_async_request", _record_connect
        )
        await _run_task(captured[0])

        assert connected == []
        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == (
            "URLs targeting private/internal networks are not allowed"
        )
        assert _staged_files() == []

    async def test_public_resolution_reaches_the_origin_and_stages(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """Positive control for the test above: same real client and transport,
        public resolution, and the body is staged."""
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://public.example.test/roads.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        monkeypatch.setattr(
            socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("93.184.216.34", p)
        )

        async def _fake_connect(self, request):
            return httpx.Response(200, stream=_Body(GEOJSON))

        monkeypatch.setattr(
            httpx.AsyncHTTPTransport, "handle_async_request", _fake_connect
        )
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert Path(job.file_path).read_bytes() == GEOJSON


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
        # The row names the intended destination from adoption on; nothing
        # was staged there and the job never became previewable.
        assert not Path(job.file_path).exists()
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

    async def test_a_failed_session_checkout_for_staging_settles_the_row(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A session the staging block cannot open still settles the job.

        The acquisition sits outside the block's own try, so the task's outer
        handler is what covers it, on a session of its own.

        Counterfactual: without that handler the row stays running with no
        error_message until the lease reaper.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/checkout.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        import app.core.db as db_module

        real_session = db_module.async_session
        calls = {"n": 0}

        def _fail_the_staging_checkout(*args, **kwargs):
            calls["n"] += 1
            # 1 is the adoption, 2 is staging, 3 is the outer settle.
            if calls["n"] == 2:
                raise RuntimeError("pool checkout timed out")
            return real_session(*args, **kwargs)

        monkeypatch.setattr(db_module, "async_session", _fail_the_staging_checkout)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "URL import failed"

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


class TestStagedRowClassification:
    async def test_staging_drops_the_dispatch_marker(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A staged row carries no dispatch marker, so an abandoned import
        settles `cancelled` rather than `failed`.

        The door stamps `commit_attempted_at` for the DOWNLOAD task, but
        `abandoned_upload` reads its absence as "no ingest was ever dispatched",
        which is true again once the file is merely staged and awaiting a user
        commit.

        Counterfactual: carrying the marker through the transition makes
        `is_abandoned_upload` False and the sweep reports the same row failed.
        """
        from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY
        from app.platform.jobs.sweep import is_abandoned_upload

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/marker.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert COMMIT_ATTEMPTED_METADATA_KEY in (job.user_metadata or {})

        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])

        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert COMMIT_ATTEMPTED_METADATA_KEY not in (job.user_metadata or {})
        assert is_abandoned_upload(job.user_metadata)


class TestNoTransactionAcrossTheDownload:
    async def test_the_download_runs_with_no_session_in_a_transaction(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """No session is left in a transaction while bytes are streaming.

        A download may run for url_import_fetch_max_seconds; holding a
        connection across it pins one per concurrent import.

        Counterfactual: with the config and quota reads sharing the session
        that spans the transfer, the sample below is non-empty.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/notx.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        import app.core.db as db_module

        real_session = db_module.async_session
        live: list = []

        def _tracking_session(*args, **kwargs):
            made = real_session(*args, **kwargs)
            live.append(made)
            return made

        monkeypatch.setattr(db_module, "async_session", _tracking_session)

        in_transaction_during_download: list[bool] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            in_transaction_during_download.append(
                any(sess.in_transaction() for sess in live)
            )
            return httpx.Response(200, content=GEOJSON)

        _install_handler(monkeypatch, _handler)
        await _run_task(captured[0])

        assert in_transaction_during_download == [False]
        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "pending"

    async def test_a_close_failure_after_the_commit_keeps_the_artifact(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A session teardown that raises after publication deletes nothing.

        Counterfactual: inferring publication from the exception instead of
        the `published` local sends this through settlement, which unlinks
        the file the durable pending row points at.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/closefail.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        import app.core.db as db_module

        real_session = db_module.async_session
        made = {"n": 0}

        def _session_whose_second_close_fails(*args, **kwargs):
            made["n"] += 1
            session = real_session(*args, **kwargs)
            if made["n"] == 3:
                # 1 is adoption, 2 is the config read, 3 is the transition.
                real_close = session.close

                async def _boom():
                    await real_close()
                    raise RuntimeError("connection reset returning to the pool")

                session.close = _boom
            return session

        monkeypatch.setattr(
            db_module, "async_session", _session_whose_second_close_fails
        )
        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert Path(job.file_path).read_bytes() == GEOJSON


class TestQueueRowHygiene:
    async def test_the_url_is_purged_from_the_queue_row_after_adoption(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """The submitted URL leaves `procrastinate_jobs.args` before the transfer.

        Counterfactual: without the purge the key is still there after the
        task runs, and the worker deletes only successful rows, so a presigned
        link outlives every non-successful delivery.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        url = "https://files.example.test/presigned.geojson?X-Amz-Signature=abc"
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": url, "filename": "presigned.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        row_id = (
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.procrastinate_jobs "
                    "(queue_name, task_name, args, status) VALUES "
                    "('ingest', 'fetch_url', jsonb_build_object("
                    "'job_id', CAST(:j AS text), 'url', CAST(:u AS text)), 'doing') "
                    "RETURNING id"
                ),
                {"j": resp.json()["job_id"], "u": url},
            )
        ).scalar_one()
        await test_db_session.commit()

        _install_body(monkeypatch, GEOJSON)
        await _run_task(
            captured[0], job_context=SimpleNamespace(job=SimpleNamespace(id=row_id))
        )

        args = (
            await test_db_session.execute(
                text("SELECT args FROM catalog.procrastinate_jobs WHERE id = :i"),
                {"i": row_id},
            )
        ).scalar_one()
        assert "url" not in args
        assert args["job_id"] == resp.json()["job_id"]


class TestPublishedArtifactSurvivesTeardown:
    async def test_a_raise_after_the_transition_keeps_the_staged_file(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A teardown failure after publication must not delete the artifact.

        On local storage the published `file_path` IS the local staging file,
        so an outer settle that owned it would leave a durable pending row
        pointing at nothing.

        Counterfactual: passing `local_dest` to the outer settle instead of
        None deletes the file this asserts still exists.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/teardown.geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text

        _install_body(monkeypatch, GEOJSON)
        real_stage = tasks_url_fetch._stage_downloaded_file

        async def _stage_then_fail(*args, **kwargs):
            await real_stage(*args, **kwargs)
            raise RuntimeError("session teardown after the transition committed")

        monkeypatch.setattr(tasks_url_fetch, "_stage_downloaded_file", _stage_then_fail)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert Path(job.file_path).read_bytes() == GEOJSON


class TestLeaseStartsAtTheClaim:
    async def test_a_queued_download_survives_a_backlog_past_the_lease(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A row whose task is still `todo` is not reaped by the running sweep.

        The door commits `running` so the UI can show a download, but the
        worker lease only starts when the task adopts it. A queue backlog
        longer than JOB_TIMEOUT_SECONDS must not settle a job nothing touched.

        Counterfactual: without the unclaimed-queue exemption the same sweep
        fails the row, and the eventual worker finds it already settled.
        """
        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/backlog.geojson"},
            headers=admin_auth_header,
        )
        job_id = uuid.UUID(resp.json()["job_id"])

        # The status trigger writes procrastinate_events unqualified, so the
        # schema has to be on the search path for this insert.
        await test_db_session.execute(text("SET LOCAL search_path = catalog, public"))
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) VALUES "
                "('ingest', 'fetch_url', jsonb_build_object("
                "'job_id', CAST(:j AS text)), 'todo')"
            ),
            {"j": str(job_id)},
        )
        expired = datetime.now(timezone.utc) - timedelta(
            seconds=JOB_TIMEOUT_SECONDS + 60
        )
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(started_at=expired, heartbeat_at=None)
        )
        await test_db_session.commit()

        await fail_stale_jobs(test_db_session)
        job = await _get_job(test_db_session, job_id)
        await test_db_session.refresh(job)
        assert job.status == "running"

        # A worker that took the job and then died leaves `doing`, and that
        # row IS reaped: the exemption is for never-claimed work only.
        await test_db_session.execute(text("SET LOCAL search_path = catalog, public"))
        await test_db_session.execute(
            text(
                "UPDATE catalog.procrastinate_jobs SET status = 'doing' "
                "WHERE args->>'job_id' = :j"
            ),
            {"j": str(job_id)},
        )
        await test_db_session.commit()
        await fail_stale_jobs(test_db_session)
        await test_db_session.refresh(job)
        assert job.status == "failed"


class TestInterruptedDownloadIsNotRetryable:
    async def test_a_crash_truncated_download_refuses_retry(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """A download the worker never finished cannot be replayed as an import.

        file_path names a destination, and a truncated CSV or GeoJSON still
        parses, so retry would import an incomplete dataset as a complete one.

        Counterfactual: without the marker, `_retry_capability` sees a file
        that exists and authorizes the replay.
        """
        from app.platform.jobs.models import URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY
        from app.platform.jobs.router import get_retry_capability

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/truncated.csv"},
            headers=admin_auth_header,
        )
        job = await _get_job(test_db_session, resp.json()["job_id"])
        assert (job.user_metadata or {}).get(URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY)

        # The shape a SIGKILL leaves: the destination bound at adoption, a
        # partial file on disk, and the row failed by the stale sweep with
        # its file_path preserved.
        partial = Path(settings.upload_staging_dir) / f"{job.id}_truncated.csv"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"id,name\n1,trunc")
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(status="failed", file_path=str(partial))
        )
        await test_db_session.commit()
        await test_db_session.refresh(job)

        can_retry, reason = await get_retry_capability(job)
        assert can_retry is False
        assert "did not finish" in reason
        partial.unlink(missing_ok=True)

    async def test_a_staged_row_is_retryable_again(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """Once staged, the marker is gone and an ordinary retry is allowed.

        Counterfactual: leaving the marker on the row makes every later
        failure of this import unretryable.
        """
        from app.platform.jobs.models import URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY
        from app.platform.jobs.router import get_retry_capability

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _accept_any_url()
        )
        captured = _capture_defer(monkeypatch)
        resp = await client.post(
            "/ingest/upload/url",
            json={"url": "https://files.example.test/whole.geojson"},
            headers=admin_auth_header,
        )
        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY not in (job.user_metadata or {})

        await test_db_session.execute(
            update(IngestJob).where(IngestJob.id == job.id).values(status="failed")
        )
        await test_db_session.commit()
        await test_db_session.refresh(job)
        can_retry, _reason = await get_retry_capability(job)
        assert can_retry is True


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


def _addrinfo(ip: str, port: int | None):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))]


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
