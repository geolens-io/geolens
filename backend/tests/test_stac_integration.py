"""Integration tests for STAC API endpoints (landing, conformance, collections, search)."""

import uuid
from urllib.parse import parse_qs, urlparse

from typing import TYPE_CHECKING

from httpx import AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.standards.stac.router import STAC_UNASSIGNED_COLLECTION_ID

from tests.factories import get_user_id


def _find_link(links: list[dict], rel: str) -> dict | None:
    """Find a link by rel value in a links list."""
    for link in links:
        if link["rel"] == rel:
            return link
    return None


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

    async def test_landing_link_media_types_match_responses(self, client: AsyncClient):
        """Search is GeoJSON and the generated API description is OpenAPI 3.1."""
        resp = await client.get("/stac/")
        assert resp.status_code == 200

        links = resp.json()["links"]
        search_link = _find_link(links, "search")
        service_desc = _find_link(links, "service-desc")

        assert search_link is not None
        assert search_link["type"] == "application/geo+json"
        assert service_desc is not None
        assert service_desc["type"] == ("application/vnd.oai.openapi+json;version=3.1")


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
        ds = await _create_raster_dataset(test_db_session, created_by=admin_id)
        coll = Collection(
            name=f"stac-list-{uuid.uuid4().hex[:8]}",
            created_by=admin_id,
        )
        test_db_session.add(coll)
        await test_db_session.flush()
        test_db_session.add(
            CollectionDataset(
                collection_id=coll.id,
                dataset_id=ds.id,
                added_by=admin_id,
            )
        )
        await test_db_session.commit()

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

    async def test_unassigned_items_have_discoverable_fallback_collection(
        self, client: AsyncClient, test_db_session
    ):
        """Published rasters without membership remain collection-browsable."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            name="Unassigned STAC Raster",
        )

        root = (await client.get("/stac/")).json()
        child_hrefs = {link["href"] for link in root["links"] if link["rel"] == "child"}
        assert any(
            href.endswith(f"/collections/{STAC_UNASSIGNED_COLLECTION_ID}")
            for href in child_hrefs
        )

        collection_list = (await client.get("/stac/collections")).json()
        fallback = next(
            collection
            for collection in collection_list["collections"]
            if collection["id"] == STAC_UNASSIGNED_COLLECTION_ID
        )
        assert fallback["type"] == "Collection"

        collection_resp = await client.get(
            f"/stac/collections/{STAC_UNASSIGNED_COLLECTION_ID}"
        )
        assert collection_resp.status_code == 200

        items_resp = await client.get(
            f"/stac/collections/{STAC_UNASSIGNED_COLLECTION_ID}/items",
            params={"limit": 200},
        )
        assert items_resp.status_code == 200
        item = next(
            feature
            for feature in items_resp.json()["features"]
            if feature["id"] == str(ds.id)
        )
        assert item["collection"] == STAC_UNASSIGNED_COLLECTION_ID
        collection_link = _find_link(item["links"], "collection")
        assert collection_link is not None
        assert collection_link["href"].endswith(
            f"/collections/{STAC_UNASSIGNED_COLLECTION_ID}"
        )

        item_resp = await client.get(
            f"/stac/collections/{STAC_UNASSIGNED_COLLECTION_ID}/items/{ds.id}"
        )
        assert item_resp.status_code == 200
        assert item_resp.json()["collection"] == STAC_UNASSIGNED_COLLECTION_ID

        search_resp = await client.get(
            "/stac/search",
            params={
                "ids": str(ds.id),
                "collections": STAC_UNASSIGNED_COLLECTION_ID,
            },
        )
        assert search_resp.status_code == 200
        assert search_resp.json()["features"][0]["collection"] == (
            STAC_UNASSIGNED_COLLECTION_ID
        )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSTACSearch:
    async def test_multiple_memberships_choose_deterministic_collection(
        self, client: AsyncClient, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"multi-membership-{uuid.uuid4().hex[:8]}",
        )
        first = Collection(
            name=f"stac-first-{uuid.uuid4().hex[:8]}", created_by=admin_id
        )
        canonical = Collection(
            name=f"stac-canonical-{uuid.uuid4().hex[:8]}", created_by=admin_id
        )
        test_db_session.add_all([first, canonical])
        await test_db_session.flush()
        test_db_session.add_all(
            [
                CollectionDataset(
                    collection_id=first.id,
                    dataset_id=dataset.id,
                    added_by=admin_id,
                    sort_order=20,
                ),
                CollectionDataset(
                    collection_id=canonical.id,
                    dataset_id=dataset.id,
                    added_by=admin_id,
                    sort_order=10,
                ),
            ]
        )
        await test_db_session.commit()

        item = await client.get(f"/stac/items/{dataset.id}")
        assert item.status_code == 200
        assert item.json()["collection"] == str(canonical.id)

        unscoped = await client.get("/stac/search", params={"ids": str(dataset.id)})
        assert unscoped.status_code == 200
        assert unscoped.json()["features"][0]["collection"] == str(canonical.id)

        scoped = await client.get(
            "/stac/search",
            params={"ids": str(dataset.id), "collections": str(first.id)},
        )
        assert scoped.status_code == 200
        assert scoped.json()["features"][0]["collection"] == str(first.id)

    async def test_search_get(self, client: AsyncClient):
        """GET /stac/search returns a FeatureCollection."""
        resp = await client.get("/stac/search", params={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert "features" in data
        assert "links" in data
        assert 'rel="self"' in resp.headers["link"]

    async def test_search_all_invalid_ids_is_geojson_with_link_header(
        self, client: AsyncClient
    ):
        resp = await client.get("/stac/search", params={"ids": "not-a-uuid"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/geo+json")
        assert 'rel="self"' in resp.headers["link"]
        assert resp.json()["features"] == []

    async def test_search_post(self, client: AsyncClient):
        """POST /stac/search returns a FeatureCollection."""
        resp = await client.post("/stac/search", json={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"

    async def test_search_with_bbox(self, client: AsyncClient):
        """GET /stac/search?bbox= filters by bounding box and preserves params."""
        resp = await client.get(
            "/stac/search",
            params={"bbox": "-180,-90,180,90", "limit": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        self_link = _find_link(data["links"], "self")
        assert self_link is not None
        qs = parse_qs(urlparse(self_link["href"]).query)
        assert qs["bbox"] == ["-180,-90,180,90"]
        assert qs["limit"] == ["5"]
        assert qs["offset"] == ["0"]

    async def test_search_with_limit(self, client: AsyncClient):
        """GET /stac/search?limit=1 returns at most 1 item."""
        resp = await client.get("/stac/search", params={"limit": 1})
        assert resp.status_code == 200
        assert len(resp.json()["features"]) <= 1
