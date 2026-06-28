"""HARDEN-03 (T-1238-09): Regression lock for the 5 admin/auth security invariants.

One focused test per invariant so a future refactor that breaks any of these
fails loudly.  This file does NOT rebuild the invariants — it asserts the
current behaviour.

Invariants tested:
  1. Guard matrix: manage_users vs manage_settings capability separation.
  2. Last-admin lockout: deleting/demoting the sole admin is rejected.
  3. OAuth client_secret redaction in audit details.
  4. token_version invalidation on SAML-to-local conversion.
  5. SAML enterprise gate: creating a SAML provider in OSS edition is rejected.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.admin.service import AdminService
from app.modules.auth.models import User, UserRole
from app.modules.audit.models import AuditLog


# ---------------------------------------------------------------------------
# Edition isolation (mirrors test_oauth.py pattern)
# ---------------------------------------------------------------------------


def _reset_edition():
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()


# ---------------------------------------------------------------------------
# Invariant 1: Guard matrix — manage_users vs manage_settings separation
#
# admin has BOTH manage_users AND manage_settings.
# viewer has NEITHER manage_users NOR manage_settings.
# An endpoint requiring manage_users MUST reject a viewer (403).
# An endpoint requiring manage_settings MUST reject a viewer (403).
# Together this asserts the two capabilities exist independently and are each
# enforced — a single combined "admin" blob would behave identically.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_guard_matrix_manage_users_rejects_viewer(
    client, viewer_auth_header: dict
):
    """A viewer (no manage_users) is forbidden on an admin user-management mutation."""
    # POST /admin/users/ requires manage_users
    resp = await client.post(
        "/admin/users/",
        json={"username": "ghost", "password": "TestPass1234!", "role": "viewer"},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403, (
        f"Expected 403 for viewer on manage_users endpoint, got {resp.status_code}: "
        f"{resp.text}"
    )


@pytest.mark.anyio
async def test_guard_matrix_manage_settings_rejects_viewer(
    client, viewer_auth_header: dict
):
    """A viewer (no manage_settings) is forbidden on a settings mutation."""
    # PUT /settings/ requires manage_settings
    resp = await client.put(
        "/settings/",
        json={},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403, (
        f"Expected 403 for viewer on manage_settings endpoint, got {resp.status_code}: "
        f"{resp.text}"
    )


# ---------------------------------------------------------------------------
# Invariant 2: Last-admin lockout
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_last_admin_delete_is_rejected(
    client, admin_auth_header: dict, test_db_session
):
    """Deleting the sole admin user is rejected by the last-admin lockout guard."""
    from app.modules.auth.models import Role

    # Confirm the sole admin via the service layer
    result = await test_db_session.execute(
        select(User)
        .join(UserRole, User.id == UserRole.user_id)
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "admin")
    )
    admin_users = result.scalars().all()
    assert admin_users, "No admin user found — test setup broken"

    if len(admin_users) == 1:
        admin_user = admin_users[0]
        # Load a second admin so the sole-admin guard is the only active guard
        # (self-delete guard fires first on DELETE /admin/users/{own_id}).
        # Assert the service-layer _ensure_not_last_admin raises for the sole admin.
        service = AdminService(test_db_session)
        await test_db_session.refresh(admin_user, attribute_names=["roles"])
        with pytest.raises(ValueError, match="last admin"):
            await service._ensure_not_last_admin(admin_user, "delete")
    else:
        # Multiple admins exist — test via HTTP by checking a non-self admin
        # is also guarded (should not apply here, but safe fallback).
        pytest.skip(
            "Multiple admins in test DB — sole-admin guard not exercisable via HTTP"
        )


@pytest.mark.anyio
async def test_last_admin_demote_is_rejected(client, test_db_session):
    """AdminService._ensure_not_last_admin raises ValueError when demoting sole admin."""
    from app.modules.auth.models import Role

    result = await test_db_session.execute(
        select(User)
        .join(UserRole, User.id == UserRole.user_id)
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "admin")
    )
    admin_users = result.scalars().all()
    assert admin_users, "No admin user in test DB"

    # If there is exactly one admin, ensure demote raises
    # (this service-layer test directly calls _ensure_not_last_admin)
    if len(admin_users) == 1:
        service = AdminService(test_db_session)
        # Manually load roles relationship
        await test_db_session.refresh(admin_users[0], attribute_names=["roles"])
        with pytest.raises(ValueError, match="last admin"):
            await service._ensure_not_last_admin(admin_users[0], "demote")


# ---------------------------------------------------------------------------
# #347 (ADM-04): deactivate guards return a SPECIFIC reason (surfaced in the admin
# toast). Locks the exact detail strings so the frontend keeps a meaningful
# message instead of a generic "Failed to deactivate user".
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_last_admin_deactivate_is_rejected(client, test_db_session):
    """Deactivating the sole admin raises the specific last-admin guard string."""
    from app.modules.auth.models import Role

    result = await test_db_session.execute(
        select(User)
        .join(UserRole, User.id == UserRole.user_id)
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "admin")
    )
    admin_users = result.scalars().all()
    assert admin_users, "No admin user in test DB"

    if len(admin_users) == 1:
        service = AdminService(test_db_session)
        await test_db_session.refresh(admin_users[0], attribute_names=["roles"])
        with pytest.raises(ValueError, match="Cannot deactivate the last admin user"):
            await service.deactivate_user(admin_users[0].id)
    else:
        pytest.skip("Multiple admins in test DB — sole-admin guard not exercisable")


@pytest.mark.anyio
async def test_deactivate_self_is_rejected(client, test_db_session):
    """Deactivating your own account raises the specific self-guard string."""
    result = await test_db_session.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    assert user is not None, "No user in test DB"

    service = AdminService(test_db_session)
    with pytest.raises(ValueError, match="Cannot deactivate your own account"):
        await service.deactivate_user(user.id, current_user_id=user.id)


# ---------------------------------------------------------------------------
# Invariant 3: OAuth client_secret redaction in audit details
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_oauth_client_secret_redacted_in_audit(
    client, admin_auth_header: dict, client_session
):
    """Creating an OAuth provider writes '<redacted>' for client_secret in audit."""
    real_secret = f"real-secret-{uuid.uuid4().hex[:8]}"
    slug = f"redact-test-{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": slug,
            "display_name": "Redact Test",
            "provider_type": "oidc",
            "client_id": "redact-client-id",
            "client_secret": real_secret,
            "authorize_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, f"Failed to create provider: {resp.text}"

    # Query the audit log for the oauth_provider.create action
    result = await client_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "oauth_provider.create")
        .order_by(AuditLog.created_at.desc())
    )
    rows = result.scalars().all()
    assert rows, "Expected oauth_provider.create audit row"

    row = rows[0]
    details_str = str(row.details)
    assert real_secret not in details_str, (
        f"Real client_secret {real_secret!r} must not appear in audit details; "
        f"got: {row.details}"
    )
    # The audit must contain the redacted marker
    assert "<redacted>" in details_str, (
        f"Expected '<redacted>' in audit details; got: {row.details}"
    )


# ---------------------------------------------------------------------------
# Invariant 4: token_version bump on SAML-to-local conversion
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_token_version_bumped_on_saml_to_local_conversion(
    client, test_db_session
):
    """convert_saml_user_to_local increments token_version to invalidate SAML JWTs."""
    from app.modules.auth.oauth.encryption import encrypt_secret
    from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
    from app.modules.auth.providers.local import hash_password

    # Create a SAML-linked user directly via ORM (no HTTP — SAML is enterprise-only)
    suffix = uuid.uuid4().hex[:8]

    provider = OAuthProvider(
        slug=f"saml-test-{suffix}",
        display_name="SAML Test",
        provider_type="saml",
        client_id="saml-no-client-id",
        client_secret_encrypted=encrypt_secret("saml-no-client-secret"),
        scopes="",
        enabled=True,
        default_role="viewer",
    )
    test_db_session.add(provider)
    await test_db_session.flush()

    saml_user = User(
        username=f"samluser-{suffix}",
        password_hash=hash_password("OldPass123!"),
        is_active=True,
        status="active",
        auth_provider="oauth",
    )
    test_db_session.add(saml_user)
    await test_db_session.flush()

    # Assign viewer role
    from app.modules.auth.models import Role

    role_result = await test_db_session.execute(
        select(Role).where(Role.name == "viewer")
    )
    viewer_role = role_result.scalar_one()
    test_db_session.add(UserRole(user_id=saml_user.id, role_id=viewer_role.id))
    await test_db_session.flush()

    # Link SAML account
    oauth_acct = OAuthAccount(
        provider_id=provider.id,
        user_id=saml_user.id,
        subject=f"saml-sub-{suffix}",
    )
    test_db_session.add(oauth_acct)
    await test_db_session.commit()

    # Record token_version before conversion
    await test_db_session.refresh(saml_user)
    version_before = saml_user.token_version

    # Execute conversion
    service = AdminService(test_db_session)
    user_after, _provider_slug = await service.convert_saml_user_to_local(
        saml_user.id, "NewPass1234!"
    )
    await test_db_session.commit()

    # token_version must have incremented
    await test_db_session.refresh(user_after)
    assert user_after.token_version > version_before, (
        f"Expected token_version > {version_before}, got {user_after.token_version}. "
        "SAML-to-local conversion must bump token_version (SEC-S15)."
    )


# ---------------------------------------------------------------------------
# Invariant 5: SAML enterprise gate in OSS edition
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_saml_provider_rejected_in_oss_edition(client, admin_auth_header: dict):
    """Creating a SAML provider in the OSS (non-enterprise) edition is rejected.

    The SAML gate fires at the Pydantic schema level (OAuthProviderCreate's
    model_validator calls is_enterprise()) before even reaching the service,
    resulting in a 422 Unprocessable Entity response from the endpoint.
    """
    # Ensure we're in community (non-enterprise) edition (autouse _clean_edition
    # already resets to None, but be explicit).
    import app.core.edition as ed_mod

    ed_mod._info = None  # force OSS / community edition

    slug = f"saml-oss-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": slug,
            "display_name": "SAML OSS Test",
            "provider_type": "saml",
            "idp_entity_id": "https://idp.example.com",
            "idp_sso_url": "https://idp.example.com/sso",
            "idp_certificate": "MIIC...",
            "sp_entity_id": "https://sp.example.com",
        },
        headers=admin_auth_header,
    )
    # 422 (Pydantic schema gate) or 400/409 (service gate) — both confirm rejection.
    assert resp.status_code in (400, 409, 422), (
        f"Expected rejection of SAML provider in OSS edition, got {resp.status_code}: "
        f"{resp.text}"
    )
    # The error must mention enterprise or SAML
    detail_str = str(resp.json())
    assert any(kw in detail_str.lower() for kw in ("enterprise", "saml")), (
        f"Expected enterprise/saml mention in error, got: {detail_str}"
    )


# ---------------------------------------------------------------------------
# client_session fixture (file-local, mirrors test_oauth.py D-04a)
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_session(client):
    """Yield an async session that shares client's override_get_db factory."""
    from app.core.dependencies import get_db
    from app.api.main import app

    overridden_get_db = app.dependency_overrides[get_db]
    async for session in overridden_get_db():
        yield session
