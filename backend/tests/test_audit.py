"""Integration tests for audit logging endpoints.

Tests cover: audit log creation from metadata edits and dataset views,
audit log querying with filters (user_id, action, date range),
pagination, and authorization enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest
from httpx import AsyncClient

from tests.factories import create_dataset, get_user_id


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
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

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
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

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
    assert any(e["action"] == "dataset.view" for e in entries)


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
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

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
    admin_id = await get_user_id(test_db_session, "admin")

    # Create some audit events by viewing datasets
    ds1 = await create_dataset(test_db_session, created_by=admin_id)
    ds2 = await create_dataset(test_db_session, created_by=admin_id)
    ds3 = await create_dataset(test_db_session, created_by=admin_id)
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


# ---------------------------------------------------------------------------
# Export tests
#
# Audit-log export is an enterprise-only feature (Team/Business pricing tier).
# In community, the route returns 404 to prevent feature leakage. The CSV/JSON
# implementations remain in core but are advertised only when an enterprise
# overlay registers an ``AuditExtension`` whose ``get_export_formats()`` lists
# them. The tests below mock that registration to exercise the success path.
# ---------------------------------------------------------------------------


def _enterprise_audit_ext():
    """Context manager that registers an AuditExtension advertising csv+json."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        import app.platform.extensions as ext_mod
        from app.core.edition import init_edition
        from app.platform.extensions.defaults import DefaultAuditExtension

        prior_ext = ext_mod._extensions.get("audit")
        prior_info = __import__("app.core.edition", fromlist=["_info"])._info

        class _ExportingAudit(DefaultAuditExtension):
            def get_export_formats(self):
                return ["csv", "json"]

        ext_mod._extensions["audit"] = _ExportingAudit()
        init_edition(["audit"])
        try:
            yield
        finally:
            if prior_ext is None:
                ext_mod._extensions.pop("audit", None)
            else:
                ext_mod._extensions["audit"] = prior_ext
            __import__("app.core.edition", fromlist=["_info"])._info = prior_info

    return _ctx()


@pytest.mark.anyio
async def test_export_audit_logs_csv_community_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Audit export returns 404 in community (boundary enforcement)."""
    resp = await client.get(
        "/admin/audit-logs/export/csv",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_export_audit_logs_json_community_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """JSON export also 404 in community."""
    resp = await client.get(
        "/admin/audit-logs/export/json",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_export_audit_logs_csv_enterprise(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Enterprise-with-AuditExtension serves CSV streaming export."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

    with _enterprise_audit_ext():
        resp = await client.get(
            "/admin/audit-logs/export/csv",
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    body = resp.text
    assert "timestamp" in body
    lines = body.strip().splitlines()
    assert len(lines) >= 2, "CSV should have header + at least one data row"


@pytest.mark.anyio
async def test_export_audit_logs_json_enterprise(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Enterprise-with-AuditExtension serves JSON streaming export."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

    with _enterprise_audit_ext():
        resp = await client.get(
            "/admin/audit-logs/export/json",
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.anyio
async def test_export_audit_logs_viewer_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer is rejected before the enterprise gate runs (permission first)."""
    with _enterprise_audit_ext():
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
    with _enterprise_audit_ext():
        resp = await client.get("/admin/audit-logs/export/csv")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_export_audit_logs_unknown_format_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Unknown format 404 in community AND enterprise (no leak)."""
    resp = await client.get(
        "/admin/audit-logs/export/xml",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404

    with _enterprise_audit_ext():
        resp = await client.get(
            "/admin/audit-logs/export/xml",
            headers=admin_auth_header,
        )
    # Extension only advertises csv+json — unknown format also 404 inside enterprise.
    assert resp.status_code == 404
