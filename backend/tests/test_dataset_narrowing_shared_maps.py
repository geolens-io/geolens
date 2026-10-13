"""Narrowing a dataset is blocked only by its owner's shared maps; other maps lose the layer."""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.modules.catalog.maps.models import Map, MapLayer
from app.processing.tiles.router import _evict_dataset_meta
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_embed_tokens import _cleanup_data_table, _create_data_table

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _public_dataset(session, owner_id, table_name: str | None = None):
    return await create_dataset(
        session,
        created_by=uuid.UUID(str(owner_id)),
        name=f"Narrowed {uuid.uuid4().hex[:6]}",
        table_name=table_name,
        visibility="public",
        geometry_type="Point",
    )


async def _public_map_using(session, dataset_id, owner_id) -> Map:
    map_obj = Map(
        name=f"Map {uuid.uuid4().hex[:6]}",
        visibility="public",
        created_by=uuid.UUID(str(owner_id)),
    )
    session.add(map_obj)
    await session.flush()
    session.add(MapLayer(map_id=map_obj.id, dataset_id=dataset_id, sort_order=0))
    await session.commit()
    return map_obj


def _layer_ids(resp) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {layer["dataset_id"] for layer in resp.json()["layers"]}


async def test_another_users_map_loses_the_layer_instead_of_blocking_the_owner(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    other_headers, other_id = await create_user(client, admin_auth_header, "editor")
    table = f"narrow_{uuid.uuid4().hex[:8]}"
    dataset = await _public_dataset(test_db_session, owner_id, table)
    map_obj = await _public_map_using(test_db_session, dataset.id, other_id)
    await _create_data_table(test_db_session, table)
    try:
        share = await client.post(f"/maps/{map_obj.id}/share/", headers=other_headers)
        assert share.status_code in (200, 201), share.text
        embed = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=other_headers
        )
        assert embed.status_code == 201, embed.text
        share_token = share.json()["token"]
        embed_header = {"X-Embed-Token": embed.json()["raw_token"]}
        tile = f"/tiles/data.{table}/0/0/0.pbf"
        assert str(dataset.id) in _layer_ids(
            await client.get(f"/maps/shared/{share_token}", headers=embed_header)
        )
        assert (await client.get(tile, headers=embed_header)).status_code in (200, 204)

        narrow = await client.patch(
            f"/datasets/{dataset.id}",
            json={"visibility": "private"},
            headers=owner_headers,
        )

        assert narrow.status_code == 200, narrow.text
        assert str(dataset.id) not in _layer_ids(
            await client.get(f"/maps/{map_obj.id}")
        )
        assert str(dataset.id) not in _layer_ids(
            await client.get(f"/maps/shared/{share_token}")
        )
        assert str(dataset.id) not in _layer_ids(
            await client.get(f"/maps/shared/{share_token}", headers=embed_header)
        )
        style = await client.get(f"/maps/{map_obj.id}/style.json")
        assert style.status_code == 200, style.text
        assert table not in style.text
        # Tile metadata is cached for up to a minute; age it out.
        _evict_dataset_meta(table)
        assert (await client.get(tile)).status_code in (401, 403, 404)
        assert (await client.get(tile, headers=embed_header)).status_code == 403
        assert str(dataset.id) not in _layer_ids(
            await client.get(f"/maps/{map_obj.id}", headers=other_headers)
        )
    finally:
        await _cleanup_data_table(test_db_session, table)


async def test_the_owners_own_shared_map_still_blocks_and_is_the_only_one_named(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, other_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _public_dataset(test_db_session, owner_id)
    own_map = await _public_map_using(test_db_session, dataset.id, owner_id)
    other_map = await _public_map_using(test_db_session, dataset.id, other_id)

    narrow = await client.patch(
        f"/datasets/{dataset.id}",
        json={"visibility": "private"},
        headers=owner_headers,
    )

    assert narrow.status_code == 422, narrow.text
    detail = narrow.json()["detail"]
    assert own_map.name in detail
    assert other_map.name not in detail


async def test_an_admin_narrowing_follows_the_owners_maps_and_still_sees_the_layer(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    other_headers, other_id = await create_user(client, admin_auth_header, "editor")
    admin_id = await get_user_id(test_db_session, "admin")
    blocked = await _public_dataset(test_db_session, owner_id)
    await _public_map_using(test_db_session, blocked.id, owner_id)
    await _public_map_using(test_db_session, blocked.id, admin_id)
    allowed = await _public_dataset(test_db_session, owner_id)
    other_map = await _public_map_using(test_db_session, allowed.id, other_id)

    refused = await client.patch(
        f"/datasets/{blocked.id}",
        json={"visibility": "private"},
        headers=admin_auth_header,
    )
    narrow = await client.patch(
        f"/datasets/{allowed.id}",
        json={"visibility": "private"},
        headers=admin_auth_header,
    )

    assert refused.status_code == 422, refused.text
    assert narrow.status_code == 200, narrow.text
    assert str(allowed.id) in _layer_ids(
        await client.get(f"/maps/{other_map.id}", headers=admin_auth_header)
    )
    assert str(allowed.id) not in _layer_ids(
        await client.get(f"/maps/{other_map.id}", headers=other_headers)
    )


async def test_an_owner_the_authority_denies_has_no_maps_that_block(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    from app.modules.auth.models import User
    from app.modules.catalog.maps import service_public
    from app.platform.extensions import DefaultPermissionExtension, RecordAudience

    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _public_dataset(test_db_session, owner_id)
    await _public_map_using(test_db_session, dataset.id, owner_id)

    class _DeniesTheOwner(DefaultPermissionExtension):
        async def record_audience(self, query, user_cls, *, grant_cls=None):
            audience = await super().record_audience(
                query, user_cls, grant_cls=grant_cls
            )
            return RecordAudience(
                users=sa.and_(audience.users, User.id != uuid.UUID(owner_id)),
                includes_anonymous=audience.includes_anonymous,
            )

    monkeypatch.setattr(service_public, "get_permission_extension", _DeniesTheOwner)

    narrow = await client.patch(
        f"/datasets/{dataset.id}",
        json={"visibility": "private"},
        headers=owner_headers,
    )

    assert narrow.status_code == 200, narrow.text
