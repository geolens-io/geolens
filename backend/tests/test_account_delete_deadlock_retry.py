"""An account delete that PostgreSQL picks as a deadlock victim against a
dataset delete or the user's own map save retries and lands."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.platform.catalog_locks as catalog_locks
from app.modules.auth.models import ApiKey, User
from app.modules.catalog.collections.models import CollectionDataset
from app.modules.catalog.datasets.domain import service_lifecycle
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps import service_update
from app.modules.catalog.maps.models import Map
from app.platform.jobs.models import IngestJob
from tests.factories import (
    create_collection_via_api,
    create_dataset,
    create_map_via_api,
    create_user,
)
from tests.lock_wait import await_lock_wait_query
from tests.test_map_share_waits_on_dataset_change import _drain

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


@pytest.fixture
async def children():
    tasks: list[asyncio.Task] = []
    yield tasks
    await _drain(tasks)


async def _world(
    client, admin_headers, session, *, owner: str, job: bool, key: bool = False
) -> dict:
    """An editor who added a dataset to a collection and, as asked, ran an
    ingest job on it or holds a key to it and last edited it. The dataset is
    the editor's own or an admin's."""
    headers, user_id = await create_user(client, admin_headers, "editor")
    user_id = uuid.UUID(user_id)
    dataset = await create_dataset(
        session,
        created_by=user_id if owner == "user" else None,
        updated_by=user_id if key else None,
        name=f"Contended {uuid.uuid4().hex[:6]}",
    )
    if job:
        session.add(
            IngestJob(
                dataset_id=dataset.id,
                source_filename="parks.geojson",
                created_by=user_id,
                status="complete",
            )
        )
    if key:
        raw = secrets.token_urlsafe(32)
        session.add(
            ApiKey(
                user_id=user_id,
                key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                fingerprint=f"{raw[:8]}…{raw[-4:]}",
                name="Dataset key",
                key_epoch=(await session.get(User, user_id)).key_epoch,
                scope="dataset_write",
                dataset_id=dataset.id,
            )
        )
    collection = await create_collection_via_api(client, admin_headers)
    session.add(
        CollectionDataset(
            collection_id=uuid.UUID(collection["id"]),
            dataset_id=dataset.id,
            added_by=user_id,
        )
    )
    await session.commit()
    return {
        "user_id": user_id,
        "headers": headers,
        "dataset_id": dataset.id,
        "title": dataset.record.title,
    }


def _pause_after(monkeypatch, module, name: str):
    """Hold a request the first time ``module.name`` returns; resolves the
    returned future with its backend pid and goes on once the event is set."""
    real = getattr(module, name)
    held: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    go = asyncio.Event()

    async def pausing(session, *args, **kwargs):
        result = await real(session, *args, **kwargs)
        if not held.done():
            held.set_result(await session.scalar(sa.text("SELECT pg_backend_pid()")))
            await go.wait()
        return result

    monkeypatch.setattr(module, name, pausing)
    return held, go


async def _account_delete_behind(
    client, admin_headers, user_id, first, held, go, children
):
    """Start ``first``, start the account delete once ``first`` holds its rows,
    and release ``first`` once the account delete waits on it."""
    children.append(asyncio.create_task(first))
    try:
        first_pid = await asyncio.wait_for(held, 30)
        children.append(
            asyncio.create_task(
                client.delete(f"/admin/users/{user_id}", headers=admin_headers)
            )
        )
        await await_lock_wait_query(blocked_by=first_pid)
    finally:
        go.set()
    return await children[0], await children[1]


async def _both_deletes(client, admin_headers, world, held, go, children, deleter):
    dataset_delete = client.request(
        "DELETE",
        f"/datasets/{world['dataset_id']}",
        json={"confirm_title": world["title"]},
        headers=world["headers"] if deleter == "user" else admin_headers,
    )
    return await _account_delete_behind(
        client, admin_headers, world["user_id"], dataset_delete, held, go, children
    )


async def _assert_account_gone_and_dataset_settled(
    session, world, dataset_deleted, account_deleted
):
    """The account delete lands; the dataset delete answers what it answers
    for a lost deadlock today, and the dataset's state matches its answer."""
    assert account_deleted.status_code == 204, account_deleted.text
    assert dataset_deleted.status_code in (204, 409), dataset_deleted.text
    session.expire_all()
    assert await session.get(User, world["user_id"]) is None
    dataset = await session.get(Dataset, world["dataset_id"])
    assert (dataset is None) == (dataset_deleted.status_code == 204)
    assert not await session.scalar(
        sa.select(sa.func.count())
        .select_from(IngestJob)
        .where(IngestJob.created_by == world["user_id"])
    )


@pytest.mark.parametrize(
    ("owner", "deleter"),
    [("other", "admin"), ("user", "admin"), ("user", "user")],
)
async def test_an_account_delete_behind_a_dataset_deletes_job_rows_lands(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    children,
    owner: str,
    deleter: str,
):
    world = await _world(
        client, admin_auth_header, test_db_session, owner=owner, job=True
    )
    held, go = _pause_after(monkeypatch, catalog_locks, "lock_ingest_jobs")

    outcomes = await _both_deletes(
        client, admin_auth_header, world, held, go, children, deleter
    )

    await _assert_account_gone_and_dataset_settled(test_db_session, world, *outcomes)


@pytest.mark.parametrize(
    ("owner", "deleter", "key"),
    [("user", "user", False), ("other", "admin", True)],
)
async def test_an_account_delete_behind_a_dataset_deletes_catalog_rows_lands(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    children,
    owner: str,
    deleter: str,
    key: bool,
):
    world = await _world(
        client, admin_auth_header, test_db_session, owner=owner, job=False, key=key
    )
    held, go = _pause_after(
        monkeypatch, service_lifecycle, "_refuse_stranding_shared_maps"
    )

    outcomes = await _both_deletes(
        client, admin_auth_header, world, held, go, children, deleter
    )

    await _assert_account_gone_and_dataset_settled(test_db_session, world, *outcomes)


async def test_an_account_delete_behind_the_users_own_map_save_lands(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch, children
):
    """The user moves their map's camera, which holds the map row and then
    writes history rows that reference the user."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    map_id = uuid.UUID((await create_map_via_api(client, headers))["id"])
    held, go = _pause_after(monkeypatch, service_update, "lock_map_layers")
    save = client.put(f"/maps/{map_id}", json={"zoom": 7}, headers=headers)

    saved, account_deleted = await _account_delete_behind(
        client, admin_auth_header, user_id, save, held, go, children
    )

    assert account_deleted.status_code == 204, account_deleted.text
    assert saved.status_code in (200, 503), saved.text
    test_db_session.expire_all()
    assert await test_db_session.get(User, uuid.UUID(user_id)) is None
    saved_map = await test_db_session.get(Map, map_id)
    assert saved_map.created_by is None
    assert (saved_map.zoom == 7) == (saved.status_code == 200)
