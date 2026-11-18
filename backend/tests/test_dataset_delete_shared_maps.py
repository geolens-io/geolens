"""Deleting a dataset is refused while its owner's shared maps show it.

Other users' maps keep losing the layer to the cascade, so nobody can block an
owner's delete by adding the dataset to a map of their own.
"""

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
import app.modules.catalog.features.service as features_service
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.embed_tokens.models import EmbedToken
from app.processing.raster.models import VrtGeneration
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_dataset_narrowing_shared_maps import _map_using
from tests.test_embed_tokens import _cleanup_data_table, _create_data_table

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _vector_dataset(session, owner_id, *, visibility="public"):
    table = f"delmap_{uuid.uuid4().hex[:8]}"
    dataset = await create_dataset(
        session,
        created_by=uuid.UUID(str(owner_id)),
        name=f"Deleted {uuid.uuid4().hex[:6]}",
        table_name=table,
        visibility=visibility,
        geometry_type="Point",
    )
    await _create_data_table(session, table)
    return dataset


async def _delete(client: AsyncClient, dataset, headers: dict):
    return await client.request(
        "DELETE",
        f"/datasets/{dataset.id}",
        json={"confirm_title": dataset.record.title},
        headers=headers,
    )


async def _still_there(session, dataset) -> tuple[bool, int, bool]:
    """Whether the dataset row, its map layers and its data table survive."""
    row = await session.scalar(sa.select(Dataset.id).where(Dataset.id == dataset.id))
    layers = await session.scalar(
        sa.select(sa.func.count())
        .select_from(MapLayer)
        .where(MapLayer.dataset_id == dataset.id)
    )
    table = await session.scalar(
        sa.text("SELECT to_regclass(:name) IS NOT NULL"),
        {"name": f"data.{dataset.table_name}"},
    )
    return row is not None, layers, bool(table)


async def test_the_owners_shared_map_refuses_the_delete_and_nothing_goes(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id)
    try:
        resp = await _delete(client, dataset, owner_headers)

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["detail"] == (
            f"Cannot delete: dataset is used in shared maps: {own_map.name}"
        )
        assert body["code"] == "dataset_in_shared_maps"
        assert body["action"] == "delete"
        assert body["shared_maps"] == [{"id": str(own_map.id), "name": own_map.name}]
        assert await _still_there(test_db_session, dataset) == (True, 1, True)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_another_users_shared_map_loses_the_layer_to_the_delete(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, other_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    other_map = await _map_using(test_db_session, dataset.id, other_id)
    try:
        resp = await _delete(client, dataset, owner_headers)

        assert resp.status_code == 204, resp.text
        assert await _still_there(test_db_session, dataset) == (False, 0, False)
        layers = await client.get(f"/maps/{other_map.id}")
        assert layers.status_code == 200, layers.text
        assert layers.json()["layers"] == []
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize(
    ("dataset_visibility", "map_visibility"),
    [("public", "private"), ("private", "public")],
)
async def test_a_map_that_shares_nothing_of_the_dataset_does_not_block(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    dataset_visibility: str,
    map_visibility: str,
):
    """A private map reaches nobody beyond its owner, and a private dataset
    reaches nobody through a public map, so neither is stranded."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(
        test_db_session, owner_id, visibility=dataset_visibility
    )
    await _map_using(test_db_session, dataset.id, owner_id, visibility=map_visibility)
    try:
        resp = await _delete(client, dataset, owner_headers)

        assert resp.status_code == 204, resp.text
        assert await _still_there(test_db_session, dataset) == (False, 0, False)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_an_admin_delete_is_refused_by_the_owners_maps_only(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    # An internal map strands only a signed-in reader who isn't the owner or an admin.
    await create_user(client, admin_auth_header, "viewer")
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _vector_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id, "internal")
    await _map_using(test_db_session, dataset.id, admin_id)
    try:
        resp = await _delete(client, dataset, admin_auth_header)

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["action"] == "delete"
        assert body["shared_maps"] == [{"id": str(own_map.id), "name": own_map.name}]
        assert await _still_there(test_db_session, dataset) == (True, 2, True)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_a_caller_without_write_access_gets_403_not_the_owners_maps(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    other_headers, _ = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id)
    try:
        resp = await _delete(client, dataset, other_headers)

        assert resp.status_code == 403, resp.text
        assert own_map.name not in resp.text
        assert await _still_there(test_db_session, dataset) == (True, 1, True)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize("path", ["/datasets/bulk-delete/", "/datasets/bulk-delete"])
async def test_bulk_delete_refuses_the_stranding_item_and_deletes_the_rest(
    client: AsyncClient, admin_auth_header: dict, test_db_session, path: str
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    blocked = await _vector_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, blocked.id, owner_id)
    free = await _vector_dataset(test_db_session, owner_id)
    try:
        resp = await client.post(
            path,
            json={
                "datasets": [
                    {"dataset_id": str(d.id), "confirm_title": d.record.title}
                    for d in (blocked, free)
                ]
            },
            headers=owner_headers,
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["deleted"], body["errors"]) == (1, 1)
        refused, deleted = body["results"]
        assert refused == {
            "dataset_id": str(blocked.id),
            "status": "error",
            "detail": f"Cannot delete: dataset is used in shared maps: {own_map.name}",
            "code": "dataset_in_shared_maps",
            "shared_maps": [{"id": str(own_map.id), "name": own_map.name}],
        }
        assert deleted["status"] == "deleted"
        assert await _still_there(test_db_session, blocked) == (True, 1, True)
        assert await _still_there(test_db_session, free) == (False, 0, False)
    finally:
        for dataset in (blocked, free):
            await _cleanup_data_table(test_db_session, dataset.table_name)


async def _embedded_private_map(client, session, owner_headers, owner_id):
    """A private dataset on the owner's private map, framed through an embed token."""
    dataset = await _vector_dataset(session, owner_id, visibility="private")
    map_obj = await _map_using(session, dataset.id, owner_id, visibility="private")
    embed = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert embed.status_code == 201, embed.text
    return dataset, map_obj, embed.json()["id"]


async def test_an_active_embed_token_on_the_owners_private_map_refuses_the_delete(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset, map_obj, _ = await _embedded_private_map(
        client, test_db_session, owner_headers, owner_id
    )
    try:
        resp = await _delete(client, dataset, owner_headers)

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["code"] == "dataset_in_shared_maps"
        assert body["action"] == "delete"
        assert body["shared_maps"] == [{"id": str(map_obj.id), "name": map_obj.name}]
        assert await _still_there(test_db_session, dataset) == (True, 1, True)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_a_public_map_with_an_embed_token_is_named_once(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    own_map = await _map_using(test_db_session, dataset.id, owner_id)
    embed = await client.post(
        f"/maps/{own_map.id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert embed.status_code == 201, embed.text
    try:
        resp = await _delete(client, dataset, owner_headers)

        assert resp.status_code == 422, resp.text
        assert resp.json()["shared_maps"] == [
            {"id": str(own_map.id), "name": own_map.name}
        ]
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize("ended", ["revoked", "expired"])
async def test_an_ended_embed_token_does_not_block_the_delete(
    client: AsyncClient, admin_auth_header: dict, test_db_session, ended: str
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset, map_obj, token_id = await _embedded_private_map(
        client, test_db_session, owner_headers, owner_id
    )
    if ended == "revoked":
        revoke = await client.delete(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/", headers=owner_headers
        )
        assert revoke.status_code == 200, revoke.text
    else:
        await test_db_session.execute(
            sa.update(EmbedToken)
            .where(EmbedToken.id == uuid.UUID(token_id))
            .values(expires_at=sa.func.now() - sa.text("interval '1 minute'"))
        )
        await test_db_session.commit()
    try:
        resp = await _delete(client, dataset, owner_headers)

        assert resp.status_code == 204, resp.text
        assert await _still_there(test_db_session, dataset) == (False, 0, False)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_bulk_delete_refuses_the_embedded_item_and_deletes_the_rest(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    blocked, map_obj, _ = await _embedded_private_map(
        client, test_db_session, owner_headers, owner_id
    )
    free = await _vector_dataset(test_db_session, owner_id, visibility="private")
    try:
        resp = await client.post(
            "/datasets/bulk-delete/",
            json={
                "datasets": [
                    {"dataset_id": str(d.id), "confirm_title": d.record.title}
                    for d in (blocked, free)
                ]
            },
            headers=owner_headers,
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["deleted"], body["errors"]) == (1, 1)
        refused, deleted = body["results"]
        assert refused["dataset_id"] == str(blocked.id)
        assert refused["code"] == "dataset_in_shared_maps"
        assert refused["shared_maps"] == [{"id": str(map_obj.id), "name": map_obj.name}]
        assert deleted["status"] == "deleted"
        assert await _still_there(test_db_session, blocked) == (True, 1, True)
        assert await _still_there(test_db_session, free) == (False, 0, False)
    finally:
        for dataset in (blocked, free):
            await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_narrowing_a_dataset_an_embed_token_serves_is_not_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The token keeps serving a private dataset, so only a delete strands it."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    embed = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=owner_headers
    )
    assert embed.status_code == 201, embed.text
    try:
        narrow = await client.patch(
            f"/datasets/{dataset.id}",
            json={"visibility": "private"},
            headers=owner_headers,
        )

        assert narrow.status_code == 200, narrow.text
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


async def test_a_vrt_dependency_answers_before_the_shared_maps(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A COG both a VRT and a shared map use keeps its dependent-VRT 409."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    source = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(str(owner_id)),
        name=f"Source {uuid.uuid4().hex[:6]}",
        record_type="raster_dataset",
    )
    vrt = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(str(owner_id)),
        name=f"Mosaic {uuid.uuid4().hex[:6]}",
        record_type="vrt_dataset",
    )
    await _map_using(test_db_session, source.id, owner_id)
    test_db_session.add(
        VrtGeneration(
            vrt_dataset_id=vrt.id,
            status="pending",
            started_at=datetime.now(timezone.utc),
            source_count=1,
            staged_source_ids=[str(source.id)],
        )
    )
    await test_db_session.commit()

    resp = await _delete(client, source, owner_headers)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["dependent_vrts"] == [
        {"vrt_dataset_id": str(vrt.id), "vrt_dataset_title": vrt.record.title}
    ]

    # With the VRT dependency gone, the shared map is what refuses.
    await test_db_session.execute(
        sa.delete(VrtGeneration).where(VrtGeneration.vrt_dataset_id == vrt.id)
    )
    await test_db_session.commit()
    resp = await _delete(client, source, owner_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["action"] == "delete"


def _hook_the_catalog_lock(monkeypatch, *, before=None, after=None):
    """Run ``before`` just ahead of the delete's catalog row lock and ``after``
    once it is held, each from a second session."""
    real = features_service.lock_catalog_rows_for_write

    async def locking(session, dataset, **kwargs):
        if before is not None:
            await before(dataset.id)
        result = await real(session, dataset, **kwargs)
        if after is not None:
            await after(dataset.id)
        return result

    monkeypatch.setattr(features_service, "lock_catalog_rows_for_write", locking)


async def _empty_public_map(session, owner_id) -> Map:
    map_obj = Map(
        name=f"Map {uuid.uuid4().hex[:6]}",
        visibility="public",
        created_by=uuid.UUID(str(owner_id)),
    )
    session.add(map_obj)
    await session.commit()
    return map_obj


async def _bulk_delete(client: AsyncClient, dataset, headers: dict):
    return await client.post(
        "/datasets/bulk-delete/",
        json={
            "datasets": [
                {"dataset_id": str(dataset.id), "confirm_title": dataset.record.title}
            ]
        },
        headers=headers,
    )


@pytest.mark.parametrize("bulk", [False, True])
async def test_a_layer_added_before_the_delete_locks_is_seen_and_refuses(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch, bulk
):
    """The check runs under the lock, so a layer committed after the request
    started but before the lock still refuses the delete."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    own_map = await _empty_public_map(test_db_session, owner_id)

    async def add_layer(dataset_id):
        async with db_module.async_session() as other:
            other.add(MapLayer(map_id=own_map.id, dataset_id=dataset_id, sort_order=0))
            await other.commit()

    _hook_the_catalog_lock(monkeypatch, before=add_layer)
    try:
        if bulk:
            resp = await _bulk_delete(client, dataset, owner_headers)
            assert resp.status_code == 200, resp.text
            refused = resp.json()["results"][0]
            assert refused["code"] == "dataset_in_shared_maps"
            assert refused["shared_maps"] == [
                {"id": str(own_map.id), "name": own_map.name}
            ]
        else:
            resp = await _delete(client, dataset, owner_headers)
            assert resp.status_code == 422, resp.text
            assert resp.json()["shared_maps"] == [
                {"id": str(own_map.id), "name": own_map.name}
            ]
        assert await _still_there(test_db_session, dataset) == (True, 1, True)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize("bulk", [False, True])
async def test_a_layer_added_while_the_delete_holds_its_lock_waits(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch, bulk
):
    """A layer insert needs the dataset row the delete holds, so it can't land
    between the check and the cascade."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    own_map = await _empty_public_map(test_db_session, owner_id)
    blocked: list[bool] = []

    async def add_layer(dataset_id):
        async with db_module.async_session() as other:
            await other.execute(sa.text("SET LOCAL lock_timeout = '200ms'"))
            other.add(MapLayer(map_id=own_map.id, dataset_id=dataset_id, sort_order=0))
            try:
                await other.commit()
            except sa.exc.DBAPIError as exc:
                blocked.append("lock timeout" in str(exc))
                await other.rollback()

    _hook_the_catalog_lock(monkeypatch, after=add_layer)
    try:
        if bulk:
            resp = await _bulk_delete(client, dataset, owner_headers)
            assert resp.status_code == 200, resp.text
            assert resp.json()["results"][0]["status"] == "deleted"
        else:
            resp = await _delete(client, dataset, owner_headers)
            assert resp.status_code == 204, resp.text
        assert blocked == [True]
        assert await _still_there(test_db_session, dataset) == (False, 0, False)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("change", ["made_public", "published", "transferred"])
async def test_a_record_change_committed_before_the_lock_is_judged(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    change,
    bulk,
):
    """The refusal reads the record as committed once the rows are locked,
    not as the request loaded it."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, map_owner_id = await create_user(client, admin_auth_header, "editor")
    if change == "transferred":
        # The admin deletes a dataset whose ownership moves to the map's owner.
        dataset = await _vector_dataset(test_db_session, owner_id)
        headers, map_owner = admin_auth_header, map_owner_id
        values = {"created_by": uuid.UUID(str(map_owner_id))}
    else:
        dataset = await _vector_dataset(
            test_db_session,
            owner_id,
            visibility="private" if change == "made_public" else "public",
        )
        if change == "published":
            await test_db_session.execute(
                sa.update(Record)
                .where(Record.id == dataset.record_id)
                .values(record_status="draft")
            )
            await test_db_session.commit()
        headers, map_owner = owner_headers, owner_id
        values = (
            {"visibility": "public"}
            if change == "made_public"
            else {"record_status": "published"}
        )
    own_map = await _map_using(test_db_session, dataset.id, map_owner)

    async def commit_change(dataset_id):
        async with db_module.async_session() as other:
            await other.execute(
                sa.update(Record).where(Record.id == dataset.record_id).values(**values)
            )
            await other.commit()

    _hook_the_catalog_lock(monkeypatch, before=commit_change)
    try:
        if bulk:
            resp = await _bulk_delete(client, dataset, headers)
            assert resp.status_code == 200, resp.text
            refused = resp.json()["results"][0]
            assert refused["code"] == "dataset_in_shared_maps"
            assert refused["shared_maps"] == [
                {"id": str(own_map.id), "name": own_map.name}
            ]
        else:
            resp = await _delete(client, dataset, headers)
            assert resp.status_code == 422, resp.text
            assert resp.json()["shared_maps"] == [
                {"id": str(own_map.id), "name": own_map.name}
            ]
        assert await _still_there(test_db_session, dataset) == (True, 1, True)
    finally:
        await _cleanup_data_table(test_db_session, dataset.table_name)
