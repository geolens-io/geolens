"""Integration tests for STAC API endpoints (landing, conformance, collections, search)."""

import uuid

from typing import TYPE_CHECKING

from httpx import AsyncClient
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import Collection, CollectionDataset
from app.datasets.models import Dataset, Record

from tests.factories import get_user_id


async def _create_raster_dataset(
    session: "AsyncSession",
    *,
    created_by: uuid.UUID,
    name: str = "STAC Test DS",
    visibility: str = "public",
):
    """Create a raster dataset — STAC only serves raster_dataset/vrt_dataset records."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test raster dataset for STAC: {name}",
        visibility=visibility,
        record_status="published",
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


class TestSTACLanding:
    async def test_landing_page(self, client: AsyncClient):
        """GET /stac/ returns a STAC catalog."""
        resp = await client.get("/stac/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Catalog"
        assert "id" in data
        assert "description" in data
        assert "links" in data
        link_rels = {link["rel"] for link in data["links"]}
        assert "self" in link_rels
        assert "root" in link_rels


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


class TestSTACConformance:
    async def test_conformance(self, client: AsyncClient):
        """GET /stac/conformance returns conformance classes."""
        resp = await client.get("/stac/conformance")
        assert resp.status_code == 200
        data = resp.json()
        assert "conformsTo" in data
        assert isinstance(data["conformsTo"], list)
        assert len(data["conformsTo"]) >= 1


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


class TestSTACCollections:
    async def test_list_collections(self, client: AsyncClient, test_db_session):
        """GET /stac/collections returns collections with links."""
        admin_id = await get_user_id(test_db_session, "admin")
        await _create_raster_dataset(test_db_session, created_by=admin_id)

        resp = await client.get("/stac/collections")
        assert resp.status_code == 200
        data = resp.json()
        assert "collections" in data
        assert "links" in data
        assert len(data["collections"]) >= 1

    async def test_get_collection_by_id(self, client: AsyncClient, test_db_session):
        """GET /stac/collections/{id} returns a single STAC collection."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(
            test_db_session, created_by=admin_id, name="STAC Single"
        )

        # Create a collection and link the dataset to it
        coll = Collection(name=f"stac-test-{uuid.uuid4().hex[:8]}", created_by=admin_id)
        test_db_session.add(coll)
        await test_db_session.flush()
        test_db_session.add(
            CollectionDataset(
                collection_id=coll.id, dataset_id=ds.id, added_by=admin_id
            )
        )
        await test_db_session.commit()

        resp = await client.get(f"/stac/collections/{coll.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Collection"
        assert data["id"] == str(coll.id)
        assert "links" in data
        assert "extent" in data

    async def test_get_collection_not_found(self, client: AsyncClient):
        """GET /stac/collections/{random_uuid} returns 404."""
        resp = await client.get(f"/stac/collections/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_private_collection_hidden(
        self, client: AsyncClient, test_db_session
    ):
        """GET /stac/collections/{id} for private dataset returns 404 to anonymous."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private STAC",
            visibility="private",
        )
        resp = await client.get(f"/stac/collections/{ds.id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSTACSearch:
    async def test_search_get(self, client: AsyncClient):
        """GET /stac/search returns a FeatureCollection."""
        resp = await client.get("/stac/search", params={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert "features" in data
        assert "links" in data

    async def test_search_post(self, client: AsyncClient):
        """POST /stac/search returns a FeatureCollection."""
        resp = await client.post("/stac/search", json={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"

    async def test_search_with_bbox(self, client: AsyncClient):
        """GET /stac/search?bbox= filters by bounding box."""
        resp = await client.get(
            "/stac/search",
            params={"bbox": "-180,-90,180,90", "limit": 5},
        )
        assert resp.status_code == 200

    async def test_search_with_limit(self, client: AsyncClient):
        """GET /stac/search?limit=1 returns at most 1 item."""
        resp = await client.get("/stac/search", params={"limit": 1})
        assert resp.status_code == 200
        assert len(resp.json()["features"]) <= 1
