"""SEC-FU-08: Column DDL feed — service helper and endpoint tests.

Tests the query_column_ddl_history service helper and the
GET /api/audit/datasets/{dataset_id}/column-ddl endpoint.

Tests 1–4: Service layer (query_column_ddl_history)
Tests 5–10: Router layer (GET /api/audit/datasets/{id}/column-ddl)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit

from tests.conftest import _create_test_user
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helper: seed column-DDL audit events
# ---------------------------------------------------------------------------

_COLUMN_DDL_ACTIONS = (
    "layer.add_column",
    "layer.rename_column",
    "layer.alter_column_type",
    "layer.drop_column",
)


async def _seed_ddl_event(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    action: str = "layer.add_column",
    user_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    """Seed a single column-DDL audit event directly and commit.

    Falls back to the seeded admin user when no user_id is supplied, satisfying
    the audit_logs.user_id FK constraint.
    """
    effective_user_id = user_id or (await get_user_id(session, "admin"))
    await audit_emit(
        session,
        AuditEvent(
            action=action,
            resource_type="dataset",
            resource_id=dataset_id,
            details=details or {"column_name": f"col_{uuid.uuid4().hex[:6]}"},
            user_id=effective_user_id,
        ),
    )
    await session.commit()


async def _create_dataset_direct(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "DDL Feed Test DS",
    visibility: str = "private",
) -> "uuid.UUID":
    """Create a minimal vector Record + Dataset pair for testing. Returns dataset_id."""
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Column DDL feed test dataset: {name}",
        visibility=visibility,
        record_status="published",
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset.id


# ===========================================================================
# Service-layer tests (Tasks 2, tests 1–4)
# ===========================================================================


@pytest.mark.anyio
async def test_query_column_ddl_history_returns_matching_rows(
    test_db_session: AsyncSession,
):
    """query_column_ddl_history returns only column-DDL rows for the dataset."""
    from app.modules.audit.service import query_column_ddl_history

    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=admin_id, name="DDL Service Test 1"
    )

    # Seed a DDL event for our dataset
    await _seed_ddl_event(test_db_session, dataset_id=dataset_id, action="layer.add_column")
    # Seed a non-DDL event (should NOT appear)
    await audit_emit(
        test_db_session,
        AuditEvent(
            action="dataset.update",
            resource_type="dataset",
            resource_id=dataset_id,
            user_id=admin_id,
        ),
    )
    # Seed a DDL event for a DIFFERENT dataset (should NOT appear)
    other_dataset_id = uuid.uuid4()
    await _seed_ddl_event(
        test_db_session, dataset_id=other_dataset_id, action="layer.drop_column"
    )

    rows, total = await query_column_ddl_history(
        test_db_session, dataset_id, limit=50, offset=0
    )

    # Only the matching DDL row for our dataset should appear
    assert total == 1, f"Expected 1 row, got {total}"
    assert len(rows) == 1
    assert rows[0].action == "layer.add_column"
    assert rows[0].resource_id == dataset_id
    assert rows[0].resource_type == "dataset"


@pytest.mark.anyio
async def test_query_column_ddl_history_returns_total_count(
    test_db_session: AsyncSession,
):
    """query_column_ddl_history returns (rows, total) matching query_audit_logs shape."""
    from app.modules.audit.service import query_column_ddl_history

    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=admin_id, name="DDL Service Test 2"
    )

    # Seed all 4 DDL action types
    for action in _COLUMN_DDL_ACTIONS:
        await _seed_ddl_event(test_db_session, dataset_id=dataset_id, action=action)

    rows, total = await query_column_ddl_history(
        test_db_session, dataset_id, limit=50, offset=0
    )

    assert isinstance(rows, list), "rows must be a list"
    assert isinstance(total, int), "total must be an int"
    assert total == 4, f"Expected total=4, got {total}"
    assert len(rows) == 4


@pytest.mark.anyio
async def test_query_column_ddl_history_empty_for_no_events(
    test_db_session: AsyncSession,
):
    """query_column_ddl_history returns ([], 0) for a dataset with no DDL history."""
    from app.modules.audit.service import query_column_ddl_history

    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=admin_id, name="DDL Service Test 3 No Events"
    )

    rows, total = await query_column_ddl_history(
        test_db_session, dataset_id, limit=50, offset=0
    )

    assert rows == [], f"Expected empty list, got {rows}"
    assert total == 0, f"Expected total=0, got {total}"


@pytest.mark.anyio
async def test_query_column_ddl_history_pagination(
    test_db_session: AsyncSession,
):
    """query_column_ddl_history respects limit and offset."""
    from app.modules.audit.service import query_column_ddl_history

    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=admin_id, name="DDL Service Test 4 Pagination"
    )

    # Seed 4 events
    for action in _COLUMN_DDL_ACTIONS:
        await _seed_ddl_event(test_db_session, dataset_id=dataset_id, action=action)

    # Limit to 2
    rows_page1, total = await query_column_ddl_history(
        test_db_session, dataset_id, limit=2, offset=0
    )
    assert total == 4, f"Total should still be 4, got {total}"
    assert len(rows_page1) == 2, f"Page 1 should have 2 rows, got {len(rows_page1)}"

    # Offset to get remaining
    rows_page2, total2 = await query_column_ddl_history(
        test_db_session, dataset_id, limit=2, offset=2
    )
    assert total2 == 4
    assert len(rows_page2) == 2

    # Pages should not overlap
    page1_ids = {r.id for r in rows_page1}
    page2_ids = {r.id for r in rows_page2}
    assert not page1_ids.intersection(page2_ids), "Pages must not overlap"


# ===========================================================================
# Router-layer tests (Task 3, tests 5–10)
# ===========================================================================


@pytest.mark.anyio
async def test_column_ddl_feed_owner_sees_history(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """Owner GETs /api/audit/datasets/{id}/column-ddl → 200 with DDL rows in DESC order."""
    # Create an editor who owns the dataset
    owner_headers, owner_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    owner_id = uuid.UUID(owner_id_str)

    dataset_id = await _create_dataset_direct(
        test_db_session,
        created_by=owner_id,
        name="DDL Feed Router Test 5 Owner",
    )

    # Seed two DDL events
    await _seed_ddl_event(
        test_db_session,
        dataset_id=dataset_id,
        action="layer.add_column",
        user_id=owner_id,
        details={"column_name": "geom"},
    )
    await _seed_ddl_event(
        test_db_session,
        dataset_id=dataset_id,
        action="layer.rename_column",
        user_id=owner_id,
        details={"old_name": "geom", "new_name": "geometry"},
    )

    resp = await client.get(
        f"/api/audit/datasets/{dataset_id}/column-ddl",
        headers=owner_headers,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "items" in body, f"Response missing 'items': {body}"
    assert "total" in body
    assert body["total"] >= 2

    # Items must be in created_at DESC order (most recent first)
    items = body["items"]
    assert len(items) >= 2
    actions = [item["action"] for item in items]
    # rename happened after add, so in DESC order rename should come first
    assert actions[0] == "layer.rename_column", (
        f"Expected rename first (most recent), got {actions}"
    )
    assert actions[1] == "layer.add_column"

    # Each row should have expected fields
    for item in items:
        assert "action" in item
        assert "created_at" in item
        assert "user_id" in item


@pytest.mark.anyio
async def test_column_ddl_feed_non_owner_gets_403_or_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """Non-owner editor cannot read another user's column-DDL history."""
    # Owner creates dataset
    owner_headers, owner_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    owner_id = uuid.UUID(owner_id_str)
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=owner_id, name="DDL Feed Test 6 Non-Owner"
    )
    await _seed_ddl_event(test_db_session, dataset_id=dataset_id, action="layer.add_column")

    # Second user (non-owner)
    other_headers, _ = await _create_test_user(client, admin_auth_header, "editor")

    resp = await client.get(
        f"/api/audit/datasets/{dataset_id}/column-ddl",
        headers=other_headers,
    )
    # Non-owner should get 403 or 404 (check_dataset_access raises 404 for private datasets)
    assert resp.status_code in (403, 404), (
        f"Expected 403 or 404, got {resp.status_code}: {resp.text}"
    )

    # Body must NOT contain dataset name or column DDL details
    body_text = resp.text
    assert "DDL Feed Test 6 Non-Owner" not in body_text
    assert "layer.add_column" not in body_text


@pytest.mark.anyio
async def test_column_ddl_feed_admin_sees_any(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """Admin user can GET /api/audit/datasets/{id}/column-ddl regardless of ownership."""
    # Create dataset owned by editor
    owner_headers, owner_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    owner_id = uuid.UUID(owner_id_str)
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=owner_id, name="DDL Feed Test 7 Admin Access"
    )
    await _seed_ddl_event(test_db_session, dataset_id=dataset_id, action="layer.add_column")

    resp = await client.get(
        f"/api/audit/datasets/{dataset_id}/column-ddl",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, f"Admin should see 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["total"] >= 1


@pytest.mark.anyio
async def test_column_ddl_feed_anonymous_gets_401_or_403(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """Anonymous (no token) access returns 401 or 403."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=admin_id, name="DDL Feed Test 8 Anonymous"
    )

    resp = await client.get(f"/api/audit/datasets/{dataset_id}/column-ddl")
    assert resp.status_code in (401, 403), (
        f"Expected 401 or 403 for anonymous, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.anyio
async def test_column_ddl_feed_missing_dataset_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Non-existent dataset_id returns 404 before audit query runs."""
    missing_id = uuid.uuid4()
    resp = await client.get(
        f"/api/audit/datasets/{missing_id}/column-ddl",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404, (
        f"Expected 404 for missing dataset, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.anyio
async def test_column_ddl_feed_pagination(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """limit and offset query params are honored."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id = await _create_dataset_direct(
        test_db_session, created_by=admin_id, name="DDL Feed Test 9 Pagination", visibility="public"
    )

    # Seed 4 events
    for action in _COLUMN_DDL_ACTIONS:
        await _seed_ddl_event(test_db_session, dataset_id=dataset_id, action=action)

    resp_p1 = await client.get(
        f"/api/audit/datasets/{dataset_id}/column-ddl?limit=2&offset=0",
        headers=admin_auth_header,
    )
    assert resp_p1.status_code == 200
    body_p1 = resp_p1.json()
    assert len(body_p1["items"]) == 2
    assert body_p1["total"] == 4
    assert body_p1["limit"] == 2
    assert body_p1["offset"] == 0

    resp_p2 = await client.get(
        f"/api/audit/datasets/{dataset_id}/column-ddl?limit=2&offset=2",
        headers=admin_auth_header,
    )
    assert resp_p2.status_code == 200
    body_p2 = resp_p2.json()
    assert len(body_p2["items"]) == 2
    assert body_p2["total"] == 4

    # Pages must not overlap
    ids_p1 = {item["action"] + str(item["created_at"]) for item in body_p1["items"]}
    ids_p2 = {item["action"] + str(item["created_at"]) for item in body_p2["items"]}
    assert not ids_p1.intersection(ids_p2), "Pagination pages must not overlap"
