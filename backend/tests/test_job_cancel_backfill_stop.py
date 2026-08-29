"""The embedding backfill's cooperative per-batch stop (#1709 review r6).

The cancel endpoint's CAS frees `uq_ingest_jobs_active_embedding_backfill`
immediately (deliberately — a cancelled-but-slot-holding job breaks the
uniform semantics and invites stuck tenants when workers die uncleanly),
and the queue abort after the commit is best-effort. Procrastinate's abort
for an async task is asyncio cancellation and needs no polling once the
request reaches the worker — but a request that never landed (the abort
call or row lookup failed, both log-and-continue by design) used to leave
the old worker embedding the WHOLE remaining catalog at provider rates
while the freed slot admitted a successor run.

The fence: ``backfill_embeddings`` now polls an opaque ``should_continue``
callback once per batch, before that batch's provider call, and
``run_embedding_backfill`` passes a fenced job-row read (status == running
under this attempt). A lost abort now costs at most ONE batch
(_BATCH_SIZE=128 texts, one provider call) of overlap; the worker's final
fenced settle then loses to the committed cancel exactly like every other
worker, and the terminal-audit unique index arbitrates the trail.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.admin.backfill_jobs import run_embedding_backfill
from app.platform.jobs.models import IngestJob
from tests.test_embedding_backfill import (
    _make_query_result,
    _make_record,
    _patch_backfill_gates,
)

pytestmark = pytest.mark.anyio

_FORCE_URL = "/admin/backfill-embeddings/?force=true"


async def test_backfill_stops_at_the_batch_boundary():
    """A False probe answer stops the run BEFORE the next batch's provider
    call — the arithmetic the review asked for: overlap after a lost abort
    is bounded to one batch of spend, not the remaining catalog."""
    from app.processing.embeddings.backfill import backfill_embeddings

    r1 = _make_record(title="Embedded before the stop")
    r2 = _make_record(title="Never reaches the provider")

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_query_result([r1, r2]))

    answers = iter([True, False])

    async def _probe() -> bool:
        return next(answers)

    with ExitStack() as stack:
        _patch_backfill_gates(stack)
        # One record per batch, so the second probe answer gates a second
        # provider call that must never happen.
        stack.enter_context(patch("app.processing.embeddings.backfill._BATCH_SIZE", 1))
        mock_batch = stack.enter_context(
            patch(
                "app.processing.embeddings.backfill.generate_embeddings_batch",
                new_callable=AsyncMock,
            )
        )
        mock_batch.return_value = [[0.1] * 3]
        result = await backfill_embeddings(session, should_continue=_probe)

    assert mock_batch.call_count == 1
    assert result["created"] == 1


async def test_task_probe_is_the_fenced_job_row_read(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
):
    """The wiring: run_embedding_backfill hands backfill_embeddings a probe
    that answers True while THIS attempt's row is `running` and False the
    moment the cancel endpoint's exact CAS commits — after which the
    worker's own fenced settle loses and the committed cancel stands."""
    import app.processing.embeddings.backfill as backfill_module
    from app.core.db import async_session
    from app.modules.admin import router as admin_router
    from app.modules.admin.backfill_jobs import EMBEDDING_BACKFILL_METADATA_KEY

    observed: dict = {}

    async def _fake_backfill(session, *, force=False, should_continue=None):
        assert should_continue is not None
        observed["while_running"] = await should_continue()
        # The concurrent cancel, committed on its own connection — the same
        # write POST /jobs/{id}/cancel performs after winning its CAS.
        async with async_session() as side_session:
            await side_session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == observed["job_uuid"],
                    IngestJob.status.in_(("pending", "running")),
                )
                .values(status="cancelled", error_message="Cancelled by user")
            )
            await side_session.commit()
        observed["after_cancel"] = await should_continue()
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _fake_backfill)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    import uuid as _uuid

    observed["job_uuid"] = _uuid.UUID(job_id)

    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    assert observed["while_running"] is True
    assert observed["after_cancel"] is False

    # The worker's terminal write lost its fence: the committed cancel is
    # the row's final word, not the run's would-be 'complete'.
    job = await test_db_session.get(IngestJob, observed["job_uuid"])
    assert job is not None
    assert job.status == "cancelled"
    assert EMBEDDING_BACKFILL_METADATA_KEY in (job.user_metadata or {})
