"""An embed token serves a dataset only while the token's creator can read it."""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant, Record
from app.modules.catalog.maps.models import Map, MapLayer
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_embed_tokens import _cleanup_data_table, _create_data_table

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


@pytest.fixture
async def data_table(test_db_session):
    table = f"embed_reader_{uuid.uuid4().hex[:8]}"
    await _create_data_table(test_db_session, table)
    yield table
    await _cleanup_data_table(test_db_session, table)


async def _dataset(session, owner_id, table, *, visibility):
    return await create_dataset(
        session,
        created_by=uuid.UUID(str(owner_id)),
        table_name=table,
        visibility=visibility,
        geometry_type="Point",
        feature_count=1,
    )


async def _embed(client, session, headers, map_owner_id, dataset_id) -> tuple[str, str]:
    """A public map holding the dataset; returns its embed token and share token."""
    map_obj = Map(
        name=f"Embed {uuid.uuid4().hex[:6]}",
        visibility="public",
        created_by=uuid.UUID(str(map_owner_id)),
    )
    session.add(map_obj)
    await session.flush()
    session.add(MapLayer(map_id=map_obj.id, dataset_id=dataset_id, sort_order=0))
    await session.commit()
    resp = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    share = await client.post(f"/maps/{map_obj.id}/share/", headers=headers)
    assert share.status_code in (200, 201), share.text
    return resp.json()["raw_token"], share.json()["token"]


async def _shared_layer_ids(client, share_token, raw_token) -> set[str]:
    resp = await client.get(
        f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
    )
    assert resp.status_code == 200, resp.text
    return {layer["dataset_id"] for layer in resp.json()["layers"]}


async def _tile_status(client, table, raw_token) -> int:
    resp = await client.get(
        f"/tiles/data.{table}/0/0/0.pbf", headers={"X-Embed-Token": raw_token}
    )
    return resp.status_code


async def test_a_third_party_embed_stops_when_the_creators_grant_is_revoked(
    client: AsyncClient, admin_auth_header: dict, test_db_session, data_table
):
    admin_id = await get_user_id(test_db_session, "admin")
    creator_headers, creator_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _dataset(
        test_db_session, admin_id, data_table, visibility="restricted"
    )
    role = Role(name=f"embed-grant-{uuid.uuid4().hex[:8]}")
    test_db_session.add(role)
    await test_db_session.flush()
    test_db_session.add(UserRole(user_id=uuid.UUID(creator_id), role_id=role.id))
    test_db_session.add(DatasetGrant(dataset_id=dataset.id, role_id=role.id))
    await test_db_session.commit()
    raw, share = await _embed(
        client, test_db_session, creator_headers, creator_id, dataset.id
    )
    assert await _tile_status(client, data_table, raw) in (200, 204)
    assert str(dataset.id) in await _shared_layer_ids(client, share, raw)

    await test_db_session.execute(
        sa.delete(DatasetGrant).where(DatasetGrant.role_id == role.id)
    )
    await test_db_session.commit()

    assert await _tile_status(client, data_table, raw) == 403
    assert str(dataset.id) not in await _shared_layer_ids(client, share, raw)


async def test_a_third_party_embed_stops_when_the_dataset_is_unpublished(
    client: AsyncClient, admin_auth_header: dict, test_db_session, data_table
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    creator_headers, creator_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _dataset(test_db_session, owner_id, data_table, visibility="public")
    raw, share = await _embed(
        client, test_db_session, creator_headers, creator_id, dataset.id
    )
    assert await _tile_status(client, data_table, raw) in (200, 204)

    await test_db_session.execute(
        sa.update(Record)
        .where(Record.id == dataset.record_id)
        .values(record_status="draft")
    )
    await test_db_session.commit()

    assert await _tile_status(client, data_table, raw) == 403


async def test_an_embed_stops_when_its_creator_is_deactivated(
    client: AsyncClient, admin_auth_header: dict, test_db_session, data_table
):
    creator_headers, creator_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _dataset(
        test_db_session, creator_id, data_table, visibility="private"
    )
    raw, share = await _embed(
        client, test_db_session, creator_headers, creator_id, dataset.id
    )
    assert await _tile_status(client, data_table, raw) in (200, 204)

    await test_db_session.execute(
        sa.update(User)
        .where(User.id == uuid.UUID(creator_id))
        .values(status="suspended", is_active=False)
    )
    await test_db_session.commit()

    assert await _tile_status(client, data_table, raw) == 403


async def test_an_owner_minted_embed_of_a_private_dataset_still_serves(
    client: AsyncClient, admin_auth_header: dict, test_db_session, data_table
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _dataset(
        test_db_session, owner_id, data_table, visibility="private"
    )
    raw, share = await _embed(
        client, test_db_session, owner_headers, owner_id, dataset.id
    )

    assert await _tile_status(client, data_table, raw) in (200, 204)
    resp = await client.get(
        f"/datasets/{dataset.id}/features.geojson",
        headers={"X-Embed-Token": raw},
    )
    assert resp.status_code == 200, resp.text


async def test_an_admin_minted_embed_serves_while_its_creator_is_an_admin(
    client: AsyncClient, admin_auth_header: dict, test_db_session, data_table
):
    admin_headers, admin_id = await create_user(client, admin_auth_header, "admin")
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _dataset(
        test_db_session, owner_id, data_table, visibility="private"
    )
    raw, share = await _embed(
        client, test_db_session, admin_headers, owner_id, dataset.id
    )
    assert await _tile_status(client, data_table, raw) in (200, 204)

    await test_db_session.execute(
        sa.delete(UserRole).where(UserRole.user_id == uuid.UUID(admin_id))
    )
    await test_db_session.commit()

    assert await _tile_status(client, data_table, raw) == 403
