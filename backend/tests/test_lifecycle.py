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

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer_group

import app.core.edition as edition_mod
from app.modules.audit.models import AuditLog
from app.modules.audit.service import log_action
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.oauth.encryption import decrypt_secret, encrypt_secret
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.providers.local import verify_password
from app.modules.catalog.datasets.domain.models import Dataset, Record
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

    Phase 220 created the original fixture for the deactivate-only test
    (oauth_accounts + oauth_providers + users scoped by slug/username).

    Phase 221 extends it to also clean up rows the LIFECYCLE-06 conversion test
    and LIFECYCLE-07 round-trip test seed:
      - audit_logs rows by user_id OR resource_id (test-seeded
        'test.seed.lifecycle' rows AND endpoint-written
        'auth.convert_saml_to_local' rows where resource_id == converted user_id).
      - user_roles rows by user_id (LIFECYCLE-06 conversion-test seed).
      - records rows by created_by (LIFECYCLE-06 record-ownership seed). Datasets
        attached via record_id are cleaned via CASCADE; an explicit datasets
        delete keyed by record_id is run BEFORE the records delete as a safety
        net for partial seeds.

    FK semantics consulted:
      * audit_logs.user_id  -> users.id  (ondelete=SET NULL,
        backend/app/modules/audit/models.py:22).
      * records.created_by  -> users.id  (ondelete=SET NULL,
        backend/app/modules/catalog/datasets/domain/models.py:121-123).
      * datasets.record_id  -> records.id (ondelete=CASCADE,
        backend/app/modules/catalog/datasets/domain/models.py:207-210).
      Dataset has NO `created_by` column; dataset ownership flows through Record.

    Mirrors the test-local cleanup pattern from Phase 220 (D-11 -- fixture stays
    test-local, NOT promoted to conftest.py).
    """
    yield
    try:
        # Resolve seeded user's id (may be absent if test failed before seeding)
        result = await test_db_session.execute(
            text("SELECT id FROM catalog.users WHERE username = :username"),
            {"username": LIFECYCLE_USERNAME},
        )
        row = result.first()
        seeded_user_id = row[0] if row is not None else None

        if seeded_user_id is not None:
            # Phase 221 NEW DELETEs (run BEFORE existing oauth/users DELETEs).
            # AuditLog.resource_id is Mapped[uuid.UUID | None] -- single :uid
            # parameter matches both `user_id` (the actor) and `resource_id`
            # (the target user the conversion endpoint records). Project
            # pattern is UUID equality (test_saml_overlay.py:699,
            # test_provenance_attribution.py:338).
            await test_db_session.execute(
                text(
                    "DELETE FROM catalog.audit_logs "
                    "WHERE user_id = :uid OR resource_id = :uid"
                ),
                {"uid": seeded_user_id},
            )
            await test_db_session.execute(
                text("DELETE FROM catalog.user_roles WHERE user_id = :uid"),
                {"uid": seeded_user_id},
            )
            # Defensive: drop any datasets pointing at the seeded user's records
            # before the records DELETE. The records cascade also handles this,
            # but an explicit pre-delete keeps the row count clean if a partial
            # seed left dataset orphans without record links.
            await test_db_session.execute(
                text(
                    "DELETE FROM catalog.datasets "
                    "WHERE record_id IN ("
                    "  SELECT id FROM catalog.records WHERE created_by = :uid"
                    ")"
                ),
                {"uid": seeded_user_id},
            )
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE created_by = :uid"),
                {"uid": seeded_user_id},
            )

        # Phase 220 EXISTING DELETEs (preserved verbatim).
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
        # Fernet ciphertext is non-deterministic (random IV per call), so compare
        # by decrypting the survivor and matching the original plaintext.
        assert decrypt_secret(survivor.idp_certificate) == LIFECYCLE_CERT_PEM
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


@pytest.mark.lifecycle
async def test_convert_saml_user_to_local_preserves_user_data(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    saml_overlay_registered,
    _cleanup_lifecycle_rows,
):
    """LIFECYCLE-06: converting a SAML user to local-password preserves audit
    history, group memberships, and record/dataset ownership.

    Seeds a representative trio of FK referrers (audit_log, user_roles, record
    + attached dataset) -- per Phase 221 D-06, three independent FKs from three
    different domains demonstrate the design promise that users.id is the
    durable handle. Note that "dataset ownership" is recorded on Record.created_by
    (the Dataset table has no created_by column; the dataset is bound to its
    record via record_id with ondelete=CASCADE -- so preserving the record
    preserves the dataset row by construction).

    Then invokes POST /admin/users/{user_id}/convert-saml-to-local/ via
    TestClient and asserts (a) the conversion succeeded, (b) every seeded FK
    referrer survives with its original user_id, (c) the new audit_log row
    records the conversion with the allow-listed details (no password material).
    """
    saved_info = edition_mod._info
    edition_mod.init_edition(["enterprise"])

    try:
        # ---------- SEED phase ----------

        # Seed SAML provider (mirrors test_overlay_removal_preserves_saml_data
        # at test_lifecycle.py:136-150 -- encrypt_secret() required for the
        # NOT-NULL Fernet ciphertext columns; Pitfall 3).
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

        # Seed SAML user (auth_provider='oauth' -- SAML users land here per
        # Phase 217 D-04).
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

        # Seed user_roles assignment -- pick the 'viewer' role (always present
        # in the seeded dev DB; verify by SELECTing it). If 'viewer' is missing,
        # SELECT any role; the test only asserts that THE seeded role row
        # survives, not that a specific role-name is present.
        role_row = (
            await test_db_session.execute(
                select(Role).where(Role.name == "viewer")
            )
        ).scalar_one_or_none()
        if role_row is None:
            role_row = (
                await test_db_session.execute(select(Role).limit(1))
            ).scalar_one()
        seeded_role_id = role_row.id

        user_role = UserRole(user_id=seeded_user_id, role_id=seeded_role_id)
        test_db_session.add(user_role)
        await test_db_session.commit()

        # Seed an AuditLog row via log_action (D-10 pattern -- log_action does
        # NOT commit; caller commits explicitly).
        await log_action(
            session=test_db_session,
            user_id=seeded_user_id,
            action="test.seed.lifecycle",
            resource_type="user",
            resource_id=seeded_user_id,
            details={"phase": "221", "purpose": "lifecycle-06-fk-survival"},
        )
        await test_db_session.commit()

        # Seed a Record row with created_by=seeded_user_id. Record carries the
        # ownership invariant for LIFECYCLE-06 (B1 fix: Dataset has no
        # created_by column -- ownership lives on Record).
        # Required non-null fields per
        # backend/app/modules/catalog/datasets/domain/models.py:73-87:
        # title (Text, NOT NULL), record_type (server_default='vector_dataset',
        # CHECK-constrained to one of the seven enum values).
        # `created_by` is nullable Mapped[UUID|None] with ondelete=SET NULL --
        # the very FK whose preservation we want to assert.
        record = Record(
            title="Phase 221 lifecycle test record (delete via cleanup)",
            record_type="vector_dataset",
            created_by=seeded_user_id,
        )
        test_db_session.add(record)
        await test_db_session.commit()
        await test_db_session.refresh(record)
        seeded_record_id = record.id

        # Optional but valuable: also seed a Dataset bound to that Record.
        # Asserting the dataset survives proves the full ownership CHAIN
        # (User <- Record.created_by, Record <- Dataset.record_id CASCADE) is
        # intact, not just the Record row in isolation.
        # Dataset table required-non-null columns: record_id (FK, unique),
        # table_name (String(255), unique, nullable=False). Use a uuid-suffixed
        # table_name to keep parallel-run uniqueness.
        dataset = Dataset(
            record_id=seeded_record_id,
            table_name=f"lifecycle_test_{uuid.uuid4().hex[:8]}",
        )
        test_db_session.add(dataset)
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        seeded_dataset_id = dataset.id

        # ---------- INVOKE phase ----------

        new_password = "lifecycle-test-newpw-2026"
        resp = await client.post(
            f"/admin/users/{seeded_user_id}/convert-saml-to-local/",
            json={"password": new_password},
            headers=admin_auth_header,
        )

        # ---------- ASSERT phase ----------

        # Response shape -- UserResponse serializes UUID -> str in the JSON
        # body; this str() comparison is for the over-the-wire form, NOT the
        # ORM-level UUID equality used in the assertions below.
        assert resp.status_code == 200, (
            f"conversion endpoint returned {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["id"] == str(seeded_user_id), (
            f"users.id changed across conversion: {body['id']} != {seeded_user_id}"
        )
        # NOTE: UserResponse schema (backend/app/modules/auth/schemas.py:48-62)
        # does NOT expose `auth_provider` -- the ORM-level assertion below on
        # the re-fetched User row is the authoritative auth_provider check.

        # Re-fetch User row to assert ORM-level state (defeats any session-cache
        # staleness from the seed phase). expire_all() is SYNC -- do NOT await
        # (B2 fix; project pattern at test_embed_tokens.py:798,852).
        test_db_session.expire_all()
        user_row = (
            await test_db_session.execute(
                select(User).where(User.id == seeded_user_id)
            )
        ).scalar_one()
        assert user_row.id == seeded_user_id  # immutable handle
        assert user_row.auth_provider == "local"
        assert user_row.password_hash is not None
        assert verify_password(new_password, user_row.password_hash), (
            "stored password hash does not verify against the supplied password"
        )

        # OAuthAccount SAML linkage row deleted
        oauth_acct_row = (
            await test_db_session.execute(
                select(OAuthAccount).where(
                    OAuthAccount.user_id == seeded_user_id,
                    OAuthAccount.provider_id == seeded_provider_id,
                )
            )
        ).scalar_one_or_none()
        assert oauth_acct_row is None, (
            "SAML oauth_accounts row was not deleted by the conversion"
        )

        # OAuthProvider row preserved (D-04 -- other users may still link)
        provider_row = (
            await test_db_session.execute(
                select(OAuthProvider).where(OAuthProvider.id == seeded_provider_id)
            )
        ).scalar_one()
        assert provider_row.provider_type == "saml"

        # user_roles row preserved (D-07)
        ur_row = (
            await test_db_session.execute(
                select(UserRole).where(
                    UserRole.user_id == seeded_user_id,
                    UserRole.role_id == seeded_role_id,
                )
            )
        ).scalar_one_or_none()
        assert ur_row is not None, "user_roles row was destroyed by conversion"

        # Seeded audit_log row preserved (D-06 -- users.id immutable, FK survives)
        seed_log_row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == seeded_user_id,
                    AuditLog.action == "test.seed.lifecycle",
                )
            )
        ).scalar_one_or_none()
        assert seed_log_row is not None, (
            "test.seed.lifecycle audit_log row was destroyed by conversion"
        )

        # NEW audit_log row written by the conversion endpoint (Plan 01 Task 3).
        # AuditLog.resource_id is Mapped[uuid.UUID | None] -- compare via UUID
        # equality (B3 fix; project pattern at test_saml_overlay.py:699 and
        # test_provenance_attribution.py:338). NO `str()` cast.
        conversion_log_row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "auth.convert_saml_to_local",
                    AuditLog.resource_id == seeded_user_id,
                )
            )
        ).scalar_one_or_none()
        assert conversion_log_row is not None, (
            "endpoint did not write the auth.convert_saml_to_local audit_log row"
        )
        assert conversion_log_row.resource_type == "user"
        # Allow-listed details only (security invariant T-221-03)
        assert conversion_log_row.details == {
            "from": "saml",
            "to": "local",
            "provider_slug": LIFECYCLE_SLUG,
        }, f"audit details not allow-listed: {conversion_log_row.details!r}"

        # Record row preserved with original created_by (D-06 -- the
        # ownership-invariant assertion for LIFECYCLE-06).
        record_row = (
            await test_db_session.execute(
                select(Record).where(Record.id == seeded_record_id)
            )
        ).scalar_one()
        assert record_row.created_by == seeded_user_id, (
            f"record.created_by changed: {record_row.created_by} != {seeded_user_id}"
        )

        # Dataset row preserved via record_id (cascade did NOT fire because the
        # Record was preserved -- this asserts the full ownership chain is
        # intact end-to-end).
        dataset_row = (
            await test_db_session.execute(
                select(Dataset).where(Dataset.id == seeded_dataset_id)
            )
        ).scalar_one()
        assert dataset_row.record_id == seeded_record_id, (
            "dataset.record_id link broken across conversion"
        )

    finally:
        edition_mod._info = saved_info
        # _extensions / _routers / _cleanup_lifecycle_rows handle DB cleanup
