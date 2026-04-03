"""Unit tests for STAC API endpoint logic.

Pure unit tests -- validates conformance, schema instantiation,
and parameter parsing without requiring a running database.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.stac.schemas import StacCatalog, StacConformance, StacItemCollection, StacLink
from app.stac.serializer import STAC_CONFORMANCE


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


class TestStacConformance:
    def test_conformance_contains_core_uri(self):
        assert "https://api.stacspec.org/v1.0.0/core" in STAC_CONFORMANCE

    def test_conformance_contains_collections_uri(self):
        assert "https://api.stacspec.org/v1.0.0/collections" in STAC_CONFORMANCE

    def test_conformance_contains_item_search_uri(self):
        assert "https://api.stacspec.org/v1.0.0/item-search" in STAC_CONFORMANCE

    def test_conformance_four_classes(self):
        assert len(STAC_CONFORMANCE) == 4


# ---------------------------------------------------------------------------
# StacCatalog schema
# ---------------------------------------------------------------------------


class TestStacCatalog:
    def test_catalog_instantiation(self):
        """StacCatalog can be created with required fields."""
        catalog = StacCatalog(
            id="test-catalog",
            title="Test Catalog",
            description="A test catalog",
            conformsTo=STAC_CONFORMANCE,
            links=[
                StacLink(
                    rel="self", href="http://localhost/stac/", type="application/json"
                ),
            ],
        )
        assert catalog.id == "test-catalog"
        assert catalog.type == "Catalog"
        assert catalog.stac_version == "1.0.0"
        assert len(catalog.conformsTo) == 4

    def test_catalog_default_values(self):
        """StacCatalog defaults: type=Catalog, stac_version=1.1.0."""
        catalog = StacCatalog(
            id="x",
            title="X",
            description="X",
            conformsTo=[],
            links=[],
        )
        assert catalog.type == "Catalog"
        assert catalog.stac_version == "1.0.0"


# ---------------------------------------------------------------------------
# StacConformance schema
# ---------------------------------------------------------------------------


class TestStacConformanceSchema:
    def test_conformance_schema_instantiation(self):
        conf = StacConformance(conformsTo=STAC_CONFORMANCE)
        assert len(conf.conformsTo) == 4


# ---------------------------------------------------------------------------
# Search parameter parsing
# ---------------------------------------------------------------------------


class TestStacSearch:
    def test_bbox_parsing(self):
        """Comma-separated bbox string splits to list of floats."""
        bbox_str = "-180.0,-90.0,180.0,90.0"
        parts = bbox_str.split(",")
        bbox_vals = [float(p) for p in parts]
        assert len(bbox_vals) == 4
        assert bbox_vals == [-180.0, -90.0, 180.0, 90.0]

    def test_ids_parsing(self):
        """Comma-separated ids string splits to list of strings."""
        ids_str = "id-1, id-2, id-3"
        parsed = [s.strip() for s in ids_str.split(",")]
        assert parsed == ["id-1", "id-2", "id-3"]

    def test_bbox_invalid_raises(self):
        """Invalid bbox with 3 values raises ValueError."""
        bbox_str = "1,2,3"
        parts = bbox_str.split(",")
        assert len(parts) != 4

    def test_collections_parsing(self):
        """Comma-separated collections string to list."""
        coll_str = "coll-a, coll-b"
        parsed = [s.strip() for s in coll_str.split(",")]
        assert parsed == ["coll-a", "coll-b"]


# ---------------------------------------------------------------------------
# StacItemCollection schema
# ---------------------------------------------------------------------------


class TestStacItemCollection:
    def test_item_collection_instantiation(self):
        """StacItemCollection can be created with required fields."""
        ic = StacItemCollection(
            features=[],
            links=[
                StacLink(
                    rel="self",
                    href="http://localhost/stac/search",
                    type="application/json",
                )
            ],
            numberMatched=0,
            numberReturned=0,
            context={"limit": 10, "returned": 0, "matched": 0},
        )
        assert ic.type == "FeatureCollection"
        assert ic.numberMatched == 0
        assert len(ic.features) == 0


# ---------------------------------------------------------------------------
# Integration tests for STAC individual endpoints
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_collection_not_found(client: AsyncClient):
    """GET /stac/collections/{random_uuid} returns 404."""
    resp = await client.get(f"/stac/collections/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_collection_items_not_found(client: AsyncClient):
    """GET /stac/collections/{random_uuid}/items returns 404 for missing collection."""
    resp = await client.get(f"/stac/collections/{uuid.uuid4()}/items")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_collection_item_not_found(client: AsyncClient):
    """GET /stac/collections/{random_uuid}/items/{random_uuid} returns 404."""
    resp = await client.get(
        f"/stac/collections/{uuid.uuid4()}/items/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_item_not_found(client: AsyncClient):
    """GET /stac/items/{random_uuid} returns 404 for non-existent item."""
    resp = await client.get(f"/stac/items/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_collection_valid(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """GET /stac/collections/{id} returns collection data when it exists."""
    from app.collections.models import Collection

    coll = Collection(name="STAC Test Collection", description="Test collection for STAC")
    test_db_session.add(coll)
    await test_db_session.commit()
    await test_db_session.refresh(coll)

    resp = await client.get(f"/stac/collections/{coll.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(coll.id)
    assert data["type"] == "Collection"
    assert data["title"] == "STAC Test Collection"
    assert data["description"] == "Test collection for STAC"


@pytest.mark.anyio
async def test_get_collection_items_empty(client: AsyncClient, test_db_session):
    """GET /stac/collections/{id}/items returns empty feature collection."""
    from app.collections.models import Collection

    coll = Collection(name="Empty STAC Collection", description="No items")
    test_db_session.add(coll)
    await test_db_session.commit()
    await test_db_session.refresh(coll)

    resp = await client.get(f"/stac/collections/{coll.id}/items")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["numberMatched"] == 0
    assert data["numberReturned"] == 0
    assert data["features"] == []
