"""Dataset and map write guards hold at the moment of writing.

A guard runs when the request starts; the row lock comes later. Each test
lets the guard pass, commits a change to the caller's standing from a second
session, and only then lets the write take its lock, so the order is fixed
without timing. The write must be refused with the guard's own 404 or 403.

Requirements: the docker database must be running with migrations applied.
"""

import gc
import uuid
import weakref
from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.authorization import (
    DATASET_WRITE_DENIED,
    check_dataset_write_access,
)
from app.modules.catalog.datasets.api import router as datasets_router
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.features.service import lock_catalog_rows_for_write
from app.modules.catalog.maps import router as maps_router
from app.modules.catalog.maps.models import Map
from app.platform.extensions import DefaultPermissionExtension
from app.modules.catalog.maps.service import (
    check_map_ownership,
    get_map,
    lock_map_for_asset_write,
    lock_map_layers,
)
from tests.factories import create_dataset, create_map_via_api, create_user

pytestmark = pytest.mark.anyio


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, target_id = await create_user(client, admin_auth_header, "editor")
    _, admin_id = await create_user(client, admin_auth_header, "admin")
    return {
        "owner": (owner_headers, uuid.UUID(owner_id)),
        "target": uuid.UUID(target_id),
        "admin": uuid.UUID(admin_id),
    }


@pytest.fixture
async def request_session(client: AsyncClient) -> AsyncIterator[AsyncSession]:
    """The session a request handler would hold, apart from the test's own."""
    async with db_module.async_session() as session:
        yield session


async def _set_dataset_owner(
    session: AsyncSession, dataset_id: uuid.UUID, owner_id: uuid.UUID, **values
) -> None:
    record_id = select(Dataset.record_id).where(Dataset.id == dataset_id)
    await session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(created_by=owner_id, **values)
    )
    await session.commit()


async def _admitted_dataset_writer(
    session: AsyncSession, dataset_id: uuid.UUID, user_id: uuid.UUID
) -> Dataset:
    dataset = await get_dataset(session, dataset_id)
    await check_dataset_write_access(
        session, dataset, dataset_id, await session.get(User, user_id)
    )
    return dataset


async def _refused(write) -> int:
    with pytest.raises(HTTPException) as refused:
        await write
    return refused.value.status_code


async def test_owner_patch_is_refused_when_a_transfer_lands_mid_request(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    dataset_id, record_id = dataset.id, dataset.record_id
    original = datasets_router.check_public_visibility_allowed

    # Runs after the handler's write guard and before it locks the rows.
    async def transfer_then_continue(db, user, visibility, **kwargs):
        await _set_dataset_owner(test_db_session, dataset_id, people["target"])
        return await original(db, user, visibility, **kwargs)

    monkeypatch.setattr(
        datasets_router, "check_public_visibility_allowed", transfer_then_continue
    )
    resp = await client.patch(
        f"/datasets/{dataset_id}", json={"title": "renamed"}, headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    title = await test_db_session.scalar(
        select(Record.title).where(Record.id == record_id)
    )
    assert title != "renamed"


async def test_owner_patch_is_refused_when_the_role_loses_edit_metadata(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    dataset_id, record_id = dataset.id, dataset.record_id
    original = datasets_router.check_public_visibility_allowed
    viewer = select(Role.id).where(Role.name == "viewer").scalar_subquery()

    # Runs after require_permission and the write guard, before the lock.
    async def demote_then_continue(db, user, visibility, **kwargs):
        await test_db_session.execute(
            update(UserRole).where(UserRole.user_id == owner_id).values(role_id=viewer)
        )
        await test_db_session.commit()
        return await original(db, user, visibility, **kwargs)

    monkeypatch.setattr(
        datasets_router, "check_public_visibility_allowed", demote_then_continue
    )
    resp = await client.patch(
        f"/datasets/{dataset_id}", json={"title": "renamed"}, headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Missing permission: edit_metadata"
    title = await test_db_session.scalar(
        select(Record.title).where(Record.id == record_id)
    )
    assert title != "renamed"


async def test_former_owner_gets_404_once_the_dataset_is_private(
    test_db_session: AsyncSession, request_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    dataset = await _admitted_dataset_writer(request_session, created.id, owner_id)

    await _set_dataset_owner(
        test_db_session, created.id, people["target"], visibility="private"
    )

    assert await _refused(lock_catalog_rows_for_write(request_session, dataset)) == 404


async def test_demoted_admin_is_refused_under_the_lock(
    test_db_session: AsyncSession, request_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    dataset = await _admitted_dataset_writer(
        request_session, created.id, people["admin"]
    )

    await test_db_session.execute(
        delete(UserRole).where(UserRole.user_id == people["admin"])
    )
    await test_db_session.commit()

    assert await _refused(lock_catalog_rows_for_write(request_session, dataset)) == 403


async def test_deactivated_owner_is_refused_under_the_lock(
    test_db_session: AsyncSession, request_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    dataset = await _admitted_dataset_writer(request_session, created.id, owner_id)

    await test_db_session.execute(
        update(User)
        .where(User.id == owner_id)
        .values(status="deactivated", is_active=False)
    )
    await test_db_session.commit()

    assert await _refused(lock_catalog_rows_for_write(request_session, dataset)) == 403


async def test_recheck_costs_one_query_per_transaction(
    test_db_session: AsyncSession, request_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    unadmitted = await get_dataset(request_session, created.id)
    statements: list[str] = []

    def count(conn, cursor, statement, *args) -> None:
        statements.append(statement)

    engine = request_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        await lock_catalog_rows_for_write(request_session, unadmitted)
        without_writer = len(statements)
        await request_session.rollback()

        dataset = await _admitted_dataset_writer(request_session, created.id, owner_id)
        statements.clear()
        await lock_catalog_rows_for_write(request_session, dataset)
        first = len(statements)
        statements.clear()
        await lock_catalog_rows_for_write(request_session, dataset)
        again = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert first == without_writer + 1
    assert again == without_writer


async def test_map_save_is_refused_when_a_transfer_lands_mid_request(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, _ = people["owner"]
    map_id = uuid.UUID((await create_map_via_api(client, owner_headers))["id"])
    original = maps_router.check_public_visibility_allowed

    # Runs after the handler's ownership check and before it writes the row.
    async def transfer_then_continue(db, user, visibility, **kwargs):
        await test_db_session.execute(
            update(Map).where(Map.id == map_id).values(created_by=people["target"])
        )
        await test_db_session.commit()
        return await original(db, user, visibility, **kwargs)

    monkeypatch.setattr(
        maps_router, "check_public_visibility_allowed", transfer_then_continue
    )
    resp = await client.put(
        f"/maps/{map_id}", json={"name": "renamed"}, headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert await test_db_session.scalar(select(Map.name).where(Map.id == map_id)) != (
        "renamed"
    )


@pytest.mark.parametrize("lock", [lock_map_layers, lock_map_for_asset_write])
async def test_map_row_locks_refuse_a_former_owner(
    client: AsyncClient,
    test_db_session: AsyncSession,
    request_session: AsyncSession,
    people: dict,
    lock,
) -> None:
    owner_headers, owner_id = people["owner"]
    map_id = uuid.UUID((await create_map_via_api(client, owner_headers))["id"])
    map_obj = await get_map(request_session, map_id)
    await check_map_ownership(
        map_obj, await request_session.get(User, owner_id), request_session
    )

    await test_db_session.execute(
        update(Map).where(Map.id == map_id).values(created_by=people["target"])
    )
    await test_db_session.commit()

    assert await _refused(lock(request_session, map_id)) == 403


async def test_admitted_writers_end_with_their_session(
    test_db_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    async with db_module.async_session() as session:
        dataset = await _admitted_dataset_writer(session, created.id, owner_id)
        await lock_catalog_rows_for_write(session, dataset)
        await session.commit()
        held = weakref.ref(session.sync_session)
    del session, dataset
    gc.collect()

    assert held() is None


async def test_bulk_delete_reports_a_refusal_under_the_lock_per_item(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    dataset_id, title = dataset.id, dataset.record.title
    original = datasets_router.delete_dataset

    async def transfer_then_delete(db, *args, **kwargs):
        await _set_dataset_owner(test_db_session, dataset_id, people["target"])
        return await original(db, *args, **kwargs)

    monkeypatch.setattr(datasets_router, "delete_dataset", transfer_then_delete)
    resp = await client.post(
        "/datasets/bulk-delete/",
        json={"datasets": [{"dataset_id": str(dataset_id), "confirm_title": title}]},
        headers=owner_headers,
    )

    assert resp.status_code == 200, resp.text
    [item] = resp.json()["results"]
    assert item["status"] == "error"
    assert item["detail"] == DATASET_WRITE_DENIED
    assert await test_db_session.scalar(
        select(Dataset.id).where(Dataset.id == dataset_id)
    )


async def test_a_later_transaction_checks_again(
    test_db_session: AsyncSession, request_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    dataset = await _admitted_dataset_writer(request_session, created.id, owner_id)
    await lock_catalog_rows_for_write(request_session, dataset)
    await request_session.commit()

    await _set_dataset_owner(test_db_session, created.id, people["target"])

    assert await _refused(lock_catalog_rows_for_write(request_session, dataset)) == 403


async def test_a_dataset_deleted_before_the_lock_is_not_found(
    test_db_session: AsyncSession, request_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    dataset = await _admitted_dataset_writer(request_session, created.id, owner_id)

    await test_db_session.execute(delete(Record).where(Record.id == dataset.record_id))
    await test_db_session.commit()

    assert await _refused(lock_catalog_rows_for_write(request_session, dataset)) == 404


async def _admitted_map_writer(
    client: AsyncClient, session: AsyncSession, people: dict, user_id: uuid.UUID
) -> uuid.UUID:
    owner_headers, _ = people["owner"]
    map_id = uuid.UUID((await create_map_via_api(client, owner_headers))["id"])
    map_obj = await get_map(session, map_id)
    await check_map_ownership(map_obj, await session.get(User, user_id), session)
    return map_id


async def test_map_lock_refuses_a_demoted_admin(
    client: AsyncClient,
    test_db_session: AsyncSession,
    request_session: AsyncSession,
    people: dict,
) -> None:
    map_id = await _admitted_map_writer(
        client, request_session, people, people["admin"]
    )

    await test_db_session.execute(
        delete(UserRole).where(UserRole.user_id == people["admin"])
    )
    await test_db_session.commit()

    assert await _refused(lock_map_layers(request_session, map_id)) == 403


async def test_map_lock_refuses_a_deactivated_owner(
    client: AsyncClient,
    test_db_session: AsyncSession,
    request_session: AsyncSession,
    people: dict,
) -> None:
    _, owner_id = people["owner"]
    map_id = await _admitted_map_writer(client, request_session, people, owner_id)

    await test_db_session.execute(
        update(User)
        .where(User.id == owner_id)
        .values(status="deactivated", is_active=False)
    )
    await test_db_session.commit()

    assert await _refused(lock_map_layers(request_session, map_id)) == 403


async def test_a_map_deleted_before_the_lock_is_not_found(
    client: AsyncClient,
    test_db_session: AsyncSession,
    request_session: AsyncSession,
    people: dict,
) -> None:
    _, owner_id = people["owner"]
    map_id = await _admitted_map_writer(client, request_session, people, owner_id)

    await test_db_session.execute(delete(Map).where(Map.id == map_id))
    await test_db_session.commit()

    assert await _refused(lock_map_layers(request_session, map_id)) == 404


async def test_a_stand_in_writer_reaches_the_extension_as_a_full_identity(
    test_db_session: AsyncSession,
    request_session: AsyncSession,
    people: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard handed only the caller's id still gives an overlay the contract."""
    from types import SimpleNamespace

    from app.platform import extensions
    from tests.test_manifest_run_admission import _ContractReadingExtension

    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    dataset = await get_dataset(request_session, created.id)
    # The guard is handed a caller object carrying the id alone.
    stand_in = SimpleNamespace(id=owner_id)
    await check_dataset_write_access(
        request_session, dataset, created.id, stand_in, user_roles={"editor"}
    )
    monkeypatch.setitem(
        extensions._extensions, "permission", _ContractReadingExtension()
    )

    await lock_catalog_rows_for_write(request_session, dataset)


class _RolesDecideExtension(DefaultPermissionExtension):
    """Grants from the identity's own roles, ignoring the roles it is handed."""

    async def check_permission(self, db, user, capability, **kwargs):
        kwargs["user_roles"] = {role.name for role in user.roles}
        return await super().check_permission(db, user, capability, **kwargs)


@pytest.mark.parametrize("demoted", [True, False])
@pytest.mark.parametrize("kind", ["dataset", "map"])
async def test_an_overlay_deciding_from_identity_roles_sees_them_as_committed(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    demoted: bool,
) -> None:
    from app.platform import extensions

    owner_headers, owner_id = people["owner"]
    monkeypatch.setitem(extensions._extensions, "permission", _RolesDecideExtension())
    viewer = select(Role.id).where(Role.name == "viewer").scalar_subquery()
    router = datasets_router if kind == "dataset" else maps_router
    original = router.check_public_visibility_allowed

    # Runs after require_permission and the write guard, before the lock.
    async def demote_then_continue(db, user, visibility, **kwargs):
        if demoted:
            await test_db_session.execute(
                update(UserRole)
                .where(UserRole.user_id == owner_id)
                .values(role_id=viewer)
            )
            await test_db_session.commit()
        return await original(db, user, visibility, **kwargs)

    monkeypatch.setattr(router, "check_public_visibility_allowed", demote_then_continue)
    if kind == "dataset":
        dataset = await create_dataset(test_db_session, created_by=owner_id)
        resp = await client.patch(
            f"/datasets/{dataset.id}", json={"title": "renamed"}, headers=owner_headers
        )
    else:
        map_id = (await create_map_via_api(client, owner_headers))["id"]
        resp = await client.put(
            f"/maps/{map_id}", json={"name": "renamed"}, headers=owner_headers
        )

    if demoted:
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Missing permission: edit_metadata"
    else:
        assert resp.status_code == 200, resp.text
