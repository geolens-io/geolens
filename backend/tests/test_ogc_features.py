"""Tests for per-dataset OGC API Features endpoints.

Verifies:
  - GET /collections lists per-dataset feature collections alongside the "datasets" catalog
  - GET /collections/{dataset_id} returns OGC collection metadata
  - GET /collections/{dataset_id}/items returns GeoJSON features with pagination
  - GET /collections/{dataset_id}/items/{featureId} returns a single feature
  - Visibility enforcement (private datasets hidden from unauthenticated users)
  - f parameter validation
  - Content-Type and Content-Crs headers
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.auth.models import User
from app.datasets.models import Dataset, Record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_test_table_and_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str | None = None,
    visibility: str = "public",
    geometry_type: str = "POINT",
    with_features: int = 0,
) -> Dataset:
    """Create a PostGIS data table and register it as a dataset.

    If with_features > 0, inserts that many Point features.
    """
    if table_name is None:
        table_name = f"test_ogc_{uuid.uuid4().hex[:8]}"

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"geom geometry(Point, 4326), "
            f"geom_4326 geometry(Geometry, 4326), "
            f"name TEXT, "
            f"status TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    # Insert features if requested
    for i in range(with_features):
        lng = -74.0 + (i * 0.01)
        lat = 40.7 + (i * 0.01)
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326, name, status) VALUES ("
                f"ST_SetSRID(ST_MakePoint({lng}, {lat}), 4326), "
                f"ST_SetSRID(ST_MakePoint({lng}, {lat}), 4326), "
                f":name, :status)"
            ).bindparams(
                name=f"Feature {i}", status="active" if i % 2 == 0 else "inactive"
            )
        )

    record = Record(
        title=f"OGC Test Layer {table_name}",
        summary="Test dataset for OGC Features compliance",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=geometry_type,
        feature_count=with_features,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "status", "type": "text"},
        ],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _cleanup_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def public_dataset(client: AsyncClient, test_db_session):
    """Create a public dataset with 5 features for testing."""
    admin_id = await _get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="public",
        with_features=5,
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


@pytest.fixture
async def private_dataset(client: AsyncClient, test_db_session):
    """Create a private dataset for visibility testing."""
    admin_id = await _get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="private",
        with_features=2,
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


# ---------------------------------------------------------------------------
# /collections list includes per-dataset feature collections
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collections_includes_dataset_collections(
    client: AsyncClient, public_dataset: Dataset
):
    """GET /collections includes per-dataset feature collections alongside 'datasets' catalog."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data

    ids = [c["id"] for c in data["collections"]]

    # The catalog collection should still be present
    assert "datasets" in ids

    # The per-dataset feature collection should be listed
    assert str(public_dataset.id) in ids

    # The per-dataset collection should have itemType=feature
    ds_coll = next(c for c in data["collections"] if c["id"] == str(public_dataset.id))
    assert ds_coll["itemType"] == "feature"


# ---------------------------------------------------------------------------
# GET /collections/{dataset_id} - Collection metadata
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_dataset_collection_metadata(
    client: AsyncClient, public_dataset: Dataset
):
    """GET /collections/{dataset_id} returns OGC collection metadata."""
    resp = await client.get(f"/collections/{public_dataset.id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["id"] == str(public_dataset.id)
    assert data["title"] == public_dataset.record.title
    assert data["itemType"] == "feature"
    assert "http://www.opengis.net/def/crs/OGC/1.3/CRS84" in data["crs"]

    # Check links
    rels = {link["rel"] for link in data["links"]}
    assert "self" in rels
    assert "items" in rels
    assert "root" in rels

    # Content-Type should be application/json
    assert "application/json" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_collection_not_found(client: AsyncClient):
    """GET /collections/{nonexistent_uuid} returns 404."""
    fake_id = uuid.uuid4()
    resp = await client.get(f"/collections/{fake_id}")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data


# ---------------------------------------------------------------------------
# GET /collections/{dataset_id}/items - Feature items
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_collection_items(client: AsyncClient, public_dataset: Dataset):
    """GET /collections/{dataset_id}/items returns GeoJSON FeatureCollection."""
    resp = await client.get(f"/collections/{public_dataset.id}/items")
    assert resp.status_code == 200
    data = resp.json()

    assert data["type"] == "FeatureCollection"
    assert "timeStamp" in data
    assert isinstance(data["numberMatched"], int)
    assert isinstance(data["numberReturned"], int)
    assert data["numberMatched"] == 5
    assert data["numberReturned"] == 5

    # Verify features are GeoJSON Feature objects
    for feature in data["features"]:
        assert feature["type"] == "Feature"
        assert "id" in feature
        assert "geometry" in feature
        assert "properties" in feature

    # Verify Content-Type
    assert "application/geo+json" in resp.headers["content-type"]

    # Verify Content-Crs header
    assert "Content-Crs" in resp.headers
    assert "CRS84" in resp.headers["Content-Crs"]


@pytest.mark.anyio
async def test_collection_items_bbox_filter(
    client: AsyncClient, public_dataset: Dataset
):
    """GET /collections/{id}/items?bbox=... filters by bounding box."""
    # Use a tight bbox around the first feature location (-74.0, 40.7)
    resp = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"bbox": "-74.01,40.69,-73.99,40.71"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberReturned"] >= 1
    assert data["numberReturned"] < 5  # Not all features in this small bbox


@pytest.mark.anyio
async def test_collection_items_property_filter(
    client: AsyncClient, public_dataset: Dataset
):
    """Non-OGC query params are treated as property filters."""
    resp = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"status": "active"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Features 0, 2, 4 have status="active" (3 out of 5)
    assert data["numberReturned"] == 3
    for feature in data["features"]:
        assert feature["properties"]["status"] == "active"


@pytest.mark.anyio
async def test_collection_items_pagination(
    client: AsyncClient, public_dataset: Dataset
):
    """Items endpoint supports pagination with limit and offset."""
    # Get first page
    resp1 = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"limit": 2},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["numberReturned"] == 2
    assert data1["numberMatched"] == 5

    # Should have a "next" link
    next_link = next((link for link in data1["links"] if link["rel"] == "next"), None)
    assert next_link is not None, "Missing 'next' pagination link"

    # Get second page
    resp2 = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"limit": 2, "offset": 2},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["numberReturned"] == 2

    # Should have both "next" and "previous" links
    prev_link = next(
        (link for link in data2["links"] if link["rel"] == "previous"), None
    )
    assert prev_link is not None, "Missing 'previous' pagination link"


@pytest.mark.anyio
async def test_collection_items_invalid_bbox(
    client: AsyncClient, public_dataset: Dataset
):
    """Invalid bbox returns 400."""
    resp = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"bbox": "invalid"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data


# ---------------------------------------------------------------------------
# GET /collections/{dataset_id}/items/{featureId} - Single feature
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_single_feature(client: AsyncClient, public_dataset: Dataset):
    """GET /collections/{id}/items/{featureId} returns a single GeoJSON Feature."""
    resp = await client.get(f"/collections/{public_dataset.id}/items/1")
    assert resp.status_code == 200
    data = resp.json()

    assert data["type"] == "Feature"
    assert data["id"] == 1
    assert "geometry" in data
    assert "properties" in data

    # Verify Content-Type and Content-Crs
    assert "application/geo+json" in resp.headers["content-type"]
    assert "Content-Crs" in resp.headers


@pytest.mark.anyio
async def test_get_single_feature_not_found(
    client: AsyncClient, public_dataset: Dataset
):
    """GET /collections/{id}/items/99999 returns 404 for non-existent feature."""
    resp = await client.get(f"/collections/{public_dataset.id}/items/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Visibility enforcement
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_private_collection_hidden_for_unauthenticated(
    client: AsyncClient, private_dataset: Dataset
):
    """Private dataset returns 404 for unauthenticated users on all OGC endpoints."""
    # Collection metadata
    resp = await client.get(f"/collections/{private_dataset.id}")
    assert resp.status_code == 404

    # Items
    resp = await client.get(f"/collections/{private_dataset.id}/items")
    assert resp.status_code == 404

    # Single feature
    resp = await client.get(f"/collections/{private_dataset.id}/items/1")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_private_collection_visible_for_admin(
    client: AsyncClient, private_dataset: Dataset, admin_auth_header: dict
):
    """Admin can access private dataset OGC endpoints."""
    resp = await client.get(
        f"/collections/{private_dataset.id}",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"/collections/{private_dataset.id}/items",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# f parameter validation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_f_param_json_accepted(client: AsyncClient, public_dataset: Dataset):
    """f=json is accepted on collection endpoints."""
    resp = await client.get(f"/collections/{public_dataset.id}", params={"f": "json"})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_f_param_xml_returns_400(client: AsyncClient, public_dataset: Dataset):
    """f=xml returns 400 on collection endpoints."""
    resp = await client.get(f"/collections/{public_dataset.id}", params={"f": "xml"})
    assert resp.status_code == 400
    data = resp.json()
    assert "Unsupported format" in data["detail"]


# ---------------------------------------------------------------------------
# OGC conformance: null exclusion, top-level links, self link query params
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_link_objects_omit_null_fields(
    client: AsyncClient, public_dataset: Dataset
):
    """Link objects in /collections/{id} response must not contain null values."""
    resp = await client.get(f"/collections/{public_dataset.id}")
    assert resp.status_code == 200
    data = resp.json()

    for link in data["links"]:
        for key, value in link.items():
            assert value is not None, f"Link field '{key}' is null in {link}"


@pytest.mark.anyio
async def test_collections_has_top_level_links(
    client: AsyncClient, public_dataset: Dataset
):
    """GET /collections includes top-level links with self and root rels."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()

    assert "links" in data
    assert isinstance(data["links"], list)
    assert len(data["links"]) > 0

    rels = {link["rel"] for link in data["links"]}
    assert "self" in rels, f"Missing 'self' rel in top-level links: {rels}"
    assert "root" in rels, f"Missing 'root' rel in top-level links: {rels}"


@pytest.mark.anyio
async def test_items_self_link_includes_query_params(
    client: AsyncClient, public_dataset: Dataset
):
    """Items self link href includes current limit/offset query params."""
    # Test with limit only
    resp = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"limit": 2},
    )
    assert resp.status_code == 200
    data = resp.json()

    self_link = next((link for link in data["links"] if link["rel"] == "self"), None)
    assert self_link is not None, "Missing self link in items response"
    assert "limit=2" in self_link["href"], (
        f"limit missing from self link: {self_link['href']}"
    )
    assert "offset=0" in self_link["href"], (
        f"offset missing from self link: {self_link['href']}"
    )

    # Test with bbox
    resp2 = await client.get(
        f"/collections/{public_dataset.id}/items",
        params={"limit": 2, "bbox": "-75,40,-73,41"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    self_link2 = next((link for link in data2["links"] if link["rel"] == "self"), None)
    assert self_link2 is not None, "Missing self link in items response with bbox"
    assert "-75,40,-73,41" in self_link2["href"], (
        f"bbox missing from self link: {self_link2['href']}"
    )
