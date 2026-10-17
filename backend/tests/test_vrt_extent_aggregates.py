"""Extent rollups and map layers show a VRT's extent as the requester sees it.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.geo import rollup_bbox, rollup_bbox_columns
from app.modules.catalog.authorization import get_user_roles, visible_extent_column
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.auth.models import User
from tests.factories import create_collection_via_api
from tests.test_vrt_extent_visibility import (
    FULL,
    HIDDEN,
    READABLE,
    _make_editor,
    _rounded,
    _vrt_with_members,
)


async def _collection_with(client, admin_auth_header, dataset_id) -> str:
    collection = await create_collection_via_api(client, admin_auth_header)
    added = await client.post(
        f"/catalog/collections/{collection['id']}/datasets/",
        json={"dataset_ids": [str(dataset_id)]},
        headers=admin_auth_header,
    )
    assert added.status_code == 200, added.text
    return collection["id"]


async def _collection_extents(client, collection_id, headers) -> dict:
    catalog = await client.get(f"/catalog/collections/{collection_id}", headers=headers)
    assert catalog.status_code == 200, catalog.text
    stac = await client.get(f"/stac/collections/{collection_id}", headers=headers)
    assert stac.status_code == 200, stac.text
    stac_list = await client.get("/stac/collections", headers=headers)
    assert stac_list.status_code == 200, stac_list.text
    listed = [c for c in stac_list.json()["collections"] if c["id"] == collection_id]
    assert len(listed) == 1
    return {
        "catalog": catalog.json()["extent_bbox"],
        "stac": stac.json()["extent"]["spatial"]["bbox"][0],
        "stac_list": listed[0]["extent"]["spatial"]["bbox"][0],
    }


async def test_collection_extents_cover_only_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    collection_id = await _collection_with(client, admin_auth_header, vrt_id)

    viewer = await _collection_extents(client, collection_id, viewer_headers)
    assert {k: _rounded(v) for k, v in viewer.items()} == dict.fromkeys(
        viewer, READABLE
    )
    admin = await _collection_extents(client, collection_id, admin_auth_header)
    assert {k: _rounded(v) for k, v in admin.items()} == dict.fromkeys(admin, FULL)


async def test_visible_extent_column_rolls_up_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The column behind the catalog-wide search extent, rolled up over one VRT."""
    _, viewer_id = await _make_editor(client, admin_auth_header)
    viewer = await test_db_session.get(User, viewer_id)
    roles = await get_user_roles(test_db_session, viewer)
    partly = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    hidden = await _vrt_with_members(test_db_session, [("private", HIDDEN)])

    async def rollup(vrt_id):
        row = (
            await test_db_session.execute(
                select(*rollup_bbox_columns(visible_extent_column(viewer, roles)))
                .select_from(Dataset)
                .join(Record, Dataset.record_id == Record.id)
                .where(Dataset.id == vrt_id)
            )
        ).one()
        return _rounded(rollup_bbox(row))

    assert await rollup(partly) == READABLE
    assert await rollup(hidden) is None


async def test_map_layer_extent_covers_only_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )

    async def layer_extents(headers) -> dict:
        created = await client.post(
            "/maps/",
            json={"name": f"vrt extent {uuid.uuid4().hex[:6]}"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        map_id = created.json()["id"]
        added = await client.post(
            f"/maps/{map_id}/layers/", json={"dataset_id": str(vrt_id)}, headers=headers
        )
        assert added.status_code in (200, 201), added.text
        fetched = await client.get(f"/maps/{map_id}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        updated = await client.put(
            f"/maps/{map_id}", json={"description": "x"}, headers=headers
        )
        assert updated.status_code == 200, updated.text
        return {
            "add_layer": added.json()["dataset_extent_bbox"],
            "get_map": fetched.json()["layers"][0]["dataset_extent_bbox"],
            "update_map": updated.json()["layers"][0]["dataset_extent_bbox"],
        }

    viewer = await layer_extents(viewer_headers)
    assert {k: _rounded(v) for k, v in viewer.items()} == dict.fromkeys(
        viewer, READABLE
    )
    admin = await layer_extents(admin_auth_header)
    assert {k: _rounded(v) for k, v in admin.items()} == dict.fromkeys(admin, FULL)
