"""Integration tests for maps CRUD, duplication, sharing, and layer management.

Tests cover: create/list/get/update/delete maps, duplicate, share tokens,
shared map access, add/remove layers, and RBAC enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import (
    ADVANCED_SHARING_ERROR,
    MapLayerDiffRequest,
)
from app.modules.catalog.maps.service import create_share_token, update_share_token

from tests.factories import create_dataset, get_user_id


BASEMAP_CONFIG_PAYLOAD = {
    "label_mode": "subtle",
    "road_visibility": "subtle",
    "boundary_visibility": "hidden",
    "building_visibility": False,
    "land_water_tone": "muted",
    "relief_contrast": "strong",
    "opacity": 0.55,
    "background_color": None,
    # Phase 1059 BSE-01: sublayer_overrides field added to BasemapConfig
    # (jsonb-additive, defaults to None). Existing tests must include the
    # field in their expected payload so equality assertions match the
    # serialized response.
    "sublayer_overrides": None,
}


def test_basemap_config_opacity_defaults_to_one():
    from app.modules.catalog.maps.schemas import BasemapConfig

    cfg = BasemapConfig()
    assert cfg.opacity == 1.0


def test_basemap_config_opacity_accepts_valid_range():
    from app.modules.catalog.maps.schemas import BasemapConfig

    assert BasemapConfig(opacity=0.0).opacity == 0.0
    assert BasemapConfig(opacity=0.55).opacity == 0.55
    assert BasemapConfig(opacity=1.0).opacity == 1.0


def test_basemap_config_opacity_rejects_out_of_range():
    import pytest
    from pydantic import ValidationError

    from app.modules.catalog.maps.schemas import BasemapConfig

    with pytest.raises(ValidationError):
        BasemapConfig(opacity=-0.1)
    with pytest.raises(ValidationError):
        BasemapConfig(opacity=1.1)


def test_basemap_config_still_rejects_unknown_fields_with_opacity_set():
    import pytest
    from pydantic import ValidationError

    from app.modules.catalog.maps.schemas import BasemapConfig

    with pytest.raises(ValidationError):
        BasemapConfig(opacity=0.5, unknown_field=1)


def test_basemap_config_background_color_accepts_hex_or_null():
    from app.modules.catalog.maps.schemas import BasemapConfig

    assert BasemapConfig(background_color=None).background_color is None
    assert BasemapConfig(background_color="#f8fafc").background_color == "#f8fafc"
    assert BasemapConfig(background_color="#F8FAFC").background_color == "#F8FAFC"


def test_basemap_config_background_color_rejects_invalid_colors():
    import pytest
    from pydantic import ValidationError

    from app.modules.catalog.maps.schemas import BasemapConfig

    for value in ("red", "#abc", "#1234567", "javascript:alert(1)"):
        with pytest.raises(ValidationError):
            BasemapConfig(background_color=value)


def test_maps_service_facade_exports_public_api() -> None:
    """The public maps service facade preserves existing caller imports."""
    from app.modules.catalog.maps import service

    required = {
        "DatasetMeta",
        "LayerRow",
        "check_map_ownership",
        "get_dataset_meta",
        "generate_default_style",
        "create_map",
        "get_map",
        "get_map_with_layers",
        "list_maps",
        "update_map",
        "delete_map",
        "bulk_check_dataset_access",
        "duplicate_map",
        "add_layer",
        "remove_layer",
        "validate_public_visibility",
        "find_public_maps_using_dataset",
        "create_share_token",
        "update_share_token",
        "get_active_share_token",
        "get_shared_map",
        "list_share_tokens",
        "revoke_share_token",
        "get_maps_for_dataset",
        "revoke_share_token_by_map",
    }

    assert required.issubset(set(service.__all__))
    missing = {name for name in required if not hasattr(service, name)}
    assert missing == set()


def _future_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


def test_layer_diff_schema_rejects_duplicate_layer_ids() -> None:
    """MapLayerDiffRequest validates duplicate updated/removed/order IDs."""
    layer_id = uuid.uuid4()

    with pytest.raises(ValidationError, match="updated layer ids must be unique"):
        MapLayerDiffRequest.model_validate(
            {
                "updated": [
                    {"id": str(layer_id), "visible": False},
                    {"id": str(layer_id), "opacity": 0.5},
                ]
            }
        )

    with pytest.raises(ValidationError, match="removed layer ids must be unique"):
        MapLayerDiffRequest.model_validate({"removed": [str(layer_id), str(layer_id)]})

    with pytest.raises(ValidationError, match="order layer ids must be unique"):
        MapLayerDiffRequest.model_validate({"order": [str(layer_id), str(layer_id)]})


def test_layer_diff_schema_rejects_invalid_style_payload() -> None:
    """Diff patches reuse the clean-paint validation from layer inputs."""
    with pytest.raises(ValidationError, match="Unsupported private paint key"):
        MapLayerDiffRequest.model_validate(
            {
                "updated": [
                    {
                        "id": str(uuid.uuid4()),
                        "paint": {"_client-cache": "leak"},
                    }
                ]
            }
        )


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


def _valid_png_data_uri() -> str:
    """Return a small but VALID PNG data URI for thumbnail tests.

    Phase 273 SEC-12: PUT /maps/{id}/thumbnail/ now runs PIL.Image.verify()
    on the decoded base64 payload. The previous shorthand
    ``iVBORw0KGgo=`` was only the 8-byte PNG magic header — not a complete
    PNG — and is correctly rejected by the verify gate. Tests that just
    need *any* accepted thumbnail use this helper.
    """
    import base64
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (4, 4), color=(0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


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

    async def test_create_map_defaults_basemap_config_to_null(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Omitted basemap_config preserves existing saved-map behavior."""
        created = await _create_map(client, admin_auth_header)

        assert created["basemap_config"] is None
        assert created["show_basemap_labels"] is True

    async def test_create_map_persists_basemap_config(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/ accepts the strict curated basemap appearance contract."""
        resp = await client.post(
            "/maps/",
            json={
                "name": f"Basemap Config Map {uuid.uuid4().hex[:6]}",
                "basemap_config": BASEMAP_CONFIG_PAYLOAD,
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()["basemap_config"] == BASEMAP_CONFIG_PAYLOAD


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
        """GET /maps/ without auth returns 200 (public maps only)."""
        resp = await client.get("/maps/")
        assert resp.status_code == 200

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
        """GET /maps/{id} without auth returns 404 (anonymous access allowed, map not found)."""
        resp = await client.get(f"/maps/{uuid.uuid4()}")
        assert resp.status_code == 404


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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Restricted DS",
            visibility="restricted",
        )
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer referencing the non-public dataset
        await client.post(
            f"/maps/{map_id}/layers",
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
        assert (
            detail["message"]
            == "Cannot set visibility to public: map contains non-public datasets"
        )

    async def test_update_map_allows_public_with_all_public_datasets(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with visibility=public succeeds when all datasets are public."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Public DS",
            visibility="public",
        )
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.post(
            f"/maps/{map_id}/layers",
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

    async def test_update_map_round_trips_basemap_config(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT /maps/{id} stores and returns curated basemap appearance fields."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"basemap_config": BASEMAP_CONFIG_PAYLOAD},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["basemap_config"] == BASEMAP_CONFIG_PAYLOAD

        fetched = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert fetched.status_code == 200
        assert fetched.json()["basemap_config"] == BASEMAP_CONFIG_PAYLOAD

    async def test_update_map_round_trips_basemap_opacity_field(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Explicit opacity round-trip: PUT 0.55 -> GET 0.55 (covers PB-A3)."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"basemap_config": {**BASEMAP_CONFIG_PAYLOAD, "opacity": 0.55}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["basemap_config"]["opacity"] == 0.55

        fetched = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert fetched.status_code == 200
        assert fetched.json()["basemap_config"]["opacity"] == 0.55

    async def test_update_map_rejects_extra_basemap_config_fields(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """The basemap_config API rejects raw/unrecognized style-layer edits."""
        created = await _create_map(client, admin_auth_header)

        resp = await client.put(
            f"/maps/{created['id']}",
            json={"basemap_config": {**BASEMAP_CONFIG_PAYLOAD, "raw_layers": []}},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Map edit history
# ---------------------------------------------------------------------------


class TestMapHistory:
    async def test_history_records_map_updates_and_preserves_audit(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        created = await _create_map(client, admin_auth_header, "History Source")
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"name": "History Renamed", "center_lng": -73.99},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        history_resp = await client.get(
            f"/maps/{map_id}/history",
            headers=admin_auth_header,
        )
        assert history_resp.status_code == 200
        history = history_resp.json()
        assert history["skip"] == 0
        assert history["limit"] == 50

        events = history["events"]
        actions = {event["action"] for event in events}
        assert {"map.create", "map.rename", "map.config_update"}.issubset(actions)

        rename = next(event for event in events if event["action"] == "map.rename")
        assert rename["map_id"] == map_id
        assert rename["target_type"] == "map"
        assert rename["target_id"] == map_id
        assert rename["target_name"] == "History Renamed"
        assert rename["actor_username"] == "admin"
        assert rename["summary"] == "Renamed map to History Renamed"
        assert rename["details"]["previous"] == "History Source"
        assert rename["details"]["current"] == "History Renamed"

        audit_result = await test_db_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "map.update")
            .where(AuditLog.resource_id == uuid.UUID(map_id))
        )
        audit_log = audit_result.scalars().first()
        assert audit_log is not None
        assert set(audit_log.details["changed_fields"]) == {"name", "center_lng"}

    async def test_history_records_layer_diff_events(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds_a = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="History Layer A",
        )
        ds_b = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="History Layer B",
        )
        ds_c = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="History Layer C",
        )
        created = await _create_map(client, admin_auth_header, "Layer History Map")

        first_resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds_a.id)},
            headers=admin_auth_header,
        )
        second_resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds_b.id)},
            headers=admin_auth_header,
        )
        first_id = first_resp.json()["id"]
        second_id = second_resp.json()["id"]

        resp = await client.patch(
            f"/maps/{created['id']}/layers",
            json={
                "added": [
                    {
                        "dataset_id": str(ds_c.id),
                        "display_name": "Added via history diff",
                    }
                ],
                "updated": [
                    {
                        "id": first_id,
                        "visible": False,
                        "paint": {"fill-color": "#22c55e"},
                    }
                ],
                "removed": [second_id],
                "order": [first_id],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        history_resp = await client.get(
            f"/maps/{created['id']}/history",
            headers=admin_auth_header,
        )
        assert history_resp.status_code == 200
        events = history_resp.json()["events"]
        actions = {event["action"] for event in events}
        assert {
            "layer.add",
            "layer.visibility_update",
            "layer.style_update",
            "layer.remove",
            "layer.reorder",
        }.issubset(actions)

        style_event = next(
            event
            for event in events
            if event["action"] == "layer.style_update"
            and event["target_id"] == first_id
        )
        assert style_event["target_type"] == "layer"
        assert style_event["target_name"] == "History Layer A"
        assert "paint" in style_event["details"]["changed_fields"]

        remove_event = next(
            event
            for event in events
            if event["action"] == "layer.remove" and event["target_id"] == second_id
        )
        assert remove_event["target_name"] == "History Layer B"

    async def test_history_requires_builder_access(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        viewer_auth_header: dict,
    ):
        created = await _create_map(client, admin_auth_header, "Private History Map")
        map_id = created["id"]

        anon_resp = await client.get(f"/maps/{map_id}/history")
        assert anon_resp.status_code == 401

        viewer_resp = await client.get(
            f"/maps/{map_id}/history",
            headers=viewer_auth_header,
        )
        assert viewer_resp.status_code == 403

        editor_resp = await client.get(
            f"/maps/{map_id}/history",
            headers=editor_auth_header,
        )
        assert editor_resp.status_code == 403


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

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Original Map (copy)"
        assert data["id"] != map_id

    async def test_duplicate_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{random_uuid}/duplicate returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/duplicate/", headers=admin_auth_header
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
            f"/maps/{map_id}/duplicate/", headers=viewer_auth_header
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header, "Map With Layers")
        map_id = created["id"]

        # Add a layer
        await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        # Duplicate
        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_count"] == 1

    async def test_duplicate_lineage(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Fork records forked_from_id and forked_from_name."""
        created = await _create_map(client, admin_auth_header, "Source Map")
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
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
            f"/maps/{source_id}/duplicate/", headers=admin_auth_header
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

        r1 = await client.post(f"/maps/{map_id}/duplicate/", headers=admin_auth_header)
        assert r1.status_code == 201
        assert r1.json()["name"] == "Collision Test (copy)"

        r2 = await client.post(f"/maps/{map_id}/duplicate/", headers=admin_auth_header)
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
            f"/maps/{source_id}/duplicate/", headers=admin_auth_header
        )
        fork1_id = r1.json()["id"]
        assert r1.json()["name"] == "Chain Test (copy)"

        # Fork the fork
        r2 = await client.post(
            f"/maps/{fork1_id}/duplicate/", headers=admin_auth_header
        )
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
        admin_id = await get_user_id(test_db_session, "admin")

        # Create a public dataset and a private dataset (owned by admin)
        public_ds = await create_dataset(
            test_db_session, created_by=admin_id, name="Public DS", visibility="public"
        )
        private_ds = await create_dataset(
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
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(public_ds.id), "sort_order": 0},
            headers=admin_auth_header,
        )
        await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(private_ds.id), "sort_order": 1},
            headers=admin_auth_header,
        )

        # Fork as viewer -- should exclude private layer
        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=viewer_auth_header
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
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
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
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(private_ds.id)},
            headers=admin_auth_header,
        )

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=viewer_auth_header
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
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Admin Private DS",
            visibility="private",
        )

        created = await _create_map(client, admin_auth_header, "Admin Fork Test")
        map_id = created["id"]
        await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(private_ds.id)},
            headers=admin_auth_header,
        )

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
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

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
        assert resp.status_code == 201
        assert resp.json()["visibility"] == "private"

    async def test_get_forked_map_shows_lineage(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET on a forked map includes forked_from_id and forked_from_name."""
        created = await _create_map(client, admin_auth_header, "Lineage Source")
        source_id = created["id"]

        fork_resp = await client.post(
            f"/maps/{source_id}/duplicate/", headers=admin_auth_header
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
        admin_id = await get_user_id(test_db_session, "admin")
        pub_ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Count Pub DS",
            visibility="public",
        )
        priv_ds1 = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Count Priv DS1",
            visibility="private",
        )
        priv_ds2 = await create_dataset(
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
                f"/maps/{map_id}/layers",
                json={"dataset_id": str(ds_id), "sort_order": order},
                headers=admin_auth_header,
            )

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=viewer_auth_header
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

        # Set a thumbnail on source (SEC-12: must be a real PNG that
        # PIL.Image.verify() accepts — see _valid_png_data_uri docstring)
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _valid_png_data_uri()},
            headers=admin_auth_header,
        )

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
        assert resp.status_code == 201
        assert resp.json()["thumbnail_url"] is None

    async def test_duplicate_preserves_widgets(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Duplicate copies the source map's widget list."""
        created = await _create_map(client, admin_auth_header, "Widget Map")
        map_id = created["id"]

        # Set widgets on source
        widget_ids = ["legend", "measurement"]
        resp = await client.put(
            f"/maps/{map_id}",
            json={"widgets": widget_ids},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["widgets"] == widget_ids

        # Duplicate
        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )
        assert resp.status_code == 201
        assert resp.json()["widgets"] == widget_ids

    async def test_update_map_widgets(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT /maps/{id} can set and clear the widgets list."""
        created = await _create_map(client, admin_auth_header, "Widgets Test")
        map_id = created["id"]

        # Initially null
        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.json()["widgets"] is None

        # Set widgets
        resp = await client.put(
            f"/maps/{map_id}",
            json={"widgets": ["measurement"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["widgets"] == ["measurement"]

        # Clear widgets
        resp = await client.put(
            f"/maps/{map_id}",
            json={"widgets": []},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["widgets"] == []

        # Restore client defaults
        resp = await client.put(
            f"/maps/{map_id}",
            json={"widgets": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["widgets"] is None


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

        resp = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
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
        resp = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "share_url" in data
        assert data["is_active"] is True

    async def test_share_expiration_requires_enterprise(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        community_edition,
    ):
        """Community cannot create expiring share links."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        resp = await client.post(
            f"/maps/{map_id}/share/",
            json={"expires_at": _future_expires_at().isoformat()},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert ADVANCED_SHARING_ERROR in resp.text

    async def test_share_expiration_allowed_in_enterprise(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        enterprise_edition,
    ):
        """Enterprise can create expiring share links."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]
        expires_at = _future_expires_at()

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        resp = await client.post(
            f"/maps/{map_id}/share/",
            json={"expires_at": expires_at.isoformat()},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200
        assert resp.json()["expires_at"] is not None

    async def test_share_idempotent(self, client: AsyncClient, admin_auth_header: dict):
        """POST /maps/{id}/share twice — second call returns the token hint (hashed storage)."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )

        resp1 = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        resp2 = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        # First call returns the full raw token; subsequent calls return the
        # 8-char hint (the raw token is not persisted after hashing).
        full_token = resp1.json()["token"]
        hint = resp2.json()["token"]
        assert full_token.startswith(hint)
        assert len(hint) == 8

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
        await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)

        resp = await client.delete(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert resp.status_code == 204

    async def test_revoke_share_no_token(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /maps/{id}/share with no active token returns 404."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.delete(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_share_map_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /maps/{random_uuid}/share returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/share/", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_share_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /maps/{id}/share as viewer returns 403."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/share/", headers=viewer_auth_header
        )
        assert resp.status_code == 403

    async def test_get_share_token_non_owner_forbidden(
        self, client: AsyncClient, admin_auth_header: dict, viewer_auth_header: dict
    ):
        """GET /maps/{id}/share as non-owner returns 403."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Make public and create share token as owner
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)

        # Viewer (non-owner) should not be able to read the share token
        resp = await client.get(f"/maps/{map_id}/share/", headers=viewer_auth_header)
        assert resp.status_code == 403

    async def test_admin_revoke_share_token_cascades_embed_tokens(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """DELETE /admin/share-tokens/{id} cascades to deactivate embed tokens."""
        # Create a public map with a share token
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        assert share_resp.status_code == 200

        # Fetch share token ID via admin listing (POST response doesn't include id)
        admin_list = await client.get(
            "/admin/share-tokens/?limit=50", headers=admin_auth_header
        )
        share_token_id = next(
            t["id"] for t in admin_list.json()["tokens"] if t["map_id"] == map_id
        )

        # Create an embed token for the map (requires layers for dataset scope).
        # Use the ORM directly to create a minimal dataset + layer for the embed token.
        from app.modules.catalog.datasets.domain.models import Dataset, Record
        from app.modules.catalog.maps.models import MapLayer

        record = Record(
            title="Cascade Test DS",
            summary="For embed cascade test",
            visibility="public",
            record_status="published",
            theme_category=["test"],
            created_by=(
                await test_db_session.execute(
                    select(User).where(User.username == "admin")
                )
            )
            .scalar_one()
            .id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(record_id=record.id, table_name="data.cascade_test")
        test_db_session.add(dataset)
        await test_db_session.flush()
        layer = MapLayer(map_id=uuid.UUID(map_id), dataset_id=dataset.id)
        test_db_session.add(layer)
        await test_db_session.commit()

        embed_resp = await client.post(
            f"/maps/{map_id}/embed-tokens/",
            json={"name": "Cascade Test Embed"},
            headers=admin_auth_header,
        )
        assert embed_resp.status_code == 201
        embed_token_id = embed_resp.json()["id"]

        # Admin revokes the share token via admin endpoint
        revoke_resp = await client.delete(
            f"/admin/share-tokens/{share_token_id}",
            headers=admin_auth_header,
        )
        assert revoke_resp.status_code == 204

        # Verify the embed token was cascade-deactivated
        embed_list = await client.get(
            f"/maps/{map_id}/embed-tokens/", headers=admin_auth_header
        )
        tokens = embed_list.json()["tokens"]
        cascade_token = [t for t in tokens if t["id"] == embed_token_id]
        assert len(cascade_token) == 1
        assert cascade_token[0]["is_active"] is False


class TestShareTokenServiceGuards:
    """Service-layer guards for schema bypasses."""

    async def test_create_share_expiration_guard_runs_before_db_lookup(
        self, community_edition
    ):
        with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
            await create_share_token(
                object(),
                uuid.uuid4(),
                uuid.uuid4(),
                expires_at=_future_expires_at(),
            )

    async def test_update_share_expiration_guard_runs_before_db_lookup(
        self, community_edition
    ):
        with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
            await update_share_token(
                object(),
                uuid.uuid4(),
                _future_expires_at(),
            )


# ---------------------------------------------------------------------------
# Get shared map
# ---------------------------------------------------------------------------


class TestSharedMap:
    async def test_get_shared_map_success(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /maps/shared/{token} returns map data."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header, "Shared Map")
        map_id = created["id"]

        layer_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert layer_resp.status_code == 201
        layer_id = layer_resp.json()["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        token = share_resp.json()["token"]

        # Access shared map (no auth required)
        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Shared Map"
        assert "layers" in data
        assert data["layers"][0]["id"] == layer_id
        assert "basemap_style" in data

    async def test_get_shared_map_includes_basemap_config(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Public share payloads include persisted basemap appearance metadata."""
        created = await _create_map(client, admin_auth_header, "Shared Basemap Map")
        map_id = created["id"]

        put_resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public", "basemap_config": BASEMAP_CONFIG_PAYLOAD},
            headers=admin_auth_header,
        )
        assert put_resp.status_code == 200
        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        token = share_resp.json()["token"]

        resp = await client.get(f"/maps/shared/{token}")

        assert resp.status_code == 200
        assert resp.json()["basemap_config"] == BASEMAP_CONFIG_PAYLOAD

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
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        token = share_resp.json()["token"]

        # Revoke
        await client.delete(f"/maps/{map_id}/share/", headers=admin_auth_header)

        # Access revoked token
        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 410

    async def test_get_shared_map_expired_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /maps/shared/{token} with a past expires_at returns 410."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import text

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        token = share_resp.json()["token"]

        # Backdate expires_at to the past via direct SQL (token is now hashed)
        import hashlib

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await test_db_session.execute(
            text(
                "UPDATE catalog.map_share_tokens SET expires_at = :past "
                "WHERE token_hash = :tok_hash"
            ),
            {"past": past, "tok_hash": token_hash},
        )
        await test_db_session.commit()

        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 410
        assert "expired" in resp.json()["detail"].lower()


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
        """POST /maps/{id}/layers adds a layer."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["dataset_id"] == str(ds.id)
        assert data["visible"] is True
        assert data["opacity"] == 1.0
        assert "id" in data

    async def test_add_layer_assigns_next_sort_order_when_omitted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers assigns unique order when sort_order is omitted."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds_a = await create_dataset(test_db_session, created_by=admin_id)
        ds_b = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        first_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds_a.id)},
            headers=admin_auth_header,
        )
        second_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds_b.id)},
            headers=admin_auth_header,
        )

        assert first_resp.status_code == 201
        assert second_resp.status_code == 201
        assert first_resp.json()["sort_order"] == 0
        assert second_resp.json()["sort_order"] == 1

    async def test_add_layer_duplicate_dataset_omitted_order_stays_distinct(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Duplicate dataset layers get stable identity through unique sort order."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        first_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        second_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        assert first_resp.status_code == 201
        assert second_resp.status_code == 201
        first = first_resp.json()
        second = second_resp.json()
        assert first["id"] != second["id"]
        assert [first["sort_order"], second["sort_order"]] == [0, 1]

    async def test_add_layer_map_not_found(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """POST /maps/{random_uuid}/layers returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/layers",
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer
        add_resp = await client.post(
            f"/maps/{map_id}/layers",
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

    async def test_remove_layer_rejects_layer_outside_map(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """DELETE /maps/{id}/layers/{layer_id} is scoped to the requested map."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        source = await _create_map(client, admin_auth_header, "Remove Source")
        target = await _create_map(client, admin_auth_header, "Remove Target")

        add_resp = await client.post(
            f"/maps/{source['id']}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert add_resp.status_code == 201
        layer_id = add_resp.json()["id"]

        resp = await client.delete(
            f"/maps/{target['id']}/layers/{layer_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

        map_resp = await client.get(f"/maps/{source['id']}", headers=admin_auth_header)
        assert map_resp.json()["layer_count"] == 1

    async def test_add_layer_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
    ):
        """POST /maps/{id}/layers as viewer returns 403."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/layers",
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
        """POST /maps/{id}/layers with custom paint/layout stores them."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        custom_paint = {"circle-radius": 10, "circle-color": "#ff0000"}
        custom_layout = {"visibility": "visible"}

        resp = await client.post(
            f"/maps/{map_id}/layers",
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

    async def test_add_layer_moves_legacy_builder_paint_to_style_config(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers accepts known legacy paint keys but stores clean paint."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers",
            json={
                "dataset_id": str(ds.id),
                "paint": {
                    "fill-color": "#ef4444",
                    "fill-opacity": 0,
                    "_fill-disabled": True,
                    "_outline-color": "#111827",
                    "_outline-width": 2,
                },
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["paint"] == {"fill-color": "#ef4444", "fill-opacity": 0}
        assert data["style_config"]["builder"] == {
            "fill_disabled": True,
            "outline_color": "#111827",
            "outline_width": 2,
        }

        stored = await test_db_session.get(MapLayer, uuid.UUID(data["id"]))
        assert stored is not None
        assert stored.paint == data["paint"]
        assert stored.style_config == data["style_config"]

    async def test_add_layer_rejects_unknown_private_paint_key(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers rejects private paint keys outside the rollout allowlist."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)

        resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds.id), "paint": {"_client-cache": "leak"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_add_layer_default_polygon_style_uses_style_config(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Default polygon style stores MapLibre paint and builder outline state separately."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)

        resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["paint"] == {"fill-color": "#3b82f6", "fill-opacity": 0.3}
        assert data["style_config"] == {
            "builder": {"outline_color": "#1d4ed8", "outline_width": 1}
        }

    async def test_update_map_layers_moves_legacy_builder_paint_to_style_config(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} full replacement keeps legacy builder state out of paint."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)

        resp = await client.put(
            f"/maps/{created['id']}",
            json={
                "layers": [
                    {
                        "dataset_id": str(ds.id),
                        "paint": {
                            "fill-color": "#22c55e",
                            "fill-opacity": 0,
                            "outline-color": "#0f172a",
                            "outline-width": 3,
                            "_fill-opacity-saved": 0.45,
                        },
                        "style_config": {
                            "mode": "categorized",
                            "builder": {"outline_width": 9},
                        },
                    }
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        layer = resp.json()["layers"][0]
        assert layer["paint"] == {"fill-color": "#22c55e", "fill-opacity": 0}
        assert layer["style_config"] == {
            "mode": "categorized",
            "builder": {
                "outline_width": 9,
                "outline_color": "#0f172a",
                "fill_opacity_saved": 0.45,
            },
        }

    async def test_patch_map_layers_applies_diff_and_preserves_stable_ids(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /maps/{id}/layers can add, update, remove, and reorder layers."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds_a = await create_dataset(
            test_db_session, created_by=admin_id, name="Layer Diff A"
        )
        ds_b = await create_dataset(
            test_db_session, created_by=admin_id, name="Layer Diff B"
        )
        ds_c = await create_dataset(
            test_db_session, created_by=admin_id, name="Layer Diff C"
        )
        created = await _create_map(client, admin_auth_header)

        first_resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds_a.id), "sort_order": 5},
            headers=admin_auth_header,
        )
        second_resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds_b.id), "sort_order": 6},
            headers=admin_auth_header,
        )
        first_id = first_resp.json()["id"]
        second_id = second_resp.json()["id"]

        resp = await client.patch(
            f"/maps/{created['id']}/layers",
            json={
                "added": [
                    {
                        "dataset_id": str(ds_c.id),
                        "sort_order": 1,
                        "display_name": "Added via diff",
                    }
                ],
                "updated": [
                    {
                        "id": first_id,
                        "visible": False,
                        "paint": {
                            "fill-color": "#22c55e",
                            "_outline-color": "#0f172a",
                        },
                    }
                ],
                "removed": [second_id],
                "order": [first_id],
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        layers = resp.json()["layers"]
        assert [layer["sort_order"] for layer in layers] == [0, 1]
        assert [layer["id"] for layer in layers][0] == first_id
        assert second_id not in {layer["id"] for layer in layers}

        updated = layers[0]
        assert updated["visible"] is False
        assert updated["paint"] == {"fill-color": "#22c55e"}
        assert updated["style_config"] == {"builder": {"outline_color": "#0f172a"}}

        added = layers[1]
        assert added["dataset_id"] == str(ds_c.id)
        assert added["display_name"] == "Added via diff"

        stored_first = await test_db_session.get(MapLayer, uuid.UUID(first_id))
        assert stored_first is not None
        assert stored_first.id == uuid.UUID(first_id)
        assert stored_first.sort_order == 0

        audit_result = await test_db_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "map.patch_layers")
            .where(AuditLog.resource_id == uuid.UUID(created["id"]))
            .order_by(AuditLog.created_at.desc())
        )
        audit_log = audit_result.scalars().first()
        assert audit_log is not None
        assert audit_log.details["added"] == 1
        assert audit_log.details["updated"] == [first_id]
        assert audit_log.details["removed"] == [second_id]

    async def test_map_layers_patch_rejects_layer_outside_map(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /maps/{id}/layers rejects updates scoped to another map."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        source = await _create_map(client, admin_auth_header, "Source Diff Map")
        target = await _create_map(client, admin_auth_header, "Target Diff Map")

        add_resp = await client.post(
            f"/maps/{source['id']}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        resp = await client.patch(
            f"/maps/{target['id']}/layers",
            json={
                "updated": [
                    {"id": add_resp.json()["id"], "visible": False},
                ]
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 400
        assert "outside this map" in resp.json()["detail"]

    async def test_full_replacement_still_recreates_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with layers remains a full delete/recreate fallback."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds_a = await create_dataset(
            test_db_session, created_by=admin_id, name="Full Replace A"
        )
        ds_b = await create_dataset(
            test_db_session, created_by=admin_id, name="Full Replace B"
        )
        created = await _create_map(client, admin_auth_header)

        add_resp = await client.post(
            f"/maps/{created['id']}/layers",
            json={"dataset_id": str(ds_a.id)},
            headers=admin_auth_header,
        )
        old_layer_id = add_resp.json()["id"]

        resp = await client.put(
            f"/maps/{created['id']}",
            json={"layers": [{"dataset_id": str(ds_b.id), "sort_order": 0}]},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        layers = resp.json()["layers"]
        assert len(layers) == 1
        assert layers[0]["dataset_id"] == str(ds_b.id)
        assert layers[0]["id"] != old_layer_id
        assert await test_db_session.get(MapLayer, uuid.UUID(old_layer_id)) is None


class TestMapLayersTrailingSlash:
    """Phase 280: POST /maps/{id}/layers must accept the trailing-slash form
    directly (no 307 redirect) so host-side fetch callers — Node test
    runners, third-party SDKs, curl clients — never resolve the relative
    Location header against the in-container ``api:8000`` Host.

    The canonical OpenAPI form is the no-slash sub-collection convention
    from ``docs/api-style.md``; the trailing-slash form is a hidden alias
    declared on the same handler. The trailing-slash regression guard
    below is the load-bearing one — it would have caught the 260508-d6i
    smoke failure (#5, #6). The parity guard ensures both decorators
    stay wired to the same handler with the same response contract.
    """

    async def test_add_layer_with_trailing_slash(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Trailing-slash form returns 201 directly — no 307 redirect.

        This is the regression guard for the 260508-d6i smoke failure.
        Reverting the alias decorator on ``add_layer_endpoint`` makes
        this test fail with status_code=307.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
            follow_redirects=False,
        )
        # Name the 307 regression mode explicitly before the generic
        # equality check so a future failure log states the cause directly.
        assert resp.status_code != 307, (
            "307 regression: trailing-slash decorator missing on "
            f"add_layer_endpoint; Location={resp.headers.get('location')!r}"
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}; "
            f"location={resp.headers.get('location')!r}"
        )
        # No redirect Location header should be emitted on the direct
        # 201 path. (If one IS emitted by a future regression, fail
        # loudly and surface the leak signature so the failure log
        # documents the in-container hostname leak the alias prevents.)
        location = resp.headers.get("location")
        assert location is None, (
            f"Unexpected Location header on direct 201: {location!r} "
            "— alias decorator missing or ordering changed"
        )

    async def test_add_layer_slash_variants_parity(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Slash and no-slash variants accept the same payload and produce
        equivalent response shapes (same fields, same dataset_id).

        Guards against future divergence between the canonical no-slash
        decorator and the trailing-slash alias — e.g., someone adding a
        response_model override to one decorator but not the other.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        payload = {"dataset_id": str(ds.id)}

        resp_no_slash = await client.post(
            f"/maps/{map_id}/layers",
            json=payload,
            headers=admin_auth_header,
            follow_redirects=False,
        )
        resp_with_slash = await client.post(
            f"/maps/{map_id}/layers/",
            json=payload,
            headers=admin_auth_header,
            follow_redirects=False,
        )

        # Both variants must succeed directly — no 307 from either form.
        assert resp_no_slash.status_code == 201, (
            f"No-slash form: expected 201, got {resp_no_slash.status_code}"
        )
        assert resp_with_slash.status_code == 201, (
            f"Trailing-slash form: expected 201, got {resp_with_slash.status_code}"
        )

        body_no_slash = resp_no_slash.json()
        body_with_slash = resp_with_slash.json()

        # Same response shape (same set of top-level keys).
        assert set(body_no_slash.keys()) == set(body_with_slash.keys()), (
            f"Response shape diverged between slash variants: "
            f"no_slash={sorted(body_no_slash.keys())!r} "
            f"with_slash={sorted(body_with_slash.keys())!r}"
        )

        # Same dataset_id round-tripped (the ID itself differs because
        # each POST creates a fresh layer row).
        assert body_no_slash["dataset_id"] == str(ds.id)
        assert body_with_slash["dataset_id"] == str(ds.id)

    async def test_patch_layers_with_trailing_slash(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """v13.14 fixup: PATCH /maps/{id}/layers/ must also accept the
        trailing-slash form directly. Phase 280 only fixed POST; this guard
        covers the sibling PATCH endpoint so future programmatic callers
        don't hit the same 307 / in-container hostname leak.

        Without the alias decorator on ``patch_map_layers_endpoint``, the
        trailing-slash form returns 405 Method Not Allowed (because POST
        is registered on /layers/ but PATCH is not), or 307 if FastAPI's
        redirect_slashes kicks in. Either failure breaks programmatic
        clients.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session, created_by=admin_id, name="PATCH Slash"
        )
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Empty diff body — exercises only the routing/method dispatch.
        resp = await client.patch(
            f"/maps/{map_id}/layers/",
            json={"added": [], "updated": [], "removed": [], "order": None},
            headers=admin_auth_header,
            follow_redirects=False,
        )

        assert resp.status_code == 200, (
            f"PATCH /maps/.../layers/ should not 307/405; got {resp.status_code} body={resp.text}"
        )
        assert "location" not in {k.lower() for k in resp.headers.keys()}
        location = resp.headers.get("location", "")
        assert "api:8000" not in location and "://api/" not in location, (
            f"in-container hostname leak: {location!r}"
        )

        # Sanity — non-slash form still works (canonical, OpenAPI-listed).
        resp_no_slash = await client.patch(
            f"/maps/{map_id}/layers",
            json={
                "added": [{"dataset_id": str(ds.id)}],
                "updated": [],
                "removed": [],
                "order": None,
            },
            headers=admin_auth_header,
            follow_redirects=False,
        )
        assert resp_no_slash.status_code == 200


# ---------------------------------------------------------------------------
# Thumbnail upload/retrieve
# ---------------------------------------------------------------------------


class TestMapThumbnail:
    async def test_upload_thumbnail(self, client: AsyncClient, admin_auth_header: dict):
        """PUT /maps/{id}/thumbnail/ uploads a thumbnail and returns 204."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # SEC-12: payload must pass PIL.Image.verify() — see
        # _valid_png_data_uri helper for the rationale.
        resp = await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _valid_png_data_uri()},
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

    async def test_upload_thumbnail_bumps_updated_at(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Thumbnail refreshes must invalidate map-card thumbnail caches."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]
        before = created["updated_at"]

        resp = await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _valid_png_data_uri()},
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

        refreshed = await client.get(f"/maps/{map_id}", headers=admin_auth_header)

        assert refreshed.status_code == 200
        assert refreshed.json()["updated_at"] != before

    async def test_get_thumbnail_after_upload(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/{id}/thumbnail/ returns image data after upload."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        upload_resp = await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _valid_png_data_uri()},
            headers=admin_auth_header,
        )
        assert upload_resp.status_code == 204

        resp = await client.get(
            f"/maps/{map_id}/thumbnail/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] in ("image/png", "image/jpeg")

    async def test_get_thumbnail_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /maps/{id}/thumbnail/ returns 404 when no thumbnail uploaded."""
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.get(
            f"/maps/{map_id}/thumbnail/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_upload_thumbnail_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """PUT /maps/{id}/thumbnail/ as viewer returns 403."""
        resp = await client.put(
            f"/maps/{uuid.uuid4()}/thumbnail/",
            json={"data_uri": "data:image/png;base64,iVBORw0KGgo="},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_upload_thumbnail_unauthenticated(self, client: AsyncClient):
        """PUT /maps/{id}/thumbnail/ without auth returns 401."""
        resp = await client.put(
            f"/maps/{uuid.uuid4()}/thumbnail/",
            json={"data_uri": "data:image/png;base64,iVBORw0KGgo="},
        )
        assert resp.status_code == 401


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
        from app.modules.catalog.maps.models import Map
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

    async def test_list_maps_invalid_sort_by_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Invalid sort_by value is rejected with 422 (Literal validation)."""
        resp = await client.get(
            "/maps/", params={"sort_by": "bogus_field"}, headers=admin_auth_header
        )
        assert resp.status_code == 422

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
            f"/maps/{map_id}/visibility-check/", headers=admin_auth_header
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
            f"/maps/{uuid.uuid4()}/visibility-check/",
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
    share_resp = await client.post(f"/maps/{map_id}/share/", headers=headers)
    token = share_resp.json()["token"]
    return map_id, token


class TestUpdateShareToken:
    pytestmark = pytest.mark.usefixtures("enterprise_edition")

    async def test_patch_share_token_set_expiration(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH /maps/{id}/share with expires_at returns 200 with updated expiration."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        resp = await client.patch(
            f"/maps/{map_id}/share/",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "2026-06-01" in data["expires_at"]
        # PATCH returns the token hint (8-char prefix), not the full raw token
        assert original_token.startswith(data["token"])

    async def test_patch_share_token_remove_expiration(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH /maps/{id}/share with expires_at=null removes expiration."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        # First set an expiration
        await client.patch(
            f"/maps/{map_id}/share/",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        # Now remove it
        resp = await client.patch(
            f"/maps/{map_id}/share/",
            json={"expires_at": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["expires_at"] is None
        # PATCH returns the token hint (8-char prefix), not the full raw token
        assert original_token.startswith(data["token"])

    async def test_patch_share_token_add_expiration_to_never_expires(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PATCH with expires_at on a never-expires token adds expiration."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        # Token was created without expiration (never expires)
        resp = await client.patch(
            f"/maps/{map_id}/share/",
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
            f"/maps/{map_id}/share/",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_patch_share_token_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """PATCH /maps/{id}/share as viewer returns 403."""
        resp = await client.patch(
            f"/maps/{uuid.uuid4()}/share/",
            json={"expires_at": "2026-06-01T00:00:00Z"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_patch_share_token_preserves_token_string(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Token hint does not change after PATCH (same underlying token)."""
        map_id, original_token = await _make_public_map_with_share_token(
            client, admin_auth_header
        )
        resp = await client.patch(
            f"/maps/{map_id}/share/",
            json={"expires_at": "2026-12-31T00:00:00Z"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        # PATCH returns the token hint; the original full token starts with it
        assert original_token.startswith(resp.json()["token"])


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

        resp = await client.get("/admin/share-tokens/", headers=admin_auth_header)
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
        """GET /admin/share-tokens/?search=... filters by map name."""
        # Create a map with a unique name and share it
        unique_name = f"SearchTest_{uuid.uuid4().hex[:6]}"
        created = await _create_map(client, admin_auth_header, name=unique_name)
        map_id = created["id"]
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)

        # Search for the unique name
        resp = await client.get(
            f"/admin/share-tokens/?search={unique_name}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(unique_name in t["map_name"] for t in data["tokens"])

        # Search for nonexistent name
        resp = await client.get(
            "/admin/share-tokens/?search=zzz_nonexistent_xyz",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_admin_filter_share_tokens_by_status(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /admin/share-tokens/?status=active returns only active tokens."""
        await _make_public_map_with_share_token(client, admin_auth_header)

        resp = await client.get(
            "/admin/share-tokens/?status=active",
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
        """GET /admin/share-tokens/?status=invalid returns 422."""
        resp = await client.get(
            "/admin/share-tokens/?status=invalid",
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_admin_share_tokens_requires_admin(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """GET /admin/share-tokens as viewer returns 403."""
        resp = await client.get("/admin/share-tokens/", headers=viewer_auth_header)
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
        f"/maps/{map_id}/layers",
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
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
        """POST /maps/{id}/layers with raster dataset returns layer_type='raster_geolens'."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers",
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
        """POST /maps/{id}/layers with vector dataset returns layer_type='vector_geolens'."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers",
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_raster_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add raster layer
        await client.post(
            f"/maps/{map_id}/layers",
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
        admin_id = await get_user_id(test_db_session, "admin")
        raster_ds = await _create_raster_dataset(test_db_session, created_by=admin_id)
        vector_ds = await create_dataset(test_db_session, created_by=admin_id)

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
        layer_types = {layer["dataset_id"]: layer["layer_type"] for layer in layers}
        assert layer_types[str(raster_ds.id)] == "raster_geolens"
        assert layer_types[str(vector_ds.id)] == "vector_geolens"

    async def test_layer_type_explicit_override(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PUT /maps/{id} with explicit layer_type persists the provided value."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer via add_layer endpoint with explicit layer_type
        resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id), "layer_type": "raster_geolens"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["layer_type"] == "raster_geolens"


async def test_update_map_layers_round_trip_sort_order(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PUT layers with sort_order=[2, 0, 1] -> response layers must be [0, 1, 2].

    Locks MapLayer.sort_order ordering through the PUT round-trip after the
    PERF-6 service-level refactor (build response from in-session state).
    Existing tests use dict[str, str] keyed by dataset_id (e.g.
    test_layer_type_auto_detect_via_put) and lose list order, so a focused
    list-order assertion is required.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds_a = await create_dataset(test_db_session, created_by=admin_id)
    ds_b = await create_dataset(test_db_session, created_by=admin_id)
    ds_c = await create_dataset(test_db_session, created_by=admin_id)

    created = await _create_map(client, admin_auth_header)
    map_id = created["id"]

    # Intentionally out-of-order in the request body so we don't accidentally
    # rely on insertion order. Sort_order values are explicit.
    resp = await client.put(
        f"/maps/{map_id}",
        json={
            "layers": [
                {"dataset_id": str(ds_a.id), "sort_order": 2},
                {"dataset_id": str(ds_b.id), "sort_order": 0},
                {"dataset_id": str(ds_c.id), "sort_order": 1},
            ]
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    layers = resp.json()["layers"]
    assert len(layers) == 3
    # The response must come back ordered by sort_order ascending [0, 1, 2].
    assert [layer["sort_order"] for layer in layers] == [0, 1, 2]
    # And the dataset bound to each sort_order should match what we PUT.
    by_order = {layer["sort_order"]: layer["dataset_id"] for layer in layers}
    assert by_order[0] == str(ds_b.id)
    assert by_order[1] == str(ds_c.id)
    assert by_order[2] == str(ds_a.id)


class TestShowInLegendRoundTrip:
    """Tests for show_in_legend persistence."""

    async def test_new_layer_defaults_show_in_legend_true(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/{id}/layers defaults show_in_legend to true."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers",
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        created = await _create_map(client, admin_auth_header)
        map_id = created["id"]

        # Add layer
        await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

        # Update with show_in_legend=false
        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [
                    {
                        "dataset_id": str(ds.id),
                        "sort_order": 0,
                        "show_in_legend": False,
                    },
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
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


# ---------------------------------------------------------------------------
# Style JSON import round-trip — terrain persistence (NEW-INT-01 regression)
# ---------------------------------------------------------------------------


class TestImportStyleJsonTerrain:
    """POST /maps/import must persist terrain_config from imported style JSON.

    Closes NEW-INT-01: prior to this test, the parser correctly populated
    ImportedStyleMap.terrain_config but the import endpoint never assigned
    it onto the persisted Map, so STYLEX-02 / FLOW-03 silently broke at the
    HTTP boundary while parser-level unit tests passed.
    """

    async def test_import_style_with_top_level_terrain_persists_terrain_config(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/import with top-level terrain block sets map.terrain_config."""
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dataset(test_db_session, created_by=admin_id)
        source_id = f"geolens-{dem.id}"

        style = {
            "version": 8,
            "name": "Imported terrain map",
            "metadata": {"geolens": {"description": "DEM hillshade with terrain"}},
            "sources": {
                source_id: {
                    "type": "raster-dem",
                    "tiles": [f"/raster-tiles/{dem.id}/tiles/{{z}}/{{x}}/{{y}}.png"],
                    "tileSize": 256,
                    "encoding": "mapbox",
                    "metadata": {
                        "geolens": {
                            "dataset_id": str(dem.id),
                            "table_name": dem.table_name,
                            "geometry_type": None,
                            "record_type": "raster_dataset",
                        }
                    },
                }
            },
            "layers": [
                {
                    "id": "layer-dem",
                    "type": "hillshade",
                    "source": source_id,
                    "metadata": {
                        "geolens": {
                            "dataset_id": str(dem.id),
                            "layer_id": str(uuid.uuid4()),
                            "layer_type": "raster_geolens",
                            "sort_order": 0,
                        }
                    },
                    "paint": {"hillshade-exaggeration": 0.5},
                    "layout": {},
                }
            ],
            "terrain": {"source": source_id, "exaggeration": 2.5},
        }

        resp = await client.post("/maps/import", json=style, headers=admin_auth_header)
        assert resp.status_code == 201, f"Import failed: {resp.text}"
        body = resp.json()
        terrain = body["map"]["terrain_config"]
        assert terrain is not None, "terrain_config dropped by import endpoint"
        assert terrain["enabled"] is True
        assert terrain["source_dataset_id"] == str(dem.id)
        assert terrain["exaggeration"] == 2.5

    async def test_import_style_without_terrain_leaves_terrain_config_null(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /maps/import without terrain block leaves terrain_config as None."""
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dataset(test_db_session, created_by=admin_id)
        source_id = f"geolens-{dem.id}"

        style = {
            "version": 8,
            "name": "Imported map without terrain",
            "metadata": {"geolens": {}},
            "sources": {
                source_id: {
                    "type": "raster",
                    "tiles": [f"/raster-tiles/{dem.id}/tiles/{{z}}/{{x}}/{{y}}.png"],
                    "tileSize": 256,
                    "metadata": {
                        "geolens": {
                            "dataset_id": str(dem.id),
                            "table_name": dem.table_name,
                            "geometry_type": None,
                            "record_type": "raster_dataset",
                        }
                    },
                }
            },
            "layers": [
                {
                    "id": "layer-raster",
                    "type": "raster",
                    "source": source_id,
                    "metadata": {
                        "geolens": {
                            "dataset_id": str(dem.id),
                            "layer_id": str(uuid.uuid4()),
                            "layer_type": "raster_geolens",
                            "sort_order": 0,
                        }
                    },
                    "paint": {},
                    "layout": {},
                }
            ],
        }

        resp = await client.post("/maps/import", json=style, headers=admin_auth_header)
        assert resp.status_code == 201, f"Import failed: {resp.text}"
        body = resp.json()
        assert body["map"]["terrain_config"] is None
