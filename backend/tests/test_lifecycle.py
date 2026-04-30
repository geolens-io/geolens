"""Integration test for the SAML enterprise overlay deactivation lifecycle (Phase 220 LIFECYCLE-04).

Closes ROADMAP Phase 220 SC#4: clearing the in-process extension registry
(simulating the operator-canonical "stop loading the geolens-enterprise overlay"
deactivation path per CONTEXT.md D-01) does NOT destroy SAML data.

The test seeds an OAuthProvider (provider_type='saml', all 4 deferred SAML
columns populated), an OAuthAccount linkage row, and a User with
auth_provider='oauth'. It then clears the three module-level state surfaces
(_extensions, _routers, app.core.edition._info via init_edition([])) and
asserts:

  1. oauth_providers row still queryable; 4 deferred columns retain values
     (loaded via select(...).options(undefer_group("saml"))).
  2. oauth_accounts linkage row still present.
  3. users row with auth_provider='oauth' still present.
  4. is_enterprise() returns False.
  5. The 4 typed registry accessors return their Default* counterparts.

D-04 (registry-level simulation in single pytest session) and D-05 (test
lives in backend/tests/test_lifecycle.py -- core repo, NOT enterprise).

The test is marked @pytest.mark.lifecycle. The marker is registered in
backend/pyproject.toml; it is NOT in the addopts deselect list, so it runs
by default in standard pytest invocations (per RESEARCH.md Pitfall 7).

The test takes the saml_overlay_registered fixture (conftest.py:454-484) so
the registry starts populated; the mid-test clear runs BEFORE the fixture's
finally block, which restores prior state on teardown. No new fixture is
needed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer_group

import app.core.edition as edition_mod
from app.modules.auth.models import User
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.platform.extensions import (
    _extensions,
    _routers,
    get_audit_extension,
    get_auth_extension,
    get_branding_extension,
    get_identity_extension,
)
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)


# ---------------------------------------------------------------------------
# Test-local fixture constants
# ---------------------------------------------------------------------------

LIFECYCLE_SLUG = "lifecycle-test"
LIFECYCLE_USERNAME = "lifecycle-saml-user"
LIFECYCLE_USER_EMAIL = "lifecycle-saml-user@example.test"
LIFECYCLE_USER_SUBJECT = "lifecycle-saml-subject-uuid"
LIFECYCLE_IDP_ENTITY_ID = "https://idp.test.lifecycle/entity"
LIFECYCLE_IDP_SSO_URL = "https://idp.test.lifecycle/sso"
LIFECYCLE_SP_ENTITY_ID = "https://geolens.test/auth/saml/lifecycle-test"
LIFECYCLE_CERT_PEM = (
    "-----BEGIN CERTIFICATE-----\nfake-pem-for-test\n-----END CERTIFICATE-----"
)


@pytest.fixture
async def _cleanup_lifecycle_rows(test_db_session: AsyncSession):
    """Best-effort teardown of any rows the lifecycle test seeded.

    Mirrors backend/tests/test_saml_overlay.py:185-219 but scoped to the
    lifecycle test's slug + username so other SAML tests are unaffected.
    """
    yield
    try:
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.oauth_accounts WHERE provider_id IN "
                "(SELECT id FROM catalog.oauth_providers WHERE slug = :slug)"
            ),
            {"slug": LIFECYCLE_SLUG},
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.oauth_providers WHERE slug = :slug"),
            {"slug": LIFECYCLE_SLUG},
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.users WHERE username = :username"),
            {"username": LIFECYCLE_USERNAME},
        )
        await test_db_session.commit()
    except Exception:
        await test_db_session.rollback()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.lifecycle
async def test_overlay_removal_preserves_saml_data(
    test_db_session: AsyncSession,
    saml_overlay_registered,
    _cleanup_lifecycle_rows,
):
    """LIFECYCLE-04: clearing the extension registry does not destroy SAML data.

    Steps:
      1. Seed (overlay is registered via saml_overlay_registered fixture).
         init_edition(["enterprise"]) flips is_enterprise() to True.
      2. Simulate "overlay not loaded": _extensions.clear(), _routers.clear(),
         init_edition([]) -- three explicit resets per RESEARCH.md Pitfall 2.
      3. Assert SQL persistence (provider + 4 deferred columns + account + user).
      4. Assert is_enterprise() is False.
      5. Assert typed accessors return Default* instances.
    """
    # 1. Seed phase -- overlay registered, edition flipped to enterprise.
    saved_info = edition_mod._info
    edition_mod.init_edition(["enterprise"])

    try:
        # Seed OAuthProvider (provider_type='saml', all 4 deferred SAML columns set).
        # client_id / client_secret_encrypted are NOT-NULL on the ORM
        # (backend/app/modules/auth/oauth/models.py:46-47) so we pass placeholder
        # strings -- same pattern as backend/tests/test_saml_overlay.py:96-137.
        provider = OAuthProvider(
            slug=LIFECYCLE_SLUG,
            display_name="Lifecycle Test IdP",
            provider_type="saml",
            client_id="unused",
            client_secret_encrypted=encrypt_secret("unused"),
            idp_entity_id=LIFECYCLE_IDP_ENTITY_ID,
            idp_sso_url=LIFECYCLE_IDP_SSO_URL,
            idp_certificate=encrypt_secret(LIFECYCLE_CERT_PEM),
            sp_entity_id=LIFECYCLE_SP_ENTITY_ID,
            enabled=True,
        )
        test_db_session.add(provider)
        await test_db_session.commit()
        await test_db_session.refresh(provider)
        seeded_provider_id = provider.id

        # Seed User (auth_provider='oauth' -- SAML users land here per Phase 217 D-04).
        user = User(
            username=LIFECYCLE_USERNAME,
            email=LIFECYCLE_USER_EMAIL,
            password_hash=None,
            is_active=True,
            auth_provider="oauth",
        )
        test_db_session.add(user)
        await test_db_session.commit()
        await test_db_session.refresh(user)
        seeded_user_id = user.id

        # Seed OAuthAccount linkage (provider -> user).
        account = OAuthAccount(
            user_id=seeded_user_id,
            provider_id=seeded_provider_id,
            subject=LIFECYCLE_USER_SUBJECT,
        )
        test_db_session.add(account)
        await test_db_session.commit()
        await test_db_session.refresh(account)

        # 2. Simulate "overlay not loaded" -- three module-level surfaces reset.
        _extensions.clear()
        _routers.clear()
        edition_mod.init_edition([])  # flips is_enterprise() to False

        # 3a. SQL: 4 deferred SAML columns retain values (loaded via undefer_group).
        stmt = (
            select(OAuthProvider)
            .where(OAuthProvider.id == seeded_provider_id)
            .options(undefer_group("saml"))
        )
        result = await test_db_session.execute(stmt)
        survivor = result.scalar_one()
        assert survivor.provider_type == "saml"
        assert survivor.idp_entity_id == LIFECYCLE_IDP_ENTITY_ID
        assert survivor.idp_sso_url == LIFECYCLE_IDP_SSO_URL
        assert survivor.idp_certificate == encrypt_secret(LIFECYCLE_CERT_PEM)
        assert survivor.sp_entity_id == LIFECYCLE_SP_ENTITY_ID

        # 3b. SQL: oauth_accounts linkage row still present.
        account_stmt = select(OAuthAccount).where(
            OAuthAccount.provider_id == seeded_provider_id,
            OAuthAccount.user_id == seeded_user_id,
        )
        account_row = (
            await test_db_session.execute(account_stmt)
        ).scalar_one_or_none()
        assert account_row is not None, (
            "OAuthAccount linkage was destroyed by registry clear"
        )
        assert account_row.subject == LIFECYCLE_USER_SUBJECT

        # 3c. SQL: User row with auth_provider='oauth' still present.
        user_stmt = select(User).where(User.id == seeded_user_id)
        user_row = (await test_db_session.execute(user_stmt)).scalar_one_or_none()
        assert user_row is not None, "User row was destroyed by registry clear"
        assert user_row.auth_provider == "oauth"
        assert user_row.username == LIFECYCLE_USERNAME

        # 4. Edition state -- is_enterprise() flipped to False.
        from app.core.edition import is_enterprise

        assert is_enterprise() is False, (
            "is_enterprise() should be False after init_edition([]) -- "
            "indicates _info was not re-initialized (RESEARCH.md Pitfall 2)"
        )

        # 5. Typed accessors fall back to Default* classes when registry is empty.
        assert isinstance(get_audit_extension(), DefaultAuditExtension)
        assert isinstance(get_branding_extension(), DefaultBrandingExtension)
        assert isinstance(get_auth_extension(), DefaultAuthExtension)
        assert isinstance(get_identity_extension(), DefaultIdentityExtension)

    finally:
        # Restore edition cache so subsequent tests see their original assumption.
        edition_mod._info = saved_info
        # _extensions / _routers are restored by the saml_overlay_registered
        # fixture's finally block (conftest.py:481-484) -- no work needed here.
