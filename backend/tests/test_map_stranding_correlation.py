"""A restricted map is stranded only by members of its own groups."""

import uuid

import pytest
from httpx import AsyncClient

from tests.factories import create_dataset, create_user
from tests.test_dataset_group_grants import _new_group

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _restricted_map(client: AsyncClient, dataset_id, headers, group_id) -> None:
    created = await client.post(
        "/maps/", json={"name": f"Map {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    layer = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(dataset_id)}, headers=headers
    )
    assert layer.status_code == 201, layer.text
    shared = await client.put(
        f"/maps/{map_id}/groups/",
        json={"group_ids": [group_id]},
        headers={**headers, "X-GeoLens-Map-Visibility": "restricted"},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == "restricted"


async def test_a_member_of_another_restricted_map_does_not_strand_the_owners_map(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, member_id = await create_user(client, admin_auth_header, "viewer")
    narrowed = await create_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="internal"
    )
    unrelated = await create_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="internal"
    )
    await test_db_session.commit()
    owner_only = await _new_group(client, admin_auth_header, [owner_id])
    with_member = await _new_group(client, admin_auth_header, [owner_id, member_id])
    await _restricted_map(client, narrowed.id, owner_headers, owner_only)
    # The member loses the narrowed dataset, but only through a map that
    # doesn't use it.
    await _restricted_map(client, unrelated.id, owner_headers, with_member)

    narrowing = await client.patch(
        f"/datasets/{narrowed.id}",
        json={"visibility": "private"},
        headers=owner_headers,
    )

    assert narrowing.status_code == 200, narrowing.text
