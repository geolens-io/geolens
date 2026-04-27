---
phase: 214-identity-protocol-extract
plan: 02
type: execute
wave: 2
depends_on: ["214-01"]
files_modified:
  - backend/app/modules/auth/dependencies.py
autonomous: true
requirements: [IDENT-02, IDENT-03]
requirements_addressed: [IDENT-02, IDENT-03]
tags: [refactor, auth, fastapi, protocol, extension, identity]

must_haves:
  truths:
    - "D-07 (part 1): `get_optional_user`, `get_current_user`, `get_current_active_user` in `backend/app/modules/auth/dependencies.py` are retyped to return `Identity` (alias of `IdentityProtocol`) instead of the concrete `User` ORM. The runtime objects returned are still concrete `User` instances; only the static return-type annotation changes. Structural subtyping (PEP 544) makes this safe — `User` already satisfies `IdentityProtocol` (verified by Plan 01)."
    - "D-15: `get_optional_user()` calls `await get_identity_extension().resolve_identity_from_token(token, request, db)` between the API-key resolution path and the JWT decode path. Order: (1) resolve API key, (2) extract bearer token, (3) NEW: if a bearer token exists, await the extension; if it returns non-None, return that as the identity, (4) fall through to the existing JWT decode + DB lookup, (5) None if no token at all."
    - "D-15 + Pitfall 9 (RESEARCH § Pitfall 9 recommendation, planning_context override): The extension wire-in is DUPLICATED inside `get_current_user()` (between the API-key path and the existing JWT-decode body) rather than refactoring `get_current_user()` to delegate to `get_optional_user()`. Reason: `get_current_user()` distinguishes expired-token vs. invalid-token via different `WWW-Authenticate` headers (RFC 6750 silent-refresh hint at lines 142-151) — delegating to `get_optional_user()` would lose this UX. ~6 lines duplicated; cleaner than losing the expired-token signal."
    - "D-16: `get_current_active_user()` is updated to take `Annotated[Identity, Depends(get_current_user)]` (was `Annotated[User, Depends(get_current_user)]`) and return `Identity`. Its body's `is_active` gate works unchanged because `Identity.is_active: bool` is part of the Protocol surface (Plan 01 D-01)."
    - "D-17: The extension is NOT consulted in `_resolve_api_key()`. API keys remain a core/community concern; if a future enterprise SCIM overlay wants to issue API keys with non-default semantics, that's a separate Protocol (deferred per CONTEXT.md `<deferred>`). The wire-in is bearer-token-only."
    - "Behavior preservation: `_resolve_api_key()` is UNCHANGED — its return type stays `User | None` (it returns the concrete ORM object via `api_key_obj.user`). The retyped deps call `_resolve_api_key()` and the returned `User` is structurally `Identity` already, so the assignment `user: Identity | None = await _resolve_api_key(...)` type-checks cleanly without any cast."
    - "Internal `User` import at `backend/app/modules/auth/dependencies.py:14` (`from app.modules.auth.models import ApiKey, User`) is KEPT — auth/dependencies.py is in the allowlist (D-09 — auth/** owns User). Plan 02 ADDS `from app.core.identity import Identity` next to it. The internal SQL queries (`select(User).where(User.id == user_id)`) keep using the concrete class."
    - "Behavior preservation: `require_role()` and `require_permission()` factories at lines 201-271 are retyped to return `Identity` (matching their `current_user: Annotated[..., Depends(get_current_active_user)]` parameter) so endpoints that consume the factory output via `Depends(require_permission(...))` get an `Identity`-typed user. The factories' bodies are unchanged."
    - "Behavior preservation: `get_cached_user_roles()` at lines 181-198 keeps `user: User | None = Depends(get_optional_user)` annotated as `Identity | None` instead. Calls `get_user_roles(db, user)` from `catalog/authorization.py` — that callee accepts `User` today; will be retyped in Plan 03 to accept `Identity`. Until Plan 03 lands, this remains a structural pass-through (concrete `User` IS-A `Identity`)."
    - "Reconciliation note (planning_context): RESEARCH.md § Pitfall 9 recommends DUPLICATING the extension wire-in across `get_optional_user` and `get_current_user` to preserve the expired-token UX (different WWW-Authenticate headers). Plan 02 follows this recommendation. CONTEXT.md D-16's wording (`get_current_user() and get_current_active_user() build on get_optional_user() in the existing pattern`) is INCORRECT for `get_current_user()` — read the live file at `auth/dependencies.py:105-166`: it has its own JWT decode body, NOT a delegation to `get_optional_user`. Plan 02 keeps both bodies and adds the extension wire-in to both."
    - "Full pytest baseline (≥1999 passing) holds because `User` structurally satisfies `Identity`; existing tests pass arguments and read attributes that are all on the Protocol surface. No test fixture change is required."
  artifacts:
    - path: "backend/app/modules/auth/dependencies.py"
      provides: "Retyped FastAPI dependencies returning Identity; extension wire-in between API-key and JWT paths in BOTH get_optional_user and get_current_user"
      contains: "get_identity_extension"
      min_lines: 280
  key_links:
    - from: "backend/app/modules/auth/dependencies.py:get_optional_user"
      to: "backend/app/platform/extensions/__init__.py:get_identity_extension"
      via: "module-level import + await call between API-key and JWT paths"
      pattern: "await get_identity_extension\\(\\)\\.resolve_identity_from_token"
    - from: "backend/app/modules/auth/dependencies.py:get_current_user"
      to: "backend/app/platform/extensions/__init__.py:get_identity_extension"
      via: "module-level import + await call between API-key and JWT paths (Pitfall 9 — duplicated to preserve expired-token UX)"
      pattern: "await get_identity_extension\\(\\)\\.resolve_identity_from_token"
    - from: "backend/app/modules/auth/dependencies.py"
      to: "backend/app/core/identity.py:Identity"
      via: "module-level import for return-type and parameter annotations"
      pattern: "from app\\.core\\.identity import Identity"
---

<objective>
Retype the three FastAPI authentication dependencies in `backend/app/modules/auth/dependencies.py` (`get_optional_user`, `get_current_user`, `get_current_active_user`) to return `Identity` instead of the concrete `User` ORM, and wire the new `IdentityExtension` registration hook into BOTH `get_optional_user` and `get_current_user` between the API-key and JWT paths. The wire-in is duplicated (RESEARCH § Pitfall 9, recommendation (b)) rather than refactoring `get_current_user` to delegate to `get_optional_user` — this preserves the expired-token vs. invalid-token UX distinction (different `WWW-Authenticate` headers per RFC 6750 silent-refresh hint at the existing lines 142-151).

Purpose: Realize ROADMAP SC#3 (extension hook lets enterprise overlays supply an alternate identity backend without core changes) by exposing an actual call site that consults `get_identity_extension()`. Realize part of SC#2 (cross-domain code types against `IdentityProtocol`) by changing the dep return types — Plan 03 then sweeps all 42 cross-domain caller files. Maintain SC#4 (1965-test baseline stays green) by leveraging structural subtyping: `User` IS-A `Identity` at the type level, so existing test fixtures (which construct `User(...)` directly) and existing endpoint bodies (which read `.id`, `.username`, `.email`, `.roles`, `.is_active`, `.created_at`) keep working unchanged.

Output: ONE file modified (`backend/app/modules/auth/dependencies.py`). Internal `User` import at line 14 is KEPT (auth/** is allowlisted per D-09). New `Identity` import is ADDED next to it. Three function signatures retyped. ~6 lines of extension wire-in code added inside `get_optional_user()` and ~6 more inside `get_current_user()`. `_resolve_api_key()` body unchanged. `get_cached_user_roles()`, `require_role()`, `require_permission()` parameter annotations updated. The 1999-test baseline holds.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/214-identity-protocol-extract/214-CONTEXT.md
@.planning/phases/214-identity-protocol-extract/214-RESEARCH.md
@.planning/phases/214-identity-protocol-extract/214-VALIDATION.md
@.planning/phases/214-identity-protocol-extract/214-01-SUMMARY.md
@backend/app/modules/auth/dependencies.py
@backend/app/modules/auth/models.py
@backend/app/core/identity.py
@backend/app/platform/extensions/__init__.py
@backend/app/modules/catalog/authorization.py

<interfaces>
<!-- The pre-Plan-02 state of `backend/app/modules/auth/dependencies.py` (272 lines, verified by reading the file 2026-04-27). The exact lines that change are listed below. -->

#### Imports section (current lines 1-17 — UNCHANGED except ADD line 14a)

CURRENT (lines 1-17 verbatim):
```python
"""FastAPI dependencies for JWT authentication and role-based access control."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import ApiKey, User
from app.modules.catalog.authorization import get_user_roles
from app.core.config import settings
from app.core.dependencies import get_db
```

CHANGES:
- ADD `from app.core.identity import Identity` after line 16 (`from app.core.config import settings`) so the imports are in stdlib → third-party → app.core → app.modules order. The `app.modules.auth.models import ApiKey, User` import on line 14 STAYS — auth/dependencies.py is allowlisted (D-09); it owns User.
- ADD `from app.platform.extensions import get_identity_extension` after the `from app.core.dependencies import get_db` import.

POST-PLAN imports block (target):
```python
"""FastAPI dependencies for JWT authentication and role-based access control."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.models import ApiKey, User
from app.modules.catalog.authorization import get_user_roles
from app.platform.extensions import get_identity_extension
```

(Note: this also re-orders the `from app.core.config` and `from app.core.dependencies` imports to be alphabetical within the `app.core.*` group AND to come BEFORE `app.modules.*` imports per ruff's isort convention. Verify with `ruff check --select=I` after the edit.)

#### `_resolve_api_key()` (current lines 23-58) — UNCHANGED

The function returns the concrete `User` ORM (via `api_key_obj.user` SQLAlchemy relationship) and Plan 02 leaves it alone. The retyped callers will assign its return value into `Identity | None` variables; structural subtyping makes that safe.

#### `get_optional_user()` (current lines 61-102) — RETYPE + ADD WIRE-IN

CURRENT signature: `async def get_optional_user(...) -> User | None:`
TARGET signature: `async def get_optional_user(...) -> Identity | None:`

CURRENT body (lines 72-102 verbatim):
```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    if token is None:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
    except jwt.PyJWTError:
        return None

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or user.status != "active":
        return None

    return user
```

TARGET body — INSERT a NEW block between the API-key path (line 75 — `return user`) and the bearer-token-None check (line 77 — `if token is None`). The new block awaits the IdentityExtension and returns its result if non-None:

```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook (Phase 214 D-15): if an enterprise overlay
    # registered an alternate identity backend, give it a chance to
    # resolve the bearer token before the existing JWT decode path.
    # Default impl returns None -> falls through to JWT below.
    if token is not None:
        ext_identity = await get_identity_extension().resolve_identity_from_token(
            token, request, db
        )
        if ext_identity is not None:
            return ext_identity

    if token is None:
        return None
    try:
        payload = jwt.decode(
            ...  # rest unchanged
```

The wire-in is exactly 7 lines (one comment block + the if-await-if-return). The `if token is None: return None` check that was on the original line 77 stays in place; the extension call short-circuits BEFORE that check only when a bearer token exists. The function's return type annotation changes from `User | None` to `Identity | None`.

#### `get_current_user()` (current lines 105-166) — RETYPE + ADD WIRE-IN (Pitfall 9 — duplicated)

CURRENT signature: `async def get_current_user(...) -> User:`
TARGET signature: `async def get_current_user(...) -> Identity:`

CURRENT body (lines 116-166): API-key short-circuit at lines 116-119, then `credentials_exception` setup at 121-125, then JWT decode body with the expired-token UX at 130-153, then DB lookup at 160-164, then return at 166.

TARGET: insert the SAME extension wire-in between the API-key short-circuit (line 119) and the `credentials_exception` setup (line 121). DO NOT refactor `get_current_user()` to delegate to `get_optional_user()` — that would erase the `jwt.ExpiredSignatureError` branch at lines 139-151 (which raises a 401 with the RFC-6750 silent-refresh hint).

The TARGET body fragment to add (right after `return user` of the API-key short-circuit, before `credentials_exception = HTTPException(...)`):

```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook (Phase 214 D-15): same pattern as
    # get_optional_user — give an enterprise overlay a chance to resolve
    # the bearer token before the existing JWT decode path. Duplicated
    # across both deps to preserve the expired-token UX in this function
    # (lines below distinguish jwt.ExpiredSignatureError -> RFC-6750
    # silent-refresh hint vs. generic invalid_token).
    if token is not None:
        ext_identity = await get_identity_extension().resolve_identity_from_token(
            token, request, db
        )
        if ext_identity is not None:
            return ext_identity

    credentials_exception = HTTPException(
        ...  # rest unchanged
```

The function's return type annotation changes from `User` to `Identity`.

#### `get_current_active_user()` (current lines 169-178) — RETYPE PARAM + RETURN

CURRENT:
```python
async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure the current user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user
```

TARGET — change BOTH the parameter annotation `Annotated[User, ...]` → `Annotated[Identity, ...]` AND the return type `-> User` → `-> Identity`. Body unchanged. The `is_active` attribute is on the Protocol surface (D-01), so the gate works structurally.

#### `get_cached_user_roles()` (current lines 181-198) — RETYPE PARAM

CURRENT line 184: `user: User | None = Depends(get_optional_user),`
TARGET line 184: `user: Identity | None = Depends(get_optional_user),`

The function calls `get_user_roles(db, user)` from `catalog/authorization.py`. That callee currently has signature `async def get_user_roles(db: AsyncSession, user: User) -> set[str]:` (verified at `catalog/authorization.py:98`); Plan 03 will retype it to accept `Identity`. Until Plan 03 lands, the call works at runtime because the actual object IS a `User` (which IS-A `Identity`); ruff/pyright may flag a covariance complaint but the project does not run pyright in CI (D-25).

#### `require_role()` and `require_permission()` (current lines 201-271) — RETYPE INTERNAL ANNOTATIONS

These are factory functions returning closures. The closures take `current_user: Annotated[User, Depends(get_current_active_user)]` and return `User`. Update both to use `Identity`.

CURRENT line 215 (inside `require_role`):
```python
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
```

TARGET:
```python
        current_user: Annotated[Identity, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> Identity:
```

CURRENT lines 244-246 (inside `require_permission`): same pattern. Change `Annotated[User, ...]` → `Annotated[Identity, ...]` and `-> User` → `-> Identity`.

The closure bodies (lines 218-225 and 247-269) call `get_cached_user_roles()`, intersect with role names, and access permission matrices. They access `current_user` only as an opaque value passed to `get_cached_user_roles()` — no attribute reads beyond what's on `Identity`. Body unchanged.

#### Allowlist verification

`backend/app/modules/auth/dependencies.py` is on the Plan 04 allowlist (D-09: "auth/** owns User. All paths under this prefix exempt"). Plan 02's edits keep the `from app.modules.auth.models import ApiKey, User` import intact. Plan 04's architecture-guard test will NOT flag this file because the pathspec `:!backend/app/modules/auth/` excludes the entire `auth/` subtree.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 02-01: Retype get_optional_user + get_current_user + get_current_active_user; add IdentityExtension wire-in to both</name>
  <files>backend/app/modules/auth/dependencies.py</files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-07, D-15, D-16, D-17 — dep retype + wire-in decisions; D-08 — UserRole/Role import disposition)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 762-784 — Pitfall 9 (extension wire-in duplication); lines 752-761 — Pitfall 8 (async-method contract); lines 729-741 — Pitfall 6 (FastAPI Annotated mismatch); lines 897-990 — full reference for the dep retype + wire-in)
    - backend/app/modules/auth/dependencies.py (current 272-line file — read end-to-end; the `_resolve_api_key()` body at lines 23-58 stays unchanged, the three retyped functions are at lines 61-178, and the factories at 201-271 take parameter annotation updates)
    - backend/app/core/identity.py (Plan 01 — verify `Identity` is exported and equals `IdentityProtocol`)
    - backend/app/platform/extensions/__init__.py (Plan 01 — verify `get_identity_extension` is exported and returns `IdentityExtension` instance)
    - backend/app/modules/auth/models.py (full file — confirm `User.is_active`, `User.id`, `User.status` are still the field names referenced inside the dep bodies; confirm `User.status != "active"` semantics so the post-extension fall-through path stays correct)
    - backend/app/modules/catalog/authorization.py (lines 95-110 — confirm `get_user_roles(db, user: User)` signature; Plan 03 retypes the parameter to `Identity`, but Plan 02 must leave the call site working with structural subtyping in the interim)
  </read_first>
  <action>
Make the following surgical edits to `backend/app/modules/auth/dependencies.py`. Use the Edit tool for each block. After each block, run `cd backend && uv run ruff check app/modules/auth/dependencies.py` to catch syntax errors before moving on.

**Edit 1 — Update imports block (top of file).**

Original (lines 14-17):
```python
from app.modules.auth.models import ApiKey, User
from app.modules.catalog.authorization import get_user_roles
from app.core.config import settings
from app.core.dependencies import get_db
```

Replace with (re-ordered to match ruff's isort convention: app.core → app.modules → app.platform; alphabetical within groups):
```python
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.models import ApiKey, User
from app.modules.catalog.authorization import get_user_roles
from app.platform.extensions import get_identity_extension
```

The `User` import on what is currently line 14 STAYS — it is needed for the SQL queries inside `get_optional_user` and `get_current_user` (`select(User).where(User.id == user_id)`) and for `_resolve_api_key`'s internal logic. `Identity` is added as a new import. `get_identity_extension` is added as a new import.

After Edit 1, run `uv run ruff check app/modules/auth/dependencies.py --select=I` to confirm import order is clean.

**Edit 2 — Retype `get_optional_user()` return; add IdentityExtension wire-in.**

Original (line 65 onward — the function signature):
```python
async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> User | None:
```

Replace `-> User | None:` with `-> Identity | None:` (single-line change to the return-type annotation only).

Original (lines 72-78 — the body's first 7 lines):
```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    if token is None:
        return None
```

Replace with (insert the 7-line extension wire-in between the API-key path and the bearer-token-None check):
```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook (Phase 214 D-15): if an enterprise overlay
    # registered an alternate identity backend, give it a chance to resolve
    # the bearer token before the existing JWT decode path. Default impl
    # returns None -> falls through to JWT below. Extension is bearer-token
    # only (D-17 — API keys remain a community concern).
    if token is not None:
        ext_identity = await get_identity_extension().resolve_identity_from_token(
            token, request, db
        )
        if ext_identity is not None:
            return ext_identity

    if token is None:
        return None
```

The rest of the function body (lines 79 onward — the JWT decode + DB lookup) is UNCHANGED. Note that `if token is None: return None` appears TWICE structurally (once before the extension wire-in is inert because the extension call is guarded by `if token is not None`, and once after as the original guard); the extension's `if token is not None` check makes the post-extension `if token is None: return None` only reachable when no token at all. This is intentional and matches the original control flow — the extension wire-in is purely additive.

**Edit 3 — Retype `get_current_user()` return; add IdentityExtension wire-in (Pitfall 9 — duplicated).**

Original (line 109 — the function signature's return type):
```python
async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> User:
```

Replace `-> User:` with `-> Identity:` (single-line change).

Original (lines 116-121 — the body up to `credentials_exception = HTTPException(...)`):
```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    credentials_exception = HTTPException(
```

Replace with (insert the 8-line extension wire-in after the API-key short-circuit, before `credentials_exception` setup):
```python
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook (Phase 214 D-15): same pattern as
    # get_optional_user. Duplicated across both deps to preserve the
    # expired-token UX (RFC 6750 silent-refresh hint at lines below)
    # rather than refactoring get_current_user to delegate to
    # get_optional_user (Pitfall 9 recommendation).
    if token is not None:
        ext_identity = await get_identity_extension().resolve_identity_from_token(
            token, request, db
        )
        if ext_identity is not None:
            return ext_identity

    credentials_exception = HTTPException(
```

The rest of `get_current_user()` (the JWT decode body with `jwt.ExpiredSignatureError` handling at lines 139-151, the user_id parse at 155-158, the DB lookup at 160-164, and the return at 166) is UNCHANGED.

**Edit 4 — Retype `get_current_active_user()` parameter + return.**

Original (lines 169-172):
```python
async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure the current user is active."""
```

Replace with:
```python
async def get_current_active_user(
    current_user: Annotated[Identity, Depends(get_current_user)],
) -> Identity:
    """Ensure the current user is active."""
```

Body (lines 173-178) unchanged.

**Edit 5 — Retype `get_cached_user_roles()` parameter.**

Original (lines 181-184):
```python
async def get_cached_user_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> set[str]:
```

Replace with:
```python
async def get_cached_user_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> set[str]:
```

Body (lines 185-198) unchanged. The call `get_user_roles(db, user)` at line 196 works structurally — Plan 03 will retype `get_user_roles`'s parameter to `Identity` for consistency.

**Edit 6 — Retype `require_role()` factory's inner closure.**

Original (lines 213-217):
```python
    async def _role_checker(
        request: Request,
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
```

Replace with:
```python
    async def _role_checker(
        request: Request,
        current_user: Annotated[Identity, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> Identity:
```

Body (lines 218-225) unchanged.

**Edit 7 — Retype `require_permission()` factory's inner closure.**

Original (lines 242-246):
```python
    async def _permission_checker(
        request: Request,
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
```

Replace with:
```python
    async def _permission_checker(
        request: Request,
        current_user: Annotated[Identity, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> Identity:
```

Body (lines 247-269) unchanged.

**Verification after all 7 edits:**

1. `cd backend && python -c "from app.modules.auth.dependencies import get_optional_user, get_current_user, get_current_active_user; print('imports ok')"` — exits 0.
2. `cd backend && python -c "from app.modules.auth.dependencies import get_optional_user; import inspect; sig = inspect.signature(get_optional_user); print(sig.return_annotation)"` — prints `Identity | None` (or the resolved string under `from __future__ import annotations` semantics — accept either string `'Identity | None'` or the typing object).
3. `cd backend && uv run ruff check app/modules/auth/dependencies.py` — exits 0.
4. `cd backend && uv run ruff format --check app/modules/auth/dependencies.py` — exits 0.
5. `cd backend && grep -c "from app.core.identity import Identity" app/modules/auth/dependencies.py` — equals 1.
6. `cd backend && grep -c "from app.platform.extensions import get_identity_extension" app/modules/auth/dependencies.py` — equals 1.
7. `cd backend && grep -c "from app.modules.auth.models import ApiKey, User" app/modules/auth/dependencies.py` — equals 1 (allowlisted; the import STAYS).
8. `cd backend && grep -c "await get_identity_extension().resolve_identity_from_token" app/modules/auth/dependencies.py` — equals 2 (one in `get_optional_user`, one in `get_current_user` — Pitfall 9 duplication verified).
9. `cd backend && grep -cE "-> (User|User \| None):" app/modules/auth/dependencies.py` — equals 1 (only `_resolve_api_key` keeps `User | None` return; the three deps and two factories all return `Identity | None` or `Identity`).
10. `cd backend && grep -cE "-> (Identity|Identity \| None):" app/modules/auth/dependencies.py` — equals 5 (`get_optional_user` returns `Identity | None`; `get_current_user`, `get_current_active_user`, `_role_checker`, `_permission_checker` return `Identity`).
11. `cd backend && uv run pytest tests/test_auth_dependencies.py tests/test_auth_jwt.py tests/test_auth_api_key.py -v --tb=short 2>/dev/null || cd backend && uv run pytest -k "test_auth or auth_dep or jwt or api_key" -v --tb=short` — auth dep tests pass.
12. `cd backend && uv run pytest tests/test_extensions.py -v --tb=short` — extension tests still pass (regression check from Plan 01).
13. `cd backend && uv run pytest -m "not perf" --tb=short -q 2>&1 | tail -10` — full suite passes; summary line shows ≥1999 passed.

If any test fails:
- `TypeError: object NoneType can't be used in 'await' expression` → Pitfall 8: the wire-in is calling a sync `resolve_identity_from_token`. Verify `DefaultIdentityExtension.resolve_identity_from_token` is `async def` (Plan 01 Task 01-02 acceptance criterion). If it is, double-check this plan's wire-in code uses `await` correctly.
- `AttributeError: 'IdentityProtocol' has no attribute 'X'` where X is `password_hash`, `auth_provider`, `last_login_at`, `status`, or `updated_at` → a caller in `auth/dependencies.py` (NOT the deps themselves) is reading a non-Identity attribute. The likely culprit: `_resolve_api_key()` at line 38 reads `user.is_active` and `user.status` — both are SAFE because `_resolve_api_key` returns `User | None` (NOT `Identity | None`); the `user` variable inside `_resolve_api_key` is the concrete ORM object. The retyped deps assign the return into `user: Identity | None = await _resolve_api_key(...)` which is a contravariant cast (concrete to Protocol — always safe in Python).
- Test failure in `test_login` / `test_jwt_*` / `test_refresh_token_*` → check the JWT decode body wasn't accidentally indented inside the wire-in. The `if token is None: return None` guard MUST appear AFTER the extension wire-in in `get_optional_user`. The `try: payload = jwt.decode(...)` block stays at the same indent as before.
- `ImportError: cannot import name 'Identity' from 'app.core.identity'` → Plan 01 didn't ship; verify `git log --oneline -- backend/app/core/identity.py` shows the Plan 01 commit landed before Plan 02 starts.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -c "from app.modules.auth.dependencies import get_optional_user, get_current_user, get_current_active_user, get_cached_user_roles, require_role, require_permission; print('ok')" && uv run ruff check app/modules/auth/dependencies.py && uv run ruff format --check app/modules/auth/dependencies.py && bash -c 'count=$(grep -c "await get_identity_extension().resolve_identity_from_token" app/modules/auth/dependencies.py); test "$count" = "2"' && bash -c 'count=$(grep -c "from app.core.identity import Identity" app/modules/auth/dependencies.py); test "$count" = "1"' && bash -c 'count=$(grep -c "from app.platform.extensions import get_identity_extension" app/modules/auth/dependencies.py); test "$count" = "1"' && bash -c 'count=$(grep -c "from app.modules.auth.models import ApiKey, User" app/modules/auth/dependencies.py); test "$count" = "1"' && uv run pytest tests/test_extensions.py -v --tb=short && uv run pytest -k "auth or jwt or api_key or login or refresh" -v --tb=short -q 2>&1 | tail -20</automated>
  </verify>
  <acceptance_criteria>
    - `backend/app/modules/auth/dependencies.py` imports `Identity` from `app.core.identity` (verify with `grep -c "^from app.core.identity import Identity$" backend/app/modules/auth/dependencies.py` equals 1).
    - `backend/app/modules/auth/dependencies.py` imports `get_identity_extension` from `app.platform.extensions` (verify with `grep -c "^from app.platform.extensions import get_identity_extension$" backend/app/modules/auth/dependencies.py` equals 1).
    - The `User` import on what was line 14 is RETAINED (verify with `grep -c "^from app.modules.auth.models import ApiKey, User$" backend/app/modules/auth/dependencies.py` equals 1; allowlisted per D-09).
    - `get_optional_user` return type is `Identity | None` (verify with `grep -c "async def get_optional_user" backend/app/modules/auth/dependencies.py` equals 1 AND `grep -A4 "async def get_optional_user" backend/app/modules/auth/dependencies.py | grep -c "Identity | None"` ≥ 1).
    - `get_current_user` return type is `Identity` (verify with `grep -c "async def get_current_user" backend/app/modules/auth/dependencies.py` equals 1 AND `grep -A4 "async def get_current_user" backend/app/modules/auth/dependencies.py | grep -cE "-> Identity:"` equals 1).
    - `get_current_active_user` parameter and return both use `Identity` (verify with `grep -A2 "async def get_current_active_user" backend/app/modules/auth/dependencies.py | grep -q "Annotated\[Identity"` AND grep for `-> Identity:` immediately after).
    - The IdentityExtension wire-in `await get_identity_extension().resolve_identity_from_token` appears EXACTLY 2 times in the file (verify with `grep -c "await get_identity_extension().resolve_identity_from_token" backend/app/modules/auth/dependencies.py` equals 2 — Pitfall 9 duplication).
    - `_resolve_api_key()` body is unchanged (verify with `grep -c "async def _resolve_api_key" backend/app/modules/auth/dependencies.py` equals 1; the function's return type stays `User | None`).
    - `get_cached_user_roles` parameter `user` is annotated `Identity | None` (verify with `grep -B1 "Depends(get_optional_user)" backend/app/modules/auth/dependencies.py | grep -q "Identity | None"`).
    - `require_role` and `require_permission` inner closures use `Annotated[Identity, ...]` (verify with `grep -c "Annotated\[Identity, Depends(get_current_active_user)\]" backend/app/modules/auth/dependencies.py` equals 2).
    - Ruff lint and format both pass on the file.
    - `cd backend && uv run pytest tests/test_extensions.py -v --tb=short` exits 0 (Plan 01's tests still pass).
    - `cd backend && uv run pytest -k "auth or jwt or api_key or login or refresh or oauth" -v --tb=short` exits 0 (auth-affected slice passes — covers VALIDATION rows 214-02-02, 214-02-03, 214-02-04, 214-02-05, 214-02-06).
    - Full backend test suite (`cd backend && uv run pytest -m 'not perf' --tb=short -q` OR `docker compose exec api uv run pytest -m 'not perf' --tb=short -q`) exits 0 with ≥1999 passing.
  </acceptance_criteria>
  <done>
    `auth/dependencies.py` retyped: three FastAPI deps return `Identity`, both `get_optional_user` and `get_current_user` consult the IdentityExtension between API-key and JWT paths (default impl returns None → existing JWT path runs unchanged in community edition), the two factories' inner closures are retyped, internal `User` import retained for SQL queries. JWT/API-key/OAuth/refresh-token flows behave identically. The 1999-test baseline holds.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Bearer token → IdentityExtension | A new code path runs on every authenticated request: `await get_identity_extension().resolve_identity_from_token(token, request, db)`. In community edition the extension is `DefaultIdentityExtension` whose `resolve_identity_from_token` returns None (no boundary crossed). When an enterprise overlay registers a custom backend, the overlay receives the bearer token (untrusted input) and must validate/decode it before returning an Identity. The seam is bearer-token-only (D-17); API keys do not cross this boundary. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-214-AB-01 | E (Elevation) — extension overrides JWT path | `get_optional_user` / `get_current_user` wire-in | mitigate | The extension is consulted ONLY when a bearer token is present (`if token is not None:` guard before the await). The default `DefaultIdentityExtension.resolve_identity_from_token` returns None, falling through to the existing JWT decode path — community-edition behavior is bit-identical to pre-Plan-02. Authorization checks downstream (`require_role`, `require_permission`) operate on whatever Identity the dep returned, structural subtyping preserves all access-control semantics (V4 ASVS unchanged per RESEARCH § Security Domain). |
| T-214-AB-02 | S (Spoofing) — extension returns spoofed identity | enterprise overlay implementation | accept | Out of scope for Phase 214. Phase 217's SAML overlay owns the token-validation contract (signed assertion, expiry, audience, replay protection per ROADMAP § Phase 217 SC#3). Phase 214 only provides the seam; the trust boundary moves to the installed package set (`pip install` boundary). RESEARCH § Security Domain row "Extension hijack" documents this. |
| T-214-AB-03 | I (Information disclosure) — bearer token leaked to extension | `await get_identity_extension().resolve_identity_from_token(token, ...)` | accept | The bearer token is already in scope of the request handler (it traversed `oauth2_scheme_optional` to get here). Passing it to a registered extension is the same trust level as the existing JWT decode call. The `request` parameter is also passed (for cookie/header introspection per CONTEXT.md "Claude's Discretion"); same trust boundary as any FastAPI middleware. |
| T-214-AB-04 | D (DoS) — extension hangs the request | enterprise overlay implementation | accept | The wire-in is `await ext.resolve_identity_from_token(...)` with no timeout. A misbehaving extension could hang every request. Phase 214 does NOT add a per-extension timeout — that's a Phase 217 concern (SAML SP must be fast or operationally monitored). The default impl returns synchronously-resolved None; community edition cannot hang. |
| T-214-AB-05 | T (Tampering) — refresh-token rotation regression | refresh-token endpoints | mitigate | Refresh-token endpoints (`auth/router.py:/refresh`) call `get_current_user` indirectly through the FastAPI dep tree. The extension wire-in runs on `/refresh` requests too. Default impl returns None → fall-through to JWT decode → existing refresh logic runs unchanged. VALIDATION row 214-02-06 explicitly verifies this with `pytest -k refresh`. |
| T-214-AB-06 | I (Information disclosure) — Identity Protocol leaks more than 6 fields | runtime objects returned by deps | accept | The runtime objects returned are concrete `User` instances. Endpoints annotated with `user: Identity = Depends(get_current_active_user)` could in principle access `user.password_hash` at runtime even though the Protocol declares only 6 fields. The defense is at the type-checking layer (pyright/IDE flags the access) AND at Plan 04's architecture-guard test (cross-domain code can't even import the concrete `User` class outside the allowlist, so the access is gone in practice). RESEARCH § Security Domain row "Information disclosure" documents this. |
| T-214-EH-03 | T (Tampering) — extension wire-in skipped for one of the deps | `get_optional_user` / `get_current_user` consistency | mitigate | Pitfall 9 — the wire-in is duplicated across both deps to preserve the expired-token UX. Acceptance criterion enforces `grep -c "await get_identity_extension().resolve_identity_from_token" == 2`. If a future contributor "deduplicates" by removing one occurrence, the test count gate catches it. The two wire-ins are kept structurally identical (same comment block, same code) so the duplication is obviously intentional. |
</threat_model>

<verification>
- IDENT-02 part (a) ("All cross-domain User import sites type against IdentityProtocol or an alias of it") — partially realized: this plan retypes the deps, Plan 03 sweeps the cross-domain callers. After this plan, the dep return types are `Identity` so any caller that types its parameter as `User` (and calls `Depends(get_optional_user)` etc.) gets a covariant assignment that ruff/pyright tolerates because `User` IS-A `Identity`. Plan 03 makes the parameter annotations match.
- IDENT-02 part (c) (existing JWT login flow operates unchanged) — verified by Task 02-01's `pytest -k "auth or jwt"` gate.
- IDENT-02 part (d) (API key path unchanged) — verified by `_resolve_api_key()` body being byte-identical (only the deps that CALL it are retyped) AND by `pytest -k api_key`.
- IDENT-02 part (e) (OAuth/OIDC unchanged) — verified by `pytest -k oauth`.
- IDENT-02 part (f) (refresh-token rotation unchanged) — verified by `pytest -k refresh` AND by T-214-AB-05 mitigation above.
- IDENT-03 (extension hook + typed accessor) — REALIZED: `get_identity_extension()` is consulted on every authenticated request; default impl returns None preserving JWT semantics; enterprise overlays can register an alternate backend without touching `auth/dependencies.py`. Phase 217 plugs in here.
- D-15 wire-in order (API key → extension → JWT decode → None) — verified by Edit 2 / Edit 3 placement.
- D-16 corrected per Pitfall 9 — `get_current_user()` does NOT delegate to `get_optional_user()`; instead the wire-in is duplicated. Acceptance criterion enforces `grep == 2`.
- D-17 (extension not consulted in API-key path) — verified by `_resolve_api_key()` body being unchanged AND by the wire-in being placed AFTER the API-key short-circuit (`if user is not None: return user`) in both deps.
- Pitfall 8 (async-method contract) — verified by Plan 01 Task 01-02 (Default returns coroutine that resolves to None) AND by the wire-in code using `await` correctly here.
- Pitfall 9 (duplication preserves expired-token UX) — verified by the JWT decode bodies in BOTH deps remaining intact, including the `jwt.ExpiredSignatureError` branch at lines 139-151 of `get_current_user` (which raises 401 with `WWW-Authenticate: Bearer error="invalid_token", error_description="The access token expired"`).
- ASVS V2 (Authentication) — covered: extension is opt-in, default-None preserves the existing JWT/API-key flow, no new authentication-bypass vector introduced.
- ROADMAP SC#4 (1965-test baseline stays green) — verified by Task 02-01's full pytest gate (≥1999 passing).
</verification>

<success_criteria>
- `backend/app/modules/auth/dependencies.py` is the only file modified by this plan; line count grows by ~16 lines (7-line wire-in × 2 + ~2 lines of new imports).
- The three FastAPI dependency functions return `Identity` (or `Identity | None`) per their signatures; structural subtyping at the call sites means existing endpoints that type `user: User = Depends(get_current_active_user)` continue to work without changes (Plan 03 will then update those annotations to `user: Identity` for consistency and to satisfy Plan 04's architecture guard).
- The IdentityExtension is consulted on every authenticated request via BOTH `get_optional_user` and `get_current_user`. The duplication is intentional (Pitfall 9) and grep-verifiable (`count == 2`).
- Default-impl behavior is bit-identical to pre-Plan-02: `await DefaultIdentityExtension().resolve_identity_from_token(...)` returns None, control falls through to the existing JWT decode path, the expired-token UX is preserved.
- Auth-affected test slice (`pytest -k "auth or jwt or api_key or login or refresh or oauth"`) passes; full pytest run (≥1999 passed) holds.
- Ruff lint and format pass.
- The reconciliation note from `<planning_context>` is honored on two points:
  (a) Pitfall 1 is respected — `audit/service.py:24` is NOT touched by this plan (Plan 03 will skip it; Plan 04 will allowlist it).
  (b) Pitfall 9 is respected — `get_current_user` does NOT delegate to `get_optional_user`; the wire-in is duplicated.
- Phase 214 ROADMAP SC#3 is realized on the consumer side: enterprise overlays can register an alternate identity backend through `geolens.extensions["identity"] = SAMLIdentityExtension()` and the dep chain will pick it up automatically without any further core changes.
</success_criteria>

<output>
After completion, create `.planning/phases/214-identity-protocol-extract/214-02-SUMMARY.md` documenting:
- Confirmation that ONE file was modified (`backend/app/modules/auth/dependencies.py`).
- The grep-verified gate values: `from app.core.identity import Identity` count=1, `get_identity_extension()` import count=1, `await get_identity_extension().resolve_identity_from_token` count=2, original `User` import retained (count=1).
- The exact line numbers of the wire-in insertions in both deps (for Plan 04's architecture-guard test review).
- Confirmation that `_resolve_api_key()` body is unchanged.
- Test results: extension tests pass, auth-affected slice passes, full pytest count.
- A note that Pitfall 9 was followed — wire-in duplicated rather than refactoring `get_current_user` to delegate.
- A note that Plan 03 will sweep the ~42 cross-domain caller files (parameter annotations `user: User` → `user: Identity` and import path `from app.modules.auth.models import User` → `from app.core.identity import Identity`).
- Pointer to Plan 03 as the next plan in the phase (Wave 3 — depends on this plan).
</output>
</content>
