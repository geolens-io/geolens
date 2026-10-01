"""A restricted dataset granted to more than one of a user's roles.

Each grant is enough on its own, so holding two granted roles must read the
same as holding one.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.auth.models import Role, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _two_new_roles_for(session, user_id: uuid.UUID) -> list[Role]:
    roles = [Role(name=f"grant-pair-{uuid.uuid4().hex[:8]}") for _ in range(2)]
    session.add_all(roles)
    await session.flush()
    session.add_all(UserRole(user_id=user_id, role_id=role.id) for role in roles)
    return roles


async def test_two_granted_roles_read_a_restricted_dataset(
    client: AsyncClient, viewer_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    viewer_id = uuid.UUID(
        (await client.get("/auth/me/", headers=viewer_auth_header)).json()["id"]
    )
    granted = await create_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="restricted",
        record_status="published",
        name="Granted to two roles",
    )
    not_granted = await create_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="restricted",
        record_status="published",
        name="Granted to neither role",
    )
    roles = await _two_new_roles_for(test_db_session, viewer_id)
    test_db_session.add_all(
        DatasetGrant(dataset_id=granted.id, role_id=role.id) for role in roles
    )
    await test_db_session.commit()

    resp = await client.get(f"/datasets/{granted.id}", headers=viewer_auth_header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(granted.id)

    denied = await client.get(f"/datasets/{not_granted.id}", headers=viewer_auth_header)
    assert denied.status_code == 404, denied.text
