"""A real 3D Tiles dataset hits every record_type-checked route (#878 B8, B25-B31).

`test_record_type_refusals.py` pins the same routes against a monkeypatched
unknown record type, proving the `capabilities()` mechanism. These tests use
the literal `tiles3d_dataset` type on a dataset shaped like a published
tileset, since that is the concrete case the audit asked for.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.factories import create_dataset, create_map_via_api, get_user_id

pytestmark = pytest.mark.anyio

POINT_GEOJSON = {"type": "Point", "coordinates": [-73.9857, 40.7484]}


@pytest.fixture
async def tiles3d_layer(test_db_session):
    """A published tiles3d dataset with no feature table, owned by admin."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Campus tileset {uuid.uuid4().hex[:8]}",
        table_name=f"tiles3d_{uuid.uuid4().hex[:12]}",
        record_type="tiles3d_dataset",
        source_format="3dtiles",
        source_filename="tileset.json",
        geometry_type=None,
        feature_count=None,
    )
    rec_id = dataset.record_id
    yield dataset
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
    )
    await test_db_session.commit()


async def test_tiles3d_column_values_are_404(
    client: AsyncClient, admin_auth_header: dict, tiles3d_layer
):
    """A tileset has no tabular columns to fetch distinct values for (B8)."""
    resp = await client.get(
        f"/datasets/{tiles3d_layer.id}/columns/name/values/",
        headers=admin_auth_header,
    )

    assert resp.status_code == 404, resp.text
    assert "no tabular columns" in resp.json()["detail"]


_FEATURE_ROUTES = [
    ("GET", "/datasets/{id}/features/", None, "has no feature items"),
    ("GET", "/datasets/{id}/features/1", None, "has no feature items"),
    ("GET", "/datasets/{id}/features.geojson", None, "has no feature items"),
    (
        "POST",
        "/datasets/{id}/features/",
        {"geometry": POINT_GEOJSON, "properties": {}},
        "has no feature table",
    ),
    (
        "PUT",
        "/datasets/{id}/features/1",
        {"geometry": POINT_GEOJSON, "properties": {}},
        "has no feature table",
    ),
    (
        "PATCH",
        "/datasets/{id}/features/1",
        {"geometry": POINT_GEOJSON, "properties": {}},
        "has no feature table",
    ),
    ("DELETE", "/datasets/{id}/features/1", None, "has no feature table"),
]


@pytest.mark.parametrize(("method", "path", "body", "detail"), _FEATURE_ROUTES)
async def test_tiles3d_feature_routes_are_404(
    client: AsyncClient,
    admin_auth_header: dict,
    tiles3d_layer,
    method: str,
    path: str,
    body: dict | None,
    detail: str,
):
    """Every feature route, read and write, 404s on a tileset (B25-B28)."""
    resp = await client.request(
        method,
        path.format(id=tiles3d_layer.id),
        json=body,
        headers=admin_auth_header,
    )

    assert resp.status_code == 404, resp.text
    assert detail in resp.json()["detail"]


async def test_tiles3d_cannot_be_added_to_a_map(
    client: AsyncClient, admin_auth_header: dict, tiles3d_layer
):
    """Both layer write paths refuse a tileset (B29-B31: shared `_infer_layer_type`)."""
    map_id = (await create_map_via_api(client, admin_auth_header))["id"]
    layer = {"dataset_id": str(tiles3d_layer.id)}

    added = await client.post(
        f"/maps/{map_id}/layers", json=layer, headers=admin_auth_header
    )
    patched = await client.patch(
        f"/maps/{map_id}/layers", json={"added": [layer]}, headers=admin_auth_header
    )

    for resp in (added, patched):
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "This dataset cannot be added to a map"
