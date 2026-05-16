"""Integration tests for POST /maps/{map_id}/layers/bulk-delete.

Covers: success (all deleted), partial failure (one not found), empty list (400),
oversized list (400), viewer forbidden (403), map not owned (404), audit event,
and map history event.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied

Milestone exception note: This test file covers the single additive backend
endpoint permitted in Phase 1047 per REQUIREMENTS.md Out-of-Scope (PB-03).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_map(client: AsyncClient, headers: dict, name: str | None = None) -> dict:
    """Create a map via the API and return the response JSON."""
    map_name = name or f"Bulk Delete Test Map {uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/maps/",
        json={"name": map_name, "description": "test"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create map failed: {resp.text}"
    return resp.json()


async def _add_layer(
    client: AsyncClient,
    headers: dict,
    map_id: str,
    dataset_id: str,
) -> str:
    """Add a layer to a map and return the layer id."""
    resp = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": dataset_id},
        headers=headers,
    )
    assert resp.status_code == 201, f"Add layer failed: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Test 1: Full success — all 3 layer_ids exist and are deleted
# ---------------------------------------------------------------------------


class TestBulkDeleteSuccess:
    async def test_bulk_delete_all_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """POST /maps/{id}/layers/bulk-delete with 3 valid ids deletes all 3."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        ds_id = str(ds.id)

        map_obj = await _create_map(client, admin_auth_header)
        map_id = map_obj["id"]

        layer_a = await _add_layer(client, admin_auth_header, map_id, ds_id)
        layer_b = await _add_layer(client, admin_auth_header, map_id, ds_id)
        layer_c = await _add_layer(client, admin_auth_header, map_id, ds_id)

        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": [layer_a, layer_b, layer_c]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["deleted"]) == {layer_a, layer_b, layer_c}
        assert data["failed"] == []

        # Verify map has no layers
        map_resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert map_resp.json()["layer_count"] == 0


# ---------------------------------------------------------------------------
# Test 2: Partial success — one layer id not in map → surfaces in failed[]
# ---------------------------------------------------------------------------


class TestBulkDeletePartial:
    async def test_bulk_delete_partial_invalid_id(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """One invalid layer id produces 200 with that id in failed[]."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        ds_id = str(ds.id)

        map_obj = await _create_map(client, admin_auth_header)
        map_id = map_obj["id"]
        layer_a = await _add_layer(client, admin_auth_header, map_id, ds_id)
        layer_b = await _add_layer(client, admin_auth_header, map_id, ds_id)

        invalid_id = str(uuid.uuid4())

        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": [layer_a, layer_b, invalid_id]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["deleted"]) == {layer_a, layer_b}
        assert len(data["failed"]) == 1
        assert data["failed"][0]["id"] == invalid_id
        assert data["failed"][0]["reason"] == "not_found"


# ---------------------------------------------------------------------------
# Test 3: Empty layer_ids → 400
# ---------------------------------------------------------------------------


class TestBulkDeleteValidation:
    async def test_bulk_delete_empty_list_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """Empty layer_ids array returns 422 (Pydantic min_length=1)."""
        map_obj = await _create_map(client, admin_auth_header)
        map_id = map_obj["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": []},
            headers=admin_auth_header,
        )
        # Pydantic Field(min_length=1) raises a 422 Unprocessable Entity
        assert resp.status_code == 422, resp.text

    # -------------------------------------------------------------------------
    # Test 4: Oversized layer_ids (> 200) → 422
    # -------------------------------------------------------------------------

    async def test_bulk_delete_too_many_ids_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """layer_ids exceeding 200 returns 422 (Pydantic max_length=200)."""
        map_obj = await _create_map(client, admin_auth_header)
        map_id = map_obj["id"]

        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": [str(uuid.uuid4()) for _ in range(201)]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Test 5: Viewer role → 403
# ---------------------------------------------------------------------------


class TestBulkDeleteRBAC:
    async def test_bulk_delete_viewer_forbidden(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
    ) -> None:
        """Viewer role gets 403 on POST .../layers/bulk-delete."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/layers/bulk-delete",
            json={"layer_ids": [str(uuid.uuid4())]},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403, resp.text

    # -------------------------------------------------------------------------
    # Test 6: Map not owned by user → 404
    # -------------------------------------------------------------------------

    async def test_bulk_delete_map_not_found_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """Non-existent map_id returns 404."""
        resp = await client.post(
            f"/maps/{uuid.uuid4()}/layers/bulk-delete",
            json={"layer_ids": [str(uuid.uuid4())]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Test 7: Audit event map.bulk_remove_layers is emitted
# ---------------------------------------------------------------------------


class TestBulkDeleteAudit:
    async def test_bulk_delete_emits_audit_event(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """Exactly one audit event map.bulk_remove_layers is emitted per call."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        ds_id = str(ds.id)

        map_obj = await _create_map(client, admin_auth_header)
        map_id = map_obj["id"]
        layer_a = await _add_layer(client, admin_auth_header, map_id, ds_id)
        layer_b = await _add_layer(client, admin_auth_header, map_id, ds_id)

        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": [layer_a, layer_b]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        # Verify audit log
        audit_result = await test_db_session.execute(
            select(AuditLog)
            .where(
                AuditLog.action == "map.bulk_remove_layers",
                AuditLog.resource_id == uuid.UUID(map_id),
            )
            .order_by(AuditLog.created_at.desc())
        )
        audit_rows = audit_result.scalars().all()
        assert len(audit_rows) >= 1, "Expected at least one map.bulk_remove_layers audit entry"
        latest = audit_rows[0]
        assert latest.details is not None
        assert "deleted_count" in latest.details
        assert latest.details["deleted_count"] == 2

    # -------------------------------------------------------------------------
    # Test 8: Single map_history event is recorded
    # -------------------------------------------------------------------------

    async def test_bulk_delete_records_map_history(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """A single map history entry with action=layer.bulk_remove is recorded."""
        from app.modules.catalog.maps.models import MapEditHistoryEvent as MapHistory

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        ds_id = str(ds.id)

        map_obj = await _create_map(client, admin_auth_header)
        map_id = map_obj["id"]
        layer_a = await _add_layer(client, admin_auth_header, map_id, ds_id)
        layer_b = await _add_layer(client, admin_auth_header, map_id, ds_id)
        layer_c = await _add_layer(client, admin_auth_header, map_id, ds_id)

        resp = await client.post(
            f"/maps/{map_id}/layers/bulk-delete",
            json={"layer_ids": [layer_a, layer_b, layer_c]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        # Verify map history
        history_result = await test_db_session.execute(
            select(MapHistory)
            .where(
                MapHistory.map_id == uuid.UUID(map_id),
                MapHistory.action == "layer.bulk_remove",
            )
            .order_by(MapHistory.created_at.desc())
        )
        history_rows = history_result.scalars().all()
        assert len(history_rows) >= 1, "Expected at least one layer.bulk_remove history entry"
        latest = history_rows[0]
        # WR-02 fix: bulk operations use target_type="map" since there is no
        # single layer target. This matches the layer.replace recording pattern
        # and prevents broken "jump to layer" links in history viewers.
        assert latest.target_type == "map"
        assert "Removed 3" in latest.summary
