"""Integration tests for GET /admin/users/export.csv endpoint.

Tests cover:
  - Admin can download a CSV with correct headers and user rows (LEADS-01)
  - A user with auth_provider='oauth' appears in the export (Google signup capture)
  - CSV injection hardening: cells starting with =, +, -, @ are tab-prefixed
  - Non-admin (viewer) request returns 403

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied

Invocation:
  cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_admin_user_export.py -x -v
"""

import csv
import io
import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient

EXPORT_URL = "/admin/users/export.csv"


@pytest.mark.anyio
async def test_export_csv_as_admin(
    client: AsyncClient,
    admin_auth_header: dict,
) -> None:
    """Admin GET /admin/users/export.csv → 200 text/csv with correct header row."""
    resp = await client.get(EXPORT_URL, headers=admin_auth_header)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    # Verify the header row is present
    lines = resp.text.splitlines()
    assert len(lines) >= 1, "CSV must have at least a header row"
    assert lines[0] == "email,display_name,auth_provider,status,created_at"
    exported_rows = list(csv.DictReader(io.StringIO(resp.text)))

    audit_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "user.export"},
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
    assert completed["resource_type"] == "user"
    assert completed["resource_id"] == requested["resource_id"]
    assert completed["details"]["format"] == "csv"
    assert completed["details"]["mode"] == "stream"
    assert completed["details"]["selected_rows"] == len(exported_rows)
    assert "selected_rows" not in requested["details"]
    assert completed["ip_address"] is not None


@pytest.mark.anyio
async def test_export_csv_contains_local_user(
    client: AsyncClient,
    admin_auth_header: dict,
) -> None:
    """Export CSV contains a locally-created user's email."""
    unique = uuid.uuid4().hex[:8]
    email = f"localuser-{unique}@example.com"

    # Create a local user via the admin API
    resp = await client.post(
        "/admin/users/",
        json={
            "username": f"localuser-{unique}",
            "email": email,
            "password": "Test1234!ABCD",
            "role": "viewer",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, f"Failed to create user: {resp.text}"

    # Export and check the user appears
    resp = await client.get(EXPORT_URL, headers=admin_auth_header)
    assert resp.status_code == 200

    reader = csv.DictReader(io.StringIO(resp.text))
    emails = [row["email"] for row in reader]
    assert email in emails, f"Expected {email!r} in export, got: {emails}"


@pytest.mark.anyio
async def test_export_csv_contains_oauth_user(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
) -> None:
    """Export CSV includes a user with auth_provider='oauth' (Google signup row)."""
    from app.modules.auth.models import User
    from app.modules.auth.providers.local import hash_password

    unique = uuid.uuid4().hex[:8]
    oauth_email = f"oauth-user-{unique}@gmail.com"

    # Insert an OAuth user directly into the DB (POST /admin/users/ only creates 'local')
    oauth_user = User(
        id=uuid.uuid4(),
        username=f"oauth-user-{unique}",
        email=oauth_email,
        password_hash=hash_password("unused-oauth-password"),
        auth_provider="oauth",
        status="active",
        is_active=True,
    )
    test_db_session.add(oauth_user)
    await test_db_session.commit()

    # Export and verify the OAuth user appears
    resp = await client.get(EXPORT_URL, headers=admin_auth_header)
    assert resp.status_code == 200

    reader = csv.DictReader(io.StringIO(resp.text))
    rows_by_email = {row["email"]: row for row in reader}

    assert oauth_email in rows_by_email, (
        f"Expected oauth email {oauth_email!r} in export. "
        f"Got emails: {list(rows_by_email.keys())}"
    )
    oauth_row = rows_by_email[oauth_email]
    assert oauth_row["auth_provider"] == "oauth", (
        f"Expected auth_provider='oauth', got: {oauth_row['auth_provider']!r}"
    )


@pytest.mark.anyio
async def test_export_csv_injection_hardened(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
) -> None:
    """CSV cells starting with =, +, -, @ are tab-prefixed (injection hardening)."""
    from app.modules.auth.models import User
    from app.modules.auth.providers.local import hash_password

    unique = uuid.uuid4().hex[:8]

    # Insert a user with injection-risky email and username
    injection_user = User(
        id=uuid.uuid4(),
        username=f"+badname-{unique}",
        email=f"=MALICIOUS()-{unique}@evil.com",
        password_hash=hash_password("unused-password"),
        auth_provider="local",
        status="active",
        is_active=True,
    )
    test_db_session.add(injection_user)
    await test_db_session.commit()

    resp = await client.get(EXPORT_URL, headers=admin_auth_header)
    assert resp.status_code == 200

    body = resp.text

    # The raw injection strings should NOT appear at the start of a cell
    assert f"=MALICIOUS()-{unique}@evil.com" not in body or (
        f"\t=MALICIOUS()-{unique}@evil.com" in body
    ), "Email starting with '=' must be tab-prefixed in the CSV"

    assert f"+badname-{unique}" not in body or (f"\t+badname-{unique}" in body), (
        "Username starting with '+' must be tab-prefixed in the CSV"
    )

    # Confirm the tab-prefixed versions ARE present
    assert f"\t=MALICIOUS()-{unique}@evil.com" in body, (
        "Expected tab-prefixed email in CSV body"
    )
    assert f"\t+badname-{unique}" in body, "Expected tab-prefixed username in CSV body"


@pytest.mark.anyio
async def test_export_csv_non_admin_403(
    client: AsyncClient,
    viewer_auth_header: dict,
) -> None:
    """Non-admin (viewer) request to export.csv returns 403."""
    resp = await client.get(EXPORT_URL, headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_export_stream_failure_records_actual_emitted_rows_without_content(
    monkeypatch,
) -> None:
    """A post-release stream failure records only safe correlated metadata."""
    from types import SimpleNamespace

    import app.core.db as db_module
    import app.modules.admin.router as admin_router

    secret_path = "/tmp/private/customer-secret.csv"
    actor_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    request_events = []
    outcome_events = []
    tenant_contexts = []

    class BrokenRows:
        def __init__(self):
            self.returned = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.returned:
                self.returned = True
                return (
                    SimpleNamespace(
                        email="safe@example.com",
                        username="safe-user",
                        auth_provider="local",
                        status="active",
                        created_at=None,
                    ),
                )
            raise RuntimeError(f"stream failed while reading {secret_path}")

    class StreamSession:
        async def stream(self, _stmt):
            return BrokenRows()

    class StreamSessionContext:
        async def __aenter__(self):
            return StreamSession()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class RequestSession:
        async def commit(self):
            return None

    async def record_request(_db, event):
        request_events.append(event)

    async def record_outcome(event):
        outcome_events.append(event)

    @contextmanager
    def record_tenant_context(value):
        tenant_contexts.append(("enter", value))
        try:
            yield
        finally:
            tenant_contexts.append(("exit", value))

    monkeypatch.setattr(db_module, "async_session", lambda: StreamSessionContext())
    monkeypatch.setattr(admin_router, "audit_emit", record_request)
    monkeypatch.setattr(admin_router, "audit_emit_durable", record_outcome)
    monkeypatch.setattr(admin_router, "tenant_job_context", record_tenant_context)

    response = await admin_router.export_users_csv(
        SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            state=SimpleNamespace(tenant_id=tenant_id),
        ),
        SimpleNamespace(id=actor_id),
        RequestSession(),
    )

    with pytest.raises(RuntimeError, match="stream failed"):
        async for _chunk in response.body_iterator:
            pass

    assert len(request_events) == 1
    assert request_events[0].details["outcome"] == "requested"
    assert len(outcome_events) == 1
    failed = outcome_events[0]
    assert failed.details["outcome"] == "failed"
    assert failed.details["selected_rows"] == 1
    assert failed.details["error_code"] == "stream_failed"
    assert failed.resource_id == request_events[0].resource_id
    assert failed.details["operation_id"] == request_events[0].details["operation_id"]
    assert secret_path not in repr(failed.details)
    assert "safe@example.com" not in repr(failed.details)
    assert tenant_contexts == [
        ("enter", tenant_id),
        ("exit", tenant_id),
        ("enter", tenant_id),
        ("exit", tenant_id),
    ]
