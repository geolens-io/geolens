"""A real point cloud dataset is refused by every record_type-checked route."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.auth.models import User
from app.platform.extensions.defaults import DefaultProcessingPort
from app.platform.sandbox.validator import build_table_allowlist
from app.processing.ai.service import _execute_search_tool
from tests.factories import create_dataset, create_map_via_api, get_user_id

pytestmark = pytest.mark.anyio

POINT_GEOJSON = {"type": "Point", "coordinates": [-73.9857, 40.7484]}


@pytest.fixture
async def pointcloud(test_db_session):
    """A published point cloud with no feature table, owned by admin."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"LiDAR tile {uuid.uuid4().hex[:8]}",
        table_name=f"pc_{uuid.uuid4().hex[:12]}",
        record_type="pointcloud_dataset",
        source_format="copc",
        source_filename="tile.copc.laz",
        geometry_type=None,
        feature_count=None,
    )
    rec_id = dataset.record_id
    yield dataset
    # A committed point cloud row blocks every later downgrade past 0070 in
    # this worker's database (see tests/alembic_helpers.py).
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
    )
    await test_db_session.commit()


_REFUSALS = [
    ("GET", "/datasets/{id}/features/", None, 404, "has no feature items"),
    ("GET", "/datasets/{id}/features/1", None, 404, "has no feature items"),
    ("GET", "/datasets/{id}/features.geojson", None, 404, "has no feature items"),
    (
        "POST",
        "/datasets/{id}/features/",
        {"geometry": POINT_GEOJSON, "properties": {}},
        404,
        "has no feature table",
    ),
    (
        "PUT",
        "/datasets/{id}/features/1",
        {"geometry": POINT_GEOJSON, "properties": {}},
        404,
        "has no feature table",
    ),
    (
        "PATCH",
        "/datasets/{id}/features/1",
        {"geometry": POINT_GEOJSON, "properties": {}},
        404,
        "has no feature table",
    ),
    ("DELETE", "/datasets/{id}/features/1", None, 404, "has no feature table"),
    ("GET", "/datasets/{id}/columns/name/values/", None, 404, "no tabular columns"),
    ("GET", "/datasets/{id}/rows/", None, 404, "has no data table"),
    (
        "POST",
        "/layers/{id}/columns/",
        {"column": {"name": "note", "type": "text"}},
        404,
        "has no data table",
    ),
    ("GET", "/datasets/{id}/export?format=csv", None, 400, "no tabular feature data"),
    ("GET", "/collections/{id}", None, 404, "not an OGC API Features collection"),
    ("GET", "/collections/{id}/items", None, 404, "has no feature items"),
    ("GET", "/collections/{id}/queryables", None, 404, "has no feature items"),
    ("GET", "/collections/{id}/items/1", None, 404, "has no feature items"),
    ("GET", "/tiles/token/{id}/", None, 404, "has no tiles"),
    ("GET", "/tiles/data.{table}/0/0/0.pbf", None, 404, "has no vector tiles"),
    ("GET", "/datasets/{id}/quicklook", None, 400, "not available for this dataset"),
    ("GET", "/datasets/{id}/download/cog", None, 400, "Not a raster dataset"),
    ("GET", "/datasets/{id}/tiles3d/tileset.json", None, 404, "Not found"),
]


@pytest.mark.parametrize(("method", "path", "body", "status", "detail"), _REFUSALS)
async def test_a_point_cloud_is_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    pointcloud,
    method: str,
    path: str,
    body: dict | None,
    status: int,
    detail: str,
):
    """Each route that needs a feature table, tiles, a raster or a tileset refuses a point cloud."""
    resp = await client.request(
        method,
        path.format(id=pointcloud.id, table=pointcloud.table_name),
        json=body,
        headers=admin_auth_header,
    )

    assert resp.status_code == status, resp.text
    assert detail in resp.json()["detail"]


async def test_a_batch_token_for_a_point_cloud_is_an_error_entry(
    client: AsyncClient, admin_auth_header: dict, pointcloud
):
    """The batch token route answers a point cloud with an error entry."""
    resp = await client.post(
        "/tiles/tokens/",
        json={"dataset_ids": [str(pointcloud.id)]},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["tokens"][str(pointcloud.id)] == {
        "error": "This dataset has no tiles"
    }


async def test_a_point_cloud_is_left_out_of_ogc_collections(
    client: AsyncClient, admin_auth_header: dict, pointcloud
):
    """The OGC collections list has no entry for a point cloud."""
    resp = await client.get("/collections?limit=200", headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    assert str(pointcloud.id) not in {c["id"] for c in resp.json()["collections"]}


async def test_a_point_cloud_cannot_be_added_to_a_map(
    client: AsyncClient, admin_auth_header: dict, pointcloud
):
    """Both layer write paths refuse a point cloud."""
    map_id = (await create_map_via_api(client, admin_auth_header))["id"]
    layer = {"dataset_id": str(pointcloud.id)}

    added = await client.post(
        f"/maps/{map_id}/layers", json=layer, headers=admin_auth_header
    )
    patched = await client.patch(
        f"/maps/{map_id}/layers", json={"added": [layer]}, headers=admin_auth_header
    )

    for resp in (added, patched):
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "This dataset cannot be added to a map"


async def test_the_sql_sandbox_leaves_a_point_cloud_out(test_db_session, pointcloud):
    """A point cloud's table_name names no data.<table>, so the sandbox omits it."""
    admin = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()

    allowlist = await build_table_allowlist(test_db_session, admin, queryable_only=True)

    assert pointcloud.table_name not in allowlist


async def test_ai_search_finds_a_point_cloud_that_add_layer_refuses(
    client: AsyncClient, admin_auth_header: dict, test_db_session, pointcloud
):
    """search_datasets can return the point cloud; add_layer on it still 400s."""
    results = await _execute_search_tool(
        test_db_session,
        SimpleNamespace(id=str(pointcloud.record.created_by)),
        {"admin"},
        {"q": pointcloud.record.title},
        port=DefaultProcessingPort(),
    )
    assert str(pointcloud.id) in {r["id"] for r in results}

    map_id = (await create_map_via_api(client, admin_auth_header))["id"]
    resp = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(pointcloud.id)},
        headers=admin_auth_header,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "This dataset cannot be added to a map"
