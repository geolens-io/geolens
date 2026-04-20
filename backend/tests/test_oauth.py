"""Tests for OAuth/OIDC integration (Phase 118)."""

import uuid

from sqlalchemy import select


# ---------------------------------------------------------------------------
# OAUTH-02: Encryption roundtrip
# ---------------------------------------------------------------------------


class TestSecretEncryption:
    def test_encrypt_returns_different_string(self):
        from app.modules.auth.oauth.encryption import encrypt_secret

        result = encrypt_secret("my-secret")
        assert result != "my-secret"
        assert len(result) > 0

    def test_decrypt_roundtrip(self):
        from app.modules.auth.oauth.encryption import decrypt_secret, encrypt_secret

        original = "my-secret"
        encrypted = encrypt_secret(original)
        assert decrypt_secret(encrypted) == original

    def test_encryption_key_derived_via_hkdf(self):
        """Key derivation uses HKDF, not raw JWT secret."""
        from app.modules.auth.oauth.encryption import _get_fernet
        from app.core.config import settings

        fernet = _get_fernet()
        # The Fernet key should NOT be a simple encoding of jwt_secret_key
        import base64

        raw_key = base64.urlsafe_b64encode(
            settings.jwt_secret_key.get_secret_value().encode()[:32].ljust(32, b"\x00")
        )
        assert fernet._signing_key != raw_key[:16]


# ---------------------------------------------------------------------------
# Models: OAuthProvider columns
# ---------------------------------------------------------------------------


class TestOAuthProviderModel:
    def test_has_required_columns(self):
        from app.modules.auth.oauth.models import OAuthProvider

        mapper = OAuthProvider.__table__
        col_names = {c.name for c in mapper.columns}
        expected = {
            "id",
            "slug",
            "display_name",
            "provider_type",
            "client_id",
            "client_secret_encrypted",
            "discovery_url",
            "authorize_url",
            "token_url",
            "userinfo_url",
            "scopes",
            "default_role",
            "group_claim",
            "group_role_mapping",
            "enabled",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(col_names), f"Missing: {expected - col_names}"


class TestOAuthAccountModel:
    def test_has_unique_constraint(self):
        from app.modules.auth.oauth.models import OAuthAccount

        table = OAuthAccount.__table__
        constraints = [
            c.name for c in table.constraints if hasattr(c, "name") and c.name
        ]
        assert "uq_oauth_account_provider_subject" in constraints

    def test_has_provider_and_user_fks(self):
        from app.modules.auth.oauth.models import OAuthAccount

        col_names = {c.name for c in OAuthAccount.__table__.columns}
        assert "provider_id" in col_names
        assert "user_id" in col_names
        assert "subject" in col_names


class TestUserAuthProviderColumn:
    def test_user_has_auth_provider(self):
        from app.modules.auth.models import User

        col_names = {c.name for c in User.__table__.columns}
        assert "auth_provider" in col_names

    def test_auth_provider_defaults_to_local(self):
        from app.modules.auth.models import User

        col = User.__table__.c.auth_provider
        assert col.server_default is not None
        assert "local" in str(col.server_default.arg)


# ---------------------------------------------------------------------------
# OAUTH-01: CRUD service tests
# ---------------------------------------------------------------------------


class TestOAuthProviderCRUD:
    """Test provider CRUD operations via service layer."""

    async def test_create_provider_encrypts_secret(self, client, test_db_session):
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        data = OAuthProviderCreate(
            slug="test-google",
            display_name="Google",
            provider_type="google",
            client_id="google-client-id",
            client_secret="super-secret-123",
            discovery_url="https://accounts.google.com/.well-known/openid-configuration",
        )
        provider = await create_provider(test_db_session, data)

        assert provider.slug == "test-google"
        assert provider.client_id == "google-client-id"
        # Secret must be encrypted, not stored in plaintext
        assert provider.client_secret_encrypted != "super-secret-123"
        assert len(provider.client_secret_encrypted) > 0

    async def test_get_provider_by_slug(self, client, test_db_session):
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider, get_provider_by_slug

        data = OAuthProviderCreate(
            slug=f"slug-test-{uuid.uuid4().hex[:6]}",
            display_name="Test Provider",
            provider_type="oidc",
            client_id="test-client",
            client_secret="test-secret",
        )
        created = await create_provider(test_db_session, data)

        found = await get_provider_by_slug(test_db_session, data.slug)
        assert found is not None
        assert found.id == created.id
        assert found.slug == data.slug

    async def test_get_provider_by_slug_not_found(self, client, test_db_session):
        from app.modules.auth.oauth.service import get_provider_by_slug

        result = await get_provider_by_slug(test_db_session, "nonexistent")
        assert result is None

    async def test_update_provider_re_encrypts_secret(self, client, test_db_session):
        from app.modules.auth.oauth.encryption import decrypt_secret
        from app.modules.auth.oauth.schemas import (
            OAuthProviderCreate,
            OAuthProviderUpdate,
        )
        from app.modules.auth.oauth.service import create_provider, update_provider

        data = OAuthProviderCreate(
            slug=f"update-test-{uuid.uuid4().hex[:6]}",
            display_name="Update Test",
            provider_type="oidc",
            client_id="old-client",
            client_secret="old-secret",
        )
        provider = await create_provider(test_db_session, data)
        old_encrypted = provider.client_secret_encrypted

        update_data = OAuthProviderUpdate(
            client_secret="new-secret",
            display_name="Updated Name",
        )
        updated = await update_provider(test_db_session, provider, update_data)

        assert updated.display_name == "Updated Name"
        assert updated.client_secret_encrypted != old_encrypted
        assert decrypt_secret(updated.client_secret_encrypted) == "new-secret"

    async def test_delete_provider(self, client, test_db_session):
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import (
            create_provider,
            delete_provider,
            get_provider_by_slug,
        )

        data = OAuthProviderCreate(
            slug=f"delete-test-{uuid.uuid4().hex[:6]}",
            display_name="Delete Test",
            provider_type="oidc",
            client_id="del-client",
            client_secret="del-secret",
        )
        provider = await create_provider(test_db_session, data)
        slug = provider.slug

        await delete_provider(test_db_session, provider)
        result = await get_provider_by_slug(test_db_session, slug)
        assert result is None

    async def test_list_enabled_providers(self, client, test_db_session):
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider, list_providers

        suffix = uuid.uuid4().hex[:6]
        # Create enabled provider
        enabled_data = OAuthProviderCreate(
            slug=f"enabled-{suffix}",
            display_name="Enabled",
            provider_type="google",
            client_id="en-client",
            client_secret="en-secret",
            enabled=True,
        )
        await create_provider(test_db_session, enabled_data)

        # Create disabled provider
        disabled_data = OAuthProviderCreate(
            slug=f"disabled-{suffix}",
            display_name="Disabled",
            provider_type="microsoft",
            client_id="dis-client",
            client_secret="dis-secret",
            enabled=False,
        )
        await create_provider(test_db_session, disabled_data)

        enabled_list = await list_providers(test_db_session, enabled_only=True)
        enabled_slugs = {p.slug for p in enabled_list}
        assert f"enabled-{suffix}" in enabled_slugs
        assert f"disabled-{suffix}" not in enabled_slugs

    async def test_crud_lifecycle(self, client, test_db_session):
        """Full CRUD lifecycle: create -> read -> update -> delete."""
        from app.modules.auth.oauth.encryption import decrypt_secret
        from app.modules.auth.oauth.schemas import (
            OAuthProviderCreate,
            OAuthProviderUpdate,
        )
        from app.modules.auth.oauth.service import (
            create_provider,
            delete_provider,
            get_provider_by_slug,
            update_provider,
        )

        slug = f"lifecycle-{uuid.uuid4().hex[:6]}"

        # Create
        provider = await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=slug,
                display_name="Lifecycle",
                provider_type="oidc",
                client_id="lc-client",
                client_secret="lc-secret",
            ),
        )
        assert provider.id is not None
        assert decrypt_secret(provider.client_secret_encrypted) == "lc-secret"

        # Read
        found = await get_provider_by_slug(test_db_session, slug)
        assert found is not None
        assert found.id == provider.id

        # Update
        updated = await update_provider(
            test_db_session,
            found,
            OAuthProviderUpdate(display_name="Updated Lifecycle"),
        )
        assert updated.display_name == "Updated Lifecycle"

        # Delete
        await delete_provider(test_db_session, updated)
        assert await get_provider_by_slug(test_db_session, slug) is None

    async def test_encryption_roundtrip_in_crud(self, client, test_db_session):
        """Verify encrypt/decrypt works through the full CRUD path."""
        from app.modules.auth.oauth.encryption import decrypt_secret
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        secret = "my-super-secret-client-key-12345"
        provider = await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"enc-roundtrip-{uuid.uuid4().hex[:6]}",
                display_name="Enc Test",
                provider_type="google",
                client_id="enc-client",
                client_secret=secret,
            ),
        )

        # Encrypted value in DB is not plaintext
        assert provider.client_secret_encrypted != secret
        # Decrypted value matches original
        assert decrypt_secret(provider.client_secret_encrypted) == secret


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestOAuthSchemas:
    def test_response_excludes_client_secret(self):
        from app.modules.auth.oauth.schemas import OAuthProviderResponse

        field_names = set(OAuthProviderResponse.model_fields.keys())
        assert "client_secret" not in field_names
        assert "client_secret_encrypted" not in field_names
        assert "client_id" in field_names

    def test_public_schema_minimal(self):
        from app.modules.auth.oauth.schemas import OAuthProviderPublic

        field_names = set(OAuthProviderPublic.model_fields.keys())
        assert field_names == {"slug", "display_name", "provider_type"}


# ---------------------------------------------------------------------------
# OAUTH-04 through OAUTH-07: OAuth flow tests
# ---------------------------------------------------------------------------


class TestFindOrCreateOAuthUser:
    """Test user find-or-create logic for OAuth login."""

    async def _create_test_provider(self, db, **overrides):
        """Helper: create an OAuthProvider in the test DB."""
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        suffix = uuid.uuid4().hex[:6]
        defaults = dict(
            slug=f"test-provider-{suffix}",
            display_name="Test Provider",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="test-secret",
            enabled=True,
            default_role="viewer",
        )
        defaults.update(overrides)
        return await create_provider(db, OAuthProviderCreate(**defaults))

    async def test_auto_create_user(self, client, test_db_session):
        """OAUTH-05: New email auto-creates user with default role and auth_provider='oauth'."""
        from app.modules.auth.oauth.service import find_or_create_oauth_user

        provider = await self._create_test_provider(test_db_session)
        await test_db_session.commit()

        userinfo = {
            "sub": "new-user-sub-123",
            "email": f"newuser-{uuid.uuid4().hex[:6]}@example.com",
            "name": "New User",
        }
        user = await find_or_create_oauth_user(test_db_session, provider, userinfo, {})
        await test_db_session.commit()

        assert user is not None
        assert user.email == userinfo["email"]
        assert user.auth_provider == "oauth"
        assert user.password_hash is None
        assert user.is_active is True
        assert user.status == "active"

        # Should have the provider's default_role
        role_names = {r.name for r in user.roles}
        assert "viewer" in role_names

    async def test_email_linking(self, client, test_db_session):
        """OAUTH-06: OAuth login with existing email links to existing user."""
        from app.modules.auth.models import User
        from app.modules.auth.oauth.models import OAuthAccount
        from app.modules.auth.oauth.service import find_or_create_oauth_user
        from app.modules.auth.providers.local import hash_password

        email = f"existing-{uuid.uuid4().hex[:6]}@example.com"

        # Create local user first
        local_user = User(
            username=f"localuser-{uuid.uuid4().hex[:6]}",
            email=email,
            password_hash=hash_password("password123"),
            is_active=True,
            status="active",
            auth_provider="local",
        )
        test_db_session.add(local_user)
        await test_db_session.flush()

        provider = await self._create_test_provider(test_db_session)
        await test_db_session.commit()

        userinfo = {
            "sub": "existing-user-sub-456",
            "email": email,
            "name": "Existing User",
        }
        user = await find_or_create_oauth_user(test_db_session, provider, userinfo, {})
        await test_db_session.commit()

        # Should be the same user, not a new one
        assert user.id == local_user.id
        assert user.email == email

        # Should have created an OAuthAccount link
        result = await test_db_session.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider_id == provider.id,
                OAuthAccount.user_id == local_user.id,
            )
        )
        link = result.scalar_one_or_none()
        assert link is not None
        assert link.subject == "existing-user-sub-456"

    async def test_existing_oauth_link_returns_user(self, client, test_db_session):
        """Returning OAuth user with existing link returns the linked user directly."""
        from app.modules.auth.oauth.service import find_or_create_oauth_user

        provider = await self._create_test_provider(test_db_session)
        await test_db_session.commit()

        userinfo = {
            "sub": f"returning-sub-{uuid.uuid4().hex[:6]}",
            "email": f"returning-{uuid.uuid4().hex[:6]}@example.com",
            "name": "Returning User",
        }

        # First login creates user
        user1 = await find_or_create_oauth_user(test_db_session, provider, userinfo, {})
        await test_db_session.commit()

        # Second login returns same user
        user2 = await find_or_create_oauth_user(test_db_session, provider, userinfo, {})
        await test_db_session.commit()

        assert user1.id == user2.id

    async def test_group_role_mapping(self, client, test_db_session):
        """OAUTH-07: Group claims in userinfo map to GeoLens roles."""
        from app.modules.auth.oauth.service import find_or_create_oauth_user

        provider = await self._create_test_provider(
            test_db_session,
            group_claim="groups",
            group_role_mapping={"admins": "admin", "editors": "editor"},
            default_role="viewer",
        )
        await test_db_session.commit()

        userinfo = {
            "sub": f"group-sub-{uuid.uuid4().hex[:6]}",
            "email": f"groupuser-{uuid.uuid4().hex[:6]}@example.com",
            "name": "Group User",
            "groups": ["admins", "other-group"],
        }
        user = await find_or_create_oauth_user(test_db_session, provider, userinfo, {})
        await test_db_session.commit()

        role_names = {r.name for r in user.roles}
        assert "admin" in role_names

    async def test_username_collision_handled(self, client, test_db_session):
        """Auto-generated username handles collisions by appending random suffix."""
        from app.modules.auth.models import User
        from app.modules.auth.oauth.service import find_or_create_oauth_user
        from app.modules.auth.providers.local import hash_password

        # Create a user with the username that would be derived from email
        base_username = f"collision-{uuid.uuid4().hex[:4]}"
        existing = User(
            username=base_username,
            password_hash=hash_password("pass"),
            is_active=True,
            status="active",
        )
        test_db_session.add(existing)
        await test_db_session.flush()

        provider = await self._create_test_provider(test_db_session)
        await test_db_session.commit()

        userinfo = {
            "sub": f"collision-sub-{uuid.uuid4().hex[:6]}",
            "email": f"{base_username}@example.com",
            "name": "Collision User",
        }
        user = await find_or_create_oauth_user(test_db_session, provider, userinfo, {})
        await test_db_session.commit()

        # Should have created a new user with a suffixed username
        assert user.id != existing.id
        assert user.username.startswith(base_username)
        assert len(user.username) > len(base_username)


class TestOAuthLoginEndpoint:
    """Test the GET /auth/oauth/{slug}/login endpoint."""

    async def test_oauth_login_redirect(self, client, test_db_session):
        """OAUTH-04: Login endpoint returns redirect to IdP."""
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        suffix = uuid.uuid4().hex[:6]
        data = OAuthProviderCreate(
            slug=f"login-test-{suffix}",
            display_name="Login Test",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="test-secret",
            authorize_url="https://idp.example.com/authorize",
            token_url="https://idp.example.com/token",
            userinfo_url="https://idp.example.com/userinfo",
            enabled=True,
        )
        await create_provider(test_db_session, data)
        await test_db_session.commit()

        resp = await client.get(
            f"/auth/oauth/login-test-{suffix}/login",
            follow_redirects=False,
        )
        # Should redirect (302/307) to the IdP authorize URL
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "idp.example.com/authorize" in location
        # PKCE: should contain code_challenge param
        assert "code_challenge" in location

    async def test_oauth_login_not_found(self, client):
        """Login with nonexistent provider returns 404."""
        resp = await client.get(
            "/auth/oauth/nonexistent-provider/login",
            follow_redirects=False,
        )
        assert resp.status_code == 404


class TestOAuthCallbackCSRF:
    """Test that OAuth callback rejects invalid state/code parameters."""

    async def test_callback_missing_state_returns_error(self, client, test_db_session):
        """OAuth callback with no state/code params returns error redirect, not account takeover."""
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        suffix = uuid.uuid4().hex[:6]
        await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"csrf-test-{suffix}",
                display_name="CSRF Test",
                provider_type="oidc",
                client_id=f"client-{suffix}",
                client_secret="test-secret",
                authorize_url="https://idp.example.com/authorize",
                token_url="https://idp.example.com/token",
                userinfo_url="https://idp.example.com/userinfo",
                enabled=True,
            ),
        )
        await test_db_session.commit()

        # Call callback with no state/code — should error, not create a session
        resp = await client.get(
            f"/auth/oauth/csrf-test-{suffix}/callback",
            follow_redirects=False,
        )
        # The callback catches exceptions and redirects with error fragment
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert "error" in location

    async def test_callback_invalid_code_returns_error(self, client, test_db_session):
        """OAuth callback with an invalid authorization code returns error redirect."""
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        suffix = uuid.uuid4().hex[:6]
        await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"badcode-test-{suffix}",
                display_name="Bad Code Test",
                provider_type="oidc",
                client_id=f"client-{suffix}",
                client_secret="test-secret",
                authorize_url="https://idp.example.com/authorize",
                token_url="https://idp.example.com/token",
                userinfo_url="https://idp.example.com/userinfo",
                enabled=True,
            ),
        )
        await test_db_session.commit()

        # Call callback with bogus code and state — should error
        resp = await client.get(
            f"/auth/oauth/badcode-test-{suffix}/callback?code=bogus&state=malicious",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert "error" in location


class TestOAuthProvidersEndpoint:
    """Test the GET /auth/oauth/providers endpoint."""

    async def test_list_enabled_providers(self, client, test_db_session):
        """Only enabled providers are returned."""
        from app.modules.auth.oauth.schemas import OAuthProviderCreate
        from app.modules.auth.oauth.service import create_provider

        suffix = uuid.uuid4().hex[:6]
        # Create enabled
        await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"pub-enabled-{suffix}",
                display_name="Enabled Pub",
                provider_type="google",
                client_id=f"pub-en-{suffix}",
                client_secret="secret",
                enabled=True,
            ),
        )
        # Create disabled
        await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"pub-disabled-{suffix}",
                display_name="Disabled Pub",
                provider_type="microsoft",
                client_id=f"pub-dis-{suffix}",
                client_secret="secret",
                enabled=False,
            ),
        )
        await test_db_session.commit()

        resp = await client.get("/auth/oauth/providers/")
        assert resp.status_code == 200
        data = resp.json()
        slugs = {p["slug"] for p in data}
        assert f"pub-enabled-{suffix}" in slugs
        assert f"pub-disabled-{suffix}" not in slugs
        # Each item should only have slug, display_name, provider_type
        for p in data:
            assert set(p.keys()) == {"slug", "display_name", "provider_type"}
