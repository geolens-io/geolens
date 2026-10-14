"""A queued replacement publishes only while its submitter can still write.

The submitter's standing changes from a second session at a fixed step of the
attempt, or of the commit request, so the order is set without timing.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.auth.models import User, UserRole
from app.modules.catalog.datasets.domain.models import Record
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.processing.ingest.publication import WriteAccessRevoked
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_settle_replacement import (  # noqa: F401 - fixtures
    _Fake,
    _settle,
    _state,
    _waits_on,
    embedding,
    notifications,
    seed,
)

pytestmark = pytest.mark.anyio


async def _commit(statement) -> None:
    async with db_module.async_session() as session:
        await session.execute(statement)
        await session.commit()


@pytest.fixture
async def editor(
    client: AsyncClient, admin_auth_header: dict
) -> tuple[dict, uuid.UUID]:
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    return headers, uuid.UUID(user_id)


@pytest.fixture
async def submitted_by_editor(seed, editor):  # noqa: F811
    """The seeded dataset and its job, owned and started by an editor."""
    _, editor_id = editor
    await _commit(
        update(Record).where(Record.id == seed.record_id).values(created_by=editor_id)
    )
    await _commit(
        update(IngestJob)
        .where(IngestJob.id == seed.job_id)
        .values(created_by=editor_id)
    )
    return seed


async def _transfer_to_admin(seeded) -> None:
    async with db_module.async_session() as session:
        admin_id = await get_user_id(session, "admin")
    await _commit(
        update(Record).where(Record.id == seeded.record_id).values(created_by=admin_id)
    )


async def test_a_replacement_whose_submitter_lost_the_dataset_is_not_published(
    submitted_by_editor,
    notifications,  # noqa: F811
) -> None:
    seeded = submitted_by_editor

    async def transfer() -> None:
        await _transfer_to_admin(seeded)

    fake = _Fake(seeded, during={"install": transfer})
    await _settle(fake)

    state = await _state(seeded)
    assert state["job"] == "failed"
    assert state["run"] == ("failed", "write_access_revoked")
    assert state["catalog"] == (1, "Test Dataset", 1)
    assert state["live"] == "before"
    assert fake.released == (None, True)
    assert notifications.await_args_list == []
    async with db_module.async_session() as session:
        reason = await session.scalar(
            select(IngestJob.error_message).where(IngestJob.id == seeded.job_id)
        )
    assert reason == str(WriteAccessRevoked())


async def test_a_transfer_the_publish_waits_behind_is_seen_once_it_commits(
    submitted_by_editor,
) -> None:
    seeded = submitted_by_editor
    async with db_module.async_session() as transfer:
        admin_id = await get_user_id(transfer, "admin")
        # Holds the record the way an ownership transfer does, until it commits.
        await transfer.execute(
            update(Record)
            .where(Record.id == seeded.record_id)
            .values(created_by=admin_id)
        )
        transfer_pid = await transfer.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(_settle(_Fake(seeded)))
        try:
            assert await _waits_on(transfer_pid, task)
            await transfer.commit()
        finally:
            await transfer.rollback()
        await asyncio.wait_for(task, timeout=20)

    state = await _state(seeded)
    assert state["run"] == ("failed", "write_access_revoked")
    assert state["live"] == "before"


async def test_a_replacement_whose_submitter_was_deactivated_is_not_published(
    submitted_by_editor, editor
) -> None:
    seeded = submitted_by_editor
    _, editor_id = editor

    async def deactivate() -> None:
        await _commit(
            update(User)
            .where(User.id == editor_id)
            .values(status="deactivated", is_active=False)
        )

    await _settle(_Fake(seeded, during={"fetch": deactivate}))

    state = await _state(seeded)
    assert state["run"] == ("failed", "write_access_revoked")
    assert state["live"] == "before"


async def test_a_replacement_whose_admin_submitter_was_demoted_is_not_published(
    seed,  # noqa: F811
    client: AsyncClient,
    admin_auth_header: dict,
) -> None:
    _, admin_id = await create_user(client, admin_auth_header, "admin")
    await _commit(
        update(IngestJob).where(IngestJob.id == seed.job_id).values(created_by=admin_id)
    )

    async def demote() -> None:
        await _commit(delete(UserRole).where(UserRole.user_id == uuid.UUID(admin_id)))

    await _settle(_Fake(seed, during={"install": demote}))

    state = await _state(seed)
    assert state["run"] == ("failed", "write_access_revoked")
    assert state["live"] == "before"


async def test_a_replacement_whose_submitter_still_owns_the_dataset_publishes(
    submitted_by_editor,
) -> None:
    await _settle(_Fake(submitted_by_editor))

    state = await _state(submitted_by_editor)
    assert state["job"] == "complete"
    assert state["live"] == "after"


async def test_the_commit_door_refuses_a_submitter_who_lost_the_dataset(
    client: AsyncClient,
    test_db_session: AsyncSession,
    editor,
) -> None:
    headers, editor_id = editor
    dataset = await create_dataset(test_db_session, created_by=editor_id)
    dataset_id, record_id = dataset.id, dataset.record_id
    job = IngestJob(
        dataset_id=dataset_id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.gpkg",
        file_path="/tmp/fake-reupload.gpkg",
        created_by=editor_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    admin_id = await get_user_id(test_db_session, "admin")

    # Runs after the door's write guard and before it takes the catalog rows.
    async def transfer_then_reserve(session, **kwargs):
        await _commit(
            update(Record).where(Record.id == record_id).values(created_by=admin_id)
        )
        return await create_pending_run(session, **kwargs)

    async def no_dispatch(fn, rollback=None, db=None, job=None):
        pass

    with (
        patch(
            "app.modules.catalog.datasets.api.router_reupload.create_pending_run",
            side_effect=transfer_then_reserve,
        ),
        patch(
            "app.modules.catalog.datasets.api.router_reupload.defer_with_orphan_guard",
            side_effect=no_dispatch,
        ),
    ):
        resp = await client.post(
            f"/datasets/{dataset_id}/reupload/{job_id}/commit",
            json={},
            headers=headers,
        )

    assert resp.status_code == 403, resp.text
    async with db_module.async_session() as session:
        runs = await session.scalar(
            select(DatasetRefreshRun.id).where(
                DatasetRefreshRun.dataset_id == dataset_id
            )
        )
        status = await session.scalar(
            select(IngestJob.status).where(IngestJob.id == job_id)
        )
    assert runs is None
    assert status == "pending"
