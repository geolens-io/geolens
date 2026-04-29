# Phase 219: oc-audit-remediate-idp-mapping - Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 4 (3 code/test + 1 doc)
**Analogs found:** 4 / 4

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `backend/app/modules/auth/oauth/schemas.py` | schema (Pydantic validator) | request-response (write-path validation) | `_validate_per_type` at same file lines 145-169 | exact (same file, same decorator, same shape) |
| `backend/app/modules/auth/oauth/service.py` | service (orchestration) | request-response (login flow) | `app/modules/settings/router.py:90-104` (`if is_enterprise(): ...` branch) | role-match (same gating pattern, different return semantics) |
| `backend/tests/test_oauth.py` | test (unit + integration) | request-response | (a) existing `test_group_role_mapping` at `test_oauth.py:458-481` for runtime tests; (b) `test_edition.py:11-22` for autouse fixture; (c) `test_saml_overlay.py:233-239, 270` for `init_edition` save/restore | exact (a, b) + role-match (c) |
| `docs-internal/audits/oc-separation-audit-v13.1-close.md` | doc (milestone-close artifact) | doc amendment (in-place) | The file itself — Scorecard line 9, banner line 20, Section 1 lines 53-55, Section 8 lines 363-372, P1 Residual Triage line 408 | self (in-place amendment per D-12) |

---

## Pattern Assignments

### `backend/app/modules/auth/oauth/schemas.py` (schema, request-response)

**Analog:** `backend/app/modules/auth/oauth/schemas.py:145-169` (existing `_validate_per_type` on `OAuthProviderCreate`).

**Imports already present** (lines 1-8 — only the edition import is new):

```python
"""Pydantic schemas for OAuth provider CRUD operations."""

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

**New import required at module top** (per D-04):

```python
from app.core.edition import is_enterprise
```

(Mirrors the import style at `backend/app/modules/settings/router.py:98` and `backend/app/platform/extensions/guards.py:7`.)

**Existing model_validator pattern to mirror** (lines 145-169 — copy this shape):

```python
    @model_validator(mode="after")
    def _validate_per_type(self):
        """Enforce per-type field requirements (RESEARCH §6, D-12).

        SAML providers require all 4 SAML fields and don't need OAuth credentials.
        OAuth providers require client_id + client_secret and must NOT have SAML
        fields populated (mixed config is rejected to prevent ambiguity).
        """
        if self.provider_type == "saml":
            missing = [f for f in _SAML_FIELDS if not getattr(self, f)]
            if missing:
                raise ValueError(
                    f"SAML providers require: {', '.join(missing)}"
                )
        else:
            if not self.client_id or not self.client_secret:
                raise ValueError(
                    f"{self.provider_type} providers require client_id and client_secret"
                )
            extra = [f for f in _SAML_FIELDS if getattr(self, f)]
            if extra:
                raise ValueError(
                    f"{self.provider_type} providers must not set SAML fields: {', '.join(extra)}"
                )
        return self
```

**Key shape elements to copy verbatim:**
- `@model_validator(mode="after")` decorator — no `@classmethod`
- Method takes `self` (post-validation instance)
- Raises `ValueError(...)` (Pydantic wraps as `ValidationError`/422)
- `return self` at end
- Triple-quoted docstring referencing the audit/CONTEXT.md decision ID

**Field references already in place** for the new validator to read (`OAuthProviderCreate` lines 121-129, `OAuthProviderUpdate` lines 240-248):

```python
# OAuthProviderCreate — lines 121-129
group_claim: str | None = Field(
    default=None,
    max_length=_GROUP_CLAIM_MAX,
    description="Name of the JWT/userinfo claim (or SAML attribute) that contains group memberships. Set to enable group-based role mapping.",
)
group_role_mapping: dict | None = Field(
    default=None,
    description="JSON object mapping IdP group names to GeoLens roles. First match wins. Falls back to default_role if no group matches.",
)

# OAuthProviderUpdate — lines 240-248
group_claim: str | None = Field(
    default=None,
    max_length=_GROUP_CLAIM_MAX,
    description="Updated group claim name.",
)
group_role_mapping: dict | None = Field(
    default=None,
    description="Updated group-to-role mapping. Pass an empty object to clear.",
)
```

**Placement:**
- On `OAuthProviderCreate`: append immediately after `_validate_per_type` (after line 169).
- On `OAuthProviderUpdate`: append at the end of the class (after line 262, after `_check_idp_url`). `OAuthProviderUpdate` currently has no `model_validator`, so the new one is the first.

**D-02 carve-out shape** (treat `{}` and `None` as allowed; only non-empty dict triggers the gate):

```python
gates_set = (self.group_claim is not None) or (
    isinstance(self.group_role_mapping, dict)
    and len(self.group_role_mapping) > 0
)
if gates_set and not is_enterprise():
    raise ValueError(
        "Group-based role mapping requires the GeoLens Enterprise overlay"
    )
return self
```

**D-03 verbatim error string** (locked — do not reword): `"Group-based role mapping requires the GeoLens Enterprise overlay"`.

---

### `backend/app/modules/auth/oauth/service.py` (service, request-response)

**Analog (closest in-repo precedent for service-layer `if is_enterprise(): ... else: ...` branching):** `backend/app/modules/settings/router.py:90-104` — the only existing site that branches behavior on `is_enterprise()` rather than just gating an entire route via `Depends(require_enterprise)`.

**Existing edition-gating analog** (`settings/router.py:90-104`):

```python
def _require_enterprise_for_key(key: str) -> None:
    """Raise 404 if a setting key belongs to an enterprise-only tab.

    Returns 404 (not 403, no detail body) to match the ``require_enterprise()``
    guard contract — community callers cannot distinguish between "key does
    not exist" and "key requires enterprise edition", which prevents both
    feature leakage and trivial enumeration of paid keys.
    """
    from app.core.edition import is_enterprise

    if is_enterprise():
        return
    cfg = _get_registry_map().get(key)
    if cfg is not None and cfg.tab in _ENTERPRISE_ONLY_TABS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
```

**Key shape elements to copy:**
- `from app.core.edition import is_enterprise` — module-top import (NOT a function-scoped lazy import; `service.py` already imports several `app.modules.*` symbols at top, so this matches local convention)
- `if is_enterprise():` — direct boolean call, no caching
- Branch contains the enterprise-only behavior; the `else` branch falls back to the safe community default

**Existing call site to wrap** (`oauth/service.py:260-263`):

```python
    # Resolve role from group mapping
    role_name = _resolve_role(
        groups, provider.group_role_mapping, provider.default_role
    )
```

**Target shape (D-05)** — gate at the call site, not inside `_resolve_role()`:

```python
    # Resolve role from group mapping (Enterprise only — D-05 / Phase 219).
    if is_enterprise():
        role_name = _resolve_role(
            groups, provider.group_role_mapping, provider.default_role
        )
    else:
        role_name = provider.default_role
```

**Pure helper to leave untouched** (`oauth/service.py:169-179`, per D-07):

```python
def _resolve_role(
    groups: list[str] | None,
    mapping: dict | None,
    default: str,
) -> str:
    """Match first group from mapping, fallback to default role."""
    if groups and mapping:
        for group in groups:
            if group in mapping:
                return mapping[group]
    return default
```

**Module-top imports already present** (lines 1-13):

```python
"""CRUD service for OAuth provider configuration and user account linking."""

import secrets
import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.oauth.schemas import OAuthProviderCreate, OAuthProviderUpdate
```

**New import to add** (alphabetically between `models` and `oauth.encryption`, or grouped with `app.modules.*`):

```python
from app.core.edition import is_enterprise
```

**Per D-06: no log line in the `else` branch.** The discretion bullet allows a `logger.info(...)` flip; the locked default is silence. If planner enables observability, the existing `logger = structlog.stdlib.get_logger(__name__)` at line 15 is already wired.

---

### `backend/tests/test_oauth.py` (test, integration + unit)

This file gets two distinct change sets, each with its own analog.

#### Change set A: split existing `test_group_role_mapping` (D-08)

**Analog:** the existing test at `backend/tests/test_oauth.py:458-481` itself.

**Existing test to split** (lines 458-481):

```python
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
```

**Existing helper that the COMMUNITY variant must NOT use** (`test_oauth.py:344-360` — runs through the new D-01 validator, which would reject):

```python
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
```

**Direct-ORM bypass pattern** (community variant must instantiate `OAuthProvider` directly — see `oauth/service.py:49-50` for the same model construction shape used in `create_provider`):

```python
# Community variant — bypass the schema validator by constructing the ORM
# instance directly. Mirrors create_provider()'s model construction at
# backend/app/modules/auth/oauth/service.py:49-50.
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider

provider = OAuthProvider(
    slug=f"test-provider-{uuid.uuid4().hex[:6]}",
    display_name="Test Provider",
    provider_type="oidc",
    client_id=f"client-{uuid.uuid4().hex[:6]}",
    client_secret_encrypted=encrypt_secret("test-secret"),
    scopes="openid profile email",
    default_role="viewer",
    group_claim="groups",
    group_role_mapping={"admins": "admin", "editors": "editor"},
    enabled=True,
)
test_db_session.add(provider)
await test_db_session.flush()
```

**Split target shape:**

1. `test_group_role_mapping_community_uses_default_role` — uses the direct-ORM bypass above; asserts `"viewer"` (default_role) is applied, NOT `"admin"`.
2. `test_group_role_mapping_enterprise_applies_mapping` — uses the existing setup (or `_create_test_provider`) under `init_edition(["enterprise"])`; assertion stays `assert "admin" in role_names`.

#### Change set B: edition-state isolation fixture (D-10)

**Analog:** `backend/tests/test_edition.py:11-22` (autouse fixture pattern).

**Existing pattern to mirror** (verbatim):

```python
def _reset_edition():
    """Reset edition state between tests."""
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()
```

**Save/restore variant** (from `backend/tests/test_saml_overlay.py:233-239, 270`) — preserves any pre-test edition state (useful if the fixture is `function`-scoped within a class but other tests in the file may have set state):

```python
# Source: backend/tests/test_saml_overlay.py:233-239 (setup) and :270 (teardown)
import app.core.edition as edition_mod
# ...
saved_info = edition_mod._info
edition_mod.init_edition(["enterprise"])
# ...
try:
    yield ...
finally:
    edition_mod._info = saved_info
```

**Recommended fixture shape for `test_oauth.py`** (per RESEARCH.md "local autouse fixture in `test_oauth.py` for now"):

```python
import pytest


def _reset_edition():
    import app.core.edition as ed_mod
    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()


@pytest.fixture
def enterprise_edition():
    """Initialize edition singleton to enterprise for the test scope."""
    from app.core.edition import init_edition

    init_edition(["enterprise"])
    yield
    # _clean_edition autouse handles teardown reset.
```

#### Change set C: new `TestIdpRoleMappingGate` class (D-09)

**Analog:** `backend/tests/test_edition.py:25-49` for the unit-test class structure with edition manipulation.

**Existing edition-init pattern in unit tests** (`test_edition.py:33-49`):

```python
    def test_edition_env_override_enterprise(self):
        """With GEOLENS_EDITION=enterprise, init_edition sets enterprise."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            init_edition([])

        assert get_edition().edition == "enterprise"

    def test_edition_env_override_community(self):
        """With GEOLENS_EDITION=community + extensions, init_edition sets community."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            init_edition(["some_ext"])

        assert get_edition().edition == "community"
```

**Pydantic ValidationError assertion pattern** — for D-09 schema-validator tests, prefer asserting on the wrapped `ValueError` message text:

```python
import pytest
from pydantic import ValidationError


class TestIdpRoleMappingGate:
    """Schema-validator gate (D-01): IdP role mapping fields rejected in community."""

    def test_create_rejects_group_role_mapping_in_community(self):
        from app.modules.auth.oauth.schemas import OAuthProviderCreate

        with pytest.raises(ValidationError) as exc_info:
            OAuthProviderCreate(
                slug="test",
                display_name="Test",
                provider_type="oidc",
                client_id="cid",
                client_secret="csecret",
                group_role_mapping={"admins": "admin"},
            )
        assert "Group-based role mapping requires the GeoLens Enterprise overlay" in str(
            exc_info.value
        )

    def test_create_accepts_group_mapping_in_enterprise(self, enterprise_edition):
        from app.modules.auth.oauth.schemas import OAuthProviderCreate

        # Should NOT raise.
        OAuthProviderCreate(
            slug="test",
            display_name="Test",
            provider_type="oidc",
            client_id="cid",
            client_secret="csecret",
            group_role_mapping={"admins": "admin"},
        )
```

**Slice list (per RESEARCH §Validation Architecture, slices 1-5):**
1. `test_create_rejects_group_role_mapping_in_community`
2. `test_create_rejects_group_claim_in_community`
3. `test_create_accepts_group_mapping_in_enterprise` (uses `enterprise_edition` fixture)
4. `test_update_rejects_group_role_mapping_in_community`
5. `test_create_with_empty_mapping_allowed_in_community` (D-02 carve-out: `group_role_mapping={}` succeeds)

---

### `docs-internal/audits/oc-separation-audit-v13.1-close.md` (doc, in-place amendment)

**Analog:** the file itself — D-12 amends 5 distinct sections in place. No external doc analog; the doc IS its own template.

**Section 1: Banner — line 20** (current):

```markdown
## ⚠ MILESTONE CLOSE BLOCKED

**Boundary Integrity grade B− does NOT meet the v13.1 close target of A−.**
```

**Target shape (D-12 edit 1):**

```markdown
## ✅ MILESTONE CLOSE VERIFIED — Phase 219 closed boundary gap

**Boundary Integrity grade [new grade] meets the v13.1 close target of A−.**

[Brief one-paragraph summary of how Phase 219 closed the gap — cite the new validator + service branch.]

### Pre-remediation state (2026-04-29)

[Original ⚠ MILESTONE CLOSE BLOCKED narrative preserved verbatim as a sub-section so the audit trail of the gap and its resolution is co-located.]
```

**Section 2: Scorecard — line 9** (current):

```markdown
| **Boundary Integrity** | **B−** | Three 🔴 violations all collapse to one architectural P0: OAuth IdP→role mapping (`oauth/models.py:82-84` columns + `oauth/schemas.py:116-129, 237-248` write API + `oauth/service.py:169-179, 261-263` runtime) executes unconditionally in community ... |
```

**Target shape (D-12 edit 2):** grade letter changes; rationale rewritten to cite the new validator (`oauth/schemas.py` `_validate_idp_mapping_gate` or chosen name) + service-layer branch (`oauth/service.py:261-263`); columns at `oauth/models.py:82-84` documented as forward-compat scaffolding for the SAML enterprise overlay (Phase 217 D-04).

**Section 3: Section 1 Findings table — lines 53-55** (current — three 🔴 rows):

```markdown
| `backend/app/modules/auth/oauth/models.py:82-84` | `default_role` / `group_claim` / `group_role_mapping` columns on OAuthProvider (IdP→role mapping) | 🔴 **Violation (UNRESOLVED — deferred from 2026-04-27)** | Gate at write path: keep columns ... |
| `backend/app/modules/auth/oauth/service.py:169-179, 261-263` | `_resolve_role()` applies `group_role_mapping` for ALL OAuth providers in `find_or_create_oauth_user()` | 🔴 **Violation (UNRESOLVED)** | Wrap in edition check at `:261-263` ... |
| `backend/app/modules/auth/oauth/schemas.py:116-129, 237-248` | `default_role` / `group_claim` / `group_role_mapping` accepted in Create/Update schemas without enterprise gate | 🔴 **Violation (UNRESOLVED)** | Add `model_validator(mode="after")` ... |
```

**Target shape (D-12 edit 3):** flip all three to 🟢 Clean; cite the new `_validate_idp_mapping_gate` validator + the `if is_enterprise():` branch at `oauth/service.py:261-263`; note columns kept as forward-compat scaffolding.

**Section 4: Section 8 grade-delta table — lines 363-372** (current):

```markdown
| Boundary Integrity | B | B− | ↓ (vs source); ↑ (vs 2026-04-27 — same) | A− | **❌ NO** |
```

**Target shape (D-12 edit 4):** add a new column (or amend the existing row) showing `B−` (v13.1-close pre-219) → `[new grade]` (v13.1-close post-219); arrow `↑`; `Met? ✅`.

**Section 5: P1 Residual Triage row 1 — line 408** (current):

```markdown
| 1 | OAuth IdP→role mapping in core (3 🔴 sites — schema + service + model) | `oauth/{schemas,service,models}.py` (§1) | **Fix-now** | ... | **Phase 219: oc-audit-remediate-idp-mapping** (proposed). Re-run audit on completion ... |
```

**Target shape (D-12 edit 5):** append `**Closed by Phase 219 (2026-04-29)**` to the Verdict or Follow-up cell; row stays for traceability.

**Additional consistency edit (RESEARCH §Pitfalls 5):** Executive Summary at line 41 references "the sixth P1 commitment is unfulfilled" — minor wording update so the summary aligns with the post-amendment state. Add a short paragraph noting Phase 219 closed the gap.

**`docs-internal/audits/oc-separation-deferred-items-20260426.md` closure marker** — per RESEARCH §Open Question 2, **skip**: no row currently tracks the IdP-mapping gate (it was fix-now, not deferred). Adding a "Closed by Phase 219" entry to a row that never existed creates noise. The v13.1-close.md amendment is sufficient close-trail.

---

## Shared Patterns

### Edition gating (`is_enterprise()`)
**Source:** `backend/app/core/edition.py:50-52`
**Apply to:** Both `oauth/schemas.py` (validator) and `oauth/service.py` (call-site branch).

```python
def is_enterprise() -> bool:
    """Return True if running in enterprise edition."""
    return get_edition().edition == "enterprise"
```

Singleton-backed, cheap to call per-request. Already consumed at `app/platform/extensions/guards.py:16`, `app/modules/settings/router.py:100, 181`.

### Edition-state test isolation
**Source:** `backend/tests/test_edition.py:11-22`
**Apply to:** Any test in `test_oauth.py` that calls `init_edition(...)`.

```python
def _reset_edition():
    import app.core.edition as ed_mod
    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()
```

Critical to avoid cross-test pollution (RESEARCH §Pitfall 1). The `_info` module-level singleton is mutated by `init_edition`; without reset, subsequent tests inherit the prior test's edition.

### Pydantic `model_validator(mode="after")` for cross-field rejection
**Source:** `backend/app/modules/auth/oauth/schemas.py:145-169`
**Apply to:** Both new validators on `OAuthProviderCreate` and `OAuthProviderUpdate`.

```python
@model_validator(mode="after")
def _validate_xxx(self):
    """Docstring citing the audit/CONTEXT.md decision ID."""
    if <bad-condition>:
        raise ValueError("<verbatim D-03 message>")
    return self
```

Standard FastAPI 422 envelope; no custom error handler needed.

### Enterprise-mode error messaging
**Source:** Audit recommendation (D-03 verbatim) + convention precedent at `backend/app/platform/extensions/guards.py`
**Apply to:** Both new validators.

Verbatim string: `"Group-based role mapping requires the GeoLens Enterprise overlay"` — names the feature ("Group-based role mapping") and the upgrade path ("Enterprise overlay"). Tests assert against this exact text.

### In-place doc amendment for milestone artifacts
**Source:** Phase 218 D-02 (precedent: `oc-separation-audit-v13.1-close.md` is the milestone-bound artifact, not a dated artifact)
**Apply to:** D-12 — amend `v13.1-close.md` in place; preserve original BLOCKED narrative as a "Pre-remediation state (2026-04-29)" subsection. Git history is the audit trail.

---

## No Analog Found

None. Every primitive needed for this phase already has clear precedent in-repo. The phase is composition + amendment, not invention (RESEARCH §Don't Hand-Roll: "Every primitive needed for this phase already exists in the repo").

---

## Metadata

**Analog search scope:**
- `backend/app/modules/auth/oauth/` (target files + same-file analogs)
- `backend/app/core/edition.py` (singleton accessor)
- `backend/app/platform/extensions/guards.py` (existing gating precedent)
- `backend/app/modules/settings/router.py` (only existing service-layer `if is_enterprise():` branch)
- `backend/tests/test_oauth.py` (existing test to split)
- `backend/tests/test_edition.py` (autouse fixture pattern)
- `backend/tests/test_saml_overlay.py` (`init_edition` save/restore pattern)
- `docs-internal/audits/oc-separation-audit-v13.1-close.md` (self-amendment target)

**Files scanned:** 8

**Pattern extraction date:** 2026-04-29
