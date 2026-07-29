"""Tests for API key authentication and admin CRUD endpoints.

Verifies that:
- Admin can create, list, and revoke API keys
- API keys authenticate to both required-auth and optional-auth endpoints
- Invalid/revoked keys are properly handled
- API keys inherit user roles/permissions
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import _create_test_user, get_auth_header

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()


@pytest.mark.anyio
async def test_create_api_key(client: AsyncClient):
    """Admin creates API key for themselves. Assert 201, response has key/id/name."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Get admin user id
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Test Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert "id" in data
    assert data["name"] == "Test Key"
    assert len(data["key"]) > 20  # token_urlsafe(32) produces ~43 chars
    assert data["fingerprint"] == f"{data['key'][:8]}…{data['key'][-4:]}"


@pytest.mark.anyio
async def test_api_key_authenticates_to_search(client: AsyncClient):
    """Create API key, use raw key in X-Api-Key header to call GET /search/datasets."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    # Create API key
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Search Key"},
        headers=admin_headers,
    )
    raw_key = resp.json()["key"]

    # Use API key to access authenticated endpoint
    search_resp = await client.get(
        "/search/datasets/",
        headers={"X-Api-Key": raw_key},
    )
    assert search_resp.status_code == 200


@pytest.mark.anyio
async def test_api_key_authenticates_to_collection_items(client: AsyncClient):
    """Use API key to call GET /collections/datasets/items. Assert 200."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Collection Key"},
        headers=admin_headers,
    )
    raw_key = resp.json()["key"]

    items_resp = await client.get(
        "/collections/datasets/items",
        headers={"X-Api-Key": raw_key},
    )
    assert items_resp.status_code == 200


@pytest.mark.anyio
async def test_invalid_api_key_returns_401(client: AsyncClient):
    """Call GET /auth/me/ with invalid X-Api-Key. Assert 401."""
    resp = await client.get(
        "/auth/me/",
        headers={"X-Api-Key": "invalid-key-value"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_revoked_api_key_returns_401(client: AsyncClient):
    """Create key, revoke via DELETE, then try to use it. Assert 401."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    # Create key
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Revoke Me"},
        headers=admin_headers,
    )
    data = resp.json()
    raw_key = data["key"]
    key_id = data["id"]

    # Revoke it
    del_resp = await client.delete(
        f"/admin/api-keys/{key_id}",
        headers=admin_headers,
    )
    assert del_resp.status_code == 204

    # Try using revoked key on authenticated endpoint
    search_resp = await client.get(
        "/auth/me/",
        headers={"X-Api-Key": raw_key},
    )
    assert search_resp.status_code == 401


@pytest.mark.anyio
async def test_invalid_api_key_falls_back_to_anonymous_on_optional_auth(
    client: AsyncClient,
):
    """Call GET /collections/datasets/items with invalid X-Api-Key (no JWT).

    Should return 200 (anonymous fallback, sees public datasets).
    """
    resp = await client.get(
        "/collections/datasets/items",
        headers={"X-Api-Key": "invalid-key-value"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_api_keys(client: AsyncClient):
    """Admin creates 2 keys, lists them. Assert both returned and raw key is NOT present."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a unique user to isolate key listing
    viewer_headers, viewer_id = await _create_test_user(client, admin_headers, "viewer")

    # Create 2 keys for that user
    key_names = set()
    expected_fingerprints: dict[str, str] = {}
    for i in range(2):
        name = f"list-test-key-{uuid.uuid4().hex[:6]}"
        key_names.add(name)
        create_resp = await client.post(
            "/admin/api-keys/",
            json={"user_id": viewer_id, "name": name},
            headers=admin_headers,
        )
        created = create_resp.json()
        expected_fingerprints[name] = created["fingerprint"]

    # List keys filtered by user
    list_resp = await client.get(
        f"/admin/api-keys/?user_id={viewer_id}",
        headers=admin_headers,
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    items = data["items"]
    assert "total" in data
    assert len(items) >= 2

    # Verify raw key is never in list response
    returned_names = set()
    for item in items:
        assert "key" not in item  # raw key must NOT be returned
        if item["name"] in expected_fingerprints:
            assert item["fingerprint"] == expected_fingerprints[item["name"]]
        returned_names.add(item["name"])

    assert key_names.issubset(returned_names)


@pytest.mark.anyio
async def test_api_key_inherits_user_roles(client: AsyncClient):
    """Create a viewer user, create API key for viewer. Use API key to access endpoint."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a viewer user
    viewer_headers, viewer_id = await _create_test_user(client, admin_headers, "viewer")

    # Create API key for the viewer
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": viewer_id, "name": "Viewer API Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    # Viewer can access search (requires authentication, viewer has access)
    search_resp = await client.get(
        "/search/datasets/",
        headers={"X-Api-Key": raw_key},
    )
    assert search_resp.status_code == 200

    # Viewer cannot access admin endpoints (requires admin role)
    admin_resp = await client.get(
        "/admin/users/",
        headers={"X-Api-Key": raw_key},
    )
    assert admin_resp.status_code == 403


# ---------------------------------------------------------------------------
# Self-service API key CRUD tests (/auth/api-keys/)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_self_service_list_api_keys(client: AsyncClient):
    """Authenticated user can list their own API keys via GET /auth/api-keys/."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.get("/auth/api-keys/", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


@pytest.mark.anyio
async def test_self_service_create_api_key(client: AsyncClient):
    """Authenticated user can create an API key via POST /auth/api-keys/."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Self-Service Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "key" in data
    assert data["name"] == "Self-Service Key"
    assert len(data["key"]) > 20
    assert data["fingerprint"] == f"{data['key'][:8]}…{data['key'][-4:]}"

    list_resp = await client.get("/auth/api-keys/", headers=admin_headers)
    listed = {item["id"]: item for item in list_resp.json()["items"]}
    assert listed[data["id"]]["fingerprint"] == data["fingerprint"]
    assert "key" not in listed[data["id"]]


@pytest.mark.anyio
async def test_self_service_delete_own_api_key(client: AsyncClient):
    """Authenticated user can delete their own API key via DELETE /auth/api-keys/{id}."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a key
    create_resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Delete Me Self"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    # Delete it
    del_resp = await client.delete(
        f"/auth/api-keys/{key_id}",
        headers=admin_headers,
    )
    assert del_resp.status_code == 204


@pytest.mark.anyio
async def test_self_service_list_api_keys_unauthenticated(client: AsyncClient):
    """GET /auth/api-keys/ without authentication returns 401."""
    resp = await client.get("/auth/api-keys/")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_self_service_cannot_delete_another_users_key(client: AsyncClient):
    """User cannot delete another user's API key (returns 404)."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a second user
    viewer_headers, viewer_id = await _create_test_user(client, admin_headers, "viewer")

    # Admin creates a key for themselves via self-service
    create_resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Admin Only Key"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    admin_key_id = create_resp.json()["id"]

    # Viewer tries to delete admin's key
    del_resp = await client.delete(
        f"/auth/api-keys/{admin_key_id}",
        headers=viewer_headers,
    )
    # The endpoint filters by current_user.id, so another user's key is "not found"
    assert del_resp.status_code == 404


# ---------------------------------------------------------------------------
# fix(#821): expiry, token_version staleness, deprecated query-param lane
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_key_with_future_expiry_accepted_and_surfaced(client: AsyncClient):
    """A key minted with a future expires_at authenticates and the expiry is
    returned by both the create response and the listing."""
    from datetime import datetime, timedelta, timezone

    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Expiring Key", "expires_at": expiry},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expires_at"] is not None

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": data["key"]})
    assert me_resp.status_code == 200

    list_resp = await client.get("/auth/api-keys/", headers=admin_headers)
    listed = {item["id"]: item for item in list_resp.json()["items"]}
    assert listed[data["id"]]["expires_at"] is not None


@pytest.mark.anyio
async def test_api_key_null_expiry_accepted(client: AsyncClient):
    """Omitting expires_at mints a non-expiring key (legacy behavior)."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Forever Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expires_at"] is None

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": data["key"]})
    assert me_resp.status_code == 200


@pytest.mark.anyio
async def test_expired_api_key_rejected(client: AsyncClient, test_db_session):
    """An expired key behaves exactly like an invalid one (401 / anonymous)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.modules.auth.models import ApiKey

    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Soon Expired"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    raw_key = data["key"]

    # Sanity: the key works before expiry.
    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    # Force the key past its expiry (mint-time validation rejects past values,
    # so an already-expired key can only be produced by time passing).
    await test_db_session.execute(
        update(ApiKey)
        .where(ApiKey.id == uuid.UUID(data["id"]))
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await test_db_session.commit()

    # Required-auth endpoint: 401, exactly like an invalid key.
    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 401

    # Optional-auth endpoint: anonymous fallback, exactly like an invalid key.
    items_resp = await client.get(
        "/collections/datasets/items",
        headers={"X-Api-Key": raw_key},
    )
    assert items_resp.status_code == 200


@pytest.mark.anyio
async def test_mint_with_past_expiry_rejected(client: AsyncClient):
    """Minting a key that is already expired is a validation error."""
    from datetime import datetime, timedelta, timezone

    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Born Dead", "expires_at": past},
        headers=admin_headers,
    )
    assert resp.status_code == 422

    # Admin mint surface enforces the same rule.
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Born Dead", "expires_at": past},
        headers=admin_headers,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_stale_key_epoch_api_key_rejected(client: AsyncClient, test_db_session):
    """A key minted before a key_epoch bump stops resolving after it."""
    from sqlalchemy import update

    from app.modules.auth.models import User

    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    _viewer_headers, viewer_id = await _create_test_user(
        client, admin_headers, "viewer"
    )

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": viewer_id, "name": "Pre-Epoch-Bump Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    # Matching key_epoch: the key authenticates.
    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    # Simulate a security-event bump (what password change / role change do).
    await test_db_session.execute(
        update(User)
        .where(User.id == uuid.UUID(viewer_id))
        .values(key_epoch=User.key_epoch + 1)
    )
    await test_db_session.commit()

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 401


@pytest.mark.anyio
async def test_api_key_invalidated_by_role_change(client: AsyncClient):
    """End-to-end: an admin role change invalidates previously minted keys."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    _viewer_headers, viewer_id = await _create_test_user(
        client, admin_headers, "viewer"
    )

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": viewer_id, "name": "Pre-Role-Change Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    # Admin changes the user's role (promotion and demotion both bump
    # key_epoch — a key must not silently change privilege level).
    patch_resp = await client.patch(
        f"/admin/users/{viewer_id}",
        json={"role": "editor"},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 401


@pytest.mark.anyio
async def test_idempotent_role_patch_keeps_api_keys_valid(client: AsyncClient):
    """Regression (#821 codex review): resubmitting the user's CURRENT role
    (e.g. a reconciliation-tool PATCH) is not a security event and must not
    bump key_epoch."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    _editor_headers, editor_id = await _create_test_user(
        client, admin_headers, "editor"
    )

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": editor_id, "name": "Idempotent PATCH Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    # PATCH the same role the user already has — a no-op, not a role change.
    patch_resp = await client.patch(
        f"/admin/users/{editor_id}",
        json={"role": "editor"},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200


@pytest.mark.anyio
async def test_api_key_mint_rejected_for_pending_user(
    client: AsyncClient, test_db_session
):
    """Regression (#821 codex review): keys cannot be minted for non-active
    owners — a pre-approval key must not exist to wake up privileged later."""
    from app.modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    pending = User(
        username=f"pending_apikey_{suffix}",
        email=f"pending_apikey_{suffix}@example.com",
        password_hash="unused",
        status="pending",
        is_active=False,
    )
    test_db_session.add(pending)
    await test_db_session.commit()

    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": str(pending.id), "name": "Pending Owner Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_pre_approval_key_does_not_survive_approval(
    client: AsyncClient, test_db_session
):
    """Regression (#821 codex review): a key that existed while the account
    was pending (legacy row predating the mint guard) must not start working
    with the approved role's privileges — approve_user bumps key_epoch."""
    import hashlib
    import secrets

    from app.modules.auth.models import ApiKey, User

    suffix = uuid.uuid4().hex[:8]
    pending = User(
        username=f"pending_legacykey_{suffix}",
        email=f"pending_legacykey_{suffix}@example.com",
        password_hash="unused",
        status="pending",
        is_active=False,
    )
    test_db_session.add(pending)
    await test_db_session.flush()

    # Simulate a legacy key minted while the account was pending (the mint
    # guard now refuses this path, so insert the row directly).
    raw_key = secrets.token_urlsafe(32)
    test_db_session.add(
        ApiKey(
            user_id=pending.id,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            fingerprint=f"{raw_key[:8]}…{raw_key[-4:]}",
            name="Legacy Pre-Approval Key",
            key_epoch=pending.key_epoch,
        )
    )
    await test_db_session.commit()

    # Pending owner: blocked by the status check.
    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 401

    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    approve_resp = await client.post(
        f"/admin/users/{pending.id}/approve/",
        json={"role": "viewer"},
        headers=admin_headers,
    )
    assert approve_resp.status_code == 200

    # Approved owner: the epoch bump keeps the pre-approval key dead.
    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 401


@pytest.mark.anyio
async def test_logout_does_not_invalidate_api_keys(client: AsyncClient):
    """Regression (#821): plain logout bumps token_version but must leave
    API keys working — keys exist to outlive browser sessions (CI, MCP,
    tile URLs)."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    viewer_headers, _viewer_id = await _create_test_user(
        client, admin_headers, "viewer"
    )

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Survives Logout Key"},
        headers=viewer_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    logout_resp = await client.post("/auth/logout/", headers=viewer_headers)
    assert logout_resp.status_code == 204

    # The JWT used for the logout is now stale (token_version bumped)...
    jwt_resp = await client.get("/auth/me/", headers=viewer_headers)
    assert jwt_resp.status_code == 401

    # ...but the API key still authenticates (key_epoch untouched).
    key_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert key_resp.status_code == 200


@pytest.mark.anyio
async def test_api_key_invalidated_by_password_change(client: AsyncClient):
    """End-to-end: a real password change invalidates previously minted keys."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    viewer_headers, _viewer_id = await _create_test_user(
        client, admin_headers, "viewer"
    )

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Pre-Password-Change Key"},
        headers=viewer_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    # _create_test_user's fixed password; the change bumps token_version.
    change_resp = await client.post(
        "/auth/change-password/",
        json={
            "current_password": "TestPass1234!",
            "new_password": "NewTestPass5678!",
        },
        headers=viewer_headers,
    )
    assert change_resp.status_code == 204

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 401


@pytest.mark.anyio
async def test_query_param_lane_still_authenticates(client: AsyncClient):
    """The deprecated ?api_key= query lane keeps working (tile-URL clients)."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Query Lane Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    me_resp = await client.get(f"/auth/me/?api_key={raw_key}")
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == ADMIN_USER
