"""Deleting a dataset clears the stored images of the maps that drew it."""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
import app.modules.catalog.datasets.api.router as datasets_router
from app.modules.catalog.maps import service_images
from app.modules.catalog.maps.models import Map, MapLayer
from tests.factories import create_dataset, create_user
from tests.test_dataset_delete_shared_maps import _delete, _vector_dataset
from tests.test_embed_tokens import _cleanup_data_table

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _map_with_images(session, owner_id, *dataset_ids) -> uuid.UUID:
    map_obj = Map(
        name=f"Map {uuid.uuid4().hex[:6]}",
        visibility="public",
        created_by=uuid.UUID(str(owner_id)),
    )
    session.add(map_obj)
    await session.flush()
    map_obj.thumbnail_uri = f"maps/thumbnails/{map_obj.id}-{uuid.uuid4().hex}.jpg"
    map_obj.og_image_uri = f"maps/og-images/{map_obj.id}-{uuid.uuid4().hex}.png"
    for order, dataset_id in enumerate(dataset_ids):
        session.add(
            MapLayer(map_id=map_obj.id, dataset_id=dataset_id, sort_order=order)
        )
    await session.commit()
    return map_obj.id


async def _image_urls(client: AsyncClient, map_id: uuid.UUID) -> tuple:
    """The image URLs an anonymous reader of the map is given."""
    resp = await client.get(f"/maps/{map_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["thumbnail_url"], resp.json()["og_image_url"]


async def _stored_images(map_id: uuid.UUID) -> tuple:
    async with db_module.async_session() as session:
        row = (
            await session.execute(
                sa.select(Map.thumbnail_uri, Map.og_image_uri).where(Map.id == map_id)
            )
        ).one()
    return tuple(row)


async def _maps_around_a_private_dataset(client, admin_auth_header, session):
    """A private dataset on another user's public maps: one beside a public
    dataset, one alone, and a map that never drew it."""
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, author_id = await create_user(client, admin_auth_header, "editor")
    private = await _vector_dataset(session, owner_id, visibility="private")
    public = await create_dataset(
        session,
        created_by=uuid.UUID(str(author_id)),
        name=f"Public {uuid.uuid4().hex[:6]}",
        visibility="public",
    )
    beside = await _map_with_images(session, author_id, public.id, private.id)
    alone = await _map_with_images(session, author_id, private.id)
    untouched = await _map_with_images(session, author_id, public.id)
    return owner_headers, private, beside, alone, untouched


@pytest.mark.parametrize("bulk", [False, True])
async def test_a_deleted_datasets_maps_lose_their_images(
    client: AsyncClient, admin_auth_header: dict, test_db_session, bulk: bool
):
    (
        owner_headers,
        private,
        beside,
        alone,
        untouched,
    ) = await _maps_around_a_private_dataset(client, admin_auth_header, test_db_session)
    kept = await _stored_images(untouched)
    assert await _image_urls(client, beside) == (None, None)
    try:
        if bulk:
            resp = await client.post(
                "/datasets/bulk-delete/",
                json={
                    "datasets": [
                        {
                            "dataset_id": str(private.id),
                            "confirm_title": private.record.title,
                        }
                    ]
                },
                headers=owner_headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["deleted"] == 1, resp.text
        else:
            resp = await _delete(client, private, owner_headers)
            assert resp.status_code == 204, resp.text

        for map_id in (beside, alone):
            assert await _image_urls(client, map_id) == (None, None)
            assert await _stored_images(map_id) == (None, None)
            thumbnail = await client.get(f"/maps/{map_id}/thumbnail/")
            assert thumbnail.status_code == 404, thumbnail.text
        assert await _stored_images(untouched) == kept
    finally:
        await _cleanup_data_table(test_db_session, private.table_name)


async def test_a_map_held_past_the_budget_keeps_its_images_and_the_delete_lands(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """The clear is best effort after the commit: a map held longer than its
    wait keeps its images, the next map is still cleared, and the delete
    answers as usual."""
    monkeypatch.setattr(service_images, "_DATASET_DELETE_IMAGE_BUDGET_S", 0.3)
    owner_headers, private, beside, alone, _ = await _maps_around_a_private_dataset(
        client, admin_auth_header, test_db_session
    )
    held, cleared = sorted((beside, alone))
    held_images = await _stored_images(held)
    try:
        async with db_module.async_session() as holder:
            await holder.execute(
                sa.select(Map.id).where(Map.id == held).with_for_update()
            )
            resp = await _delete(client, private, owner_headers)
            assert holder.in_transaction()
            await holder.rollback()

        assert resp.status_code == 204, resp.text
        assert await _stored_images(held) == held_images
        assert await _stored_images(cleared) == (None, None)
    finally:
        await _cleanup_data_table(test_db_session, private.table_name)


async def test_the_images_are_cleared_before_the_storage_reap_starts(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """The reap awaits object storage, so a slow or cancelled one can't leave
    the images readable."""
    owner_headers, private, beside, alone, _ = await _maps_around_a_private_dataset(
        client, admin_auth_header, test_db_session
    )
    seen_at_reap: list[tuple] = []
    real_reap = datasets_router._reap_after_commit

    async def recording_reap(*deletions):
        seen_at_reap.extend([await _stored_images(beside), await _stored_images(alone)])
        await real_reap(*deletions)

    monkeypatch.setattr(datasets_router, "_reap_after_commit", recording_reap)
    try:
        resp = await _delete(client, private, owner_headers)

        assert resp.status_code == 204, resp.text
        assert seen_at_reap == [(None, None), (None, None)]
    finally:
        await _cleanup_data_table(test_db_session, private.table_name)
