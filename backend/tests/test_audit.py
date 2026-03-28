"""Integration tests for audit logging endpoints.

Tests cover: audit log creation from metadata edits and dataset views,
audit log querying with filters (user_id, action, date range),
pagination, and authorization enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
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


async def _create_audit_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """Insert a public dataset for audit tests."""
    table_name = f"ds_audit_{uuid.uuid4().hex[:8]}"
    record = Record(
        title=f"Audit Test Dataset {uuid.uuid4().hex[:6]}",
        summary="Dataset for audit log testing",
        theme_category=["audit-test"],
        visibility="public",
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
        source_filename="audit.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Audit log creation tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_metadata_edit_creates_audit_log(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    test_db_session,
):
    """PATCH /datasets/{id} creates a metadata.edit audit log entry."""
    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_audit_dataset(test_db_session, created_by=admin_id)

    # Editor edits the dataset metadata
    patch_resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"summary": "updated by editor"},
        headers=editor_auth_header,
    )
    assert patch_resp.status_code == 200

    # Admin queries audit logs for metadata.edit
    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "metadata.edit"},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    data = log_resp.json()
    assert data["total"] >= 1

    # Find the log entry for our dataset
    entries = [log for log in data["logs"] if log.get("resource_id") == str(ds.id)]
    assert len(entries) >= 1
    entry = entries[0]
    assert entry["action"] == "metadata.edit"
    assert entry["resource_type"] == "dataset"


@pytest.mark.anyio
async def test_dataset_view_creates_audit_log(
    client: AsyncClient,
    admin_auth_header: dict,
    viewer_auth_header: dict,
    test_db_session,
):
    """GET /datasets/{id} creates a dataset.view audit log entry."""
    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_audit_dataset(test_db_session, created_by=admin_id)

    # Viewer views the dataset
    view_resp = await client.get(
        f"/datasets/{ds.id}",
        headers=viewer_auth_header,
    )
    assert view_resp.status_code == 200

    # Admin queries audit logs for dataset.view
    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "dataset.view"},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    data = log_resp.json()
    assert data["total"] >= 1

    entries = [log for log in data["logs"] if log.get("resource_id") == str(ds.id)]
    assert len(entries) >= 1
    assert entries[0]["action"] == "dataset.view"


# ---------------------------------------------------------------------------
# Audit log filtering tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_audit_log_filter_by_user(
    client: AsyncClient,
    admin_auth_header: dict,
    viewer_auth_header: dict,
    test_db_session,
):
    """Filter audit logs by user_id returns only that user's logs."""
    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_audit_dataset(test_db_session, created_by=admin_id)

    # Admin views the dataset (creates a log for admin)
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

    # Filter by admin user_id
    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"user_id": str(admin_id)},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    data = log_resp.json()
    # All returned logs belong to admin
    for log in data["logs"]:
        assert log["user_id"] == str(admin_id)


@pytest.mark.anyio
async def test_audit_log_filter_by_action(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Filter audit logs by action returns only matching actions."""
    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "metadata.edit"},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    data = log_resp.json()
    for log in data["logs"]:
        assert log["action"] == "metadata.edit"


@pytest.mark.anyio
async def test_audit_log_filter_by_date_range(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Filter audit logs by date range returns logs within that range."""
    log_resp = await client.get(
        "/admin/audit-logs/",
        params={
            "date_from": "2026-01-01T00:00:00Z",
            "date_to": "2026-12-31T23:59:59Z",
        },
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    data = log_resp.json()
    # All returned logs should be in 2026
    for log in data["logs"]:
        assert log["created_at"].startswith("2026")


# ---------------------------------------------------------------------------
# Pagination test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_audit_log_pagination(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Audit log pagination returns correct page size."""
    admin_id = await _get_user_id(test_db_session, "admin")

    # Create some audit events by viewing datasets
    ds1 = await _create_audit_dataset(test_db_session, created_by=admin_id)
    ds2 = await _create_audit_dataset(test_db_session, created_by=admin_id)
    ds3 = await _create_audit_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{ds1.id}", headers=admin_auth_header)
    await client.get(f"/datasets/{ds2.id}", headers=admin_auth_header)
    await client.get(f"/datasets/{ds3.id}", headers=admin_auth_header)

    # Request page with limit=2
    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"limit": 2, "skip": 0},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    data = log_resp.json()
    assert len(data["logs"]) == 2
    assert data["total"] >= 3


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_audit_log_viewer_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer cannot access audit logs (403)."""
    resp = await client.get(
        "/admin/audit-logs/",
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_audit_log_unauthenticated_returns_401(
    client: AsyncClient,
):
    """Unauthenticated request to audit logs returns 401."""
    resp = await client.get("/admin/audit-logs/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_audit_logs_csv(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /admin/audit-logs/export/csv returns 200 with text/csv content and header row."""
    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_audit_dataset(test_db_session, created_by=admin_id)

    # Trigger a dataset.view audit log
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

    resp = await client.get(
        "/admin/audit-logs/export/csv",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    disposition = resp.headers.get("content-disposition", "")
    assert ".csv" in disposition
    body = resp.text
    assert "timestamp" in body
    assert "action" in body
    lines = body.strip().splitlines()
    assert len(lines) >= 2, "CSV should have header + at least one data row"


@pytest.mark.anyio
async def test_export_audit_logs_json(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /admin/audit-logs/export/json returns 200 with application/json array."""
    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_audit_dataset(test_db_session, created_by=admin_id)

    # Trigger a dataset.view audit log
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

    resp = await client.get(
        "/admin/audit-logs/export/json",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")
    disposition = resp.headers.get("content-disposition", "")
    assert ".json" in disposition
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1, "JSON export should contain at least one audit log entry"


@pytest.mark.anyio
async def test_export_audit_logs_viewer_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer cannot export audit logs (403)."""
    resp = await client.get(
        "/admin/audit-logs/export/csv",
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_export_audit_logs_unauthenticated_returns_401(
    client: AsyncClient,
):
    """Unauthenticated request to export audit logs returns 401."""
    resp = await client.get("/admin/audit-logs/export/csv")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_export_audit_logs_invalid_format(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Invalid export format returns 422 (FastAPI Literal validation)."""
    resp = await client.get(
        "/admin/audit-logs/export/xml",
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
