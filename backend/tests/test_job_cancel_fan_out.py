"""Cancel racing POST /ingest/commit-fan-out/{job_id} (#1709 review r2 P1, r5 P1).

The fan-out endpoint queues children (each committed and deferred inside
``create_fan_out_jobs``) and its finale used to be a blind
``job.status = "fanned_out"`` write — a cancel that terminated a
still-pending parent mid-loop was silently overwritten while every child
kept importing. The round-2 fix fenced the transition and had the loser
cancel its children, but that reconciliation ran only AFTER the dispatch
loop and rightly refused to touch terminal rows — so a cancel committing
mid-loop still let an already-deferred fast child claim and COMPLETE
first, and a 200 cancel created that child's dataset anyway.

Round 5 makes the parent transition the MUTEX for the whole dispatch:
``claim_fan_out_parent`` CASes ``pending -> fanned_out`` (fenced on the
attempt id the endpoint observed) and COMMITS before the first child
exists. Exactly two serializations remain:

- Cancel wins: the claim matches zero rows, the endpoint 409s, and ZERO
  children were ever created. The round-2 loser-reconciliation block is
  deleted — the window it compensated (children existing while the parent
  CAS loses) is unreachable under this ordering.
- Fan-out wins: the parent is terminal, every later cancel gets 409
  ``job_already_finished``, and each child is its own individually
  cancellable IngestJob (uniform scope, per the ratified design).

The CR-02 all-failed contract survives as a fenced restore: when every
layer fails to queue, ``restore_fan_out_parent_pending`` CASes
``(fanned_out, attempt) -> pending`` so the user can retry without a
re-upload — it can only undo the flip this request wrote.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.platform.jobs.models import IngestJob
from app.processing.ingest.service import claim_fan_out_parent, create_fan_out_jobs
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


async def _children_of(session, parent_id) -> list[IngestJob]:
    rows = await session.execute(
        select(IngestJob).where(
            text("user_metadata->>'fan_out_parent_id' = :pid").bindparams(
                pid=str(parent_id)
            )
        )
    )
    return list(rows.scalars())


def _cancel_cas_values() -> dict:
    """The exact write the cancel endpoint's CAS performs."""
    return {"status": "cancelled", "error_message": "Cancelled by user"}


class TestCancelWinsBeforeTheFlip:
    async def test_lost_claim_409s_with_zero_children(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Cancel commits between the pending read and the pre-dispatch
        claim: the claim loses, the endpoint 409s, and NO child was ever
        created — the exact promise the round-2 post-loop shape could not
        keep for fast children."""
        from app.core.db import async_session

        job = await _make_pending_parent(test_db_session, layers=["buildings", "roads"])

        async def _cancel_then_claim(session, parent_job, *, parent_attempt_id):
            # The concurrent cancel, made deterministic: committed on its own
            # connection before the claim evaluates.
            async with async_session() as side_session:
                await side_session.execute(
                    update(IngestJob)
                    .where(
                        IngestJob.id == parent_job.id,
                        IngestJob.status == "pending",
                    )
                    .values(**_cancel_cas_values())
                )
                await side_session.commit()
            return await claim_fan_out_parent(
                session, parent_job, parent_attempt_id=parent_attempt_id
            )

        with patch(
            "app.processing.ingest.router.claim_fan_out_parent",
            side_effect=_cancel_then_claim,
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

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "job_conflict"
        assert detail["status"] == "cancelled"

        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert await _children_of(test_db_session, job.id) == []


class TestFanOutWinsThenCancelIsRefused:
    @pytest.mark.usefixtures("mock_defer_guard")
    async def test_no_cancel_window_exists_during_dispatch(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The fast-child scenario, pinned. Mid-loop — after child 1 exists
        and a fast worker has already COMPLETED it — the cancel endpoint's
        exact CAS matches zero rows, because the parent went terminal
        before any child existed. The completed child's dataset is
        legitimate: the cancel was REFUSED, not silently violated."""
        from app.core.db import async_session

        job = await _make_pending_parent(test_db_session, layers=["buildings", "roads"])
        observed: dict = {"cancel_rowcount": None, "fast_child": None}
        calls = {"n": 0}

        async def _fast_child_then_cancel_attempt(original_job, layer, session):
            result = await create_fan_out_jobs(original_job, layer, session)
            calls["n"] += 1
            if calls["n"] == 1 and result.new_job_id is not None:
                async with async_session() as side_session:
                    # The fast worker: child 1 claims and completes.
                    await side_session.execute(
                        update(IngestJob)
                        .where(IngestJob.id == result.new_job_id)
                        .values(status="complete")
                    )
                    # The concurrent cancel's CAS against the parent: the
                    # endpoint would only write on rowcount > 0.
                    cancel_cas = await side_session.execute(
                        update(IngestJob)
                        .where(
                            IngestJob.id == original_job.id,
                            IngestJob.status.in_(("pending", "running")),
                        )
                        .values(**_cancel_cas_values())
                    )
                    await side_session.commit()
                observed["cancel_rowcount"] = cancel_cas.rowcount
                observed["fast_child"] = result.new_job_id
            return result

        with patch(
            "app.processing.ingest.router.create_fan_out_jobs",
            side_effect=_fast_child_then_cancel_attempt,
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
        assert [r["status"] for r in resp.json()["results"]] == ["queued", "queued"]
        # The mid-dispatch cancel found the parent already terminal.
        assert observed["cancel_rowcount"] == 0

        await test_db_session.refresh(job)
        assert job.status == "fanned_out"

        # A real cancel after the fact reports the honest outcome...
        parent_cancel = await client.post(
            f"/jobs/{job.id}/cancel", headers=admin_auth_header
        )
        assert parent_cancel.status_code == 409
        assert parent_cancel.json()["detail"]["code"] == "job_already_finished"

        # ...the fast child keeps its completed dataset, and the slow child
        # remains individually cancellable (uniform scope).
        children = {c.id: c for c in await _children_of(test_db_session, job.id)}
        fast = children.pop(observed["fast_child"])
        assert fast.status == "complete"
        (slow,) = children.values()
        slow_cancel = await client.post(
            f"/jobs/{slow.id}/cancel", headers=admin_auth_header
        )
        assert slow_cancel.status_code == 200
        await test_db_session.refresh(slow)
        assert slow.status == "cancelled"

    @pytest.mark.usefixtures("mock_defer_guard")
    async def test_uncontested_fan_out_still_lands_terminal(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """No race: the pre-existing contract holds — parent fanned_out
        with completed_at, children queued."""
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


class TestAllLayersFailed:
    async def test_all_failed_restores_pending_for_retry(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """CR-02 under the early flip: every defer fails, the fenced
        restore puts the parent back to `pending` so the user can retry
        without a re-upload — and a cancel afterwards works normally."""
        job = await _make_pending_parent(test_db_session, layers=["buildings"])

        async def _raise(fn, rollback=None, db=None):
            raise RuntimeError("queue down")

        with patch(
            "app.platform.jobs.defer_guard.defer_with_orphan_guard",
            side_effect=_raise,
        ):
            resp = await client.post(
                f"/ingest/commit-fan-out/{job.id}",
                json={"layers": [{"layer_name": "buildings"}]},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        assert resp.json()["results"][0]["status"] == "failed"

        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert job.completed_at is None

        cancel = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert cancel.status_code == 200
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
