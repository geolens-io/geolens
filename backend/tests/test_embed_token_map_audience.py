"""An embed token can't open a map to anonymous holders beyond its audience."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, insert, select, update

from app.core.config import settings
from app.modules.auth.models import Role, UserRole
from app.modules.catalog.maps.models import Map
from app.modules.catalog.write_recheck import PUBLIC_VISIBILITY_DENIED
from app.modules.embed_tokens.router import RESTRICTED_MAP_EMBED_REFUSED
from app.modules.embed_tokens.service import validate_embed_token_access
from tests.conftest import _create_test_user
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


@pytest.fixture
def _restrict_public_visibility(monkeypatch):
    import app.core.persistent_config as pc

    class _AlwaysOn:
        async def get(self, _db):
            return True

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _AlwaysOn())


@pytest.fixture
async def editor(client: AsyncClient, admin_auth_header):
    headers, user_id = await _create_test_user(client, admin_auth_header, "editor")
    return {"headers": headers, "id": uuid.UUID(user_id)}


async def _map_with_layer(
    client: AsyncClient, session, headers: dict, owner_id: uuid.UUID, visibility: str
) -> tuple[str, uuid.UUID]:
    dataset = await create_dataset(
        session, created_by=owner_id, visibility=visibility, geometry_type="Point"
    )
    await session.commit()
    created = await client.post(
        "/maps/", json={"name": "Embed audience"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    added = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(dataset.id)}, headers=headers
    )
    assert added.status_code == 201, added.text
    return map_id, dataset.id


async def _set_visibility(session, map_id: str, visibility: str) -> None:
    await session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(visibility=visibility)
    )
    await session.commit()


async def _mint(client: AsyncClient, map_id: str, headers: dict):
    return await client.post(f"/maps/{map_id}/embed-tokens/", json={}, headers=headers)


async def _share_with_new_group(
    client: AsyncClient, admin_auth_header: dict, map_id: str, owner: dict
) -> None:
    group = await client.post(
        "/admin/groups/",
        json={"name": f"embed-audience-{uuid.uuid4().hex[:8]}"},
        headers=admin_auth_header,
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    joined = await client.post(
        f"/admin/groups/{group_id}/members/",
        json={"user_ids": [str(owner["id"])]},
        headers=admin_auth_header,
    )
    assert joined.is_success, joined.text
    shared = await client.put(
        f"/maps/{map_id}/groups/",
        json={"group_ids": [group_id], "confirm": "map_only"},
        headers={**owner["headers"], "X-GeoLens-Map-Visibility": "restricted"},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == "restricted"


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_restricted_public_visibility_refuses_a_non_admin_mint_on_a_private_map(
    client: AsyncClient, test_db_session, editor
):
    map_id, _ = await _map_with_layer(
        client, test_db_session, editor["headers"], editor["id"], "private"
    )

    refused = await _mint(client, map_id, editor["headers"])

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PUBLIC_VISIBILITY_DENIED


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_restricted_public_visibility_still_lets_an_admin_or_a_public_map_mint(
    client: AsyncClient, admin_auth_header, test_db_session, editor
):
    admin_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    admin_map, _ = await _map_with_layer(
        client, test_db_session, admin_auth_header, admin_id, "private"
    )
    assert (await _mint(client, admin_map, admin_auth_header)).status_code == 201

    public_map, _ = await _map_with_layer(
        client, test_db_session, editor["headers"], editor["id"], "public"
    )
    await _set_visibility(test_db_session, public_map, "public")
    assert (await _mint(client, public_map, editor["headers"])).status_code == 201


async def test_a_private_map_mints_while_public_visibility_is_open(
    client: AsyncClient, test_db_session, editor
):
    map_id, _ = await _map_with_layer(
        client, test_db_session, editor["headers"], editor["id"], "private"
    )

    assert (await _mint(client, map_id, editor["headers"])).status_code == 201


async def test_a_map_shared_with_groups_refuses_every_mint(
    client: AsyncClient, admin_auth_header, test_db_session, editor
):
    map_id, _ = await _map_with_layer(
        client, test_db_session, editor["headers"], editor["id"], "private"
    )
    await _share_with_new_group(client, admin_auth_header, map_id, editor)

    for headers in (editor["headers"], admin_auth_header):
        refused = await _mint(client, map_id, headers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == RESTRICTED_MAP_EMBED_REFUSED


async def test_a_token_stops_serving_once_its_map_is_restricted(
    client: AsyncClient, test_db_session, editor
):
    map_id, dataset_id = await _map_with_layer(
        client, test_db_session, editor["headers"], editor["id"], "private"
    )
    minted = await _mint(client, map_id, editor["headers"])
    assert minted.status_code == 201, minted.text
    raw_token = minted.json()["raw_token"]
    assert await validate_embed_token_access(raw_token, dataset_id, test_db_session)

    # Written directly, so no revocation runs and only the use-time check stands.
    await _set_visibility(test_db_session, map_id, "restricted")

    assert not await validate_embed_token_access(raw_token, dataset_id, test_db_session)


async def _mint_while_holding_the_map(
    client: AsyncClient, session, map_id: str, headers: dict, change
):
    """Mint while ``session`` holds the map row and an uncommitted ``change``,
    committed once the mint is waiting on that row."""
    await session.execute(
        select(Map.id)
        .where(Map.id == uuid.UUID(map_id))
        .with_for_update(key_share=True)
    )
    await change()
    mint = asyncio.create_task(_mint(client, map_id, headers))
    await asyncio.sleep(0.8)
    assert not mint.done(), "the mint should be waiting on the map row"
    await session.commit()
    return await mint


async def test_a_mint_waiting_on_a_map_going_restricted_is_refused(
    client: AsyncClient, test_db_session, editor
):
    map_id, _ = await _map_with_layer(
        client, test_db_session, editor["headers"], editor["id"], "private"
    )

    async def restrict() -> None:
        await test_db_session.execute(
            update(Map)
            .where(Map.id == uuid.UUID(map_id))
            .values(visibility="restricted")
        )

    refused = await _mint_while_holding_the_map(
        client, test_db_session, map_id, editor["headers"], restrict
    )

    assert refused.status_code == 409, refused.text


@pytest.mark.usefixtures("_restrict_public_visibility")
async def test_a_mint_waiting_on_its_owners_demotion_is_judged_on_the_new_role(
    client: AsyncClient, admin_auth_header, test_db_session
):
    headers, owner_id = await _create_test_user(client, admin_auth_header, "admin")
    owner_id = uuid.UUID(owner_id)
    map_id, _ = await _map_with_layer(
        client, test_db_session, headers, owner_id, "private"
    )
    editor_role = await test_db_session.scalar(
        select(Role.id).where(Role.name == "editor")
    )
    await test_db_session.commit()

    async def demote() -> None:
        await test_db_session.execute(
            delete(UserRole).where(UserRole.user_id == owner_id)
        )
        await test_db_session.execute(
            insert(UserRole).values(user_id=owner_id, role_id=editor_role)
        )

    refused = await _mint_while_holding_the_map(
        client, test_db_session, map_id, headers, demote
    )

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PUBLIC_VISIBILITY_DENIED
