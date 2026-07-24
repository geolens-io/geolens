"""Unit tests for STAC API endpoint logic.

Pure unit tests -- validates conformance, schema instantiation,
and parameter parsing without requiring a running database.
"""

import json
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.standards.stac.schemas import (
    StacCatalog,
    StacConformance,
    StacItemCollection,
    StacItemCollectionResponse,
    StacItemResponse,
    StacLink,
)
from app.standards.stac.router import _item_collection_response
from app.standards.stac.serializer import STAC_CONFORMANCE


def _find_link(links: list[dict], rel: str) -> dict | None:
    """Find a link by rel value in a links list."""
    for link in links:
        if link["rel"] == rel:
            return link
    return None


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

    def test_conformance_three_classes(self):
        assert len(STAC_CONFORMANCE) == 3


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
        assert len(catalog.conformsTo) == 3

    def test_catalog_default_values(self):
        """StacCatalog defaults: type=Catalog, stac_version=1.0.0."""
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
        assert len(conf.conformsTo) == 3


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

    def test_serialized_collection_matches_typed_response_contract(self):
        item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "item-1",
            "geometry": None,
            "properties": {"datetime": "2026-01-15T00:00:00Z"},
            "links": [{"rel": "self", "href": "https://example.test/item-1"}],
            "assets": {"data": {"href": "https://example.test/item-1.tif"}},
        }
        result = StacItemCollection(
            features=[item],
            links=[
                StacLink(
                    rel="self",
                    href="https://example.test/stac/search",
                    type="application/geo+json",
                )
            ],
            numberMatched=1,
            numberReturned=1,
            context={"limit": 10, "returned": 1, "matched": 1},
        )

        response = _item_collection_response(result)
        parsed = StacItemCollectionResponse.model_validate_json(response.body)
        payload = json.loads(response.body)

        assert response.media_type == "application/geo+json"
        assert parsed.features[0].id == "item-1"
        assert payload["type"] == "FeatureCollection"
        # Optional link fields serialize as omitted, not null — the STAC link
        # schema types `method` as a ^[A-Z]+$ string.
        assert "method" not in payload["links"][0]
        assert payload["features"][0] == item

    def test_item_bbox_requires_exactly_four_or_six_coordinates(self):
        item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "item-1",
            "geometry": None,
            "properties": {"datetime": None},
            "links": [],
            "assets": {},
        }

        assert len(StacItemResponse.model_validate({**item, "bbox": [0] * 6}).bbox) == 6
        with pytest.raises(ValueError):
            StacItemResponse.model_validate({**item, "bbox": [0] * 5})


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
    resp = await client.get(f"/stac/collections/{uuid.uuid4()}/items/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_item_not_found(client: AsyncClient):
    """GET /stac/items/{random_uuid} returns 404 for non-existent item."""
    resp = await client.get(f"/stac/items/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_collapse_licenses():
    """Member licenses collapse: none → None, one → itself, mixed → various."""
    from app.standards.stac.router import _collapse_licenses

    assert _collapse_licenses(None) is None
    assert _collapse_licenses([None]) is None
    assert _collapse_licenses(["CC-BY-4.0", None]) == "CC-BY-4.0"
    assert _collapse_licenses(["CC-BY-4.0", "ODbL-1.0"]) == "various"


async def _create_collection_with_item(
    session, name: str, description: str, *, license: str | None = None
):
    """Create a Collection holding one public published raster dataset.

    Collections with no visible STAC Items are hidden from the STAC surface,
    so router tests must seed at least one item.
    """
    from app.modules.catalog.collections.models import Collection, CollectionDataset
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from tests.factories import get_user_id

    coll = Collection(name=name, description=description)
    session.add(coll)
    record = Record(
        title=f"{name} item",
        summary=f"Raster item for {name}",
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        license=license,
        created_by=await get_user_id(session, "admin"),
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        srid=4326,
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()
    session.add(CollectionDataset(collection_id=coll.id, dataset_id=dataset.id))
    await session.commit()
    await session.refresh(coll)
    return coll


@pytest.mark.anyio
async def test_get_collection_valid(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """GET /stac/collections/{id} returns collection data when it has items."""
    coll = await _create_collection_with_item(
        test_db_session,
        "STAC Test Collection",
        "Test collection for STAC",
        license="CC-BY-4.0",
    )

    resp = await client.get(f"/stac/collections/{coll.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(coll.id)
    assert data["type"] == "Collection"
    assert data["title"] == "STAC Test Collection"
    assert data["description"] == "Test collection for STAC"
    # License aggregates from member records instead of hardcoding proprietary.
    assert data["license"] == "CC-BY-4.0"


@pytest.mark.anyio
async def test_get_collection_without_items_hidden(
    client: AsyncClient, test_db_session
):
    """A collection with no visible STAC Items is hidden (404), not served
    with a fabricated global extent."""
    from app.modules.catalog.collections.models import Collection

    coll = Collection(name="Empty STAC Collection", description="No items")
    test_db_session.add(coll)
    await test_db_session.commit()
    await test_db_session.refresh(coll)

    resp = await client.get(f"/stac/collections/{coll.id}")
    assert resp.status_code == 404
    resp = await client.get(f"/stac/collections/{coll.id}/items")
    assert resp.status_code == 404

    listing = await client.get("/stac/collections")
    assert str(coll.id) not in [c["id"] for c in listing.json()["collections"]]


@pytest.mark.anyio
async def test_collection_items_self_link_preserves_active_params(
    client: AsyncClient, test_db_session
):
    """STAC collection items self link preserves active filter params."""
    coll = await _create_collection_with_item(
        test_db_session, "Filtered STAC Collection", "One item"
    )

    resp = await client.get(
        f"/stac/collections/{coll.id}/items",
        params={
            "bbox": "-180,-90,180,90",
            "datetime": "2024-01-01T00:00:00Z/2024-12-31T00:00:00Z",
            "limit": 1,
            "offset": 2,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    self_link = _find_link(data["links"], "self")
    assert self_link is not None
    qs = parse_qs(urlparse(self_link["href"]).query)
    assert qs["bbox"] == ["-180,-90,180,90"]
    assert qs["datetime"] == ["2024-01-01T00:00:00Z/2024-12-31T00:00:00Z"]
    assert qs["limit"] == ["1"]
    assert qs["offset"] == ["2"]
    assert 'rel="self"' in resp.headers["link"]
