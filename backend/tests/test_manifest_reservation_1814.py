"""fix(#1814): a manifest entry claims its key before its source is fetched.

The apply loop used to insert the ``IngestJob`` row only after the entry's
source had finished downloading, so the in-flight check and the row that makes
it true were separated by a network fetch. A client that timed out mid-download
and retried passed the check a second time and queued the same entry twice.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from fastapi import HTTPException, Request
from sqlalchemy import event, func, select, text, update

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.quota.schemas import UserQuotaUsage
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import (
    JOB_TIMEOUT_SECONDS,
    fail_stale_jobs,
    stale_pending_cutoff_seconds,
)
from app.processing.ingest import manifest_service
from app.processing.ingest.manifest_reservation import (
    MANIFEST_STAGE_DOWNLOADING,
    MANIFEST_STAGE_METADATA_KEY,
    expire_stale_manifest_reservations,
)
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)

pytestmark = pytest.mark.anyio

_FIXTURE = "tests/fixtures/ingest/basic_attrs.geojson"


def _manifest_dataset(
    *,
    key: str,
    title: str = "Road centerlines",
    uri: str = _FIXTURE,
) -> dict:
    return {
        "key": key,
        "title": title,
        "description": f"{title} description",
        "sources": [{"type": "vector", "uri": uri, "format": "geojson"}],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": "draft"},
    }


def _request(*datasets: dict, dry_run: bool = False) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        {
            "manifest_version": "1",
            "catalog": {"title": "Manifest catalog"},
            "datasets": list(datasets),
            "dry_run": dry_run,
        }
    )


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


async def _admin_user(session) -> User:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one()


def _stage_fixture() -> Path:
    destination = Path(settings.upload_staging_dir) / _FIXTURE
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", destination)
    return destination


def _staged_bytes(name: str, size: int = 4096) -> Path:
    path = Path(settings.upload_staging_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


async def _jobs_for_key(session, key: str) -> list[IngestJob]:
    # populate_existing, because these assertions are about the row and a
    # settlement written as a fenced UPDATE does not reach the identity map.
    # Narrower than expire_all(), which would also expire the caller's own User.
    result = await session.execute(
        select(IngestJob)
        .where(IngestJob.user_metadata["manifest_key"].astext == key)
        .order_by(IngestJob.created_at)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars())


@contextmanager
def _ingest_job_writes(session):
    """Record every INSERT and UPDATE issued against ``catalog.ingest_jobs``.

    Listens on the session's sync engine, so it sees what the database was
    actually asked to do rather than what the ORM was asked to do. Each entry
    carries its rowcount, so a caller can ask either question: did anything
    reach the table at all, or did anything change a row.
    """
    bind = session.get_bind()
    engine = getattr(bind, "sync_engine", bind)
    seen: list[tuple[str, int]] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        collapsed = " ".join(statement.split())
        if "ingest_jobs" in collapsed and collapsed.upper().startswith(
            ("INSERT", "UPDATE")
        ):
            seen.append((collapsed, cursor.rowcount or 0))

    event.listen(engine, "after_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "after_cursor_execute", _record)


def _writes(
    recorded: list[tuple[str, int]], verb: str, *, changed: bool = False
) -> list[str]:
    return [
        statement
        for statement, rowcount in recorded
        if statement.upper().startswith(verb) and (rowcount > 0 or not changed)
    ]


class _GatedDownload:
    """Mocked source download that parks until the test releases it."""

    def __init__(self) -> None:
        self.started = anyio.Event()
        self.release = anyio.Event()
        self.calls = 0

    async def __call__(
        self,
        prepared,
        *,
        max_size_bytes: int,
        quota_byte_limit: int | None = None,
    ) -> str:
        self.calls += 1
        path = _staged_bytes(f"manifest_1814_gated_{self.calls}.geojson")
        self.started.set()
        # A second call is the defect: it can only happen if the concurrent
        # apply classified the same entry as new. Release both so the test
        # fails on the count and the classification rather than on a deadline.
        if self.calls > 1:
            self.release.set()
        await self.release.wait()
        return str(path)


class TestReservationClosesTheDownloadWindow:
    async def test_a_retry_during_the_download_attaches_to_the_reserved_job(
        self, client, clean_tables
    ):
        """The defect, end to end.

        Two applies of one entry, the second submitted while the first is
        still downloading. Before the reservation, both passed the in-flight
        check and both downloaded and queued: the CLI's documented
        "re-applying immediately can queue that entry twice".
        """
        import app.core.db as db_module

        request = _request(
            _manifest_dataset(
                key="manifest-1814-retry",
                uri="https://data.example.test/roads.geojson",
            )
        )
        download = _GatedDownload()
        first: dict = {}

        async def _run_first() -> None:
            async with db_module.async_session() as session:
                user = await _admin_user(session)
                first["response"] = await apply_manifest(
                    session, request, user, _http_request()
                )

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=download,
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            try:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(_run_first)
                    with anyio.fail_after(30):
                        await download.started.wait()
                        async with db_module.async_session() as retry_session:
                            retry_user = await _admin_user(retry_session)
                            retry = await apply_manifest(
                                retry_session, request, retry_user, _http_request()
                            )
                    download.release.set()
            finally:
                download.release.set()

        assert download.calls == 1
        created = first["response"].results[0]
        assert created.action == "create"
        assert created.job_id is not None
        queue.assert_awaited_once()

        attached = retry.results[0]
        assert attached.action == "skip"
        assert attached.job_id == created.job_id
        assert "queued or running" in attached.message

        async with db_module.async_session() as session:
            jobs = await _jobs_for_key(session, "manifest-1814-retry")
        assert [job.id for job in jobs] == [created.job_id]
        assert jobs[0].file_path is not None
        assert MANIFEST_STAGE_METADATA_KEY not in jobs[0].user_metadata

    async def test_a_different_fingerprint_during_the_download_is_refused(
        self, client, clean_tables
    ):
        """The reservation answers the conflict branch too, not only the retry.

        A second entry for the same key with different content used to sail
        past the in-flight check during the download window and queue a
        competing job over the same manifest key.
        """
        import app.core.db as db_module

        original = _request(
            _manifest_dataset(
                key="manifest-1814-conflict",
                uri="https://data.example.test/roads.geojson",
            )
        )
        competing = _request(
            _manifest_dataset(
                key="manifest-1814-conflict",
                title="Competing roads",
                uri="https://data.example.test/roads.geojson",
            )
        )
        download = _GatedDownload()
        first: dict = {}

        async def _run_first() -> None:
            async with db_module.async_session() as session:
                user = await _admin_user(session)
                first["response"] = await apply_manifest(
                    session, original, user, _http_request()
                )

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=download,
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
        ):
            try:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(_run_first)
                    with anyio.fail_after(30):
                        await download.started.wait()
                        async with db_module.async_session() as other_session:
                            other_user = await _admin_user(other_session)
                            conflict = await apply_manifest(
                                other_session, competing, other_user, _http_request()
                            )
                    download.release.set()
            finally:
                download.release.set()

        assert download.calls == 1
        assert first["response"].results[0].action == "create"
        result = conflict.results[0]
        assert result.action == "error"
        assert "in-flight apply" in result.message
        assert result.job_id is None

        async with db_module.async_session() as session:
            jobs = await _jobs_for_key(session, "manifest-1814-conflict")
        assert len(jobs) == 1


class TestReservationFailureReleasesTheKey:
    async def test_a_failed_download_settles_the_reservation(
        self, test_db_session, clean_tables
    ):
        """A download that dies leaves a terminal row, and the key free."""
        request = _request(
            _manifest_dataset(
                key="manifest-1814-download-failure",
                uri="https://data.example.test/roads.geojson",
            )
        )

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(side_effect=RuntimeError("connection reset")),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            failed = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert failed.results[0].action == "error"
        assert "connection reset" in failed.results[0].message
        queue.assert_not_awaited()

        settled = await _jobs_for_key(test_db_session, "manifest-1814-download-failure")
        assert len(settled) == 1
        assert settled[0].status in {"failed", "cancelled"}
        assert settled[0].completed_at is not None

        staged = _staged_bytes("manifest_1814_after_failure.geojson")
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            retried = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert retried.results[0].action == "create"
        queue.assert_awaited_once()
        assert (
            len(await _jobs_for_key(test_db_session, "manifest-1814-download-failure"))
            == 2
        )

    async def test_a_reservation_settled_under_us_never_queues(
        self, test_db_session, clean_tables
    ):
        """The staging bind is fenced, so a superseded attempt drops its bytes.

        This is the other half of the staleness rule: a reservation expired by
        a later apply is terminal, and the slow attempt that still owns the
        download must not queue on top of the row that replaced it.
        """
        request = _request(
            _manifest_dataset(
                key="manifest-1814-lost",
                uri="https://data.example.test/roads.geojson",
            )
        )
        staged = _staged_bytes("manifest_1814_lost.geojson")

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.processing.ingest.manifest_service."
                "bind_reservation_to_staged_source",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert response.results[0].action == "error"
        assert "lost its reservation" in response.results[0].message
        queue.assert_not_awaited()
        assert not staged.exists()

    async def test_a_database_failure_during_the_bind_still_clears_the_key(
        self, test_db_session, clean_tables
    ):
        """fix(#1814 codex r1): the settlement runs on a reset session.

        A statement that failed leaves the transaction refusing every further
        statement, so a settlement issued straight onto it raises too. Before
        the reset, the reservation stayed pending in the downloading stage and
        every re-apply attached to a job that would never queue.
        """
        request = _request(
            _manifest_dataset(
                key="manifest-1814-poisoned",
                uri="https://data.example.test/roads.geojson",
            )
        )
        staged = _staged_bytes("manifest_1814_poisoned.geojson")

        async def _poisoning_bind(db, job, *, file_path: str) -> bool:
            await db.execute(text("SELECT 1 / 0"))
            return True

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.processing.ingest.manifest_service."
                "bind_reservation_to_staged_source",
                new=_poisoning_bind,
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert response.results[0].action == "error"
        queue.assert_not_awaited()
        assert not staged.exists()

        settled = await _jobs_for_key(test_db_session, "manifest-1814-poisoned")
        assert len(settled) == 1
        assert settled[0].status in {"failed", "cancelled"}
        assert MANIFEST_STAGE_METADATA_KEY not in (settled[0].user_metadata or {})

        # The key is free: a re-apply creates its own job instead of attaching.
        retry_staged = _staged_bytes("manifest_1814_poisoned_retry.geojson")
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(retry_staged)),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            retried = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert retried.results[0].action == "create"
        assert retried.results[0].job_id != settled[0].id
        queue.assert_awaited_once()

    async def test_a_queue_refusal_before_dispatch_still_frees_the_key(
        self, test_db_session, clean_tables
    ):
        """A row that never reached the queue must not hold its key.

        The orphan guard settles the row for every dispatch failure, but a
        refusal raised before it runs would otherwise leave the entry pending
        until the sweep.
        """
        _stage_fixture()
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-queue-refusal"))

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(side_effect=HTTPException(status_code=400, detail="no path")),
        ):
            refused = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert refused.results[0].action == "error"
        settled = await _jobs_for_key(test_db_session, "manifest-1814-queue-refusal")
        assert len(settled) == 1
        assert settled[0].status == "failed"

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            retried = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert retried.results[0].action == "create"
        queue.assert_awaited_once()

    async def test_a_durable_bind_whose_commit_raises_keeps_its_bytes(
        self, test_db_session, clean_tables
    ):
        """fix(#1814): the row decides the cleanup, not the exception.

        A commit can be durable in PostgreSQL and still raise on the
        acknowledgement. Deciding from the exception deleted the staged source
        and left a `pending` row pointing at nothing, with no queued task, and
        every re-apply attached to it until the sweep ran.
        """
        request = _request(
            _manifest_dataset(
                key="manifest-1814-ambiguous",
                uri="https://data.example.test/roads.geojson",
            )
        )
        staged = _staged_bytes("manifest_1814_ambiguous.geojson")

        async def _durable_then_raise(db) -> None:
            await db.commit()
            raise RuntimeError("acknowledgement lost")

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.processing.ingest.manifest_service._commit_staged_bind",
                new=_durable_then_raise,
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert response.results[0].action == "error"
        assert "acknowledgement lost" in response.results[0].message
        queue.assert_not_awaited()
        # The bind landed, so the bytes are what /jobs/{id}/retry needs.
        assert staged.exists()

        settled = await _jobs_for_key(test_db_session, "manifest-1814-ambiguous")
        assert len(settled) == 1
        assert settled[0].status == "failed"
        assert settled[0].file_path == str(staged)
        assert MANIFEST_STAGE_METADATA_KEY not in settled[0].user_metadata

        # And the key is free: a re-apply does not attach to the dead job.
        retry_staged = _staged_bytes("manifest_1814_ambiguous_retry.geojson")
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(retry_staged)),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            retried = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert retried.results[0].action == "create"
        assert retried.results[0].job_id != settled[0].id
        queue.assert_awaited_once()

    async def test_a_post_admission_failure_returns_its_bytes_to_the_batch_ledger(
        self, test_db_session, clean_tables
    ):
        """Invariant 4: the request-local ledger must not keep a failed entry's
        bytes, or a later entry in the same manifest is refused for storage
        nobody is using."""
        request = _request(
            _manifest_dataset(
                key="manifest-1814-ledger-a",
                uri="https://data.example.test/a.geojson",
            ),
            _manifest_dataset(
                key="manifest-1814-ledger-b",
                uri="https://data.example.test/b.geojson",
            ),
        )
        usage = UserQuotaUsage(
            bytes_used=0, dataset_count=0, storage_cap=6000, count_cap=0
        )
        real_bind = manifest_service.bind_reservation_to_staged_source
        binds: list[object] = []

        async def _flaky_bind(db, job, *, file_path: str) -> bool:
            binds.append(job.id)
            if len(binds) == 1:
                raise RuntimeError("bind interrupted")
            return await real_bind(db, job, file_path=file_path)

        downloads = 0

        async def _download(prepared, *, max_size_bytes, quota_byte_limit=None) -> str:
            nonlocal downloads
            downloads += 1
            return str(_staged_bytes(f"manifest_1814_ledger_{downloads}.geojson"))

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.modules.quota.service.get_user_quota_usage",
                new=AsyncMock(return_value=usage),
            ),
            patch("app.modules.quota.service.check_upload_quota", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=_download,
            ),
            patch(
                "app.processing.ingest.manifest_service."
                "bind_reservation_to_staged_source",
                new=_flaky_bind,
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
        ):
            response = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert [result.action for result in response.results] == ["error", "create"]
        assert "bind interrupted" in response.results[0].message


class TestStaleReservations:
    """The reservation runs under the fixed running lease, not the pending one.

    fix(#1814 audit): a committed `pending` row with no file_path and no queue
    task matches every clause of `stale_pending_clauses`, and
    `pending_job_timeout_seconds` may legally be 61s while a manifest download
    has no wall-clock bound of its own. The reservation was therefore reapable
    mid-flight by the sweep, the worker's startup recovery, the status poll and
    the next apply, and every retry repeated the loss.
    """

    def _reservation(self, user, dataset, prepared, *, age_seconds: float) -> IngestJob:
        return IngestJob(
            source_filename=prepared.source_filename,
            file_path=None,
            created_by=user.id,
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            user_metadata={
                **manifest_job_metadata(
                    dataset,
                    prepared,
                    fingerprint=manifest_dataset_fingerprint(dataset),
                ),
                MANIFEST_STAGE_METADATA_KEY: MANIFEST_STAGE_DOWNLOADING,
            },
        )

    async def test_a_live_download_survives_the_pending_sweep(
        self, client, clean_tables
    ):
        """The audit's counterfactual: a download older than the pending cutoff.

        Aged past `pending_job_timeout_seconds` with its lease still fresh, then
        put through the real `fail_stale_jobs`. Before the lease it came back
        `cancelled` mid-download, the staging bind then matched nothing, and the
        entry answered "lost its reservation" for every retry.
        """
        import app.core.db as db_module

        key = "manifest-1814-long-download"
        request = _request(
            _manifest_dataset(key=key, uri="https://data.example.test/big.geojson")
        )
        download = _GatedDownload()
        first: dict = {}
        observed: dict = {}

        async def _run_first() -> None:
            async with db_module.async_session() as session:
                user = await _admin_user(session)
                first["response"] = await apply_manifest(
                    session, request, user, _http_request()
                )

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=download,
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            try:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(_run_first)
                    with anyio.fail_after(60):
                        await download.started.wait()
                        async with db_module.async_session() as sweeper:
                            now = datetime.now(timezone.utc)
                            aged = now - timedelta(
                                seconds=stale_pending_cutoff_seconds(
                                    completion_bound=False
                                )
                                + 600
                            )
                            await sweeper.execute(
                                update(IngestJob)
                                .where(
                                    IngestJob.user_metadata["manifest_key"].astext
                                    == key
                                )
                                .values(created_at=aged, started_at=now)
                                .execution_options(synchronize_session=False)
                            )
                            await sweeper.commit()
                            await fail_stale_jobs(sweeper, detailed=True)
                            sweeper.expire_all()
                            observed["status"] = (
                                await sweeper.execute(
                                    select(IngestJob.status).where(
                                        IngestJob.user_metadata["manifest_key"].astext
                                        == key
                                    )
                                )
                            ).scalar_one()
                    download.release.set()
            finally:
                download.release.set()

        assert observed["status"] == "running"
        created = first["response"].results[0]
        assert created.action == "create"
        queue.assert_awaited_once()

        async with db_module.async_session() as session:
            bound = (await _jobs_for_key(session, key))[0]
        assert bound.status == "pending"
        assert bound.file_path is not None
        assert MANIFEST_STAGE_METADATA_KEY not in bound.user_metadata
        # The pending clock restarts at staging, not at a creation that predates
        # the whole download.
        assert bound.user_metadata["staged_at"] is not None

    async def test_a_stale_reservation_does_not_block_the_key(
        self, test_db_session, clean_tables
    ):
        """An API process that dies mid-download must not hold a key forever."""
        _stage_fixture()
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-stale"))
        prepared = await classify_manifest_source(request.datasets[0].sources[0])
        abandoned = self._reservation(
            user,
            request.datasets[0],
            prepared,
            age_seconds=JOB_TIMEOUT_SECONDS + 60,
        )
        test_db_session.add(abandoned)
        await test_db_session.commit()
        abandoned_id = abandoned.id

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        result = response.results[0]
        assert result.action == "create"
        assert result.job_id != abandoned_id
        queue.assert_awaited_once()

        reaped = await test_db_session.get(
            IngestJob, abandoned_id, populate_existing=True
        )
        assert reaped.status == "failed"
        assert MANIFEST_STAGE_METADATA_KEY not in reaped.user_metadata

    async def test_a_reservation_inside_the_lease_still_holds_the_key(
        self, test_db_session, clean_tables
    ):
        """The budget is the running sweep's own lease, read at call time.

        Pinned from both sides against the one number, so the in-flight check
        and the background sweep cannot start disagreeing about which rows are
        still live.
        """
        _stage_fixture()
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-budget"))
        prepared = await classify_manifest_source(request.datasets[0].sources[0])
        fresh = self._reservation(
            user,
            request.datasets[0],
            prepared,
            age_seconds=JOB_TIMEOUT_SECONDS - 60,
        )
        test_db_session.add(fresh)
        await test_db_session.commit()

        assert (
            await expire_stale_manifest_reservations(
                test_db_session, "manifest-1814-budget"
            )
            == 0
        )
        await test_db_session.commit()

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.results[0].action == "skip"
        assert response.results[0].job_id == fresh.id
        queue.assert_not_awaited()

    async def test_the_expiry_leaves_a_queued_manifest_job_alone(
        self, test_db_session, clean_tables
    ):
        """Only rows still in the downloading stage are the expiry's business."""
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-queued"))
        prepared = await classify_manifest_source(request.datasets[0].sources[0])
        queued = IngestJob(
            source_filename=prepared.source_filename,
            file_path="/tmp/manifest-1814-queued.geojson",
            created_by=user.id,
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(days=30),
            user_metadata=manifest_job_metadata(
                request.datasets[0],
                prepared,
                fingerprint=manifest_dataset_fingerprint(request.datasets[0]),
            ),
        )
        test_db_session.add(queued)
        await test_db_session.commit()

        assert (
            await expire_stale_manifest_reservations(
                test_db_session, "manifest-1814-queued"
            )
            == 0
        )


class TestFencedWritesAreSingleStatements:
    """One fenced UPDATE per transition, not a fenced one plus an ORM flush.

    fix(#1814): the instance has to describe the row after a fenced write, but
    plain assignment marks it dirty and the caller's own commit then flushes a
    second, unfenced update over the fenced one. `set_committed_value` writes
    the attribute as already-committed state instead.
    """

    async def test_the_staging_bind_emits_one_update(
        self, test_db_session, clean_tables
    ):
        _stage_fixture()
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-one-bind"))

        with (
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
            _ingest_job_writes(test_db_session) as statements,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.results[0].action == "create"
        assert len(_writes(statements, "INSERT", changed=True)) == 1, statements
        assert len(_writes(statements, "UPDATE", changed=True)) == 1, statements

    async def test_the_reservation_release_emits_one_update(
        self, test_db_session, clean_tables
    ):
        request = _request(
            _manifest_dataset(
                key="manifest-1814-one-release",
                uri="https://data.example.test/roads.geojson",
            )
        )
        staged = _staged_bytes("manifest_1814_one_release.geojson")

        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.modules.quota.service.check_upload_quota",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=413, detail="quota denied")
                ),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
            _ingest_job_writes(test_db_session) as statements,
        ):
            response = await apply_manifest(
                test_db_session,
                request,
                await _admin_user(test_db_session),
                _http_request(),
            )

        assert response.results[0].action == "error"
        assert len(_writes(statements, "INSERT", changed=True)) == 1, statements
        assert len(_writes(statements, "UPDATE", changed=True)) == 1, statements


class TestDryRunReservesNothing:
    async def test_dry_run_writes_nothing_and_leaves_a_stale_row_alone(
        self, test_db_session, clean_tables
    ):
        """fix(#1814): a preview is a read.

        The staleness expiry used to run before the dry-run return, so a
        preview settled another caller's abandoned reservation. It now runs
        only for a real apply, at the cost that a preview can still report an
        entry in flight where an apply would take it.
        """
        _stage_fixture()
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-dry-stale"))
        prepared = await classify_manifest_source(request.datasets[0].sources[0])
        abandoned = IngestJob(
            source_filename=prepared.source_filename,
            file_path=None,
            created_by=user.id,
            status="running",
            started_at=datetime.now(timezone.utc)
            - timedelta(seconds=JOB_TIMEOUT_SECONDS + 60),
            user_metadata={
                **manifest_job_metadata(
                    request.datasets[0],
                    prepared,
                    fingerprint=manifest_dataset_fingerprint(request.datasets[0]),
                ),
                MANIFEST_STAGE_METADATA_KEY: MANIFEST_STAGE_DOWNLOADING,
            },
        )
        test_db_session.add(abandoned)
        await test_db_session.commit()
        abandoned_id = abandoned.id

        preview = _request(
            _manifest_dataset(key="manifest-1814-dry-stale"), dry_run=True
        )
        with (
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
            _ingest_job_writes(test_db_session) as statements,
        ):
            response = await apply_manifest(
                test_db_session, preview, user, _http_request()
            )

        assert response.dry_run is True
        # Statement level, not row level: a preview must not send a write to
        # the table at all, even one its fence would match nothing with.
        assert statements == [], statements

        untouched = await test_db_session.get(
            IngestJob, abandoned_id, populate_existing=True
        )
        assert untouched.status == "running"
        assert untouched.completed_at is None
        assert (
            untouched.user_metadata[MANIFEST_STAGE_METADATA_KEY]
            == MANIFEST_STAGE_DOWNLOADING
        )

    async def test_dry_run_leaves_no_reservation(self, test_db_session, clean_tables):
        _stage_fixture()
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-1814-dry"), dry_run=True)
        before = await test_db_session.scalar(select(func.count(IngestJob.id)))

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.results[0].action == "create"
        assert response.results[0].job_id is None
        queue.assert_not_awaited()
        assert await test_db_session.scalar(select(func.count(IngestJob.id))) == before
        assert await _jobs_for_key(test_db_session, "manifest-1814-dry") == []
