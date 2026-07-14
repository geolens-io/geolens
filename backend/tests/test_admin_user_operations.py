"""Integration tests for admin user delete and embedding backfill endpoints.

Tests cover:
  - DELETE /admin/users/{id} — removes user, cascades API keys, self-delete guard,
    auth enforcement, 404 for missing user
  - POST /admin/backfill-embeddings/ — admin trigger with force, auth enforcement

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import _create_test_user


# ---------------------------------------------------------------------------
# DELETE /admin/users/{id}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_user_removes_user(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} hard-deletes the user and returns 204."""
    # Create a user to delete
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")

    # Verify user exists
    resp = await client.get(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 200

    # Delete user
    resp = await client.delete(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 204

    # Verify user is gone
    resp = await client.get(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_user_cascades_api_keys(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} also removes the user's API keys."""
    # Create a user
    _, user_id = await _create_test_user(client, admin_auth_header, "editor")

    # Create an API key for this user
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": user_id, "name": "test-key"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201

    # Verify API key exists
    resp = await client.get(
        f"/admin/api-keys/?user_id={user_id}", headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # Delete user
    resp = await client.delete(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 204

    # Verify API keys are gone
    resp = await client.get(
        f"/admin/api-keys/?user_id={user_id}", headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.anyio
async def test_delete_user_cannot_delete_self(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} returns 400 when admin tries to delete themselves."""
    # Get current admin user ID
    resp = await client.get("/auth/me/", headers=admin_auth_header)
    assert resp.status_code == 200
    admin_id = resp.json()["id"]

    # Try to self-delete
    resp = await client.delete(f"/admin/users/{admin_id}", headers=admin_auth_header)
    assert resp.status_code == 400
    assert "cannot delete" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_delete_user_forbidden_for_non_admin(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """DELETE /admin/users/{id} returns 403 for viewer role."""
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/admin/users/{fake_id}", headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_delete_user_404_for_nonexistent(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} returns 404 for a non-existent user ID."""
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/admin/users/{fake_id}", headers=admin_auth_header)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /admin/backfill-embeddings/
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_backfill_embeddings_force_admin(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /admin/backfill-embeddings/?force=true returns 200 for admin."""
    resp = await client.post(
        "/admin/backfill-embeddings/?force=true",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "processed" in data
    assert "created" in data
    assert "errors" in data

    audit_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "embedding.backfill"},
        headers=admin_auth_header,
    )
    assert audit_resp.status_code == 200
    entries = audit_resp.json()["logs"]
    completed = next(
        entry for entry in entries if entry["details"]["outcome"] == "completed"
    )
    requested = next(
        entry
        for entry in entries
        if entry["details"]["outcome"] == "requested"
        and entry["details"]["operation_id"] == completed["details"]["operation_id"]
    )
    assert completed["resource_type"] == "record_embedding"
    assert completed["details"]["force"] is True
    assert completed["details"]["processed"] == data["processed"]
    assert completed["ip_address"] is not None
    assert requested["details"]["force"] is True
    assert requested["ip_address"] is not None


@pytest.mark.anyio
async def test_backfill_failure_after_force_delete_has_durable_safe_audit(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """A committed force-delete remains bracketed by requested/failed audits."""
    from sqlalchemy import delete, select

    from app.modules.audit.models import AuditLog
    from app.processing.embeddings import backfill as backfill_module
    from app.processing.embeddings.models import RecordEmbedding

    secret_error = "provider-secret-token=do-not-expose"
    requested_was_durable = False

    async def fail_after_committed_delete(session, *, force):
        nonlocal requested_was_durable
        assert force is True
        existing = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "embedding.backfill",
                        AuditLog.details["outcome"].astext == "requested",
                    )
                )
            ).scalars()
        )
        requested_was_durable = bool(existing)
        await session.execute(delete(RecordEmbedding))
        await session.commit()
        raise RuntimeError(secret_error)

    monkeypatch.setattr(
        backfill_module, "backfill_embeddings", fail_after_committed_delete
    )

    response = await client.post(
        "/admin/backfill-embeddings/?force=true",
        headers=admin_auth_header,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Embedding backfill failed. See server logs for details."
    )
    assert secret_error not in response.text
    assert requested_was_durable is True

    audit_response = await client.get(
        "/admin/audit-logs/",
        params={"action": "embedding.backfill"},
        headers=admin_auth_header,
    )
    assert audit_response.status_code == 200
    entries = audit_response.json()["logs"]
    failed = next(entry for entry in entries if entry["details"]["outcome"] == "failed")
    operation_id = failed["details"]["operation_id"]
    requested = next(
        entry
        for entry in entries
        if entry["details"]["outcome"] == "requested"
        and entry["details"]["operation_id"] == operation_id
    )
    assert requested["details"] == {
        "force": True,
        "operation_id": operation_id,
        "outcome": "requested",
    }
    assert failed["details"] == {
        "force": True,
        "operation_id": operation_id,
        "outcome": "failed",
        "error_code": "backfill_failed",
    }
    assert secret_error not in str(failed["details"])


@pytest.mark.anyio
async def test_backfill_embeddings_forbidden_for_non_admin(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """POST /admin/backfill-embeddings/ returns 403 for non-admin."""
    resp = await client.post(
        "/admin/backfill-embeddings/?force=true",
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_backfill_embeddings_without_force(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /admin/backfill-embeddings/ (no force) returns 200 with counts."""
    resp = await client.post(
        "/admin/backfill-embeddings/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "processed" in data
    assert "created" in data
    assert "skipped" in data
    assert "errors" in data


@pytest.mark.anyio
async def test_ai_status_mutation_requires_manage_settings(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Reading operational AI status does not imply authority to mutate it."""
    import app.platform.extensions as ext_mod
    from app.platform.extensions.defaults import DefaultPermissionExtension

    class UsersOnlyPermissionExtension(DefaultPermissionExtension):
        async def check_permission(
            self,
            db,
            user,
            capability,
            *,
            user_roles,
            permission_matrix=None,
            resource=None,
        ):
            if capability == "manage_users":
                return True
            if capability == "manage_settings":
                return False
            return await super().check_permission(
                db,
                user,
                capability,
                user_roles=user_roles,
                permission_matrix=permission_matrix,
                resource=resource,
            )

    previous = ext_mod._extensions.get("permission")
    ext_mod._extensions["permission"] = UsersOnlyPermissionExtension()
    try:
        read_resp = await client.get("/admin/ai-status/", headers=admin_auth_header)
        assert read_resp.status_code == 200
        mutate_resp = await client.patch(
            "/admin/ai-status/",
            json={"enabled": not read_resp.json()["enabled"]},
            headers=admin_auth_header,
        )
        assert mutate_resp.status_code == 403
    finally:
        if previous is None:
            ext_mod._extensions.pop("permission", None)
        else:
            ext_mod._extensions["permission"] = previous


@pytest.mark.anyio
async def test_ai_status_mutation_audit_includes_client_ip(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Persistent-setting audit context includes the request IP."""
    current = await client.get("/admin/ai-status/", headers=admin_auth_header)
    assert current.status_code == 200
    original = current.json()["enabled"]
    try:
        updated = await client.patch(
            "/admin/ai-status/",
            json={"enabled": not original},
            headers=admin_auth_header,
        )
        assert updated.status_code == 200, updated.text

        audit_resp = await client.get(
            "/admin/audit-logs/",
            params={"action": "update"},
            headers=admin_auth_header,
        )
        entries = [
            entry
            for entry in audit_resp.json()["logs"]
            if entry["resource_type"] == "setting"
            and entry["details"].get("setting_key") == "ai_enabled"
        ]
        assert entries
        assert entries[0]["details"]["new_value"] == (not original)
        assert entries[0]["ip_address"] is not None
    finally:
        await client.patch(
            "/admin/ai-status/",
            json={"enabled": original},
            headers=admin_auth_header,
        )


# ---------------------------------------------------------------------------
# POST /admin/users/ — 409 conflict for duplicate username
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_user_duplicate_username_returns_409(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Creating a user with an existing username returns 409."""
    # First creation should succeed
    username = f"dup_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": "TestPass1234!", "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201

    # Duplicate should return 409
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": "OtherPass456!", "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 409
    assert (
        "already" in resp.json()["detail"].lower()
        or "exists" in resp.json()["detail"].lower()
    )


# ---------------------------------------------------------------------------
# GET /admin/users/?search=... — accent-insensitive search (T-1/T-2 regression)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_users_search_is_accent_insensitive(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Admin user search must fold accents on BOTH sides.

    The users trigram indexes are on ``lower(catalog.immutable_unaccent(...))``,
    so the query unaccents the column; the search PATTERN must be unaccented too,
    or an accented search term (e.g. ``josé``) would never match an unaccented
    stored value (``jose``). Regression guard for the admin-search fix: the
    buggy version (unaccented column vs accent-preserved pattern) returns no
    match here.
    """
    unique = uuid.uuid4().hex[:8]
    username = f"jose{unique}"  # ASCII stored value
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": "TestPass1234!", "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    created_id = resp.json()["id"]

    # Accented search term must still find the unaccented username.
    resp = await client.get(
        "/admin/users/",
        params={"search": f"josé{unique}"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()["users"]}
    assert created_id in ids, "accented search term did not match unaccented username"

    # Plain (unaccented) search term also finds it.
    resp = await client.get(
        "/admin/users/",
        params={"search": f"jose{unique}"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()["users"]}
    assert created_id in ids, "plain search term did not match username"
