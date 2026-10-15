"""An ownership transfer re-checks, under the row lock, that its actor is
still an admin.

Each test lets the handler's guard pass, commits a change to the caller's
standing from a second session straight after it, and lets the request run on.
The write must be refused with the guard's 403 or 404 and leave nothing behind.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.maps import router_ownership
from app.modules.catalog.datasets.api import router as datasets_router
from app.modules.catalog.maps.models import Map
from tests.factories import create_dataset

from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _commit,
    _map_with_layer,
    _move_to_role,
    people,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_init_tile_pool_for_tests")]


async def test_map_transfer_by_a_demoted_admin_who_owns_it_is_refused(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_headers, admin_id = people["admin"]
    map_id, _ = await _map_with_layer(test_db_session, admin_id)

    original = router_ownership.transfer_map_owner

    # Runs after the handler's ownership and admin checks.
    async def demote_then_transfer(*args, **kwargs):
        await _commit(_move_to_role(admin_id, "editor"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(router_ownership, "transfer_map_owner", demote_then_transfer)
    resp = await client.patch(
        f"/maps/{map_id}",
        json={"owner_id": str(people["target"])},
        headers=admin_headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Only an admin may transfer ownership."
    async with db_module.async_session() as session:
        owner = await session.scalar(select(Map.created_by).where(Map.id == map_id))
    assert owner == admin_id


async def test_dataset_transfer_by_a_demoted_admin_who_owns_it_is_refused(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_headers, admin_id = people["admin"]
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    dataset_id, record_id = dataset.id, dataset.record_id
    original = datasets_router.check_public_visibility_allowed

    # Runs after the PATCH's guards and before it locks the rows.
    async def demote_then_continue(db, user, visibility, **kwargs):
        await _commit(_move_to_role(admin_id, "editor"))
        return await original(db, user, visibility, **kwargs)

    monkeypatch.setattr(
        datasets_router, "check_public_visibility_allowed", demote_then_continue
    )
    resp = await client.patch(
        f"/datasets/{dataset_id}",
        json={"owner_id": str(people["target"])},
        headers=admin_headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Only an admin may transfer ownership."
    async with db_module.async_session() as session:
        owner = await session.scalar(
            select(Record.created_by).where(Record.id == record_id)
        )
    assert owner == admin_id
