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
