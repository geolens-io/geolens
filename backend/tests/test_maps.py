"""Integration tests for maps CRUD, duplication, sharing, and layer management.

Tests cover: create/list/get/update/delete maps, duplicate, share tokens,
shared map access, add/remove layers, and RBAC enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Map Test DS",
    visibility: str = "public",
) -> Dataset:
    """Insert a Record + Dataset pair for layer tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Dataset for map tests: {name}",
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
        geometry_type="Point",
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_map(
    client: AsyncClient, headers: dict, name: str | None = None
) -> dict:
    """Create a map via the API and return the response JSON."""
    map_name = name or f"Test Map {uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/maps/",
        json={"name": map_name, "description": "test description"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create map failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Create map
# ---------------------------------------------------------------------------


class TestCreateMap:
    async def test_create_map_as_admin(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/ as admin returns 201 with correct fields."""
        resp = await client.post(
            "/maps/",
            json={"name": "Admin Map", "description": "Created by admin"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Admin Map"
        assert data["description"] == "Created by admin"
        assert data["visibility"] == "private"
        assert data["layer_count"] == 0
        assert data["layers"] == []
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_map_as_editor(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /maps/ as editor returns 201."""
        resp = await client.post(
            "/maps/",
            json={"name": f"Editor Map {uuid.uuid4().hex[:6]}"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 201

    async def test_create_map_as_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /maps/ as viewer returns 403."""
        resp = await client.post(
            "/maps/",
            json={"name": "Should Fail"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_create_map_unauthenticated(self, client: AsyncClient):
        """POST /maps/ without auth returns 401."""
        resp = await client.post(
            "/maps/",
            json={"name": "No Auth"},
        )
        assert resp.status_code == 401

    async def test_create_map_minimal(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/ with only name (no description) returns 201."""
        resp = await client.post(
            "/maps/",
            json={"name": f"Minimal Map {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        assert resp.json()["description"] is None


# ---------------------------------------------------------------------------
# List maps
# ---------------------------------------------------------------------------


class TestListMaps:
    async def test_list_maps_as_admin(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/ as admin returns maps with total."""
        # Create a map to ensure at least one exists
        await _create_map(client, admin_auth_header)

        resp = await client.get("/maps/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "maps" in data
        assert "total" in data
        assert data["total"] >= 1

    async def test_list_maps_as_editor_sees_own(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """GET /maps/ as editor returns only their own maps."""
        # Create a map as editor
        created = await _create_map(client, editor_auth_header, "Editor Own Map")

        resp = await client.get("/maps/", headers=editor_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        map_ids = {m["id"] for m in data["maps"]}
        assert created["id"] in map_ids

    async def test_list_maps_unauthenticated(self, client: AsyncClient):
        """GET /maps/ without auth returns 401."""
        resp = await client.get("/maps/")
        assert resp.status_code == 401

    async def test_list_maps_pagination(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/?limit=1 returns at most 1 map."""
        await _create_map(client, admin_auth_header)
        await _create_map(client, admin_auth_header)

        resp = await client.get(
            "/maps/", params={"limit": 1}, headers=admin_auth_header
        )
        assert resp.status_code == 200
        assert len(resp.json()["maps"]) <= 1


# ---------------------------------------------------------------------------
# Get map
# ---------------------------------------------------------------------------


class TestGetMap:
    async def test_get_map_success(self, client: AsyncClient, admin_auth_header: dict):
        """GET /maps/{id} returns the map with layers."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == map_id
        assert data["name"] == created["name"]
        assert "layers" in data

    async def test_get_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/{random_uuid} returns 404."""
        resp = await client.get(f"/maps/{uuid.uuid4()}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_get_map_unauthenticated(self, client: AsyncClient):
        """GET /maps/{id} without auth returns 401."""
        resp = await client.get(f"/maps/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Update map
# ---------------------------------------------------------------------------


class TestUpdateMap:
    async def test_update_map_name(self, client: AsyncClient, admin_auth_header: dict):
        """PUT /maps/{id} updates name and description."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"name": "Updated Name", "description": "Updated desc"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"
        assert data["description"] == "Updated desc"

    async def test_update_map_viewport(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT /maps/{id} updates viewport fields."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"center_lng": -74.0, "center_lat": 40.7, "zoom": 10.0},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["center_lng"] == -74.0
        assert data["center_lat"] == 40.7
        assert data["zoom"] == 10.0

    async def test_update_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT /maps/{random_uuid} returns 404."""
        resp = await client.put(
            f"/maps/{uuid.uuid4()}",
            json={"name": "Ghost"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_update_map_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """PUT /maps/{id} as viewer returns 403."""
        resp = await client.put(
            f"/maps/{uuid.uuid4()}",
            json={"name": "Should Fail"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_update_map_non_owner_editor_forbidden(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
    ):
        """PUT /maps/{id} as editor who doesn't own the map returns 403."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"name": "Hijack"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 403

    async def test_update_map_rejects_public_with_non_public_datasets(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with visibility=public returns 400 when map has non-public datasets."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Restricted DS",
            visibility="restricted",
        )
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer referencing the non-public dataset
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        # Attempt to set visibility to public
        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        raw_detail = resp.json()["detail"]
        # ProblemDetail handler serializes dict detail as a JSON string
        detail = json.loads(raw_detail) if isinstance(raw_detail, str) else raw_detail
        assert "Restricted DS" in detail["datasets"]
        assert detail["message"] == "Cannot set visibility to public: map contains non-public datasets"

    async def test_update_map_allows_public_with_all_public_datasets(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with visibility=public succeeds when all datasets are public."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Public DS",
            visibility="public",
        )
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

    async def test_update_map_public_no_layers_succeeds(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """PUT /maps/{id} with visibility=public succeeds for maps with no layers."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"


# ---------------------------------------------------------------------------
# Delete map
# ---------------------------------------------------------------------------


class TestDeleteMap:
    async def test_delete_map_as_owner(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /maps/{id} as owner returns 204."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.delete(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 204

        # Verify gone
        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_delete_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /maps/{random_uuid} returns 404."""
        resp = await client.delete(f"/maps/{uuid.uuid4()}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_delete_map_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """DELETE /maps/{id} as viewer returns 403."""
        resp = await client.delete(f"/maps/{uuid.uuid4()}", headers=viewer_auth_header)
        assert resp.status_code == 403

    async def test_delete_map_non_owner_editor_forbidden(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
    ):
        """DELETE /maps/{id} as editor who doesn't own the map returns 403."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.delete(f"/maps/{map_id}", headers=editor_auth_header)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Duplicate map
# ---------------------------------------------------------------------------


class TestDuplicateMap:
    async def test_duplicate_map_success(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{id}/duplicate creates a copy with '(copy)' suffix."""
        created = await _create_map(client, admin_auth_header, "Original Map")
        map_id = created["id"]

        resp = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Original Map (copy)"
        assert data["id"] != map_id

    async def test_duplicate_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{random_uuid}/duplicate returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/duplicate", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_duplicate_map_viewer_allowed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
    ):
        """POST /maps/{id}/duplicate as viewer returns 201 (any auth user can fork)."""
        # Create a public map as admin so viewer can see it
        created = await _create_map(client, admin_auth_header, "Public Map For Viewer")
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        resp = await client.post(
            f"/maps/{map_id}/duplicate", headers=viewer_auth_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["visibility"] == "private"
        assert "excluded_layer_count" in data

    async def test_duplicate_map_preserves_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Duplicated map includes layers from the original."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header, "Map With Layers")
        map_id = created["id"]

        # Add a layer
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        # Duplicate
        resp = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_count"] == 1

    async def test_duplicate_lineage(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Fork records forked_from_id and forked_from_name."""
        created = await _create_map(client, admin_auth_header, "Source Map")
        map_id = created["id"]

        resp = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["forked_from_id"] == map_id
        assert data["forked_from_name"] == "Source Map"

    async def test_lineage_after_source_delete(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After deleting source, fork's forked_from_id becomes null."""
        created = await _create_map(client, admin_auth_header, "Doomed Source")
        source_id = created["id"]

        fork_resp = await client.post(
            f"/maps/{source_id}/duplicate", headers=admin_auth_header
        )
        fork_id = fork_resp.json()["id"]

        # Delete the source
        del_resp = await client.delete(f"/maps/{source_id}", headers=admin_auth_header)
        assert del_resp.status_code == 204

        # GET the fork -- lineage should be null
        get_resp = await client.get(f"/maps/{fork_id}", headers=admin_auth_header)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["forked_from_id"] is None
        assert data["forked_from_name"] is None

    async def test_duplicate_name_collision(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """First fork is '(copy)', second is '(copy 2)'."""
        created = await _create_map(client, admin_auth_header, "Collision Test")
        map_id = created["id"]

        r1 = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert r1.status_code == 201
        assert r1.json()["name"] == "Collision Test (copy)"

        r2 = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert r2.status_code == 201
        assert r2.json()["name"] == "Collision Test (copy 2)"

    async def test_duplicate_no_copy_chaining(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Forking 'X (copy)' produces 'X (copy 2)', not 'X (copy) (copy)'."""
        created = await _create_map(client, admin_auth_header, "Chain Test")
        source_id = created["id"]

        # First fork
        r1 = await client.post(
            f"/maps/{source_id}/duplicate", headers=admin_auth_header
        )
        fork1_id = r1.json()["id"]
        assert r1.json()["name"] == "Chain Test (copy)"

        # Fork the fork
        r2 = await client.post(f"/maps/{fork1_id}/duplicate", headers=admin_auth_header)
        assert r2.status_code == 201
        assert r2.json()["name"] == "Chain Test (copy 2)"

    async def test_duplicate_rbac_filtering(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Viewer fork excludes layers referencing private datasets they don't own."""
        admin_id = await _get_user_id(test_db_session, "admin")

        # Create a public dataset and a private dataset (owned by admin)
        public_ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Public DS", visibility="public"
        )
        private_ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private DS",
            visibility="private",
        )

        # Create a public map with both layers
        created = await _create_map(client, admin_auth_header, "RBAC Test Map")
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(public_ds.id), "sort_order": 0},
            headers=admin_auth_header,
        )
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(private_ds.id), "sort_order": 1},
            headers=admin_auth_header,
        )

        # Fork as viewer -- should exclude private layer
        resp = await client.post(
            f"/maps/{map_id}/duplicate", headers=viewer_auth_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_count"] == 1
        assert data["excluded_layer_count"] == 1

    async def test_duplicate_all_layers_excluded(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Fork with only inaccessible layers produces empty map shell."""
        admin_id = await _get_user_id(test_db_session, "admin")
        private_ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="All Private DS",
            visibility="private",
        )

        created = await _create_map(client, admin_auth_header, "All Excluded Map")
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(private_ds.id)},
            headers=admin_auth_header,
        )

        resp = await client.post(
            f"/maps/{map_id}/duplicate", headers=viewer_auth_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_count"] == 0
        assert data["excluded_layer_count"] == 1

    async def test_duplicate_admin_sees_all_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Admin fork includes all layers regardless of visibility."""
        admin_id = await _get_user_id(test_db_session, "admin")
        private_ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Admin Private DS",
            visibility="private",
        )

        created = await _create_map(client, admin_auth_header, "Admin Fork Test")
        map_id = created["id"]
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(private_ds.id)},
            headers=admin_auth_header,
        )

        resp = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_count"] == 1
        assert data["excluded_layer_count"] == 0

    async def test_duplicate_always_private(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Fork of a public map is always private."""
        created = await _create_map(client, admin_auth_header, "Public Source")
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )

        resp = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert resp.status_code == 201
        assert resp.json()["visibility"] == "private"

    async def test_get_forked_map_shows_lineage(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET on a forked map includes forked_from_id and forked_from_name."""
        created = await _create_map(client, admin_auth_header, "Lineage Source")
        source_id = created["id"]

        fork_resp = await client.post(
            f"/maps/{source_id}/duplicate", headers=admin_auth_header
        )
        fork_id = fork_resp.json()["id"]

        get_resp = await client.get(f"/maps/{fork_id}", headers=admin_auth_header)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["forked_from_id"] == source_id
        assert data["forked_from_name"] == "Lineage Source"

    async def test_excluded_layer_count_in_response(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Response excluded_layer_count matches actual excluded layers."""
        admin_id = await _get_user_id(test_db_session, "admin")
        pub_ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Count Pub DS",
            visibility="public",
        )
        priv_ds1 = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Count Priv DS1",
            visibility="private",
        )
        priv_ds2 = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Count Priv DS2",
            visibility="private",
        )

        created = await _create_map(client, admin_auth_header, "Count Test Map")
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        for ds_id, order in [(pub_ds.id, 0), (priv_ds1.id, 1), (priv_ds2.id, 2)]:
            await client.post(
                f"/maps/{map_id}/layers/",
                json={"dataset_id": str(ds_id), "sort_order": order},
                headers=admin_auth_header,
            )

        resp = await client.post(
            f"/maps/{map_id}/duplicate", headers=viewer_auth_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_count"] == 1
        assert data["excluded_layer_count"] == 2

    async def test_duplicate_no_thumbnail(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Fork does not copy source thumbnail."""
        created = await _create_map(client, admin_auth_header, "Thumb Source")
        map_id = created["id"]

        # Set a thumbnail on source
        await client.put(
            f"/maps/{map_id}/thumbnail",
            content="data:image/png;base64,iVBORw0KGgo=",
            headers={**admin_auth_header, "content-type": "text/plain"},
        )

        resp = await client.post(f"/maps/{map_id}/duplicate", headers=admin_auth_header)
        assert resp.status_code == 201
        assert resp.json()["thumbnail"] is None


# ---------------------------------------------------------------------------
# Share token create/revoke
# ---------------------------------------------------------------------------


class TestShareToken:
    async def test_share_requires_public_visibility(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{id}/share on a private map returns 400."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]
        assert created["visibility"] == "private"

        resp = await client.post(f"/maps/{map_id}/share", headers=admin_auth_header)
        assert resp.status_code == 400
        assert "public" in resp.json()["detail"].lower()

    async def test_share_public_map_success(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{id}/share on a public map returns token."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Make it public
        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        # Share
        resp = await client.post(f"/maps/{map_id}/share", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "share_url" in data
        assert data["is_active"] is True

    async def test_share_idempotent(self, client: AsyncClient, admin_auth_header: dict):
        """POST /maps/{id}/share twice returns the same token."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )

        resp1 = await client.post(f"/maps/{map_id}/share", headers=admin_auth_header)
        resp2 = await client.post(f"/maps/{map_id}/share", headers=admin_auth_header)
        assert resp1.json()["token"] == resp2.json()["token"]

    async def test_revoke_share_token(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /maps/{id}/share revokes the share token."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await client.post(f"/maps/{map_id}/share", headers=admin_auth_header)

        resp = await client.delete(f"/maps/{map_id}/share", headers=admin_auth_header)
        assert resp.status_code == 204

    async def test_revoke_share_no_token(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /maps/{id}/share with no active token returns 404."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.delete(f"/maps/{map_id}/share", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_share_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{random_uuid}/share returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/share", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_share_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /maps/{id}/share as viewer returns 403."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/share", headers=viewer_auth_header
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Get shared map
# ---------------------------------------------------------------------------


class TestSharedMap:
    async def test_get_shared_map_success(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/shared/{token} returns map data."""
        created = await _create_map(client, admin_auth_header, "Shared Map")
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        share_resp = await client.post(
            f"/maps/{map_id}/share", headers=admin_auth_header
        )
        token = share_resp.json()["token"]

        # Access shared map (no auth required)
        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Shared Map"
        assert "layers" in data
        assert "basemap_style" in data

    async def test_get_shared_map_invalid_token(self, client: AsyncClient):
        """GET /maps/shared/{bogus_token} returns 404."""
        resp = await client.get("/maps/shared/bogus_token_12345")
        assert resp.status_code == 404

    async def test_get_shared_map_revoked_token(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/shared/{token} after revocation returns 410."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        share_resp = await client.post(
            f"/maps/{map_id}/share", headers=admin_auth_header
        )
        token = share_resp.json()["token"]

        # Revoke
        await client.delete(f"/maps/{map_id}/share", headers=admin_auth_header)

        # Access revoked token
        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 410


# ---------------------------------------------------------------------------
# Add/remove layers
# ---------------------------------------------------------------------------


class TestMapLayers:
    async def test_add_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers/ adds a layer."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["dataset_id"] == str(ds.id)
        assert data["visible"] is True
        assert data["opacity"] == 1.0
        assert "id" in data

    async def test_add_layer_map_not_found(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """POST /maps/{random_uuid}/layers/ returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/layers/",
            json={"dataset_id": str(uuid.uuid4())},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_remove_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """DELETE /maps/{id}/layers/{layer_id} removes the layer."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer
        add_resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        layer_id = add_resp.json()["id"]

        # Remove layer
        resp = await client.delete(
            f"/maps/{map_id}/layers/{layer_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

        # Verify map has no layers
        map_resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert map_resp.json()["layer_count"] == 0

    async def test_remove_layer_not_found(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """DELETE /maps/{id}/layers/{random_uuid} returns 404."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.delete(
            f"/maps/{map_id}/layers/{uuid.uuid4()}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_add_layer_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
    ):
        """POST /maps/{id}/layers/ as viewer returns 403."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/layers/",
            json={"dataset_id": str(uuid.uuid4())},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_remove_layer_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
    ):
        """DELETE /maps/{id}/layers/{layer_id} as viewer returns 403."""
        resp = await client.delete(
            f"/maps/{uuid.uuid4()}/layers/{uuid.uuid4()}",
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_add_layer_with_custom_style(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers/ with custom paint/layout stores them."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        custom_paint = {"circle-radius": 10, "circle-color": "#ff0000"}
        custom_layout = {"visibility": "visible"}

        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={
                "dataset_id": str(ds.id),
                "paint": custom_paint,
                "layout": custom_layout,
                "opacity": 0.5,
                "sort_order": 1,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["paint"] == custom_paint
        assert data["layout"] == custom_layout
        assert data["opacity"] == 0.5
        assert data["sort_order"] == 1


# ---------------------------------------------------------------------------
# Visibility check endpoint
# ---------------------------------------------------------------------------


class TestSearchSortFilterAuthor:
    """Tests for search, sort, visibility filter, and author username on GET /maps/."""

    async def test_list_maps_search_by_name(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/?search=TestMap returns maps with 'TestMap' in name, not others."""
        await _create_map(client, admin_auth_header, "UniqueTestMap Alpha")
        await _create_map(client, admin_auth_header, "Unrelated Bravo")

        resp = await client.get(
            "/maps/", params={"search": "UniqueTestMap"}, headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        names = [m["name"] for m in data["maps"]]
        assert any("UniqueTestMap" in n for n in names)
        assert all("UniqueTestMap" in n or n != "Unrelated Bravo" for n in names)
        # total should reflect filtered count
        assert data["total"] >= 1

    async def test_list_maps_search_by_description(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/?search=description-keyword returns maps matching description."""
        # Create map with unique description keyword
        resp = await client.post(
            "/maps/",
            json={"name": "Desc Search Map", "description": "xyzzy-unique-keyword"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        resp = await client.get(
            "/maps/",
            params={"search": "xyzzy-unique-keyword"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        found = [
            m
            for m in data["maps"]
            if m["description"] and "xyzzy-unique-keyword" in m["description"]
        ]
        assert len(found) >= 1

    async def test_list_maps_sort_by_name_asc(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/?sort_by=name&sort_dir=asc returns maps alphabetically A-Z."""
        await _create_map(client, admin_auth_header, "AAA SortTest")
        await _create_map(client, admin_auth_header, "ZZZ SortTest")

        resp = await client.get(
            "/maps/",
            params={"sort_by": "name", "sort_dir": "asc", "search": "SortTest"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        names = [m["name"] for m in resp.json()["maps"]]
        sort_test_names = [n for n in names if "SortTest" in n]
        assert sort_test_names == sorted(sort_test_names)

    async def test_list_maps_sort_by_created_at_desc(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/?sort_by=created_at&sort_dir=desc returns newest first."""
        await _create_map(client, admin_auth_header, "SortCreated First")
        await _create_map(client, admin_auth_header, "SortCreated Second")

        resp = await client.get(
            "/maps/",
            params={
                "sort_by": "created_at",
                "sort_dir": "desc",
                "search": "SortCreated",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        maps = resp.json()["maps"]
        sc_maps = [m for m in maps if "SortCreated" in m["name"]]
        if len(sc_maps) >= 2:
            # Second created should appear first in desc order
            assert sc_maps[0]["name"] == "SortCreated Second"

    async def test_list_maps_visibility_filter_public(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/?visibility=public returns only public maps."""
        created = await _create_map(client, admin_auth_header, "VisFilter Public Map")
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await _create_map(client, admin_auth_header, "VisFilter Private Map")

        resp = await client.get(
            "/maps/", params={"visibility": "public"}, headers=admin_auth_header
        )
        assert resp.status_code == 200
        visibilities = {m["visibility"] for m in resp.json()["maps"]}
        assert visibilities == {"public"} or len(resp.json()["maps"]) == 0

    async def test_list_maps_visibility_filter_private(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
    ):
        """GET /maps/?visibility=private returns only caller's private maps."""
        await _create_map(client, editor_auth_header, "VisFilter EditorPrivate")

        resp = await client.get(
            "/maps/", params={"visibility": "private"}, headers=editor_auth_header
        )
        assert resp.status_code == 200
        for m in resp.json()["maps"]:
            assert m["visibility"] == "private"

    async def test_list_maps_created_by_username(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """response.maps[].created_by_username is a string matching the creator's username."""
        await _create_map(client, admin_auth_header, "Username Test Map")

        resp = await client.get("/maps/", headers=admin_auth_header)
        assert resp.status_code == 200
        maps = resp.json()["maps"]
        assert len(maps) >= 1
        for m in maps:
            assert "created_by_username" in m
        # Find our test map
        test_map = next((m for m in maps if m["name"] == "Username Test Map"), None)
        assert test_map is not None
        assert test_map["created_by_username"] == "admin"

    async def test_list_maps_created_by_username_null_deleted_user(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """created_by_username is null when user account deleted (LEFT JOIN)."""
        from app.maps.models import Map
        from sqlalchemy import text

        # Create a temporary user
        temp_user = User(
            username=f"tempuser_{uuid.uuid4().hex[:8]}",
            email=f"temp_{uuid.uuid4().hex[:8]}@test.com",
            password_hash="fakehash",
        )
        test_db_session.add(temp_user)
        await test_db_session.flush()

        # Create a map owned by the temp user
        orphan_map = Map(
            name="Orphan Map Deleted User",
            description="no user",
            created_by=temp_user.id,
        )
        test_db_session.add(orphan_map)
        await test_db_session.commit()
        await test_db_session.refresh(orphan_map)
        map_id = orphan_map.id

        # Set created_by to NULL to simulate deleted user (FK prevents actual delete)
        await test_db_session.execute(
            text("UPDATE catalog.maps SET created_by = NULL WHERE id = :mid"),
            {"mid": map_id},
        )
        await test_db_session.commit()

        resp = await client.get(
            "/maps/",
            params={"search": "Orphan Map Deleted User"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        maps = resp.json()["maps"]
        orphan = next((m for m in maps if m["name"] == "Orphan Map Deleted User"), None)
        assert orphan is not None
        assert orphan["created_by_username"] is None

    async def test_list_maps_invalid_sort_by_falls_back(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Invalid sort_by value falls back to updated_at (no error)."""
        resp = await client.get(
            "/maps/", params={"sort_by": "bogus_field"}, headers=admin_auth_header
        )
        assert resp.status_code == 200

    async def test_search_resets_total_count(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Search filters affect total count, not just results."""
        await _create_map(client, admin_auth_header, "CountReset Alpha")
        await _create_map(client, admin_auth_header, "CountReset Beta")
        await _create_map(client, admin_auth_header, "Unrelated Gamma")

        # Get total without search
        resp_all = await client.get("/maps/", headers=admin_auth_header)
        total_all = resp_all.json()["total"]

        # Get total with search
        resp_filtered = await client.get(
            "/maps/", params={"search": "CountReset"}, headers=admin_auth_header
        )
        total_filtered = resp_filtered.json()["total"]

        assert total_filtered < total_all
        assert total_filtered >= 2


class TestVisibilityCheck:
    async def test_visibility_check_empty_map(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/{id}/visibility-check on map with no layers returns empty."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.get(
            f"/maps/{map_id}/visibility-check", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_non_public"] is False
        assert data["non_public_datasets"] == []

    async def test_visibility_check_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/{random_uuid}/visibility-check returns 404."""
        resp = await client.get(
            f"/maps/{uuid.uuid4()}/visibility-check",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update share token (PATCH)
# ---------------------------------------------------------------------------


async def _make_public_map_with_share_token(
    client: AsyncClient, headers: dict
) -> tuple[str, str]:
    """Helper: create a public map with a share token. Returns (map_id, token)."""
    created = await _create_map(client, headers)
    map_id = created["id"]
    await client.put(
        f"/maps/{map_id}",
        json={"visibility": "public"},
        headers=headers,
    )
    share_resp = await client.post(f"/maps/{map_id}/share", headers=headers)
    token = share_resp.json()["token"]
    return map_id, token


class TestUpdateShareToken:
    async def test_patch_share_token_set_expiration(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH /maps/{id}/share with expires_at returns 200 with updated expiration."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        resp = await client.patch(
            f"/maps/{map_id}/share",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "2026-06-01" in data["expires_at"]
        assert data["token"] == original_token

    async def test_patch_share_token_remove_expiration(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH /maps/{id}/share with expires_at=null removes expiration."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        # First set an expiration
        await client.patch(
            f"/maps/{map_id}/share",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        # Now remove it
        resp = await client.patch(
            f"/maps/{map_id}/share",
            json={"expires_at": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["expires_at"] is None
        assert data["token"] == original_token

    async def test_patch_share_token_add_expiration_to_never_expires(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH with expires_at on a never-expires token adds expiration."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        # Token was created without expiration (never expires)
        resp = await client.patch(
            f"/maps/{map_id}/share",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["expires_at"] is not None
        assert "2026-06-01" in data["expires_at"]

    async def test_patch_share_token_no_token_404(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH /maps/{id}/share on a map with no share token returns 404."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        resp = await client.patch(
            f"/maps/{map_id}/share",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_patch_share_token_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """PATCH /maps/{id}/share as viewer returns 403."""
        resp = await client.patch(
            f"/maps/{uuid.uuid4()}/share",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_patch_share_token_preserves_token_string(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Token string itself does not change after PATCH."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        resp = await client.patch(
            f"/maps/{map_id}/share",
            json={"expires_at": "2026-12-31T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["token"] == original_token


# ---------------------------------------------------------------------------
# Admin share token listing (search & filter)
# ---------------------------------------------------------------------------


class TestAdminShareTokenListing:
    async def test_admin_list_share_tokens(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /admin/share-tokens returns tokens with total count."""
        # Ensure at least one share token exists
        await _make_public_map_with_share_token(client, admin_auth_header)

        resp = await client.get("/admin/share-tokens", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "tokens" in data
        assert "total" in data
        assert data["total"] >= 1

    async def test_admin_search_share_tokens(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """GET /admin/share-tokens?search=... filters by map name."""
        # Create a map with a unique name and share it
        unique_name = f"SearchTest_{uuid.uuid4().hex[:6]}"
        created = await _create_map(client, admin_auth_header, name=unique_name)
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await client.post(f"/maps/{map_id}/share", headers=admin_auth_header)

        # Search for the unique name
        resp = await client.get(
            f"/admin/share-tokens?search={unique_name}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(unique_name in t["map_name"] for t in data["tokens"])

        # Search for nonexistent name
        resp = await client.get(
            "/admin/share-tokens?search=zzz_nonexistent_xyz",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_admin_filter_share_tokens_by_status(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /admin/share-tokens?status=active returns only active tokens."""
        await _make_public_map_with_share_token(client, admin_auth_header)

        resp = await client.get(
            "/admin/share-tokens?status=active",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        # All returned tokens should be active (is_active=true and not expired)
        for token in data["tokens"]:
            assert token["is_active"] is True

    async def test_admin_filter_invalid_status_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /admin/share-tokens?status=invalid returns 422."""
        resp = await client.get(
            "/admin/share-tokens?status=invalid",
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_admin_share_tokens_requires_admin(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """GET /admin/share-tokens as viewer returns 403."""
        resp = await client.get(
            "/admin/share-tokens", headers=viewer_auth_header
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Dataset maps endpoint
# ---------------------------------------------------------------------------


async def _create_map_with_layer(
    client: AsyncClient,
    headers: dict,
    session,
    *,
    map_name: str,
    dataset_id: uuid.UUID,
    visibility: str = "private",
) -> dict:
    """Create a map, optionally set visibility, and add a dataset layer."""
    created = await _create_map(client, headers, map_name)
    map_id = created["id"]
    if visibility != "private":
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": visibility},
            headers=headers,
        )
    await client.post(
        f"/maps/{map_id}/layers/",
        json={"dataset_id": str(dataset_id)},
        headers=headers,
    )
    return created


class TestDatasetMaps:
    """Tests for GET /datasets/{id}/maps/ — maps containing a dataset."""

    async def test_dataset_maps_admin_sees_all(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
    ):
        """Admin sees all maps containing the dataset, including others' private maps."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="DM Admin DS"
        )

        # Admin creates a private map with this dataset
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Admin Private",
            dataset_id=ds.id,
            visibility="private",
        )
        # Editor creates a private map with this dataset
        await _create_map_with_layer(
            client,
            editor_auth_header,
            test_db_session,
            map_name="DM Editor Private",
            dataset_id=ds.id,
            visibility="private",
        )
        # Admin creates a public map
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Public Map",
            dataset_id=ds.id,
            visibility="public",
        )

        resp = await client.get(f"/datasets/{ds.id}/maps/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        names = {m["name"] for m in data["maps"]}
        assert "DM Admin Private" in names
        assert "DM Editor Private" in names
        assert "DM Public Map" in names
        assert data["total"] == len(data["maps"])

    async def test_dataset_maps_user_sees_own_internal_public(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
    ):
        """Regular user sees own maps + internal + public, not others' private."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="DM User DS"
        )

        # Admin creates a private map (editor should NOT see)
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM AdminOnly Private",
            dataset_id=ds.id,
            visibility="private",
        )
        # Admin creates an internal map (editor SHOULD see)
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Internal Map",
            dataset_id=ds.id,
            visibility="internal",
        )
        # Admin creates a public map (editor SHOULD see)
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Public Map2",
            dataset_id=ds.id,
            visibility="public",
        )
        # Editor creates own private map (editor SHOULD see)
        await _create_map_with_layer(
            client,
            editor_auth_header,
            test_db_session,
            map_name="DM Editor Own",
            dataset_id=ds.id,
            visibility="private",
        )

        resp = await client.get(f"/datasets/{ds.id}/maps/", headers=editor_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        names = {m["name"] for m in data["maps"]}
        assert "DM AdminOnly Private" not in names  # other user's private
        assert "DM Internal Map" in names
        assert "DM Public Map2" in names
        assert "DM Editor Own" in names

    async def test_dataset_maps_anonymous_sees_public_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Anonymous user sees only public maps."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="DM Anon DS"
        )

        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Anon Private",
            dataset_id=ds.id,
            visibility="private",
        )
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Anon Internal",
            dataset_id=ds.id,
            visibility="internal",
        )
        await _create_map_with_layer(
            client,
            admin_auth_header,
            test_db_session,
            map_name="DM Anon Public",
            dataset_id=ds.id,
            visibility="public",
        )

        resp = await client.get(f"/datasets/{ds.id}/maps/")
        assert resp.status_code == 200
        data = resp.json()
        names = {m["name"] for m in data["maps"]}
        assert "DM Anon Private" not in names
        assert "DM Anon Internal" not in names
        assert "DM Anon Public" in names

    async def test_dataset_maps_empty_result(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Dataset with no maps returns empty list."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="DM Empty DS"
        )

        resp = await client.get(f"/datasets/{ds.id}/maps/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["maps"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# layer_type round-trip
# ---------------------------------------------------------------------------


async def _create_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Raster Test DS",
    visibility: str = "public",
) -> Dataset:
    """Insert a Record + Dataset pair with record_type='raster_dataset'."""
    table_name = f"rds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Raster dataset for map tests: {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        record_type="raster_dataset",
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=None,
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


class TestLayerTypeRoundTrip:
    """Tests for layer_type persistence and auto-detection."""

    async def test_add_raster_layer_returns_raster_layer_type(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers/ with raster dataset returns layer_type='raster_geolens'."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_type"] == "raster_geolens"

    async def test_add_vector_layer_returns_vector_layer_type(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers/ with vector dataset returns layer_type='vector_geolens'."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_type"] == "vector_geolens"

    async def test_layer_type_round_trip_get(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET /maps/{id} returns layer_type='raster_geolens' for raster layers."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add raster layer
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        # GET map and verify layer_type persists
        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 200
        layers = resp.json()["layers"]
        assert len(layers) == 1
        assert layers[0]["layer_type"] == "raster_geolens"

    async def test_layer_type_auto_detect_via_put(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with raster layer omitting layer_type auto-detects to raster_geolens."""
        admin_id = await _get_user_id(test_db_session, "admin")
        raster_ds = await _create_raster_dataset(test_db_session, created_by=admin_id)
        vector_ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # PUT with layers but no layer_type specified
        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [
                    {"dataset_id": str(raster_ds.id), "sort_order": 0},
                    {"dataset_id": str(vector_ds.id), "sort_order": 1},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        layers = resp.json()["layers"]
        layer_types = {
            layer["dataset_id"]: layer["layer_type"] for layer in layers
        }
        assert layer_types[str(raster_ds.id)] == "raster_geolens"
        assert layer_types[str(vector_ds.id)] == "vector_geolens"

    async def test_layer_type_explicit_override(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with explicit layer_type persists the provided value."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer via add_layer endpoint with explicit layer_type
        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id), "layer_type": "raster_geolens"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_type"] == "raster_geolens"


class TestShowInLegendRoundTrip:
    """Tests for show_in_legend persistence."""

    async def test_new_layer_defaults_show_in_legend_true(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers/ defaults show_in_legend to true."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        assert resp.json()["show_in_legend"] is True

    async def test_show_in_legend_round_trip_via_put(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with show_in_legend=false persists and returns on GET."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer
        await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        # Update with show_in_legend=false
        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [
                    {"dataset_id": str(ds.id), "sort_order": 0, "show_in_legend": False},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        layers = resp.json()["layers"]
        assert len(layers) == 1
        assert layers[0]["show_in_legend"] is False

        # Verify it persists on GET
        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["layers"][0]["show_in_legend"] is False

    async def test_show_in_legend_defaults_true_when_omitted_in_put(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} without show_in_legend defaults to true."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [
                    {"dataset_id": str(ds.id), "sort_order": 0},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["layers"][0]["show_in_legend"] is True
