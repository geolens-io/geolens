"""A group membership change that loses a deadlock to a publish sharing with the group runs once more; a second loss answers 503."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import GroupMember
from app.modules.catalog import group_access
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGroupGrant,
    Record,
)
from app.modules.catalog.group_sharing import lock_share_groups
from app.platform.catalog_locks import lock_catalog_rows
from tests.factories import create_user, get_user_id
from tests.test_admin_groups import _wait_until_blocking
from tests.test_dataset_group_grants import _new_group
from tests.test_tile_signature_revocation_1963 import _make_vector

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.usefixtures("_init_tile_pool_for_tests"),
]

# Bounded only so a backend that never parks fails readably instead of
# hanging; not an assertion about how long anything took.
_BARRIER_POLLS = 3000
_BARRIER_INTERVAL_SECONDS = 0.01


@pytest.fixture
async def shared(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """A dataset shared with an empty group, and a viewer to add to it."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _make_vector(
        test_db_session, created_by=admin_id, visibility="private"
    )
    group_id = await _new_group(client, admin_auth_header, [])
    shared = await client.put(
        f"/datasets/{dataset.id}/groups/",
        json={"group_ids": [group_id]},
        headers=admin_auth_header,
    )
    assert shared.status_code == 200, shared.text
    _, user_id = await create_user(client, admin_auth_header, "viewer")
    table = dataset.table_name
    yield {
        "dataset": dataset,
        "group": uuid.UUID(group_id),
        "user": uuid.UUID(user_id),
    }
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


async def _members(session: AsyncSession, group_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    return list(rows)


async def _await_lock_wait(probe: AsyncSession, pid: int) -> None:
    for _ in range(_BARRIER_POLLS):
        wait_event_type = await probe.scalar(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
            {"pid": pid},
        )
        await probe.rollback()
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(_BARRIER_INTERVAL_SECONDS)
    pytest.fail(f"backend {pid} never waited on a lock")


async def test_a_change_that_loses_a_deadlock_to_a_publish_runs_again(
    client: AsyncClient, admin_auth_header: dict, test_db_session, shared
):
    """The publish takes the dataset then the group; the change takes the
    group then the dataset and closes the cycle, so with the publish's
    deadlock_timeout raised, PostgreSQL always picks the change."""
    dataset: Dataset = shared["dataset"]
    group_id, user_id = shared["group"], shared["user"]
    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)

    async with factory() as publish, factory() as user_holder, factory() as probe:
        # Parks the change after it locks the group and before it writes the
        # dataset: adding a member takes the user's row FOR KEY SHARE.
        await user_holder.execute(
            text("SELECT id FROM catalog.users WHERE id = :id FOR UPDATE"),
            {"id": user_id},
        )
        await publish.execute(text("SET LOCAL deadlock_timeout = '10min'"))
        publish_pid = await publish.scalar(text("SELECT pg_backend_pid()"))
        await lock_catalog_rows(
            publish,
            dataset_cls=Dataset,
            record_cls=Record,
            dataset_id=dataset.id,
            record_id=dataset.record_id,
            lock_timeout=None,
        )

        adding = asyncio.create_task(
            client.post(
                f"/admin/groups/{group_id}/members/",
                json={"user_ids": [str(user_id)]},
                headers=admin_auth_header,
            )
        )
        await _wait_until_blocking(user_holder)

        sharing = asyncio.create_task(
            lock_share_groups(
                publish,
                {group_id},
                select(DatasetGroupGrant.group_id).where(
                    DatasetGroupGrant.dataset_id == dataset.id
                ),
                dataset.tenant_id,
            )
        )
        await _await_lock_wait(probe, publish_pid)

        await user_holder.rollback()
        await sharing
        await publish.commit()
        resp = await adding

    assert resp.status_code == 200, resp.text
    assert resp.json()["member_count"] == 1
    test_db_session.expire_all()
    assert await _members(test_db_session, group_id) == [user_id]


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(("deadlocks", "status", "members"), [(1, 200, 1), (2, 503, 0)])
async def test_one_deadlock_is_retried_and_a_second_answers_503(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    shared,
    monkeypatch,
    deadlocks: int,
    status: int,
    members: int,
):
    real = group_access.bump_publication_versions
    calls = 0

    async def bump(session, dataset_ids):
        nonlocal calls
        calls += 1
        if calls <= deadlocks:
            raise DBAPIError("UPDATE catalog.datasets", {}, _Orig("40P01"))
        await real(session, dataset_ids)

    monkeypatch.setattr(group_access, "bump_publication_versions", bump)

    resp = await client.post(
        f"/admin/groups/{shared['group']}/members/",
        json={"user_ids": [str(shared["user"])]},
        headers=admin_auth_header,
    )

    assert resp.status_code == status, resp.text
    assert calls == 2
    test_db_session.expire_all()
    assert len(await _members(test_db_session, shared["group"])) == members
