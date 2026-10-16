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
import app.modules.auth.permissions as permissions
from app.core.identity import IdentityProtocol
from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import Record
from app.platform.extensions import get_processing_port
from app.platform.jobs.models import (
    ADMITTED_CAPABILITY_METADATA_KEY,
    ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY,
    IngestJob,
)
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


async def _record_admission(seeded, capability: str | None) -> None:
    """What the door that queued the seeded job records about its admission."""
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, seeded.job_id)
        metadata = dict(job.user_metadata or {})
        metadata.pop(ADMITTED_CAPABILITY_METADATA_KEY, None)
        if capability is not None:
            metadata[ADMITTED_CAPABILITY_METADATA_KEY] = capability
        job.user_metadata = metadata
        await session.commit()


def _matrix_without(monkeypatch: pytest.MonkeyPatch, capability: str) -> None:
    """Editors lose ``capability`` and keep the rest."""
    effective = permissions.get_effective_permissions

    async def narrowed(db):
        matrix = await effective(db)
        matrix["editor"][capability] = False
        return matrix

    monkeypatch.setattr(permissions, "get_effective_permissions", narrowed)


async def test_a_replacement_whose_submitter_was_moved_to_viewer_is_not_published(
    submitted_by_editor, editor
) -> None:
    seeded = submitted_by_editor
    _, editor_id = editor
    await _record_admission(seeded, "edit_metadata")
    viewer = select(Role.id).where(Role.name == "viewer").scalar_subquery()

    async def demote() -> None:
        await _commit(
            update(UserRole).where(UserRole.user_id == editor_id).values(role_id=viewer)
        )

    await _settle(_Fake(seeded, during={"install": demote}))

    state = await _state(seeded)
    assert state["run"] == ("failed", "write_access_revoked")
    assert state["live"] == "before"


@pytest.mark.parametrize(
    ("recorded", "removed", "published"),
    [
        # A manifest apply admitted under upload, an editor without upload.
        ("upload", "upload", False),
        # A door that required only upload, an editor without edit_metadata.
        ("upload", "edit_metadata", True),
        # A re-upload, refresh or restore, an editor without edit_metadata.
        ("edit_metadata", "edit_metadata", False),
        # A door that required no capability, such as an overlay's sync door.
        (None, "edit_metadata", True),
    ],
)
async def test_a_replacement_rechecks_the_capability_its_door_recorded(
    submitted_by_editor,
    monkeypatch: pytest.MonkeyPatch,
    recorded: str | None,
    removed: str,
    published: bool,
) -> None:
    seeded = submitted_by_editor
    await _record_admission(seeded, recorded)
    _matrix_without(monkeypatch, removed)

    await _settle(_Fake(seeded))

    state = await _state(seeded)
    if published:
        assert state["job"] == "complete"
        assert state["live"] == "after"
    else:
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


async def test_the_write_guard_is_handed_a_complete_identity(
    submitted_by_editor, monkeypatch: pytest.MonkeyPatch
) -> None:
    port_cls = type(get_processing_port())
    original = port_cls.check_dataset_write_access
    identities: list[bool] = []

    async def recording(self, session, dataset, dataset_id, user, **kwargs):
        identities.append(isinstance(user, IdentityProtocol))
        return await original(self, session, dataset, dataset_id, user, **kwargs)

    monkeypatch.setattr(port_cls, "check_dataset_write_access", recording)
    await _settle(_Fake(submitted_by_editor))

    assert identities == [True]
    assert (await _state(submitted_by_editor))["job"] == "complete"


@pytest.mark.parametrize(
    ("restricted", "demoted", "published"),
    [(True, True, False), (True, False, True), (False, True, True)],
)
async def test_a_public_replacement_rechecks_that_its_admin_still_is_one(
    submitted_by_editor,
    editor,
    monkeypatch: pytest.MonkeyPatch,
    restricted: bool,
    demoted: bool,
    published: bool,
) -> None:
    """An admin owner queued a replacement that makes the data public while
    public visibility was restricted to admins."""
    import app.core.persistent_config as persistent_config

    seeded = submitted_by_editor
    _, owner_id = editor
    admin = select(Role.id).where(Role.name == "admin").scalar_subquery()
    await _commit(
        update(UserRole).where(UserRole.user_id == owner_id).values(role_id=admin)
    )
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, seeded.job_id)
        job.user_metadata = {
            **(job.user_metadata or {}),
            ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY: True,
        }
        await session.commit()

    class _Restriction:
        async def get(self, _db):
            return restricted

    monkeypatch.setattr(persistent_config, "RESTRICT_PUBLIC_VISIBILITY", _Restriction())
    editor_role = select(Role.id).where(Role.name == "editor").scalar_subquery()

    async def demote() -> None:
        if demoted:
            await _commit(
                update(UserRole)
                .where(UserRole.user_id == owner_id)
                .values(role_id=editor_role)
            )

    await _settle(_Fake(seeded, during={"install": demote}))

    state = await _state(seeded)
    if published:
        assert state["job"] == "complete"
        assert state["live"] == "after"
    else:
        assert state["run"] == ("failed", "write_access_revoked")
        assert state["live"] == "before"


@pytest.mark.parametrize(("demoted", "published"), [(True, False), (False, True)])
async def test_a_raw_source_replacement_rechecks_that_its_admin_still_is_one(
    submitted_by_editor, editor, demoted: bool, published: bool
) -> None:
    """An admin owner queued a replacement from an admin-only raw seed source."""
    from app.platform.jobs.models import ADMITTED_RAW_SOURCE_METADATA_KEY

    seeded = submitted_by_editor
    _, owner_id = editor
    admin = select(Role.id).where(Role.name == "admin").scalar_subquery()
    await _commit(
        update(UserRole).where(UserRole.user_id == owner_id).values(role_id=admin)
    )
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, seeded.job_id)
        job.user_metadata = {
            **(job.user_metadata or {}),
            ADMITTED_RAW_SOURCE_METADATA_KEY: True,
        }
        await session.commit()
    editor_role = select(Role.id).where(Role.name == "editor").scalar_subquery()

    async def demote() -> None:
        if demoted:
            await _commit(
                update(UserRole)
                .where(UserRole.user_id == owner_id)
                .values(role_id=editor_role)
            )

    await _settle(_Fake(seeded, during={"install": demote}))

    state = await _state(seeded)
    if published:
        assert state["job"] == "complete"
        assert state["live"] == "after"
    else:
        assert state["run"] == ("failed", "write_access_revoked")
        assert state["live"] == "before"
