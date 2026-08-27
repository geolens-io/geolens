"""feat(#1676): the import and re-upload-commit doors lease their token too.

#1220 gave the refresh door a one-use Valkey handoff so a service credential
never lands in ``catalog.procrastinate_jobs.args``. The other two doors kept
dispatching the raw token, while the import UI promised the opposite. These
tests pin the three states those doors now have, at both ends of the handoff:

- **state 1** store configured -> a reference travels, the secret does not,
  and the worker spends the reference exactly once;
- **state 2** store configured but unreachable -> 503 at the door, nothing
  dispatched, and no half-written state left for a sweep to unwind;
- **state 3** no store configured -> the durable argument this door has
  always sent, which is the whole reason these two doors do not simply refuse.

State 3 has a test of its own for each door because it is the branch a
tidy-up would delete: it looks like an oversight and is the only thing
keeping protected import working on a stock install, where ``REDIS_URL`` is
unset and the ``valkey`` service is behind the ``cloud-dev`` profile.

The last class covers the renewal query, which had to be widened for the
first-import door — the one leasing door that writes no ``dataset_refresh_
runs`` row and so matched nothing under the old inner join.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import select, text

from app.platform.jobs.models import IngestJob
from app.platform.refresh import credentials as creds
from app.platform.refresh.models import DatasetRefreshRun

from tests.factories import create_dataset, get_user_id

# The fake store and its fixture are #1220's; reusing them keeps the two
# suites answering to one model of what a credential backend does, the way
# test_refresh_pagination_1675 reuses test_refresh_gate_1269's harness.
from tests.test_service_refresh_1220 import (  # noqa: F401
    _FakeCredentialBackend,
    credential_backend,
)

pytestmark = pytest.mark.anyio

_SERVICE_URL = "https://example.arcgis.test/rest/services/Parcels/FeatureServer/0"


class _DownBackend:
    """Configured, reachable by settings, unreachable in fact.

    The distinction this class exists for: ``credential_store_available()``
    reads the SETTING, so an outage gets past every door's availability check
    and surfaces at the stash. State 2 is what happens then.
    """

    async def put(self, key, value, ttl_seconds):
        raise creds.CredentialStoreUnavailable("valkey is away")

    async def take(self, key):
        raise creds.CredentialStoreUnavailable("valkey is away")

    async def renew(self, key, ttl_seconds):
        return False


@pytest.fixture
def no_credential_store(monkeypatch):
    """The stock install: no backend installed, no REDIS_URL set."""
    from app.core.config import settings

    creds.set_credential_backend(None)
    monkeypatch.setattr(settings, "redis_url", None, raising=False)
    yield
    creds.set_credential_backend(None)


@pytest.fixture
def down_credential_store():
    backend = _DownBackend()
    creds.set_credential_backend(backend)
    try:
        yield backend
    finally:
        creds.set_credential_backend(None)


async def _service_import_job(session, *, created_by: uuid.UUID) -> IngestJob:
    """A pending first-import job bound to a remote service layer."""
    job = IngestJob(
        source_filename="Parcels",
        source_url=_SERVICE_URL,
        source_layer="0",
        created_by=created_by,
        status="pending",
        user_metadata={"service_type": "ArcGIS:FeatureServer", "layer_id": 0},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _service_reupload_job(
    session, *, dataset_id: uuid.UUID, created_by: uuid.UUID
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Parcels",
        source_url=_SERVICE_URL,
        source_layer="roads",
        created_by=created_by,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@asynccontextmanager
async def _import_harness(defer_side_effect=None):
    """Patch the SSRF probe and the deferred task; yield the task mock.

    ``task.defer_async.call_args.kwargs`` IS what becomes
    ``procrastinate_jobs.args`` — Procrastinate serializes those kwargs
    verbatim into the column — so inspecting the call is equivalent to
    querying a row this harness never lets reach the real queue. The same
    equivalence #1220's dispatch harness documents and relies on.

    ``validate_url_for_ssrf`` is patched in its DEFINING module: both
    ``commit_import`` and the worker re-import it lazily, so a patch on the
    router's namespace would be rebound away on the next call.
    """
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None, side_effect=defer_side_effect)
    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch("app.processing.ingest.tasks.ingest_service", task),
    ):
        yield task


@asynccontextmanager
async def _reupload_harness(defer_side_effect=None):
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None, side_effect=defer_side_effect)
    file_task = MagicMock()
    file_task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.reupload_service_task.return_value = task
    port.reupload_file_task.return_value = file_task
    port.priority_queue_threshold_bytes = 10_000_000
    with patch(
        "app.modules.catalog.datasets.api.router_reupload.get_catalog_port",
        return_value=port,
    ):
        yield task


async def _reload(session, job_id: uuid.UUID) -> IngestJob:
    """Re-read a row the request transaction wrote, through the same session.

    ``populate_existing`` rather than ``expire_all``: the handler and this
    session share an identity map, so without it the already-loaded instance
    is returned unchanged and every assertion below reads the pre-request
    values. ``expire_all`` fixes that and breaks something else — it expires
    EVERY loaded object, so the next plain attribute read on any of them
    (``dataset.id``, two lines later) becomes lazy IO in a sync context and
    raises ``MissingGreenlet``.
    """
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Door 1 — first import (POST /ingest/commit/{job_id})
# ---------------------------------------------------------------------------


class TestImportDoor:
    async def test_a_token_reaches_the_worker_as_a_reference_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """The sentinel is the token STRING, in every durable surface.

        Asserting a ``token`` key is absent passes just as happily when the
        value moved to another key, which is the exact shape of the bug this
        lease exists to prevent — so the assertion is on the value.
        """
        secret = "tok-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)

        with structlog.testing.capture_logs() as captured:
            async with _import_harness() as task:
                resp = await client.post(
                    f"/ingest/commit/{job.id}",
                    json={"title": "Parcels", "token": secret},
                    headers=admin_auth_header,
                )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["credential_ref"]
        assert kwargs["token"] is None
        assert secret not in str(kwargs)

        reloaded = await _reload(test_db_session, job.id)
        assert secret not in str(reloaded.user_metadata)
        assert reloaded.user_metadata["service_auth_required"] is True
        assert secret not in str(captured)

        # And the secret really is retrievable by the reference, once.
        assert await creds.claim_service_credential(kwargs["credential_ref"]) == secret

    async def test_without_a_store_the_import_still_runs_on_the_durable_argument(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        no_credential_store,
    ) -> None:
        """State 3, pinned deliberately rather than left as an accident.

        A stock install has no ``REDIS_URL``. Refusing here — which is what
        the refresh door does, and what a later tidy-up would "fix" this into
        — would stop protected imports working on every one of them. The log
        line is asserted with the branch so an operator can answer "is this
        install leasing?" from logs rather than from settings archaeology,
        and so that deleting the branch cannot pass this test quietly.
        """
        secret = "tok-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)

        with structlog.testing.capture_logs() as captured:
            async with _import_harness() as task:
                resp = await client.post(
                    f"/ingest/commit/{job.id}",
                    json={"title": "Parcels", "token": secret},
                    headers=admin_auth_header,
                )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["token"] == secret
        assert kwargs["credential_ref"] is None

        fallbacks = [
            entry
            for entry in captured
            if entry.get("event") == "service_credential_durable_fallback"
        ]
        assert len(fallbacks) == 1, captured
        assert fallbacks[0]["door"] == "import"
        # The line names the door, never the secret and never a reference.
        assert secret not in str(fallbacks[0])

    async def test_a_store_that_is_down_returns_503_and_finalizes_the_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        down_credential_store,
    ) -> None:
        """State 2, and the half this door has to do for itself.

        ``commit_import`` commits the job BEFORE dispatching, so unlike the
        two doors that stage before their own commit this one cannot answer
        an unreachable store by rolling back. A bare raise would leave the row
        `pending`, holding against the stale sweep for an hour, for a dispatch
        that provably never happened.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": "never-stashed"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        assert resp.json()["detail"]["code"] == "credential_store_unavailable"
        task.defer_async.assert_not_awaited()

        reloaded = await _reload(test_db_session, job.id)
        assert reloaded.status == "failed"
        assert reloaded.completed_at is not None

    async def test_a_public_import_is_untouched_by_any_of_this(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        down_credential_store,
    ) -> None:
        """No token, no credential, no store involvement — even a broken one.

        The counterfactual for the two tests above: if the 503 were keyed on
        the store rather than on the request carrying a secret, this would
        fail, and every unauthenticated service import on an install with a
        sick Valkey would fail with it.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["token"] is None
        assert kwargs["credential_ref"] is None

    async def test_a_queue_outage_discards_the_credential_it_stashed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """The dispatch failed, so nothing will ever claim it.

        The TTL is the real guarantee; this only shortens a window we already
        know is dead. Asserting it directly because "best-effort" is exactly
        the kind of call that gets dropped in a refactor without a test
        noticing.
        """
        secret = "tok-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)

        async with _import_harness(
            defer_side_effect=RuntimeError("queue unavailable")
        ) as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": secret},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        ref = task.defer_async.call_args.kwargs["credential_ref"]
        # Asserted before the claim: claim_service_credential(None) raises the
        # same CredentialExpiredError from its shape guard, so without this the
        # test passes just as happily on a door that leased nothing at all.
        assert ref
        with pytest.raises(creds.CredentialExpiredError):
            await creds.claim_service_credential(ref)

        reloaded = await _reload(test_db_session, job.id)
        assert reloaded.status == "failed"


# ---------------------------------------------------------------------------
# Door 2 — re-upload commit (POST /datasets/{id}/reupload/{job_id}/commit)
# ---------------------------------------------------------------------------


class TestReuploadCommitDoor:
    async def _dataset(self, session, *, created_by: uuid.UUID):
        return await create_dataset(
            session,
            created_by=created_by,
            name="Service Reupload Dataset",
            visibility="public",
            feature_count=100,
            source_filename="original.geojson",
            source_url="https://old.example.test/source",
        )

    async def _run_for(self, session, dataset_id: uuid.UUID):
        return (
            await session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.dataset_id == dataset_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def test_a_token_reaches_the_worker_as_a_reference_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = "tok-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._dataset(test_db_session, created_by=admin_id)
        job = await _service_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )

        with structlog.testing.capture_logs() as captured:
            async with _reupload_harness() as task:
                resp = await client.post(
                    f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                    json={"token": secret},
                    headers=admin_auth_header,
                )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["credential_ref"]
        assert kwargs["token"] is None
        assert secret not in str(kwargs)

        reloaded = await _reload(test_db_session, job.id)
        assert secret not in str(reloaded.user_metadata)
        assert reloaded.user_metadata["service_auth_required"] is True

        run = await self._run_for(test_db_session, dataset.id)
        assert run is not None
        assert secret not in str((run.error_message, run.error_code, run.origin_kind))
        assert secret not in str(captured)

        assert await creds.claim_service_credential(kwargs["credential_ref"]) == secret

    async def test_without_a_store_the_reupload_still_runs_on_the_durable_argument(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        no_credential_store,
    ) -> None:
        """State 3 at the second door. Same reason, same shape, own test.

        Both doors are pinned separately on purpose: one of them silently
        losing the fallback is exactly the half-migration this change exists
        to finish, and a shared test would let either half regress alone.
        """
        secret = "tok-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._dataset(test_db_session, created_by=admin_id)
        job = await _service_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )

        with structlog.testing.capture_logs() as captured:
            async with _reupload_harness() as task:
                resp = await client.post(
                    f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                    json={"token": secret},
                    headers=admin_auth_header,
                )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["token"] == secret
        assert kwargs["credential_ref"] is None

        fallbacks = [
            entry
            for entry in captured
            if entry.get("event") == "service_credential_durable_fallback"
        ]
        assert len(fallbacks) == 1, captured
        assert fallbacks[0]["door"] == "reupload_commit"
        assert secret not in str(fallbacks[0])

    async def test_a_store_that_is_down_returns_503_and_rolls_the_request_back(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        down_credential_store,
    ) -> None:
        """State 2, staged before the commit so the rollback is total.

        The reserved run is the part that matters: leaving one behind would
        hold the dataset against the admission index and answer the retry —
        the one the operator makes once Valkey is back — with `dataset_busy`.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._dataset(test_db_session, created_by=admin_id)
        job = await _service_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )

        async with _reupload_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"token": "never-stashed"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        assert resp.json()["detail"]["code"] == "credential_store_unavailable"
        task.defer_async.assert_not_awaited()
        assert await self._run_for(test_db_session, dataset.id) is None
        assert (await _reload(test_db_session, job.id)).status == "pending"

    async def test_a_public_reupload_is_untouched_by_a_broken_store(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        down_credential_store,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._dataset(test_db_session, created_by=admin_id)
        job = await _service_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )

        async with _reupload_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["token"] is None
        assert kwargs["credential_ref"] is None


# ---------------------------------------------------------------------------
# Redemption — the worker end of the import door's handoff
# ---------------------------------------------------------------------------


class TestImportWorkerRedemption:
    """``ingest_service`` spends the reference, and spends it once.

    Driven through the real task entry point with only the outbound ogr2ogr
    boundary faked, so the claim's PLACEMENT is under test and not just the
    helper it calls.
    """

    async def _drive(
        self, session, monkeypatch, *, credential_ref, token=None, error_text="stop"
    ):
        from app.processing.ingest import tasks_vector
        from app.processing.ingest.ogr import IngestionError

        admin_id = await get_user_id(session, "admin")
        job = await _service_import_job(session, created_by=admin_id)

        seen: dict = {}

        class _FakeProcessingPort:
            def build_gdal_source(self, *args, **kwargs):
                return "FAKE_GDAL_SOURCE", "0"

        async def _fallback(import_fn, source_layer, **kwargs):
            seen["token"] = kwargs.get("token")
            raise IngestionError(error_text)

        monkeypatch.setattr("app.platform.security.validate_url_for_ssrf", AsyncMock())
        monkeypatch.setattr(
            "app.platform.extensions.get_processing_port", lambda: _FakeProcessingPort()
        )
        monkeypatch.setattr(
            "app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:"
        )
        monkeypatch.setattr(
            tasks_vector, "_run_service_import_with_wfs_fallback", _fallback
        )

        with pytest.raises(IngestionError):
            await tasks_vector.ingest_service.func(
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                source_url=_SERVICE_URL,
                source_layer="0",
                user_id=str(admin_id),
                token=token,
                credential_ref=credential_ref,
            )
        return job, seen

    async def test_the_reference_is_redeemed_for_the_fetch_and_spent(
        self,
        test_db_session,
        monkeypatch,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = "tok-" + uuid.uuid4().hex
        ref = await creds.stash_service_credential(secret)

        _job, seen = await self._drive(test_db_session, monkeypatch, credential_ref=ref)

        assert seen["token"] == secret
        # Single-use: the same dispatch retried cannot fetch again. #1220's
        # Decision 3 — a credential is request-scoped, so a run that outlives
        # its credential must ask a human rather than retry unauthenticated
        # and report the origin's 401 as the fault.
        with pytest.raises(creds.CredentialExpiredError):
            await creds.claim_service_credential(ref)

    async def test_a_spent_reference_fails_the_job_rather_than_fetching_bare(
        self,
        test_db_session,
        monkeypatch,
        credential_backend,  # noqa: F811
    ) -> None:
        """The claim is placed AFTER phase 1 for this reason.

        Phase 1 is what writes ``status='running'``, and the failure write at
        the bottom of the task is fenced on it. Claim before phase 1 and a
        spent credential leaves the job `pending` with nothing recorded — the
        silent-hang shape, not a failure anyone can read.
        """
        from app.processing.ingest import tasks_vector

        ref = await creds.stash_service_credential("already-spent")
        assert await creds.claim_service_credential(ref) == "already-spent"

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)

        called = {"fetch": False}

        class _FakeProcessingPort:
            def build_gdal_source(self, *args, **kwargs):
                return "FAKE_GDAL_SOURCE", "0"

        async def _fallback(import_fn, source_layer, **kwargs):
            called["fetch"] = True

        monkeypatch.setattr("app.platform.security.validate_url_for_ssrf", AsyncMock())
        monkeypatch.setattr(
            "app.platform.extensions.get_processing_port", lambda: _FakeProcessingPort()
        )
        monkeypatch.setattr(
            "app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:"
        )
        monkeypatch.setattr(
            tasks_vector, "_run_service_import_with_wfs_fallback", _fallback
        )

        with pytest.raises(creds.CredentialExpiredError):
            await tasks_vector.ingest_service.func(
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                source_url=_SERVICE_URL,
                source_layer="0",
                user_id=str(admin_id),
                credential_ref=ref,
            )

        # Never reached the origin: a fall-through would have collected a 401
        # and reported a working service as broken.
        assert called["fetch"] is False
        reloaded = await _reload(test_db_session, job.id)
        assert reloaded.status == "failed"
        assert "already used or has expired" in (reloaded.error_message or "")

    async def test_an_unreachable_store_is_an_outage_not_an_expiry(
        self, down_credential_store
    ) -> None:
        """Two answers, and only one of them is about the credential.

        A store that ANSWERS "no such key" is evidence the secret was claimed
        or expired. A store that cannot be reached is evidence of an outage
        and nothing else. Reporting the second as the first sends the reader
        to re-issue a token that was never the problem — the #1277 finding,
        pinned here for the door that inherited the mechanism.
        """
        with pytest.raises(creds.CredentialStoreUnavailable):
            await creds.resolve_worker_credential(None, "a" * 24)

    async def test_the_claimed_secret_is_scrubbed_out_of_the_failure(
        self,
        test_db_session,
        monkeypatch,
        credential_backend,  # noqa: F811
    ) -> None:
        """The exact-value layer, which only a holder of the value can do.

        ``run_ogr2ogr_service`` and ``redact_url_credentials`` already scrub
        by URL SHAPE, which covers a token nobody holds. This task now holds
        one, so an origin that echoes it back in some other shape is covered
        too — and ``error_message`` is a durable column, which is the whole
        point of the lease.
        """
        secret = "tok-" + uuid.uuid4().hex
        ref = await creds.stash_service_credential(secret)

        job, _seen = await self._drive(
            test_db_session,
            monkeypatch,
            credential_ref=ref,
            error_text=f"origin rejected token={secret}",
        )

        reloaded = await _reload(test_db_session, job.id)
        assert reloaded.status == "failed"
        assert secret not in (reloaded.error_message or "")


# ---------------------------------------------------------------------------
# Renewal — the query the run-less import door forced open
# ---------------------------------------------------------------------------


class TestRenewalCoversEveryLeasingDoor:
    """The regression the lease itself would have introduced.

    ``_RENEWABLE_CREDENTIALS_SQL`` inner-joined ``dataset_refresh_runs``,
    which every #1220 dispatch has and which the re-upload commit door writes
    too (``create_pending_run``). The first-import door writes none. Left as
    an inner join, an import's credential would have been renewed zero times
    and expired at the TTL — so a protected import queued behind a long
    ingest would fail ``credential_expired`` where today it simply waits.

    No refresh-path test could have caught that, and no import-path test
    catches a refresh-path regression from widening the join, so both live
    here and both directions are asserted in one pass.
    """

    async def _procrastinate_row(self, session, *, job_id, ref, pj_status="todo"):
        # Procrastinate's insert trigger writes procrastinate_events through
        # unqualified names, so the schema has to be on the search_path for a
        # hand-written INSERT the way it is for the library's own.
        await session.execute(text("SET LOCAL search_path TO catalog, public"))
        await session.execute(
            text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) "
                "VALUES ('ingest', 'ingest_service', "
                "jsonb_build_object('job_id', CAST(:job_id AS text), "
                "'credential_ref', CAST(:ref AS text)), "
                "CAST(:pj_status AS catalog.procrastinate_job_status))"
            ),
            {"job_id": str(job_id), "ref": ref, "pj_status": pj_status},
        )

    async def _import_dispatch(self, session, *, ref, job_status="pending"):
        """A leased first import: an ingest job with NO refresh run."""
        admin_id = await get_user_id(session, "admin")
        job = await _service_import_job(session, created_by=admin_id)
        job.status = job_status
        await self._procrastinate_row(session, job_id=job.id, ref=ref)
        await session.commit()
        return job

    async def _refresh_dispatch(self, session, *, ref, run_status="pending"):
        """A leased refresh: the #1220 shape, ingest job plus a run row."""
        from app.platform.refresh.service import create_pending_run

        admin_id = await get_user_id(session, "admin")
        dataset = await create_dataset(
            session,
            created_by=admin_id,
            name=f"Renewal {uuid.uuid4().hex[:8]}",
            visibility="public",
            source_url=_SERVICE_URL,
        )
        job = IngestJob(
            dataset_id=dataset.id,
            source_url=_SERVICE_URL,
            source_layer="0",
            created_by=admin_id,
            status="pending",
            user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        run = await create_pending_run(
            session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=admin_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        run.status = run_status
        await self._procrastinate_row(session, job_id=job.id, ref=ref)
        await session.commit()
        return job

    async def test_one_pass_renews_both_shapes(
        self,
        client: AsyncClient,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """A run-bearing refresh and a run-less import, renewed together.

        The refresh half is the regression guard on the LEFT JOIN: a
        generalization that quietly stopped matching #1220's own shape would
        be the worse bug, and it would look like a passing import test.
        """
        import_ref = await creds.stash_service_credential("import-waiting")
        refresh_ref = await creds.stash_service_credential("refresh-waiting")
        await self._import_dispatch(test_db_session, ref=import_ref)
        await self._refresh_dispatch(test_db_session, ref=refresh_ref)

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 2

        # Renewal must not consume: both are still claimable afterwards.
        assert await creds.claim_service_credential(import_ref) == "import-waiting"
        assert await creds.claim_service_credential(refresh_ref) == "refresh-waiting"

    async def test_a_terminal_row_of_either_shape_is_not_renewed(
        self,
        client: AsyncClient,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """Both stops still stop. Widening the join must not widen the life.

        The import branch's stop is ``ingest_jobs.status`` because there is no
        run to ask; the refresh branch's is the run's, unchanged. A pass that
        renewed either of these would be durable storage wearing a TTL.
        """
        import_ref = await creds.stash_service_credential("import-is-over")
        refresh_ref = await creds.stash_service_credential("refresh-is-over")
        await self._import_dispatch(
            test_db_session, ref=import_ref, job_status="failed"
        )
        await self._refresh_dispatch(
            test_db_session, ref=refresh_ref, run_status="failed"
        )

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 0

    async def test_a_live_import_job_with_a_terminal_run_defers_to_the_run(
        self,
        client: AsyncClient,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """The fallback is a fallback, not a second opinion.

        When a run row EXISTS it owns the liveness question, exactly as it did
        before the join was widened — the ingest job's own status must not
        resurrect a credential the run has already finished with. The row here
        has both: a terminal run and a job still marked running.
        """
        ref = await creds.stash_service_credential("run-said-no")
        job = await self._refresh_dispatch(
            test_db_session, ref=ref, run_status="succeeded"
        )
        job.status = "running"
        await test_db_session.commit()

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 0
