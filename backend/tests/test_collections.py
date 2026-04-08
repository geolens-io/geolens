"""Integration tests for collection CRUD, membership, and visibility endpoints.

Tests cover: create/edit/delete collections (auth and validation),
add/remove datasets (multi-membership), aggregated extent computation,
RBAC on member dataset listings, and audit logging.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, update

from app.datasets.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    visibility: str = "public",
    extent_wkt: str | None = None,
    data_vintage_start: date | None = None,
    data_vintage_end: date | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        temporal_start=data_vintage_start,
        temporal_end=data_vintage_end,
    )
    session.add(record)
    await session.flush()

    if extent_wkt:
        await session.execute(
            update(Record)
            .where(Record.id == record.id)
            .values(spatial_extent=func.ST_GeomFromText(extent_wkt, 4326))
        )

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# SC1: Create collection (COLL-01)
# ---------------------------------------------------------------------------


class TestCreateCollection:
    async def test_create_collection_as_admin(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /catalog/collections as admin returns 201 with correct fields."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": "Admin Collection", "description": "Created by admin"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Admin Collection"
        assert data["description"] == "Created by admin"
        assert data["dataset_count"] == 0
        assert data["extent_bbox"] is None
        assert "id" in data

    async def test_create_collection_as_editor(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /catalog/collections as editor returns 201."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Editor Collection {uuid.uuid4().hex[:6]}"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 201

    async def test_create_collection_as_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /catalog/collections as viewer returns 403."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": "Should Fail"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_create_collection_unauthenticated(self, client: AsyncClient):
        """POST /catalog/collections without auth returns 401."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": "No Auth"},
        )
        assert resp.status_code == 401

    async def test_create_collection_duplicate_name(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Creating two collections with the same name returns 409."""
        unique_name = f"Duplicate Test {uuid.uuid4().hex[:6]}"
        resp1 = await client.post(
            "/catalog/collections/",
            json={"name": unique_name},
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/catalog/collections/",
            json={"name": unique_name},
            headers=admin_auth_header,
        )
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# SC2: Edit and delete (COLL-02)
# ---------------------------------------------------------------------------


class TestUpdateDeleteCollection:
    async def test_update_collection(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """PATCH /catalog/collections/{id} updates name."""
        # Create
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Update Me {uuid.uuid4().hex[:6]}"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 201
        coll_id = resp.json()["id"]

        # Update
        resp = await client.patch(
            f"/catalog/collections/{coll_id}",
            json={"name": "Updated Name"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_delete_collection_as_admin(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /catalog/collections/{id} as admin returns 204."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Delete Me {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        coll_id = resp.json()["id"]

        resp = await client.delete(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

        # Verify gone
        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_delete_collection_as_editor_allowed(
        self, client: AsyncClient, admin_auth_header: dict, editor_auth_header: dict
    ):
        """DELETE /catalog/collections/{id} as editor succeeds (manage_collections capability)."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Editor Delete {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        coll_id = resp.json()["id"]

        resp = await client.delete(
            f"/catalog/collections/{coll_id}",
            headers=editor_auth_header,
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# SC3: Multi-membership (COLL-03)
# ---------------------------------------------------------------------------


class TestCollectionMembership:
    async def test_add_datasets_to_collection(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST datasets to collection adds them; GET lists them."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds1 = await _create_dataset(
            test_db_session, created_by=admin_id, name="Coll DS 1"
        )
        ds2 = await _create_dataset(
            test_db_session, created_by=admin_id, name="Coll DS 2"
        )

        # Create collection
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Membership Test {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        coll_id = resp.json()["id"]

        # Add datasets
        resp = await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds1.id), str(ds2.id)]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["added"] == 2

        # List datasets in collection
        resp = await client.get(
            f"/catalog/collections/{coll_id}/datasets/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        ds_ids = {d["id"] for d in data["datasets"]}
        assert str(ds1.id) in ds_ids
        assert str(ds2.id) in ds_ids

    async def test_remove_dataset_from_collection(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """DELETE dataset from collection removes it."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Remove DS"
        )

        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Remove Test {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        # Add
        await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds.id)]},
            headers=admin_auth_header,
        )

        # Remove
        resp = await client.delete(
            f"/catalog/collections/{coll_id}/datasets/{ds.id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

        # Verify removed
        resp = await client.get(
            f"/catalog/collections/{coll_id}/datasets/",
            headers=admin_auth_header,
        )
        assert resp.json()["total"] == 0

    async def test_dataset_in_multiple_collections(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Same dataset can exist in multiple collections."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Multi Coll DS"
        )

        # Create two collections
        resp1 = await client.post(
            "/catalog/collections/",
            json={"name": f"Multi A {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        resp2 = await client.post(
            "/catalog/collections/",
            json={"name": f"Multi B {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_a = resp1.json()["id"]
        coll_b = resp2.json()["id"]

        # Add same dataset to both
        await client.post(
            f"/catalog/collections/{coll_a}/datasets/",
            json={"dataset_ids": [str(ds.id)]},
            headers=admin_auth_header,
        )
        await client.post(
            f"/catalog/collections/{coll_b}/datasets/",
            json={"dataset_ids": [str(ds.id)]},
            headers=admin_auth_header,
        )

        # Both collections list the dataset
        resp_a = await client.get(
            f"/catalog/collections/{coll_a}/datasets/",
            headers=admin_auth_header,
        )
        resp_b = await client.get(
            f"/catalog/collections/{coll_b}/datasets/",
            headers=admin_auth_header,
        )
        assert resp_a.json()["total"] == 1
        assert resp_b.json()["total"] == 1

        # Dataset detail shows both collections
        resp = await client.get(
            f"/datasets/{ds.id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        colls = resp.json().get("collections", [])
        coll_ids = {c["id"] for c in colls}
        assert coll_a in coll_ids
        assert coll_b in coll_ids

    async def test_add_duplicate_dataset_idempotent(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Adding same dataset twice returns added=0 on second call."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Idempotent DS"
        )

        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Idempotent Test {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        # First add
        resp = await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds.id)]},
            headers=admin_auth_header,
        )
        assert resp.json()["added"] == 1

        # Second add (duplicate)
        resp = await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds.id)]},
            headers=admin_auth_header,
        )
        assert resp.json()["added"] == 0


# ---------------------------------------------------------------------------
# SC4: Aggregated extent (COLL-05)
# ---------------------------------------------------------------------------


class TestCollectionExtent:
    async def test_collection_extent_computed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Collection with datasets has non-null extent_bbox and temporal dates."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds1 = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Extent DS 1",
            extent_wkt="POLYGON((-74 40, -74 41, -73 41, -73 40, -74 40))",
            data_vintage_start=date(2020, 1, 1),
            data_vintage_end=date(2020, 12, 31),
        )
        ds2 = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Extent DS 2",
            extent_wkt="POLYGON((-75 39, -75 40, -74 40, -74 39, -75 39))",
            data_vintage_start=date(2021, 6, 1),
            data_vintage_end=date(2022, 6, 30),
        )

        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Extent Test {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds1.id), str(ds2.id)]},
            headers=admin_auth_header,
        )

        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extent_bbox"] is not None
        assert len(data["extent_bbox"]) == 4
        assert data["temporal_start"] == "2020-01-01"
        assert data["temporal_end"] == "2022-06-30"
        assert data["dataset_count"] == 2

    async def test_collection_extent_empty_when_no_datasets(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Collection with no members has null extents."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Empty Extent {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extent_bbox"] is None
        assert data["temporal_start"] is None
        assert data["temporal_end"] is None

    async def test_collection_extent_mixed_null_and_present_spatial_extent(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Aggregation over records with NULL spatial_extent must not crash.

        Protects compute_collection_extent in collections/service.py:243-244
        which uses ST_Envelope(ST_Collect(Record.spatial_extent)). ST_Collect
        should safely skip NULL values and return a valid envelope based on
        the non-NULL member.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        # One dataset with a real spatial extent
        ds_with_extent = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="With Extent",
            extent_wkt="POLYGON((-74 40, -74 41, -73 41, -73 40, -74 40))",
        )
        # One dataset with NULL spatial extent (no extent_wkt passed)
        ds_null = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Null Extent",
        )

        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Mixed Extent {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        add_resp = await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds_with_extent.id), str(ds_null.id)]},
            headers=admin_auth_header,
        )
        assert add_resp.status_code in (200, 201)

        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        # Must succeed and produce an envelope from the non-NULL member only
        assert resp.status_code == 200
        data = resp.json()
        assert data["extent_bbox"] is not None, (
            "ST_Envelope(ST_Collect(...)) should yield a bbox when at least "
            "one member has a non-NULL spatial_extent"
        )
        assert len(data["extent_bbox"]) == 4
        assert data["dataset_count"] == 2

    async def test_collection_extent_all_null_spatial_extent(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Collection where every member has NULL spatial_extent returns None."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds1 = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Null Ext 1",
        )
        ds2 = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Null Ext 2",
        )

        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"All Null Extent {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds1.id), str(ds2.id)]},
            headers=admin_auth_header,
        )

        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extent_bbox"] is None
        assert data["dataset_count"] == 2


# ---------------------------------------------------------------------------
# SC5: RBAC on member datasets (visibility filtering)
# ---------------------------------------------------------------------------


class TestCollectionVisibility:
    async def test_collection_datasets_respects_visibility(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Viewer sees only public datasets in a collection, not private ones."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds_public = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="RBAC Public DS",
            visibility="public",
        )
        ds_private = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="RBAC Private DS",
            visibility="private",
        )

        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"RBAC Test {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        await client.post(
            f"/catalog/collections/{coll_id}/datasets/",
            json={"dataset_ids": [str(ds_public.id), str(ds_private.id)]},
            headers=admin_auth_header,
        )

        # Admin sees both
        resp = await client.get(
            f"/catalog/collections/{coll_id}/datasets/",
            headers=admin_auth_header,
        )
        assert resp.json()["total"] == 2

        # Viewer sees only public
        resp = await client.get(
            f"/catalog/collections/{coll_id}/datasets/",
            headers=viewer_auth_header,
        )
        assert resp.json()["total"] == 1
        assert resp.json()["datasets"][0]["id"] == str(ds_public.id)

        # Collection detail for viewer shows dataset_count=1
        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=viewer_auth_header,
        )
        assert resp.json()["dataset_count"] == 1


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestListCollections:
    async def test_list_collections(self, client: AsyncClient, admin_auth_header: dict):
        """GET /catalog/collections returns collections with total."""
        name_a = f"List A {uuid.uuid4().hex[:6]}"
        name_b = f"List B {uuid.uuid4().hex[:6]}"
        await client.post(
            "/catalog/collections/",
            json={"name": name_a},
            headers=admin_auth_header,
        )
        await client.post(
            "/catalog/collections/",
            json={"name": name_b},
            headers=admin_auth_header,
        )

        resp = await client.get(
            "/catalog/collections/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        names = {c["name"] for c in data["collections"]}
        assert name_a in names
        assert name_b in names

    async def test_list_collections_with_datasets_has_counts_and_extents(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET /catalog/collections returns correct dataset_count and extent for each collection."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Batch Count DS",
            extent_wkt="POLYGON((-74 40, -74 41, -73 41, -73 40, -74 40))",
            data_vintage_start=date(2023, 1, 1),
            data_vintage_end=date(2023, 12, 31),
        )

        name_with = f"WithDS {uuid.uuid4().hex[:6]}"
        name_empty = f"EmptyDS {uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/catalog/collections/",
            json={"name": name_with},
            headers=admin_auth_header,
        )
        coll_with_id = resp.json()["id"]
        await client.post(
            "/catalog/collections/",
            json={"name": name_empty},
            headers=admin_auth_header,
        )

        await client.post(
            f"/catalog/collections/{coll_with_id}/datasets/",
            json={"dataset_ids": [str(ds.id)]},
            headers=admin_auth_header,
        )

        resp = await client.get(
            "/catalog/collections/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        colls = {c["name"]: c for c in resp.json()["collections"]}

        # Collection with datasets: count and extent populated
        assert colls[name_with]["dataset_count"] == 1
        assert colls[name_with]["extent_bbox"] is not None
        assert colls[name_with]["temporal_start"] == "2023-01-01"

        # Empty collection: defaults applied
        assert colls[name_empty]["dataset_count"] == 0
        assert colls[name_empty]["extent_bbox"] is None
        assert colls[name_empty]["temporal_start"] is None

    async def test_get_single_collection(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /catalog/collections/{id} returns correct fields."""
        resp = await client.post(
            "/catalog/collections/",
            json={"name": f"Single Test {uuid.uuid4().hex[:6]}", "description": "desc"},
            headers=admin_auth_header,
        )
        coll_id = resp.json()["id"]

        resp = await client.get(
            f"/catalog/collections/{coll_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == coll_id
        assert data["description"] == "desc"
        assert "created_at" in data
        assert "updated_at" in data

    async def test_get_nonexistent_collection(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /catalog/collections/{random_uuid} returns 404."""
        resp = await client.get(
            f"/catalog/collections/{uuid.uuid4()}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Audit integration
# ---------------------------------------------------------------------------


class TestCollectionAudit:
    async def test_collection_create_audit(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After creating a collection, audit log has a collection.create entry."""
        coll_name = f"Audit Test {uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/catalog/collections/",
            json={"name": coll_name},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # Check audit logs
        resp = await client.get(
            "/admin/audit-logs/",
            params={"action": "collection.create"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        actions = [log["action"] for log in resp.json()["logs"]]
        assert "collection.create" in actions
