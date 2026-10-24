"""Narrowing a dataset is blocked only by its owner's shared maps; other maps lose the layer."""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.processing.tiles.router import _evict_dataset_meta
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_dataset_group_grants import _new_group
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


async def _map_using(session, dataset_id, owner_id, visibility="public") -> Map:
    map_obj = Map(
        name=f"Map {uuid.uuid4().hex[:6]}",
        visibility=visibility,
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
    map_obj = await _map_using(test_db_session, dataset.id, other_id)
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
    own_map = await _map_using(test_db_session, dataset.id, owner_id)
    other_map = await _map_using(test_db_session, dataset.id, other_id)

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
    await _map_using(test_db_session, blocked.id, owner_id)
    await _map_using(test_db_session, blocked.id, admin_id)
    allowed = await _public_dataset(test_db_session, owner_id)
    other_map = await _map_using(test_db_session, allowed.id, other_id)

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
    await _map_using(test_db_session, dataset.id, owner_id)

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


async def test_a_map_named_not_found_still_gets_the_shared_map_refusal(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _public_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id)
    own_map.name = "Roads not found"
    await test_db_session.commit()

    narrow = await client.patch(
        f"/datasets/{dataset.id}",
        json={"visibility": "private"},
        headers=owner_headers,
    )

    assert narrow.status_code == 422, narrow.text
    assert "Roads not found" in narrow.json()["detail"]


async def _status(session, dataset_id) -> str:
    session.expire_all()
    return await session.scalar(
        sa.select(Record.record_status)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )


async def _unpublish(client, dataset_id, headers):
    return await client.patch(
        f"/datasets/{dataset_id}", json={"record_status": "draft"}, headers=headers
    )


async def _restricted_map_using(client, dataset_id, headers, group_id) -> None:
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


async def test_unpublishing_a_dataset_on_the_owners_internal_map_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _public_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id, "internal")

    refused = await _unpublish(client, dataset.id, owner_headers)

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == (
        f"Cannot unpublish: dataset is used in shared maps: {own_map.name}"
    )
    assert await _status(test_db_session, dataset.id) == "published"


async def test_unpublishing_a_dataset_a_restricted_maps_member_reads_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, member_id = await create_user(client, admin_auth_header, "viewer")
    group = await _new_group(client, admin_auth_header, [owner_id, member_id])
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="internal"
    )
    await test_db_session.commit()
    await _restricted_map_using(client, dataset.id, owner_headers, group)

    refused = await _unpublish(client, dataset.id, owner_headers)

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"].startswith("Cannot unpublish:")
    assert await _status(test_db_session, dataset.id) == "published"


@pytest.mark.parametrize(
    "maps", ["none", "private", "another_users", "restricted_to_the_owner_alone"]
)
async def test_unpublishing_without_a_stranded_map_succeeds(
    client: AsyncClient, admin_auth_header: dict, test_db_session, maps
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, other_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _public_dataset(test_db_session, owner_id)
    if maps == "private":
        await _map_using(test_db_session, dataset.id, owner_id, "private")
    elif maps == "another_users":
        await _map_using(test_db_session, dataset.id, other_id, "internal")
    elif maps == "restricted_to_the_owner_alone":
        group = await _new_group(client, admin_auth_header, [owner_id])
        await _restricted_map_using(client, dataset.id, owner_headers, group)

    unpublished = await _unpublish(client, dataset.id, owner_headers)

    assert unpublished.status_code == 200, unpublished.text
    assert await _status(test_db_session, dataset.id) == "draft"


@pytest.mark.parametrize(
    ("path", "target"), [("status", "internal"), ("target-status", "draft")]
)
async def test_the_publication_status_endpoints_refuse_a_stranding_unpublish(
    client: AsyncClient, admin_auth_header: dict, test_db_session, path, target
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _public_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id, "internal")

    refused = await client.patch(
        f"/datasets/{dataset.id}/{path}/",
        json={"status": target},
        headers=owner_headers,
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == (
        f"Cannot unpublish: dataset is used in shared maps: {own_map.name}"
    )
    assert await _status(test_db_session, dataset.id) == "published"


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # Widening alone passes, but the unpublish in the same edit strands.
        ("internal", "public", 422),
        # Unpublishing alone would strand, but nobody but the owner reads it now.
        ("private", "public", 200),
    ],
)
async def test_a_visibility_and_status_edit_is_judged_on_the_combined_result(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    before,
    after,
    expected,
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility=before
    )
    await _map_using(test_db_session, dataset.id, owner_id, "internal")

    edited = await client.patch(
        f"/datasets/{dataset.id}",
        json={"visibility": after, "record_status": "draft"},
        headers=owner_headers,
    )

    assert edited.status_code == expected, edited.text
    stored = "draft" if expected == 200 else "published"
    assert await _status(test_db_session, dataset.id) == stored


async def test_an_authority_that_cannot_answer_still_lets_a_draft_publish(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    from app.modules.catalog.maps import service_public

    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), record_status="draft"
    )
    await _map_using(test_db_session, dataset.id, owner_id, "internal")
    monkeypatch.setattr(
        service_public, "answers_audience_questions", lambda permission: False
    )

    published = await client.patch(
        f"/datasets/{dataset.id}",
        json={"record_status": "published"},
        headers=owner_headers,
    )

    assert published.status_code == 200, published.text
    assert await _status(test_db_session, dataset.id) == "published"
