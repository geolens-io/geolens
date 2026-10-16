"""A write an admin was let through to make something public, while public
visibility is restricted to admins, re-checks under its lock that they still
are one.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.catalog.datasets.api import router as datasets_router
from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.maps import router as maps_router
from app.modules.catalog.maps.models import Map
from app.modules.catalog.write_recheck import PUBLIC_VISIBILITY_DENIED
from tests.factories import create_dataset, create_map_via_api, create_user
from tests.test_public_visibility_gate import (  # noqa: F401 - fixture
    _restrict_public_visibility,
)
from tests.write_recheck_races import _commit, _move_to_role

pytestmark = pytest.mark.anyio


@pytest.fixture
async def owning_admin(client: AsyncClient, admin_auth_header: dict) -> tuple:
    headers, user_id = await create_user(client, admin_auth_header, "admin")
    return headers, uuid.UUID(user_id)


def _demote_after_the_gate(monkeypatch, router, user_id: uuid.UUID) -> None:
    """Demote ``user_id`` to editor straight after the router's public gate."""
    original = router.check_public_visibility_allowed

    async def gate_then_demote(db, user, visibility, **kwargs):
        roles = await original(db, user, visibility, **kwargs)
        await _commit(_move_to_role(user_id, "editor"))
        return roles

    monkeypatch.setattr(router, "check_public_visibility_allowed", gate_then_demote)


async def _record_visibility(record_id: uuid.UUID) -> str:
    async with db_module.async_session() as session:
        return await session.scalar(
            select(Record.visibility).where(Record.id == record_id)
        )


async def _map_visibility(map_id: uuid.UUID) -> str:
    async with db_module.async_session() as session:
        return await session.scalar(select(Map.visibility).where(Map.id == map_id))


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_a_dataset_made_public_by_a_demoted_admin_is_refused(
    client: AsyncClient,
    test_db_session: AsyncSession,
    owning_admin: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, admin_id = owning_admin
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )
    dataset_id, record_id = dataset.id, dataset.record_id

    _demote_after_the_gate(monkeypatch, datasets_router, admin_id)
    resp = await client.patch(
        f"/datasets/{dataset_id}", json={"visibility": "public"}, headers=headers
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == PUBLIC_VISIBILITY_DENIED
    assert await _record_visibility(record_id) == "private"


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_a_map_made_public_by_a_demoted_admin_is_refused(
    client: AsyncClient,
    owning_admin: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, admin_id = owning_admin
    map_id = uuid.UUID((await create_map_via_api(client, headers))["id"])

    _demote_after_the_gate(monkeypatch, maps_router, admin_id)
    resp = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == PUBLIC_VISIBILITY_DENIED
    assert await _map_visibility(map_id) == "private"


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_an_admin_who_stays_one_makes_the_dataset_public(
    client: AsyncClient, test_db_session: AsyncSession, owning_admin: tuple
) -> None:
    headers, admin_id = owning_admin
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )

    resp = await client.patch(
        f"/datasets/{dataset.id}", json={"visibility": "public"}, headers=headers
    )

    assert resp.status_code == 200, resp.text
    assert await _record_visibility(dataset.record_id) == "public"


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_an_editor_write_that_leaves_visibility_alone_passes(
    client: AsyncClient, test_db_session: AsyncSession, admin_auth_header: dict
) -> None:
    headers, editor_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(test_db_session, created_by=uuid.UUID(editor_id))

    resp = await client.patch(
        f"/datasets/{dataset.id}", json={"title": "Renamed"}, headers=headers
    )

    assert resp.status_code == 200, resp.text


async def test_without_the_restriction_a_demoted_owner_still_publishes(
    client: AsyncClient,
    test_db_session: AsyncSession,
    owning_admin: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, admin_id = owning_admin
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )

    _demote_after_the_gate(monkeypatch, datasets_router, admin_id)
    resp = await client.patch(
        f"/datasets/{dataset.id}", json={"visibility": "public"}, headers=headers
    )

    assert resp.status_code == 200, resp.text
    assert await _record_visibility(dataset.record_id) == "public"


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_the_record_follows_the_latest_gate_check(
    test_db_session: AsyncSession, owning_admin: tuple
) -> None:
    """A manifest apply gates one entry after another in one session; an
    entry that asks for no public visibility is not held to the admin rule."""
    from app.modules.auth.models import User
    from app.modules.catalog.authorization import (
        check_dataset_write_access,
        check_public_visibility_allowed,
    )
    from app.modules.catalog.datasets.domain.service import get_dataset
    from app.modules.catalog.features.service import lock_catalog_rows_for_write

    _, admin_id = owning_admin
    created = await create_dataset(test_db_session, created_by=admin_id)
    async with db_module.async_session() as request:
        admin = await request.get(User, admin_id)
        dataset = await get_dataset(request, created.id)
        await check_dataset_write_access(request, dataset, created.id, admin)
        await check_public_visibility_allowed(request, admin, "public")
        await check_public_visibility_allowed(request, admin, "private")
        await _commit(_move_to_role(admin_id, "editor"))

        await lock_catalog_rows_for_write(request, dataset)
