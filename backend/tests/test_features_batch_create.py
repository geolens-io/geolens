"""POST /datasets/{id}/features/ with a GeoJSON FeatureCollection body.

The whole collection is inserted in one transaction or not at all.

Requires the Docker test database.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.audit.models import AuditLog
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.features.schemas import MAX_FEATURES_PER_BATCH

from tests.factories import get_user_id
from tests.test_features_crud import _cleanup_table, _create_test_table_and_dataset

POINT_A = {"type": "Point", "coordinates": [-73.9857, 40.7484]}
POINT_B = {"type": "Point", "coordinates": [-118.2437, 34.0522]}
POINT_C = {"type": "Point", "coordinates": [-87.6298, 41.8781]}
POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[-73.99, 40.74], [-73.98, 40.74], [-73.98, 40.75], [-73.99, 40.74]]
    ],
}


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def _feature(geometry: dict, **properties) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


@pytest.fixture
async def point_layer(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, geometry_type="POINT"
    )
    table_name, record_id = dataset.table_name, dataset.record_id
    yield dataset
    await _cleanup_table(test_db_session, table_name)
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await test_db_session.commit()


async def _rows(session, table_name: str) -> list[tuple]:
    result = await session.execute(
        text(
            f"SELECT gid, name, ST_AsText(geom_4326) FROM data.{table_name} ORDER BY gid"
        )
    )
    return [tuple(row) for row in result.all()]


async def _catalog_state(session, dataset: Dataset) -> tuple:
    result = await session.execute(
        select(Dataset.feature_count, Dataset.tile_cache_version).where(
            Dataset.id == dataset.id
        )
    )
    return tuple(result.one())


async def test_collection_inserts_every_feature_in_order(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    _, version_before = await _catalog_state(test_db_session, point_layer)
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json=_collection(
            _feature(POINT_A, name="a"),
            _feature(POINT_B, name="b", status="open"),
            _feature(POINT_C, name="c"),
        ),
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {"type", "features", "table_id", "tile_cache_version"}
    assert body["type"] == "FeatureCollection"
    assert "location" not in resp.headers
    assert resp.headers["content-type"] == "application/geo+json"

    rows = await _rows(test_db_session, point_layer.table_name)
    ids = [feature["id"] for feature in body["features"]]
    assert [row[0] for row in rows] == ids
    assert [row[1] for row in rows] == ["a", "b", "c"]
    assert rows[1][2] == "POINT(-118.2437 34.0522)"
    # Each member is what a single create would have answered with.
    assert body["features"][1] == {
        "type": "Feature",
        "id": ids[1],
        "geometry": POINT_B,
        "properties": {"name": "b", "status": "open"},
        "table_id": body["table_id"],
        "tile_cache_version": body["tile_cache_version"],
    }

    count, version_after = await _catalog_state(test_db_session, point_layer)
    assert count == 3
    # One tile generation for the whole collection, not one per feature.
    assert version_after == (version_before or 1) + 1
    assert body["tile_cache_version"] == version_after

    events = (
        (
            await test_db_session.execute(
                select(AuditLog).where(AuditLog.resource_id == point_layer.id)
            )
        )
        .scalars()
        .all()
    )
    assert [event.action for event in events] == ["feature.bulk_insert"]
    assert events[0].details["gids"] == ids
    assert events[0].details["count"] == 3
    assert events[0].details["property_fields"] == ["name", "status"]


@pytest.mark.parametrize(
    ("bad_feature", "status", "message"),
    [
        (_feature(POLYGON, name="bad"), 400, "mismatch"),
        (_feature(POINT_C, nonexistent="x"), 400, "unknown property"),
    ],
)
async def test_refused_feature_inserts_nothing_and_names_its_index(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    point_layer,
    bad_feature,
    status,
    message,
):
    state_before = await _catalog_state(test_db_session, point_layer)
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json=_collection(
            _feature(POINT_A, name="a"), _feature(POINT_B, name="b"), bad_feature
        ),
        headers=admin_auth_header,
    )
    assert resp.status_code == status, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "feature_refused"
    assert detail["index"] == 2
    assert message in detail["message"].lower()

    assert await _rows(test_db_session, point_layer.table_name) == []
    assert await _catalog_state(test_db_session, point_layer) == state_before


async def test_schema_invalid_feature_is_named_by_position(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json=_collection(_feature(POINT_A), {"type": "Feature", "properties": {}}),
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "body.features.1.geometry: Field required"
    assert await _rows(test_db_session, point_layer.table_name) == []


async def test_collection_over_the_cap_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json=_collection(*[_feature(POINT_A)] * (MAX_FEATURES_PER_BATCH + 1)),
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    assert f"at most {MAX_FEATURES_PER_BATCH} items" in resp.json()["detail"]
    assert await _rows(test_db_session, point_layer.table_name) == []


async def _assert_refused_write(client, headers, session, dataset) -> None:
    resp = await client.post(
        f"/datasets/{dataset.id}/features/",
        json=_collection(_feature(POINT_A, name="a")),
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert await _rows(session, dataset.table_name) == []


async def test_collection_from_a_non_owner_editor_is_refused(
    client: AsyncClient, editor_auth_header: dict, test_db_session, point_layer
):
    await _assert_refused_write(
        client, editor_auth_header, test_db_session, point_layer
    )


async def test_collection_from_a_viewer_is_refused(
    client: AsyncClient, viewer_auth_header: dict, test_db_session, point_layer
):
    await _assert_refused_write(
        client, viewer_auth_header, test_db_session, point_layer
    )


async def test_collection_refuses_an_idempotency_key(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json=_collection(_feature(POINT_A, name="a")),
        headers={**admin_auth_header, "Idempotency-Key": "batch-1"},
    )
    assert resp.status_code == 422, resp.text
    assert "Idempotency-Key" in resp.json()["detail"]
    assert await _rows(test_db_session, point_layer.table_name) == []


async def test_single_feature_body_is_unchanged(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json={"geometry": POINT_A, "properties": {"name": "solo"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    assert resp.headers["content-type"] == "application/geo+json"
    body = resp.json()
    assert set(body) == {
        "type",
        "id",
        "geometry",
        "properties",
        "table_id",
        "tile_cache_version",
    }
    assert body["type"] == "Feature"
    assert body["properties"] == {"name": "solo", "status": None}

    invalid = await client.post(
        f"/datasets/{point_layer.id}/features/",
        json={"properties": {"name": "no geometry"}},
        headers=admin_auth_header,
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "body.geometry: Field required"
