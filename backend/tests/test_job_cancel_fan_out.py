"""Cancel racing POST /ingest/commit-fan-out/{job_id} (#1709 review r2 P1).

The fan-out endpoint queues children (each committed and deferred inside
``create_fan_out_jobs``) BEFORE the parent reaches its terminal status, and
its finale used to be a blind ``job.status = "fanned_out"`` attribute write.
``POST /jobs/{id}/cancel`` could therefore terminate a still-pending parent
mid-loop and have that committed ``cancelled`` row silently overwritten
while every child kept importing — a 200 cancel that still created every
requested dataset.

The transitions are now mutually exclusive, same fence discipline as
everywhere else in #1677:

- Fan-out's pending→fanned_out transition is a CAS fenced on the status and
  attempt id it observed when it admitted the request
  (``finalize_fan_out_parent``). Losing it means a cancel landed mid-loop,
  and the loser reconciles: the children it just queued are CAS-cancelled,
  their queue rows best-effort aborted, and their per-layer results
  rewritten to ``failed`` so the caller sees the true outcome.
- Cancel loses cleanly to a committed fan-out: a ``fanned_out`` parent is
  terminal, so the cancel 409s and the children are untouched — each child
  is its own IngestJob, individually cancellable through the same endpoint
  (uniform scope, per the ratified design).
- The all-layers-failed branch no longer writes ``pending`` back to the
  parent at all: that blind write could resurrect a row the cancel endpoint
  had just terminated.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.platform.jobs.models import IngestJob
from app.processing.ingest.service import create_fan_out_jobs
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio


@pytest.fixture
def mock_defer_guard():
    """Replace defer_with_orphan_guard so nothing hits Procrastinate.

    Same seam as tests/test_ingest_fan_out.py: the guard is imported lazily
    inside create_fan_out_jobs, so the source module is patched.
    """

    async def _noop(fn, rollback=None, db=None):
        pass

    with patch(
        "app.platform.jobs.defer_guard.defer_with_orphan_guard",
        side_effect=_noop,
    ):
        yield


async def _make_pending_parent(session, *, layers: list[str]) -> IngestJob:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        source_filename="multi.gpkg",
        file_path="/tmp/fake-multi.gpkg",
        status="pending",
        attempt_id=uuid.uuid4(),
        created_by=admin_id,
        user_metadata={"all_layers": layers, "file_type": "vector"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def _cancelling_create_fan_out(flip_after_call: int = 1):
    """Wrap the real create_fan_out_jobs: after call N, commit the exact
    write the cancel endpoint's CAS performs on the parent — the mid-loop
    interleaving, made deterministic."""
    state = {"calls": 0}

    async def _wrapped(original_job, layer, session):
        result = await create_fan_out_jobs(original_job, layer, session)
        state["calls"] += 1
        if state["calls"] == flip_after_call:
            await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == original_job.id,
                    IngestJob.status == "pending",
                )
                .values(status="cancelled", error_message="Cancelled by user")
            )
            await session.commit()
        return result

    return _wrapped


async def _children_of(session, parent_id) -> list[IngestJob]:
    rows = await session.execute(
        select(IngestJob).where(
            text("user_metadata->>'fan_out_parent_id' = :pid").bindparams(
                pid=str(parent_id)
            )
        )
    )
    return list(rows.scalars())


class TestFanOutLosesToCancel:
    @pytest.mark.usefixtures("mock_defer_guard")
    async def test_lost_final_cas_cancels_the_queued_children(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Cancel lands between the first and second child: the fan-out's
        terminal CAS loses, the parent STAYS cancelled, and both children —
        created before and after the cancel — end cancelled instead of
        importing."""
        job = await _make_pending_parent(test_db_session, layers=["buildings", "roads"])

        with patch(
            "app.processing.ingest.router.create_fan_out_jobs",
            side_effect=_cancelling_create_fan_out(flip_after_call=1),
        ):
            resp = await client.post(
                f"/ingest/commit-fan-out/{job.id}",
                json={
                    "layers": [
                        {"layer_name": "buildings"},
                        {"layer_name": "roads"},
                    ]
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        results = resp.json()["results"]
        assert [r["status"] for r in results] == ["failed", "failed"]
        assert all("Cancelled" in (r["error"] or "") for r in results)

        # The committed cancel was honored, not overwritten.
        await test_db_session.refresh(job)
        assert job.status == "cancelled"

        children = await _children_of(test_db_session, job.id)
        assert len(children) == 2
        assert {c.status for c in children} == {"cancelled"}
        assert {c.error_message for c in children} == {"Cancelled by user"}

    @pytest.mark.usefixtures("mock_defer_guard")
    async def test_uncontested_fan_out_still_lands_terminal(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """No race: the CAS wins and the pre-existing contract holds —
        parent fanned_out, children queued."""
        job = await _make_pending_parent(test_db_session, layers=["buildings"])

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "buildings"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text
        assert resp.json()["results"][0]["status"] == "queued"

        await test_db_session.refresh(job)
        assert job.status == "fanned_out"
        assert job.completed_at is not None

        children = await _children_of(test_db_session, job.id)
        assert len(children) == 1
        assert children[0].status == "pending"

    async def test_all_layers_failed_does_not_resurrect_a_cancelled_parent(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """queued_count == 0 branch: the old code blind-wrote 'pending' back
        to the parent, which would overwrite a cancel that landed mid-loop.
        The branch must leave the parent exactly as the winner wrote it."""
        job = await _make_pending_parent(test_db_session, layers=["buildings"])

        async def _raise(fn, rollback=None, db=None):
            raise RuntimeError("queue down")

        with (
            patch(
                "app.platform.jobs.defer_guard.defer_with_orphan_guard",
                side_effect=_raise,
            ),
            patch(
                "app.processing.ingest.router.create_fan_out_jobs",
                side_effect=_cancelling_create_fan_out(flip_after_call=1),
            ),
        ):
            resp = await client.post(
                f"/ingest/commit-fan-out/{job.id}",
                json={"layers": [{"layer_name": "buildings"}]},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        assert resp.json()["results"][0]["status"] == "failed"

        await test_db_session.refresh(job)
        assert job.status == "cancelled"


class TestCancelLosesToFanOut:
    async def test_cancel_of_fanned_out_parent_is_409_and_children_untouched(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Fan-out committed first: the parent is terminal, cancel loses
        cleanly, and the children keep running — each is its own IngestJob
        the user can cancel individually (uniform scope)."""
        admin_id = await get_user_id(test_db_session, "admin")
        parent = IngestJob(
            source_filename="multi.gpkg",
            file_path="/tmp/fake-multi.gpkg",
            status="fanned_out",
            attempt_id=uuid.uuid4(),
            created_by=admin_id,
            user_metadata={"all_layers": ["a", "b"], "file_type": "vector"},
        )
        test_db_session.add(parent)
        await test_db_session.flush()
        children = [
            IngestJob(
                source_filename="multi.gpkg",
                file_path="/tmp/fake-multi.gpkg",
                status="pending",
                attempt_id=uuid.uuid4(),
                created_by=admin_id,
                user_metadata={
                    "layer_name": name,
                    "fan_out_parent_id": str(parent.id),
                },
            )
            for name in ("a", "b")
        ]
        test_db_session.add_all(children)
        await test_db_session.commit()

        resp = await client.post(f"/jobs/{parent.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "job_already_finished"

        for child in children:
            await test_db_session.refresh(child)
            assert child.status == "pending"

        # And each child remains individually cancellable through the same
        # door — the design's uniform scope.
        first = await client.post(
            f"/jobs/{children[0].id}/cancel", headers=admin_auth_header
        )
        assert first.status_code == 200
        await test_db_session.refresh(children[0])
        assert children[0].status == "cancelled"
