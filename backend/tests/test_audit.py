"""Integration tests for audit logging endpoints.

Tests cover: audit log creation from metadata edits and dataset views,
audit log querying with filters (user_id, action, date range),
pagination, and authorization enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid
from datetime import datetime, timezone

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
    test_db_session,
):
    """PATCH /datasets/{id} creates a metadata.edit audit log entry."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

    # The owner (admin) edits the dataset metadata
    patch_resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"summary": "updated by owner"},
        headers=admin_auth_header,
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


@pytest.mark.anyio
async def test_audit_log_resolves_dataset_resource_name(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """fix(#620): list endpoint returns the dataset title as resource_name."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session, created_by=admin_id, name="Audit Name Target"
    )

    view_resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
    assert view_resp.status_code == 200

    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"resource_id": str(ds.id)},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    entries = log_resp.json()["logs"]
    assert len(entries) >= 1
    assert all(e["resource_name"] == "Audit Name Target" for e in entries)

    # A row pointing at a deleted/unknown resource resolves to None, not an error.
    from app.modules.audit.service import log_action

    ghost_id = uuid.uuid4()
    await log_action(
        test_db_session, admin_id, "dataset.view", "dataset", resource_id=ghost_id
    )
    await test_db_session.commit()

    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"resource_id": str(ghost_id)},
        headers=admin_auth_header,
    )
    assert log_resp.status_code == 200
    entries = log_resp.json()["logs"]
    assert len(entries) == 1
    assert entries[0]["resource_name"] is None


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
async def test_audit_log_filter_by_resource_id(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Resource identifiers are first-class filters, not search-text matches."""
    admin_id = await get_user_id(test_db_session, "admin")
    target = await create_dataset(test_db_session, created_by=admin_id)
    other = await create_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{target.id}", headers=admin_auth_header)
    await client.get(f"/datasets/{other.id}", headers=admin_auth_header)

    log_resp = await client.get(
        "/admin/audit-logs/",
        params={"resource_type": "dataset", "resource_id": str(target.id)},
        headers=admin_auth_header,
    )

    assert log_resp.status_code == 200
    logs = log_resp.json()["logs"]
    assert logs
    assert {entry["resource_id"] for entry in logs} == {str(target.id)}
    assert {entry["resource_type"] for entry in logs} == {"dataset"}


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
# Export tests. Community includes bounded CSV and JSON export. Enterprise adds
# automated compliance workflows and external streaming integrations.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_audit_logs_csv_community(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    community_edition,
):
    """Community serves a bounded CSV streaming export."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

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
    # fix(#620): exports carry the resolved resource name (appended last so
    # positional consumers of the previous column layout keep working).
    assert lines[0].endswith("resource_name")
    assert "Test Dataset" in body
    # The snapshot/export ID boundary prevents an export from recursively
    # including the event generated by that same export.
    assert "audit.export" not in body

    audit_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "audit.export"},
        headers=admin_auth_header,
    )
    assert audit_resp.status_code == 200
    events = audit_resp.json()["logs"]
    completed = next(
        event for event in events if event["details"].get("outcome") == "completed"
    )
    operation_id = completed["details"]["operation_id"]
    requested = next(
        event
        for event in events
        if event["details"].get("operation_id") == operation_id
        and event["details"].get("outcome") == "requested"
    )
    assert completed["details"]["format"] == "csv"
    assert completed["details"]["mode"] == "stream"
    assert completed["details"]["row_limit"] == 100_000
    assert completed["details"]["selected_rows"] == len(lines) - 1
    assert "selected_rows" not in requested["details"]
    assert completed["resource_id"] == requested["resource_id"]
    assert completed["ip_address"] is not None


def test_audit_csv_sanitizes_formula_prefixes_in_user_controlled_cells():
    """Spreadsheet software must not execute a malicious exported username."""
    from app.modules.audit.router import _safe_csv_cell

    for prefix in ("=", "+", "-", "@"):
        assert _safe_csv_cell(f"{prefix}SUM(1,1)") == f"\t{prefix}SUM(1,1)"
    assert _safe_csv_cell("ordinary-user") == "ordinary-user"


@pytest.mark.anyio
async def test_durable_audit_survives_actor_deletion(monkeypatch):
    """A terminal event falls back to NULL when its actor no longer exists."""
    import app.core.db as db_module
    import app.modules.audit.service as audit_service
    from app.modules.audit.service import AuditEvent

    emitted = []

    class MissingActorSession:
        async def scalar(self, _statement):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class SessionContext:
        async def __aenter__(self):
            return MissingActorSession()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    async def record_event(_session, event):
        emitted.append(event)

    monkeypatch.setattr(db_module, "async_session", lambda: SessionContext())
    monkeypatch.setattr(audit_service, "audit_emit", record_event)

    await audit_service.audit_emit_durable(
        AuditEvent(
            user_id=uuid.uuid4(),
            action="audit.export",
            resource_type="audit_log",
        )
    )

    assert len(emitted) == 1
    assert emitted[0].user_id is None


@pytest.mark.anyio
async def test_export_audit_logs_applies_identity_and_resource_filters(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """List and export share user/resource filter semantics and audit context."""
    admin_id = await get_user_id(test_db_session, "admin")
    target = await create_dataset(test_db_session, created_by=admin_id)
    other = await create_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{target.id}", headers=admin_auth_header)
    await client.get(f"/datasets/{other.id}", headers=admin_auth_header)

    params = {
        "user_id": str(admin_id),
        "resource_type": "dataset",
        "resource_id": str(target.id),
        "max_rows": 1,
    }
    resp = await client.get(
        "/admin/audit-logs/export/json",
        params=params,
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["resource_type"] == "dataset"
    assert rows[0]["resource_id"] == str(target.id)
    assert rows[0]["username"] == "admin"

    audit_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "audit.export"},
        headers=admin_auth_header,
    )
    events = audit_resp.json()["logs"]
    completed = next(
        event for event in events if event["details"].get("outcome") == "completed"
    )
    details = completed["details"]
    assert details["filters"]["user_id"] == str(admin_id)
    assert details["filters"]["resource_type"] == "dataset"
    assert details["filters"]["resource_id"] == str(target.id)
    assert details["row_limit"] == 1
    assert details["selected_rows"] == len(rows)


@pytest.mark.anyio
async def test_export_audit_logs_json_community(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    community_edition,
):
    """Community serves a bounded JSON streaming export."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)
    await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)

    resp = await client.get(
        "/admin/audit-logs/export/json",
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # fix(#620): the viewed dataset's row resolves its record title.
    ds_rows = [r for r in data if r["resource_id"] == str(ds.id)]
    assert ds_rows and all(r["resource_name"] == "Test Dataset" for r in ds_rows)


@pytest.mark.anyio
async def test_export_completion_counts_rows_visible_when_stream_starts(monkeypatch):
    """A row committed after intent is counted when the streaming SELECT sees it."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import app.core.db as db_module
    import app.core.tenancy as tenancy
    import app.modules.audit.router as audit_router
    from app.core.db.tenant_session import current_tenant_var

    actor_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    streamed_rows = [
        SimpleNamespace(
            created_at=datetime.now(timezone.utc),
            user=SimpleNamespace(username="admin"),
            action="first.action",
            resource_type="dataset",
            resource_id=uuid.uuid4(),
            ip_address="127.0.0.1",
            details=None,
        )
    ]
    request_events = []
    outcome_events = []

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class RequestSession:
        async def commit(self):
            return None

    async def stream_rows(_session, **_filters):
        assert current_tenant_var.get() == tenant_id
        for row in streamed_rows:
            yield row

    async def record_request(_db, event):
        request_events.append(event)

    async def record_outcome(event):
        assert current_tenant_var.get() == tenant_id
        outcome_events.append(event)

    async def fake_resolve_names(_db, _logs):
        # fix(#620): the fake async_session yields a bare object(), so the
        # real batched name lookup cannot run here; names aren't under test.
        return {}

    preflight_count = AsyncMock(side_effect=AssertionError("no preflight count"))
    monkeypatch.setattr(db_module, "async_session", lambda: SessionContext())
    monkeypatch.setattr(audit_router, "query_audit_logs", preflight_count)
    monkeypatch.setattr(audit_router, "stream_audit_logs", stream_rows)
    monkeypatch.setattr(audit_router, "resolve_resource_names", fake_resolve_names)
    monkeypatch.setattr(audit_router, "audit_emit", record_request)
    monkeypatch.setattr(audit_router, "audit_emit_durable", record_outcome)
    monkeypatch.setattr(tenancy, "is_multi_tenant", lambda: True)

    prior_tenant_id = current_tenant_var.get()
    request_token = current_tenant_var.set(tenant_id)
    try:
        response = await audit_router.export_audit_logs(
            format="json",
            request=SimpleNamespace(
                client=SimpleNamespace(host="127.0.0.1"),
                state=SimpleNamespace(tenant_id=tenant_id),
            ),
            user_id=None,
            action=None,
            resource_type=None,
            resource_id=None,
            date_from=None,
            date_to=None,
            search=None,
            max_rows=100,
            user=SimpleNamespace(id=actor_id),
            db=RequestSession(),
        )
    finally:
        # Match TenantContextMiddleware resetting the request context before
        # Starlette begins iterating the response body.
        current_tenant_var.reset(request_token)
    assert current_tenant_var.get() == prior_tenant_id

    # Simulate a concurrent commit after the durable request event but before
    # the fresh streaming SELECT establishes its MVCC statement snapshot.
    streamed_rows.append(
        SimpleNamespace(
            created_at=datetime.now(timezone.utc),
            user=SimpleNamespace(username="admin"),
            action="concurrent.action",
            resource_type="dataset",
            resource_id=uuid.uuid4(),
            ip_address="127.0.0.1",
            details=None,
        )
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    assert len(json.loads("".join(chunks))) == 2
    preflight_count.assert_not_awaited()
    assert request_events[0].details["outcome"] == "requested"
    assert outcome_events[0].details["outcome"] == "completed"
    assert outcome_events[0].details["selected_rows"] == 2
    assert outcome_events[0].resource_id == request_events[0].resource_id
    assert current_tenant_var.get() == prior_tenant_id


@pytest.mark.anyio
async def test_export_audit_logs_viewer_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """A viewer cannot export audit logs."""
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
async def test_export_audit_logs_unknown_format_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Unknown formats return 404."""
    resp = await client.get(
        "/admin/audit-logs/export/xml",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_export_audit_logs_enforces_community_row_limit(
    client: AsyncClient,
    admin_auth_header: dict,
):
    resp = await client.get(
        "/admin/audit-logs/export/json?max_rows=100001",
        headers=admin_auth_header,
    )

    assert resp.status_code == 422
