"""An item an ArcGIS migration shares with a group reaches its members only.

`geolens arcgis migrate` imports as an admin, commits a group-only dataset
as restricted (a map as private), shares it with the GeoLens group, then
hands it to its owner. These follow that order through the real routes and
their access guards.

Requirements: the docker database must be running with migrations applied.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.modules.auth.models import User
from tests.factories import create_dataset, create_map_via_api, create_user
from tests.test_dataset_group_grants import _new_group

pytestmark = pytest.mark.anyio

OPT_IN = {"X-GeoLens-Map-Visibility": "restricted"}


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "viewer")
    outsider, _ = await create_user(client, admin_auth_header, "viewer")
    group = await _new_group(client, admin_auth_header, [member_id])
    return {
        "owner": owner,
        "owner_id": owner_id,
        "member": member,
        "outsider": outsider,
        "group": group,
    }


async def _listed(client: AsyncClient, headers: dict, dataset_id: uuid.UUID) -> bool:
    listed = await client.get("/datasets/", params={"limit": 200}, headers=headers)
    assert listed.status_code == 200, listed.text
    return str(dataset_id) in {d["id"] for d in listed.json()["datasets"]}


async def test_a_migrated_group_only_dataset_reaches_its_group_and_no_one_else(
    client: AsyncClient, admin_auth_header: dict, test_db_session, people
):
    admin_id = await test_db_session.scalar(
        select(User.id).where(User.username == settings.geolens_admin_username)
    )
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, visibility="restricted"
    )
    url = f"/datasets/{dataset.id}"
    assert (await client.get(url, headers=people["member"])).status_code == 404

    shared = await client.put(
        f"{url}/groups/",
        json={"group_ids": [people["group"]]},
        headers=admin_auth_header,
    )
    assert shared.status_code == 200, shared.text
    moved = await client.patch(
        url, json={"owner_id": people["owner_id"]}, headers=admin_auth_header
    )
    assert moved.status_code == 200, moved.text

    assert (await client.get(url, headers=people["member"])).status_code == 200
    assert (await client.get(url, headers=people["owner"])).status_code == 200
    assert (await client.get(url, headers=people["outsider"])).status_code == 404
    assert (await client.get(url)).status_code in (401, 404)
    assert await _listed(client, people["member"], dataset.id)
    assert not await _listed(client, people["outsider"], dataset.id)


async def test_a_migrated_group_only_map_reaches_its_group_and_no_one_else(
    client: AsyncClient, admin_auth_header: dict, people
):
    created = await create_map_via_api(client, admin_auth_header)
    url = f"/maps/{created['id']}"
    assert created["visibility"] == "private"

    shared = await client.put(
        f"{url}/groups/",
        json={"group_ids": [people["group"]], "confirm": "map_only"},
        headers={**admin_auth_header, **OPT_IN},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == "restricted"
    moved = await client.patch(
        url,
        json={"owner_id": people["owner_id"]},
        headers={**admin_auth_header, **OPT_IN},
    )
    assert moved.status_code == 200, moved.text

    member = await client.get(url, headers={**people["member"], **OPT_IN})
    assert member.status_code == 200, member.text
    assert member.json()["visibility"] == "restricted"
    assert (await client.get(url, headers=people["owner"])).status_code == 200
    outsider = await client.get(url, headers={**people["outsider"], **OPT_IN})
    assert outsider.status_code == 404
