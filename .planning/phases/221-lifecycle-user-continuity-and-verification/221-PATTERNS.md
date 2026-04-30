# Phase 221: lifecycle-user-continuity-and-verification - Pattern Map

**Mapped:** 2026-04-30
**Files analyzed:** 6 (3 backend code edits, 1 test edit, 2 docs edits)
**Analogs found:** 6 / 6 (every file has a high-quality in-repo analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/modules/admin/router.py` | controller (FastAPI route) | request-response | self — `deactivate_user` (router.py:213-249) | exact |
| `backend/app/modules/admin/service.py` | service (DB mutation) | CRUD | self — `update_user` (service.py:114-172) | exact |
| `backend/app/modules/admin/schemas.py` | model (Pydantic schema) | request-response | self — `AdminUserCreate.password` (schemas.py:23-26) | exact |
| `backend/tests/test_lifecycle.py` | test (integration / lifecycle) | event-driven (registry) + request-response (TestClient) | self — `test_overlay_removal_preserves_saml_data` (test_lifecycle.py:111-235) | exact |
| `docs/edition-deactivation.md` | docs (operator runbook edit) | request-response (human-read) | self — pre-flight §3 step 3 (lines 79-81) | exact (in-place TODO replacement) |
| `docs/edition-reactivation.md` | docs (operator runbook edit) | request-response (human-read) | self — `## References` block (lines 72-76) | exact (one-paragraph forward-pointer insertion) |

## Pattern Assignments

### `backend/app/modules/admin/schemas.py` (model, request-response)

**Analog:** `AdminUserCreate.password` field at `backend/app/modules/admin/schemas.py:17-26`

**Imports already present** (schemas.py:1-9 — verified):
```python
"""Admin schemas for user management endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.auth.schemas import UserResponse
```
No new imports needed; `BaseModel` and `Field` already imported.

**Password Field pattern** (schemas.py:17-27):
```python
class AdminUserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=150,
        description="Login username (3-150 chars). Must be unique across the system.",
    )
    password: str = Field(
        min_length=8,
        max_length=256,
        description="Initial password (minimum 8 characters). The user can change this after first login.",
    )
```

**Application:** add a new single-field `SamlToLocalConversion(BaseModel)` class with one `password` field copied verbatim from this pattern (`min_length=8`, `max_length=256`, similar description). Per CONTEXT.md D-01 + RESEARCH.md Standard Stack §Pydantic v2: do NOT add an `auth_provider` field, `email`, or anything else — single-purpose schema.

**Where to insert:** alongside `UserUpdate` at schemas.py:60-80 (the existing user-mutation schemas cluster there).

---

### `backend/app/modules/admin/service.py` (service, CRUD)

**Analog:** `AdminService.update_user` at `backend/app/modules/admin/service.py:114-172`

**Imports already present** (service.py:1-16 — verified):
```python
"""Admin service: user CRUD, role assignment, and catalog stats."""

import uuid

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.schemas import (
    CatalogStatsResponse,
    EmbeddingStatsResponse,
    UserUpdate,
)
from app.modules.auth.models import ApiKey, Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.modules.catalog.datasets.domain.models import Dataset, Record
```

**Application:**
- `delete` and `select` are already imported.
- `hash_password` (line 15) is already imported — black-box reuse.
- ADD to the schemas import block: `SamlToLocalConversion` (Phase 221 new schema).
- ADD a new import: `from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider`.

**Load → validate → mutate → flush → refresh → return pattern** (service.py:114-172):
```python
async def update_user(self, user_id: uuid.UUID, updates: UserUpdate) -> User:
    """Update a user's fields and/or role.

    Raises ValueError if user not found or role not found.
    """
    result = await self.db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    # Apply non-None scalar fields
    if updates.email is not None:
        ...
        user.email = updates.email

    if updates.is_active is not None:
        ...
        user.is_active = updates.is_active

    # Handle role change
    if updates.role is not None:
        ...
        # Remove existing roles
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        # Add new role
        self.db.add(UserRole(user_id=user_id, role_id=new_role.id))

    await self.db.flush()
    await self.db.refresh(user)
    return user
```

**ORM `delete()` clause pattern** (service.py:166):
```python
await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
```
Phase 221's `oauth_accounts` row deletion uses this exact form, scoped by `(user_id, provider_id IN saml_providers)` — see Pattern 2 sketch in 221-RESEARCH.md.

**ValueError contract** (service.py:121-122):
```python
if user is None:
    raise ValueError("User not found")
```
Phase 221's `convert_saml_user_to_local` raises `ValueError` for: (a) user not found, (b) `auth_provider != "oauth"`, (c) no SAML linkage row found. The router maps these to 404 / 422.

**Application:** new method `convert_saml_user_to_local(self, user_id: uuid.UUID, password: str) -> tuple[User, str]` mirrors the load-validate-mutate-return shape above. Returns `(user, provider_slug)` so the router can populate `audit_log.details.provider_slug` (per RESEARCH.md A1). Insert between `update_user` (ends at line 172) and `list_users` (starts at line 174).

---

### `backend/app/modules/admin/router.py` (controller, request-response)

**Analog:** `deactivate_user` at `backend/app/modules/admin/router.py:213-249` — single-purpose POST mutation with `log_action` + `db.commit()`

**Imports already present** (router.py:1-43 — verified):
```python
import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.schemas import (
    AdminApiKeyCreateRequest,
    ...
    UserUpdate,
)
from app.modules.admin.service import AdminService
from app.modules.audit.service import log_action
from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import ApiKey, User
from app.modules.auth.schemas import ApiKeyCreateResponse, UserResponse
from app.core.config import settings as app_settings
from app.core.dependencies import get_client_ip, get_db
```
No new imports needed except adding `SamlToLocalConversion` to the schemas import block.

**Trailing-slash POST mutation route pattern** (router.py:213-249):
```python
@router.post(
    "/users/{user_id}/deactivate/",
    response_model=UserResponse,
)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Deactivate a user (admin only)."""
    service = AdminService(db)
    try:
        user = await service.deactivate_user(user_id, current_user.id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    ip = get_client_ip(request)
    await log_action(
        session=db,
        user_id=current_user.id,
        action="user.deactivate",
        resource_type="user",
        resource_id=user_id,
        details={"username": user.username},
        ip_address=ip,
    )
    await db.commit()
    return _user_response(user)
```

**Application notes (per RESEARCH.md Pitfall 4 + Pattern 1):**
- Route URL MUST end with trailing slash: `"/users/{user_id}/convert-saml-to-local/"`.
- Self-conversion guard goes BEFORE `service = AdminService(db)`, mirroring the role self-change guard at router.py:180-184. Use status `422_UNPROCESSABLE_ENTITY` (matches `update_user`'s self-action guard pattern).
- ValueError mapping: "not found" → 404, everything else → 422 (NOT 400 — `convert` operations are validation failures, mirroring `update_user`'s 409 mapping at line 195-198 but using 422 for "user state inconsistent" semantics).
- `log_action` call and `db.commit()` come AFTER the service returns successfully (matches deactivate_user lines 238-248). Do NOT log inside the service.
- `details={"from": "saml", "to": "local", "provider_slug": provider_slug}` — explicit allow-list per RESEARCH.md Open Question 1 (no password material in audit details).

**Self-action guard pattern** (router.py:180-184) — copy verbatim with adjusted detail string:
```python
if user_id == current_user.id and body.role is not None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Cannot change your own role",
    )
```
Phase 221 strips the `body.role is not None` clause (every conversion is in-scope) and uses detail "Cannot convert your own account; use a different admin account" (per RESEARCH.md Pitfall 7).

**Where to insert:** alongside `update_user` (line 168) or `deactivate_user` (line 213). Recommendation: immediately after `deactivate_user` (line 250) since both are single-purpose user-state mutations.

---

### `backend/tests/test_lifecycle.py` (test, integration / lifecycle)

**Analog:** self — `test_overlay_removal_preserves_saml_data` at `backend/tests/test_lifecycle.py:110-235` (Phase 220 test)

**Imports pattern** (test_lifecycle.py:33-57 — verified):
```python
from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer_group

import app.core.edition as edition_mod
from app.modules.auth.models import User
from app.modules.auth.oauth.encryption import decrypt_secret, encrypt_secret
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
```

**Application — additional imports needed for Phase 221:**
- `from httpx import AsyncClient` (for the conversion test's TestClient)
- `from app.modules.audit.models import AuditLog` (for the audit-log assertion)
- `from app.modules.audit.service import log_action` (for D-10 seed)
- `from app.modules.auth.models import Role, UserRole` (for the conversion test's user_roles seed)
- Possibly `from app.modules.auth.providers.local import verify_password` (to assert the new password hash is valid post-conversion)

**Module docstring shape** (test_lifecycle.py:1-31) — extend, don't rewrite:
The existing docstring documents Phase 220's deactivate-only test. Phase 221 expands it to describe all three test functions: deactivate-only (220), conversion (221 LIFECYCLE-06), round-trip (221 LIFECYCLE-07). Module-level constants block (lines 64-73) extends with any new fixture constants.

**Test-local cleanup fixture pattern** (test_lifecycle.py:76-102):
```python
@pytest.fixture
async def _cleanup_lifecycle_rows(test_db_session: AsyncSession):
    """Best-effort teardown of any rows the lifecycle test seeded."""
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
```

**Application — extend `_cleanup_lifecycle_rows` (per CONTEXT.md D-11):**
- Add a `text("SELECT id FROM catalog.users WHERE username = :username")` lookup at the top of the try block.
- If a user_id is resolved, prepend DELETEs (in dependency order):
  1. `DELETE FROM catalog.audit_logs WHERE user_id = :uid` (test-seeded `test.seed.lifecycle` rows AND endpoint-written `auth.convert_saml_to_local` rows)
  2. `DELETE FROM catalog.user_roles WHERE user_id = :uid` (LIFECYCLE-06 conversion-test seed)
  3. (Optional) `DELETE FROM catalog.datasets WHERE created_by = :uid` (LIFECYCLE-06 dataset seed)
- Then keep the existing 3 DELETEs (oauth_accounts, oauth_providers, users) in their current order.

**Seed pattern (Phase 220 working reference)** (test_lifecycle.py:136-174):
```python
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

account = OAuthAccount(
    user_id=seeded_user_id,
    provider_id=seeded_provider_id,
    subject=LIFECYCLE_USER_SUBJECT,
)
test_db_session.add(account)
await test_db_session.commit()
await test_db_session.refresh(account)
```
Both new tests reuse this seed verbatim. Pitfall 3 inheritance: `client_secret_encrypted=encrypt_secret("unused")` and `idp_certificate=encrypt_secret(LIFECYCLE_CERT_PEM)` — Fernet ciphertext required at-rest.

**Three-surface registry reset pattern (deactivate side)** (test_lifecycle.py:177-179):
```python
_extensions.clear()
_routers.clear()
edition_mod.init_edition([])  # flips is_enterprise() to False
```
LIFECYCLE-07 round-trip test reuses this verbatim for the deactivate phase.

**Three-surface registry RE-POPULATION pattern (reactivate side, NEW for Phase 221)** — derived by mirroring `conftest.py:466-478` (the `saml_overlay_registered` fixture's setup steps):
```python
# Reactivate phase — Pattern 3 Shape A (mirror the fixture verbatim)
from geolens_enterprise.auth.saml import EnterpriseSamlExtension
from geolens_enterprise.auth.saml.router import router as saml_router

ext = EnterpriseSamlExtension()
_extensions["auth"] = ext
_extensions["identity"] = ext
_routers.append(saml_router)
edition_mod.init_edition(["enterprise"])  # third surface — flips is_enterprise() back to True
```
Per RESEARCH.md Pattern 3 Shape A and Pitfall 1: imports are deferred inside the test body (NOT at module level) so collection succeeds in community-only environments. NEVER call `register_extensions(_extensions)` blindly — it writes to the dict-key `_extensions["_routers"]`, NOT to the module-level `_routers` list (RESEARCH.md Pitfall 2).

**Deferred-column query pattern** (test_lifecycle.py:182-194):
```python
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
assert decrypt_secret(survivor.idp_certificate) == LIFECYCLE_CERT_PEM
assert survivor.sp_entity_id == LIFECYCLE_SP_ENTITY_ID
```
Round-trip test reuses this verbatim for symmetry assertion (assertion #4 in 221-RESEARCH.md §LIFECYCLE-07 contract). Note: Fernet ciphertext is non-deterministic (random IV) — ALWAYS compare via `decrypt_secret(...)`, never raw equality on the encrypted value.

**Edition state save/restore pattern** (test_lifecycle.py:128-129 + 232-233):
```python
saved_info = edition_mod._info
edition_mod.init_edition(["enterprise"])

try:
    ...
finally:
    edition_mod._info = saved_info
```
Both new tests use this pattern. The reactivate-side round-trip test additionally re-flips `init_edition(["enterprise"])` mid-test, then the finally block still restores `saved_info` (the pre-test snapshot).

**Audit-log seed pattern (NEW for Phase 221, derived from `audit/service.py:49-67`)** — `log_action` does NOT commit; the test must commit explicitly:
```python
from app.modules.audit.service import log_action
await log_action(
    session=test_db_session,
    user_id=seeded_user_id,
    action="test.seed.lifecycle",
    resource_type="user",
    resource_id=seeded_user_id,
    details={"phase": "221", "purpose": "round-trip-symmetry"},
)
await test_db_session.commit()
```
Per `audit/service.py:58`: docstring confirms "Does NOT commit -- caller's transaction handles it." Test commits after seeding.

**TestClient HTTP invocation pattern (NEW for Phase 221, derived from `test_admin_user_operations.py:26-46`)**:
```python
@pytest.mark.anyio
async def test_X(
    client: AsyncClient,
    admin_auth_header: dict,
):
    resp = await client.post(
        f"/admin/users/{user_id}/convert-saml-to-local/",
        json={"password": "new-strong-password-123"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_provider"] == "local"
```
Phase 221's conversion test uses this shape. NOTE the trailing slash on the URL (Pitfall 4 — without it the `client` fixture follows redirects and may lose the JSON body).

**Marker pattern** (test_lifecycle.py:110):
```python
@pytest.mark.lifecycle
async def test_X(...):
```
Both new tests carry the marker. Marker registered in `backend/pyproject.toml:74` (Phase 220 inheritance — no edit needed).

---

### `docs/edition-deactivation.md` (docs edit, in-place TODO replacement)

**Analog:** self — pre-flight §3 step 3 at lines 79-81 (the existing TODO blockquote that Phase 221 replaces in-place); Phase 220's runbook style established at the same file's lines 60-77 + 87-138

**Existing line to REPLACE** (docs/edition-deactivation.md:79-81 — verified):
```markdown
3. **Communicate to SAML-authenticated users.**

   > **Existing SAML users will lose their login path.** Phase 221 ships the user re-onboarding procedure ("Handling existing SAML users", planned). Until that lands, communicate the downgrade to SAML users out-of-band and convert their accounts manually via the admin UI (set local password or convert to OIDC).
```

**Replacement (sketch — per CONTEXT.md D-12)**: replace lines 79-81 with a forward-link to the new section, then insert the new top-level `## Handling existing SAML users` section after the destructive-path content.

**Inventory SQL reuse** (lines 70-77 — verified, copy verbatim into the new section's "Step 1: Inventory SAML users"):
```sql
SELECT COUNT(*) AS saml_users
FROM catalog.users u
JOIN catalog.oauth_accounts oa ON oa.user_id = u.id
JOIN catalog.oauth_providers op ON op.id = oa.provider_id
WHERE op.provider_type = 'saml'
  AND u.auth_provider = 'oauth';
```
The new section may extend this query to select `u.id, u.username, u.email, op.slug AS provider_slug` for per-user iteration (per 221-RESEARCH.md Pattern 4). Both forms are acceptable; pick whichever the planner prefers.

**Section structure pattern** (docs/edition-deactivation.md:87-138 — verified — "Deactivation sequence (canonical path)"):
- ATX `## Section` for top-level, `### Step N: ...` for substeps
- ```bash``` blocks for shell commands; ```sql``` for queries
- `> **Bold lead** ...` blockquote callouts for warnings (e.g., line 119: `> **GEOLENS_EDITION=community alone is incomplete deactivation.**`)

**Cross-link backtick-wrap pattern** (line 142 — verified):
```markdown
... see [`docs/edition-reactivation.md`](edition-reactivation.md).
```

**Existing maintenance-window sentence** (line 83 — verified — IMPORTANT, preserve verbatim):
```markdown
4. **Plan a maintenance window.** SAML logins fail immediately when the overlay is removed. Existing JWTs continue to work until they expire (per `ACCESS_TOKEN_EXPIRE_MINUTES`).
```
Per RESEARCH.md Pitfall 8: the new "Handling existing SAML users" section MUST explicitly state the ordering — convert users AFTER overlay removal so `/auth/saml/*` returns 404 and no SAML login can race the conversion. The maintenance-window sentence is already aligned; the new section reinforces it.

**Curl auth-token pattern (NEW per RESEARCH.md Pitfall 5)** — uses `/auth/login/` form-data, NOT `/auth/token`:
```bash
TOKEN=$(curl -fsS -X POST http://localhost:8000/auth/login/ \
  -d "username=$ADMIN_USER&password=$ADMIN_PASSWORD" \
  | jq -r .access_token)
```
Verified against `backend/tests/conftest.py:328-334` — `get_auth_header()` posts form-data to `/auth/login/`.

**Conversion endpoint curl pattern (NEW for Phase 221)** — trailing slash mandatory (Pitfall 4):
```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "<temp-strong-password>"}' \
  http://localhost:8000/admin/users/<user-id>/convert-saml-to-local/
```

**Application:** the new top-level `## Handling existing SAML users` section is inserted between the existing "## Database state after the safe path" (line 140) and "## Destructive path: permanent decommissioning" (line 144), or after the "Destructive path" section — placement is planner's call (RESEARCH.md A7). The forward-link from §pre-flight step 3 (replacing lines 79-81) MUST be an anchor link `(#handling-existing-saml-users)` so it resolves to the new top-level heading.

---

### `docs/edition-reactivation.md` (docs edit, one-paragraph forward-pointer)

**Analog:** self — `## References` block at lines 72-76 (verified) and `## Why this works` at line 68 (verified)

**Existing structure** (docs/edition-reactivation.md:68-76 — verified):
```markdown
## Why this works

The 4 SAML columns on `catalog.oauth_providers` are added by `e002_add_saml_columns` (the enterprise alembic head). The ORM declares them `deferred=True, deferred_group="saml"` — when the overlay is absent, default queries never load them, so community deployments work unchanged. The columns and rows persist physically regardless of whether the overlay is loaded; re-mounting only restores the consumer (the SAML router and admin UI) of pre-existing data.

## References

- [`docs/edition-deactivation.md`](edition-deactivation.md) — the inverse procedure; pre-flight `pg_dump` snapshot is the safety net referenced in step 5 of the verification checklist.
- [`docs/saml.md`](saml.md) — SAML setup, IdP configuration, hardening defaults.
```

**Application (per CONTEXT.md D-13):** insert a new short section between `## End-to-end smoke test` (line 64) and `## Why this works` (line 68), OR (alternative) before `## References` at line 72. Recommended placement: a new `## Caveats` section (or `## Note on previously converted SAML users`) at line ~68, since "Why this works" is a closing remark about the technical mechanism.

**Forward-pointer paragraph wording (sketch — per CONTEXT.md D-13):**
```markdown
## Note on previously converted SAML users

If SAML users were converted to local-password during deactivation (per [`docs/edition-deactivation.md`](edition-deactivation.md) §Handling existing SAML users), those conversions persist after reactivation. The users continue logging in via local-password until an admin manually re-links them to a SAML provider. Automating reverse conversion is on the deferred roadmap.
```

**Verification grep targets (per RESEARCH.md §LIFECYCLE-06 doc-grep block):**
- `grep -q -i 'converted' docs/edition-reactivation.md` — must pass
- `grep -q 'edition-deactivation' docs/edition-reactivation.md` — already passes (line 74); preserve

---

## Shared Patterns

### Self-Action Guard (admin endpoints)

**Source:** `backend/app/modules/admin/router.py:180-184` (`update_user`'s self-role-change guard)

**Apply to:** `backend/app/modules/admin/router.py` — new `convert_saml_to_local` endpoint

```python
if user_id == current_user.id:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Cannot convert your own account; use a different admin account",
    )
```
422 (NOT 400 / 403) — matches `update_user`'s self-action guard pattern. Per RESEARCH.md Pitfall 7.

### ValueError → HTTPException Mapping (admin endpoints)

**Source:** `backend/app/modules/admin/router.py:188-198` (`update_user` mapping) + `backend/app/modules/admin/router.py:228-237` (`deactivate_user` mapping)

**Apply to:** all admin endpoints that call AdminService methods raising ValueError

```python
try:
    user, provider_slug = await service.convert_saml_user_to_local(user_id, body.password)
except ValueError as exc:
    detail = str(exc)
    if "not found" in detail.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
```
Convention: the service raises `ValueError("User not found")` → 404; any other ValueError → 422. Phase 221 uses 422 (not 400/409) because conversion failures are validation/state-inconsistency failures, not generic conflicts.

### Audit-Log Write (admin endpoints)

**Source:** `backend/app/modules/admin/router.py:200-209` (`user.update`) + `backend/app/modules/audit/service.py:49-67` (`log_action` signature)

**Apply to:** every admin mutation endpoint

```python
ip = get_client_ip(request)
await log_action(
    session=db,
    user_id=current_user.id,        # the admin performing the action
    action="auth.convert_saml_to_local",
    resource_type="user",
    resource_id=user_id,             # the user being converted
    details={"from": "saml", "to": "local", "provider_slug": provider_slug},
    ip_address=ip,
)
await db.commit()
return _user_response(user)
```
**Critical:** `log_action` does NOT commit (audit/service.py:58 docstring confirms). The router commits AFTER `log_action` adds the row. The audit-log entry is the LAST step before commit per CONTEXT.md D-05 — failure of any earlier step rolls back without leaving an orphan audit entry.

`details` is an explicit allow-list (`{"from", "to", "provider_slug"}`) — NEVER include the password (in any form) per RESEARCH.md Open Question 1.

### Three Module-Level State Surfaces (lifecycle test)

**Source:** Phase 220 RESEARCH §Pitfall 2 + `backend/tests/test_lifecycle.py:177-179` (deactivate side, working) + `backend/tests/conftest.py:466-478` (reactivate side, mirrored from fixture)

**Apply to:** `backend/tests/test_lifecycle.py` round-trip test — both deactivate AND reactivate phases

```python
# DEACTIVATE — three surfaces all reset
_extensions.clear()
_routers.clear()
edition_mod.init_edition([])

# REACTIVATE — three surfaces all RE-populated symmetrically (Pattern 3 Shape A)
from geolens_enterprise.auth.saml import EnterpriseSamlExtension
from geolens_enterprise.auth.saml.router import router as saml_router

ext = EnterpriseSamlExtension()
_extensions["auth"] = ext
_extensions["identity"] = ext
_routers.append(saml_router)
edition_mod.init_edition(["enterprise"])
```
Skip ANY of the three on either side and the test fails for the wrong reason or, worse, silently passes asymmetrically.

### Deferred Enterprise Imports (lifecycle test)

**Source:** `backend/tests/conftest.py:471-473` (the fixture's deferred imports)

**Apply to:** `backend/tests/test_lifecycle.py` — every `geolens_enterprise.*` import in both new tests

```python
# Inside test body or fixture, NEVER at module top:
from geolens_enterprise.auth.saml import EnterpriseSamlExtension
from geolens_enterprise.auth.saml.router import router as saml_router
```
Per Phase 220 RESEARCH §Pitfall 5: deferred imports let the test FILE collect successfully in community-only environments; only tests that actually request the fixture/import fail with ImportError. Module-level imports break collection.

### Trailing-Slash Convention (FastAPI routes + curl examples)

**Source:** `backend/app/modules/admin/router.py:213-214` (deactivate_user uses trailing slash) + project memory MEMORY.md "FastAPI trailing slashes"

**Apply to:** `backend/app/modules/admin/router.py` new route, `docs/edition-deactivation.md` curl example, `backend/tests/test_lifecycle.py` TestClient invocation

```python
@router.post("/users/{user_id}/convert-saml-to-local/", response_model=UserResponse)
```
```bash
curl ... http://localhost:8000/admin/users/<user-id>/convert-saml-to-local/
```
```python
resp = await client.post(f"/admin/users/{user_id}/convert-saml-to-local/", ...)
```
Routes defined with trailing `/` cause 307 redirects when called WITHOUT it — `httpx.AsyncClient` follows redirects by default but the JSON body may be lost on the redirect (RESEARCH.md Pitfall 4). All three surfaces must agree.

### Verification-by-Grep Discipline (runbooks)

**Source:** Phase 220 PATTERNS.md §Verification-by-grep Discipline + 221-RESEARCH.md §LIFECYCLE-06 doc-grep block

**Apply to:** both `docs/edition-deactivation.md` and `docs/edition-reactivation.md` edits

The phase VALIDATION.md will grep for these literal strings — the runbook edits MUST contain them verbatim:
- `## Handling existing SAML users` (deactivation runbook — exact heading)
- `convert-saml-to-local/` (deactivation runbook curl — with trailing slash)
- `auth.convert_saml_to_local` or `audit` (deactivation runbook — audit-log mention)
- `oidc` (deactivation runbook appendix — case-insensitive)
- `converted` (reactivation runbook — case-insensitive)

Negative greps (these strings MUST NOT appear post-edit):
- `Phase 221 ships the user re-onboarding` (TODO marker gone from deactivation runbook)
- `manually via the admin UI` (false claim removed from deactivation runbook)

---

## No Analog Found

None. Every Phase 221 file has a high-quality in-repo analog:
- 3 backend code files: existing admin module patterns are exact matches.
- 1 test file: Phase 220's `test_lifecycle.py` provides the exact Phase 220 deactivate-only test pattern; both new tests are extensions, not new categories.
- 2 docs files: Phase 220 already shipped the deactivation runbook with `docs/saml.md` as the tonal reference; Phase 221's edits are in-place insertions to existing operator runbooks.

The audit-log catalog file mentioned in CONTEXT.md D-14 (potential `app/modules/audit/actions.py` enum) does NOT exist — verified via 221-RESEARCH.md §Runtime State Inventory. The `auth.convert_saml_to_local` action ships as a string literal at the call site (consistent with `user.update`, `user.deactivate` precedent in `admin/router.py:200-208` + `:239-247`).

## Metadata

**Analog search scope:**
- `backend/app/modules/admin/` (router, service, schemas)
- `backend/app/modules/audit/` (service for log_action)
- `backend/app/modules/auth/` (models, providers/local for hash_password, oauth/models for OAuthAccount/Provider)
- `backend/tests/` (test_lifecycle.py, test_saml_overlay.py for _seed_saml_provider, test_admin_user_operations.py for TestClient pattern, conftest.py for saml_overlay_registered + admin_auth_header + test_db_session)
- `docs/` (edition-deactivation.md, edition-reactivation.md, saml.md as tonal reference)
- 220-PATTERNS.md (inherited shared patterns)
- 221-RESEARCH.md (Pattern 1-4 sketches + Pitfalls 1-9)

**Files scanned:** 11
- backend/app/modules/admin/router.py (lines 1-50, 160-249)
- backend/app/modules/admin/service.py (lines 1-180)
- backend/app/modules/admin/schemas.py (lines 1-100)
- backend/app/modules/audit/service.py (full)
- backend/app/modules/auth/models.py (lines 1-90)
- backend/app/modules/auth/oauth/models.py (lines 1-130)
- backend/app/modules/auth/providers/local.py (full)
- backend/tests/test_lifecycle.py (full)
- backend/tests/test_saml_overlay.py (lines 85-145 — `_seed_saml_provider` helper)
- backend/tests/test_admin_user_operations.py (lines 1-120 — TestClient pattern)
- backend/tests/conftest.py (lines 320-485 — admin_auth_header + saml_overlay_registered fixtures)
- docs/edition-deactivation.md (lines 60-160 — pre-flight + canonical path + destructive path)
- docs/edition-reactivation.md (full)

**Pattern extraction date:** 2026-04-30
**Upstream context:** 221-CONTEXT.md (D-01..D-14 locked), 221-RESEARCH.md (Patterns 1-4, Pitfalls 1-9, Validation Architecture LIFECYCLE-06+07 contracts), 220-PATTERNS.md (inherited fixture/seed/registry patterns)
