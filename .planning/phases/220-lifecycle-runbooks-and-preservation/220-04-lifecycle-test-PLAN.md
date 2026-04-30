---
phase: 220-lifecycle-runbooks-and-preservation
plan: 04
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/pyproject.toml
  - backend/tests/test_lifecycle.py
autonomous: true
requirements:
  - LIFECYCLE-04

must_haves:
  truths:
    - "`pytest -m lifecycle` collects and passes a single test that exercises the registry-level deactivation simulation (per D-04)"
    - "Test seeds an OAuthProvider row with provider_type='saml' and all 4 deferred SAML columns populated, plus a matching OAuthAccount linkage row, plus a User with auth_provider='oauth'"
    - "Test clears `_extensions` + `_routers` + re-calls `init_edition([])` (per D-04 + RESEARCH.md Pitfall 2 — three module-level state surfaces, three explicit resets)"
    - "Test asserts: 4 SAML columns + provider row + account row + user row + `is_enterprise() == False` + 4 typed accessors return Default* classes (per D-04 step 5)"
    - "Lifecycle marker registered in backend/pyproject.toml; NOT added to addopts deselect list (per RESEARCH.md Pitfall 7)"
  artifacts:
    - path: "backend/pyproject.toml"
      provides: "lifecycle pytest marker registration"
      contains: 'lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)'
    - path: "backend/tests/test_lifecycle.py"
      provides: "Registry-level deactivation integration test (LIFECYCLE-04)"
      contains:
        - "@pytest.mark.lifecycle"
        - "saml_overlay_registered"
        - "_extensions.clear()"
        - "_routers.clear()"
        - "init_edition([])"
        - "undefer_group"
        - "DefaultAuditExtension"
        - "DefaultBrandingExtension"
        - "DefaultAuthExtension"
        - "DefaultIdentityExtension"
  key_links:
    - from: "backend/tests/test_lifecycle.py"
      to: "backend/tests/conftest.py"
      via: "saml_overlay_registered fixture"
      pattern: "saml_overlay_registered"
    - from: "backend/tests/test_lifecycle.py"
      to: "app.platform.extensions"
      via: "imports _extensions, _routers, accessors, defaults"
      pattern: "from app.platform.extensions import"
    - from: "backend/tests/test_lifecycle.py"
      to: "app.core.edition"
      via: "init_edition([]) flips is_enterprise()"
      pattern: "init_edition"
---

<objective>
Register the `lifecycle` pytest marker in backend/pyproject.toml and author backend/tests/test_lifecycle.py — the single registry-level integration test that proves LIFECYCLE-04: disabling the enterprise edition (without `alembic downgrade`) preserves `oauth_providers` SAML rows + the 4 `deferred=True` SAML columns + `oauth_accounts` linkage + the user row.

Purpose: Behavioral guarantee, not just docs. The test reuses every existing fixture and helper (`saml_overlay_registered`, `_seed_saml_provider`-style seeding, `undefer_group("saml")` query pattern) per RESEARCH.md "Don't Hand-Roll" — smallest possible diff.

Output: One marker line added to backend/pyproject.toml; one new test file backend/tests/test_lifecycle.py with one async test function.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md
@backend/tests/conftest.py
@backend/tests/test_saml_overlay.py
@backend/app/core/edition.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/defaults.py
@backend/app/modules/auth/oauth/models.py
@backend/app/modules/auth/oauth/encryption.py
@backend/pyproject.toml

<interfaces>
<!-- Key contracts the test exercises. Extracted from codebase — no exploration needed. -->

From backend/app/platform/extensions/__init__.py (the registry the test clears):
```python
_extensions: dict[str, Any] = {}    # populated by register_extensions()
_routers: list[APIRouter] = []
_loaded: bool = False    # benign sentinel; do NOT reset (per RESEARCH.md Pitfall 3)

def get_audit_extension() -> AuditExtension: ...     # returns _extensions["audit"] or DefaultAuditExtension()
def get_branding_extension() -> BrandingExtension: ...
def get_auth_extension() -> AuthExtension: ...
def get_identity_extension() -> IdentityExtension: ...
```

From backend/app/platform/extensions/defaults.py (the test asserts these are returned):
```python
class DefaultAuditExtension(AuditExtension): ...
class DefaultBrandingExtension(BrandingExtension): ...
class DefaultAuthExtension(AuthExtension): ...
class DefaultIdentityExtension(IdentityExtension): ...
```

From backend/app/core/edition.py:
```python
_info: EditionInfo | None = None    # cached singleton

def init_edition(loaded_extensions: list[str]) -> None:
    """Honors GEOLENS_EDITION env override; falls back to extension presence."""
def is_enterprise() -> bool: ...
```

From backend/app/modules/auth/oauth/models.py (the table + ORM the test seeds):
```python
class OAuthProvider(Base):
    __tablename__ = "oauth_providers"
    __table_args__ = {"schema": "catalog"}
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str]
    display_name: Mapped[str]
    provider_type: Mapped[str]    # 'saml' for this test
    client_id: Mapped[str]    # NOT-NULL — placeholder "unused"
    client_secret_encrypted: Mapped[str]    # NOT-NULL — encrypt_secret("unused")
    enabled: Mapped[bool]
    # 4 deferred SAML columns (deferred=True, deferred_group="saml"):
    idp_entity_id: Mapped[str | None]
    idp_sso_url: Mapped[str | None]
    idp_certificate: Mapped[str | None]
    sp_entity_id: Mapped[str | None]

class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = {"schema": "catalog"}
    id, user_id, provider_id, subject  # links provider → user
```

From backend/app/modules/auth/models.py:
```python
class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "catalog"}
    auth_provider: Mapped[str]    # 'oauth' for SAML JIT-provisioned users
```

From backend/app/modules/auth/oauth/encryption.py:
```python
def encrypt_secret(plaintext: str) -> str:    # Fernet-encrypt for at-rest storage
```

From backend/tests/conftest.py:454-484 (REUSE — do NOT reimplement):
```python
@pytest.fixture
def saml_overlay_registered():
    """Saves _extensions + _routers state; registers EnterpriseSamlExtension; yields; restores on teardown."""
```
</interfaces>

<seed_helper_reference>
From backend/tests/test_saml_overlay.py:96-137 — `_seed_saml_provider()` is the existing pattern. The lifecycle test can either:
(a) import it (cleaner) — `from tests.test_saml_overlay import _seed_saml_provider, FIXTURE_SLUG, FIXTURE_IDP_ENTITY_ID, FIXTURE_CERT_PEM, FIXTURE_SP_ENTITY_ID`,
(b) define a tiny test-local helper.
Recommend (a) — keeps the seed contract DRY.

NB: client_id and client_secret_encrypted are NOT-NULL on the ORM (oauth/models.py:40-41); the seed helper passes placeholder strings. idp_certificate is encrypted at rest via encrypt_secret().
</seed_helper_reference>

<destructive_path_prohibition>
The test MUST NOT call `alembic downgrade` mid-test (per RESEARCH.md Anti-Pattern 3). The whole point of the test is "schema persists when overlay is gone." The 4 SAML columns remain physically present in the test DB after teardown — that is the correct, expected state.

The test MUST NOT touch saml_router_mod._outstanding_requests or replay_cache._seen (per RESEARCH.md Pitfall 3 — those are needed for SAML ACS replay tests, NOT this test).
</destructive_path_prohibition>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Register `lifecycle` pytest marker in backend/pyproject.toml</name>
  <files>backend/pyproject.toml</files>
  <read_first>
    - backend/pyproject.toml (current `markers` list at lines 71-75)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (lines 343-366 — exact append pattern + Pitfall 7 prohibition on touching addopts)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md (Pitfall 7)
  </read_first>
  <action>
Append exactly one line to the `markers = [...]` list in `[tool.pytest.ini_options]` at backend/pyproject.toml (current lines 71-75). The line's text MUST be (verbatim):

```
    "lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)",
```

Drop it after the existing `architecture: ...` line. Final state (the entire `markers = [...]` block):

```toml
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
    "lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)",
]
```

**DO NOT** modify `addopts` (currently `addopts = "-m 'not perf'"` at backend/pyproject.toml:70). Per RESEARCH.md Pitfall 7: lifecycle is intended to run by default; only `perf` is heavy enough to need opt-out. Adding `not lifecycle` to addopts would silently uncoverage the test in the standard CI run.

**DO NOT** touch any other line in pyproject.toml.
  </action>
  <verify>
    <automated>
grep -F '"lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)"' backend/pyproject.toml && \
grep -F 'addopts = "-m '"'"'not perf'"'"'"' backend/pyproject.toml && \
! grep -F 'not lifecycle' backend/pyproject.toml
    </automated>
  </verify>
  <acceptance_criteria>
    - The exact marker line `"lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)",` is present in backend/pyproject.toml.
    - The `addopts` line still reads exactly `addopts = "-m 'not perf'"` (no `lifecycle` deselection added).
    - No occurrence of the literal string `not lifecycle` anywhere in backend/pyproject.toml.
    - Diff to backend/pyproject.toml is exactly +1 line, 0 lines removed.
  </acceptance_criteria>
  <done>The `lifecycle` marker is registered. `pytest --markers` from backend/ lists it. addopts unchanged.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Author backend/tests/test_lifecycle.py — registry-level deactivation simulation test</name>
  <files>backend/tests/test_lifecycle.py</files>
  <read_first>
    - backend/tests/conftest.py (lines 454-484: `saml_overlay_registered` fixture — REUSE; lines 113-176: multi-head alembic discovery for context)
    - backend/tests/test_saml_overlay.py (lines 1-150: imports, FIXTURE_* constants, _seed_saml_provider helper — pattern + import targets; lines 220-280: saml_router_mounted fixture for the init_edition save/restore pattern; lines 285+ for marker syntax)
    - backend/app/core/edition.py (init_edition signature, _info singleton mechanics)
    - backend/app/platform/extensions/__init__.py (typed accessors + _extensions/_routers state)
    - backend/app/platform/extensions/defaults.py (Default* classes the test asserts)
    - backend/app/modules/auth/oauth/models.py (lines 40-78: OAuthProvider ORM with the 4 deferred SAML columns)
    - backend/app/modules/auth/oauth/encryption.py (encrypt_secret signature)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md (Pattern 1 sketch + Pitfalls 2/3/8 + Code Examples)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (test_lifecycle.py pattern assignments — verbatim seed code in lines 158-202; module docstring shape; deferred-column query pattern)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md (LIFECYCLE-04 5-assertion contract)
  </read_first>
  <behavior>
    - Test 1 (the only test): `test_overlay_removal_preserves_saml_data` — given a SAML provider+account+user seeded with the overlay registered, when `_extensions` and `_routers` are cleared and `init_edition([])` is re-called, then:
      - `oauth_providers` row with `provider_type='saml'` is still queryable.
      - All 4 deferred SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) retain the values set during seed (queried via `select(...).options(undefer_group("saml"))`).
      - `oauth_accounts` linkage row to the seeded user is still present.
      - `users` row with `auth_provider='oauth'` is still present.
      - `is_enterprise()` returns `False`.
      - `get_audit_extension()` returns a `DefaultAuditExtension` instance.
      - `get_branding_extension()` returns a `DefaultBrandingExtension` instance.
      - `get_auth_extension()` returns a `DefaultAuthExtension` instance.
      - `get_identity_extension()` returns a `DefaultIdentityExtension` instance.
    - Edge case: edition `_info` save/restore — test saves `edition_mod._info` before flipping and restores it in a `finally` so other tests' assumptions are not corrupted (per test_saml_overlay.py:233-270 pattern).
    - Edge case: Cleanup — seeded SAML rows must NOT pollute other tests; reuse the `_cleanup_saml_providers` fixture pattern from test_saml_overlay.py:185-219 (or take it as a fixture if importable; fallback: define a test-local cleanup yield-fixture that DELETEs the seeded rows after the test).
  </behavior>
  <action>
Create backend/tests/test_lifecycle.py with the following exact structure:

```python
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
lives in backend/tests/test_lifecycle.py — core repo, NOT enterprise).

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
# Test-local fixtures
# ---------------------------------------------------------------------------

LIFECYCLE_SLUG = "lifecycle-test"
LIFECYCLE_IDP_ENTITY_ID = "https://idp.test.lifecycle/entity"
LIFECYCLE_IDP_SSO_URL = "https://idp.test.lifecycle/sso"
LIFECYCLE_SP_ENTITY_ID = "https://geolens.test/auth/saml/lifecycle-test"
LIFECYCLE_CERT_PEM = (
    "-----BEGIN CERTIFICATE-----\nfake-pem-for-test\n-----END CERTIFICATE-----"
)
LIFECYCLE_USER_EMAIL = "lifecycle-saml-user@example.test"
LIFECYCLE_USER_SUBJECT = "lifecycle-saml-subject-uuid"


@pytest.fixture
async def _cleanup_lifecycle_rows(test_db_session: AsyncSession):
    """Best-effort teardown of any rows the lifecycle test seeded.

    Mirrors backend/tests/test_saml_overlay.py:185-219 but scoped to the
    lifecycle test's slug + email so other SAML tests are unaffected.
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
            text("DELETE FROM catalog.users WHERE email = :email"),
            {"email": LIFECYCLE_USER_EMAIL},
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
         init_edition([]) — three explicit resets per RESEARCH.md Pitfall 2.
      3. Assert SQL persistence (provider + 4 deferred columns + account + user).
      4. Assert is_enterprise() is False.
      5. Assert typed accessors return Default* instances.
    """
    # 1. Seed phase — overlay registered, edition flipped to enterprise.
    saved_info = edition_mod._info
    edition_mod.init_edition(["enterprise"])

    try:
        # Seed OAuthProvider (provider_type='saml', all 4 deferred SAML columns set).
        # client_id / client_secret_encrypted are NOT-NULL on the ORM
        # (backend/app/modules/auth/oauth/models.py:40-41) so we pass placeholder
        # strings — same pattern as backend/tests/test_saml_overlay.py:96-137.
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

        # Seed User (auth_provider='oauth' — SAML users land here per Phase 217 D-04).
        user = User(
            email=LIFECYCLE_USER_EMAIL,
            full_name="Lifecycle Test User",
            hashed_password=None,
            is_active=True,
            auth_provider="oauth",
        )
        test_db_session.add(user)
        await test_db_session.commit()
        await test_db_session.refresh(user)
        seeded_user_id = user.id

        # Seed OAuthAccount linkage (provider → user).
        account = OAuthAccount(
            user_id=seeded_user_id,
            provider_id=seeded_provider_id,
            subject=LIFECYCLE_USER_SUBJECT,
        )
        test_db_session.add(account)
        await test_db_session.commit()
        await test_db_session.refresh(account)

        # 2. Simulate "overlay not loaded" — three module-level surfaces reset.
        _extensions.clear()
        _routers.clear()
        edition_mod.init_edition([])    # flips is_enterprise() to False

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
        account_row = (await test_db_session.execute(account_stmt)).scalar_one_or_none()
        assert account_row is not None, "OAuthAccount linkage was destroyed by registry clear"
        assert account_row.subject == LIFECYCLE_USER_SUBJECT

        # 3c. SQL: User row with auth_provider='oauth' still present.
        user_stmt = select(User).where(User.id == seeded_user_id)
        user_row = (await test_db_session.execute(user_stmt)).scalar_one_or_none()
        assert user_row is not None, "User row was destroyed by registry clear"
        assert user_row.auth_provider == "oauth"
        assert user_row.email == LIFECYCLE_USER_EMAIL

        # 4. Edition state — is_enterprise() flipped to False.
        from app.core.edition import is_enterprise

        assert is_enterprise() is False, (
            "is_enterprise() should be False after init_edition([]) — "
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
        # fixture's finally block (conftest.py:481-484) — no work needed here.
```

**Critical implementation notes:**
- `from __future__ import annotations` is the FIRST line after the module docstring (matches test_saml_overlay.py:20).
- The `_cleanup_lifecycle_rows` fixture is test-local (scoped to the lifecycle slug/email) — does NOT clobber other SAML tests' rows.
- The test takes `saml_overlay_registered` (existing conftest fixture); it does NOT take `saml_router_mounted` (which mounts the FastAPI router and is heavier than this test needs).
- The `init_edition` save/restore pattern is taken verbatim from test_saml_overlay.py:233 + 270.
- After the test body, `_extensions` and `_routers` are restored by `saml_overlay_registered`'s `finally` block (conftest.py:481-484) — RESEARCH.md confirms this teardown is correct because the fixture's restore runs AFTER the test body's clear.
- The test asserts on `provider_type == "saml"` AND on each of the 4 deferred columns individually — this satisfies VALIDATION.md's 5-assertion contract.
- DO NOT add a `/auth/saml/{slug}/login` 404 assertion (per CONTEXT.md Claude's Discretion + RESEARCH.md Pitfall 8 — SQL-only assertions are sufficient for LIFECYCLE-04 literal text; route-404 assertions on `app.routes` are fragile due to test-order side effects).
- DO NOT call `alembic downgrade` (per RESEARCH.md Anti-Pattern 3).
- DO NOT touch `saml_router_mod._outstanding_requests` or `replay_cache._seen` (per RESEARCH.md Pitfall 3).

**Run it locally to confirm green before committing:**
```bash
cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle
```
Expected: `test_overlay_removal_preserves_saml_data PASSED`.

If the import chain fails because `geolens-enterprise` is not installed locally, fix the local env (`uv add --editable ../../geolens-enterprise`) — the test fixture `saml_overlay_registered` defers the enterprise import inside its body (conftest.py:471-473) so collection still succeeds in community-only environments, but the test body itself requires the overlay to be importable.
  </action>
  <verify>
    <automated>
test -f backend/tests/test_lifecycle.py && \
grep -q '@pytest.mark.lifecycle' backend/tests/test_lifecycle.py && \
grep -q 'saml_overlay_registered' backend/tests/test_lifecycle.py && \
grep -q '_extensions.clear()' backend/tests/test_lifecycle.py && \
grep -q '_routers.clear()' backend/tests/test_lifecycle.py && \
grep -q 'init_edition(\[\])' backend/tests/test_lifecycle.py && \
grep -q 'undefer_group' backend/tests/test_lifecycle.py && \
grep -q 'DefaultAuditExtension' backend/tests/test_lifecycle.py && \
grep -q 'DefaultBrandingExtension' backend/tests/test_lifecycle.py && \
grep -q 'DefaultAuthExtension' backend/tests/test_lifecycle.py && \
grep -q 'DefaultIdentityExtension' backend/tests/test_lifecycle.py && \
grep -q "auth_provider == .oauth." backend/tests/test_lifecycle.py && \
! grep -q 'alembic downgrade' backend/tests/test_lifecycle.py && \
! grep -q '_outstanding_requests' backend/tests/test_lifecycle.py && \
! grep -q 'replay_cache' backend/tests/test_lifecycle.py && \
cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle 2>&1 | grep -q 'test_overlay_removal_preserves_saml_data PASSED'
    </automated>
  </verify>
  <acceptance_criteria>
    - File `backend/tests/test_lifecycle.py` exists.
    - File contains `@pytest.mark.lifecycle` decorator on the test function.
    - File takes the `saml_overlay_registered` fixture (reused; not reimplemented).
    - File contains all three module-level resets: `_extensions.clear()`, `_routers.clear()`, `init_edition([])`.
    - File queries deferred columns with `undefer_group("saml")`.
    - File asserts the 4 deferred SAML columns retain their seeded values.
    - File asserts the OAuthAccount linkage row exists post-clear.
    - File asserts the User row with `auth_provider='oauth'` exists post-clear.
    - File asserts `is_enterprise() is False`.
    - File asserts the 4 typed accessors return `Default{Audit,Branding,Auth,Identity}Extension` instances.
    - File does NOT call `alembic downgrade` (per Anti-Pattern 3).
    - File does NOT mutate SAML's internal `_outstanding_requests` or `replay_cache` (per Pitfall 3).
    - `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` exits 0 with `test_overlay_removal_preserves_saml_data PASSED`.
    - Test runtime < 5 seconds (single integration test against existing fixtures).
  </acceptance_criteria>
  <done>backend/tests/test_lifecycle.py contains exactly one test function, marked @pytest.mark.lifecycle, that exercises the registry-level deactivation simulation and asserts the 5-part contract from VALIDATION.md. The test passes locally against an environment with geolens-enterprise installed.</done>
</task>

</tasks>

<verification>
- Marker registered: `cd backend && uv run pytest --markers | grep -q '@pytest.mark.lifecycle'` returns 0.
- Test collects: `cd backend && uv run pytest tests/test_lifecycle.py --collect-only` lists the test.
- Test passes: `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` exits 0.
- No regressions: `cd backend && uv run pytest -v -m 'not perf'` exits 0 (lifecycle is included by default per Pitfall 7).
- No emojis in test file.
</verification>

<success_criteria>
- LIFECYCLE-04 satisfied: `pytest -m lifecycle` collects + passes a single test that proves overlay-removal preserves oauth_providers SAML rows + 4 deferred columns + oauth_accounts linkage + user row.
- D-04 honored: registry-level simulation in a single pytest session (no docker-compose swap, no alembic mid-test).
- D-05 honored: test lives in backend/tests/test_lifecycle.py (core repo, not enterprise).
- Pitfall 7 honored: `addopts` unchanged.
</success_criteria>

<output>
After completion, create `.planning/phases/220-lifecycle-runbooks-and-preservation/220-04-SUMMARY.md` capturing: test name, marker registration confirmation, the 5-part assertion contract verified, runtime, and any deviations.
</output>
