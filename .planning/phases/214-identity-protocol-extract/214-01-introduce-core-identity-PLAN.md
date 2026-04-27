---
phase: 214-identity-protocol-extract
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/core/identity.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/platform/extensions/__init__.py
  - backend/app/platform/extensions/protocols.py
  - backend/tests/test_extensions.py
autonomous: true
requirements: [IDENT-01, IDENT-03]
requirements_addressed: [IDENT-01, IDENT-03]
tags: [refactor, protocol, extension, layering, open-core, identity]

must_haves:
  truths:
    - "D-01/D-03/D-04: `backend/app/core/identity.py` is a NEW file defining `RoleProtocol` (single attribute `name: str`), `IdentityProtocol` (6 attributes: `id: uuid.UUID`, `username: str`, `email: str | None`, `is_active: bool`, `roles: Sequence[RoleProtocol]`, `created_at: datetime`), `IdentityExtension` (one async method `resolve_identity_from_token(token, request, db) -> Identity | None`), and `Identity = IdentityProtocol` alias. All three Protocols are decorated `@runtime_checkable`."
    - "D-06: The concrete `User` ORM model at `backend/app/modules/auth/models.py` is NOT modified — no inheritance, no class-level conformance assertion, no TYPE_CHECKING annotation in `auth/models.py`. Structural subtyping handles conformance: `User.id: Mapped[uuid.UUID]`, `User.username: Mapped[str]`, `User.email: Mapped[str | None]`, `User.is_active: Mapped[bool]`, `User.created_at: Mapped[datetime]`, `User.roles: Mapped[list[Role]]` (and `Role.name: Mapped[str]`) already match the Protocol surface."
    - "D-12/D-14: `backend/app/platform/extensions/defaults.py` gains `DefaultIdentityExtension` whose `resolve_identity_from_token()` is `async def` (Pitfall 8 — MUST be async) and returns `None`. This is the community-edition fallback; existing JWT/API-key path runs unchanged when no enterprise overlay registers."
    - "D-13: `backend/app/platform/extensions/__init__.py` exposes a NEW typed accessor `get_identity_extension() -> IdentityExtension` mirroring the existing `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` accessors (these DO exist on main per planning_context reconciliation note — RESEARCH.md Pitfall 2 was based on an older branch). Accessor body: `_extensions.get('identity') or DefaultIdentityExtension()`, with `# type: ignore[return-value]` if the registered overlay branch is taken."
    - "Module docstring of `core/identity.py` follows the discipline of `platform/extensions/protocols.py` — explicitly states it uses only stdlib types (plus `fastapi.Request` and `sqlalchemy.ext.asyncio.AsyncSession` for the extension method signature) to avoid the `core -> modules.auth` import edge this milestone closes. References Phase 214 / IDENT-01..03 and notes Phase 217 as first concrete consumer."
    - "Reconciliation note (planning_context): RESEARCH.md § Pitfall 1 corrects CONTEXT.md `<canonical_refs>`'s classification of `audit/service.py:24` — that import is a function-scope SQL-filter use (`select(User.id).where(User.username.ilike(pattern))`), not a TYPE_CHECKING annotation. It MUST stay concrete and join the allowlist in Plan 04. This plan does NOT migrate it (Plan 03 caller-migration sweep skips it; Plan 04 architecture-guard test allowlist excludes it via `:!backend/app/modules/audit/service.py`)."
    - "Reconciliation note (planning_context): RESEARCH.md § Pitfall 2 said the typed accessors didn't exist; on the current `main` branch they DO exist at `backend/app/platform/extensions/__init__.py:82,90,98`. CONTEXT.md is correct; planner mirrors them verbatim."
    - "After this plan: zero behavior change. No caller imports the new file yet (Plan 03 does that); `get_identity_extension()` is callable but unwired (Plan 02 wires it). Full pytest baseline (≥1999 passing) holds because nothing in production code calls the new symbols yet."
  artifacts:
    - path: "backend/app/core/identity.py"
      provides: "Cross-domain identity contract: RoleProtocol, IdentityProtocol, IdentityExtension, Identity alias"
      contains: "class IdentityProtocol(Protocol)"
      min_lines: 50
    - path: "backend/app/platform/extensions/defaults.py"
      provides: "Extended with DefaultIdentityExtension (community fallback returning None)"
      contains: "class DefaultIdentityExtension"
      min_lines: 25
    - path: "backend/app/platform/extensions/__init__.py"
      provides: "Extended with get_identity_extension() typed accessor"
      contains: "def get_identity_extension"
      min_lines: 110
    - path: "backend/tests/test_extensions.py"
      provides: "Extended with test coverage for get_identity_extension() default + registered paths"
      contains: "test_get_identity_extension_returns_default_when_unregistered"
      min_lines: 200
  key_links:
    - from: "backend/app/platform/extensions/__init__.py"
      to: "backend/app/platform/extensions/defaults.py:DefaultIdentityExtension"
      via: "typed accessor fallback (mirrors get_branding_extension pattern)"
      pattern: "DefaultIdentityExtension"
    - from: "backend/app/platform/extensions/__init__.py"
      to: "backend/app/core/identity.py:IdentityExtension"
      via: "import for return-type annotation"
      pattern: "from app.core.identity import IdentityExtension"
---

<objective>
Introduce the cross-domain identity contract as pure-additive code: create `backend/app/core/identity.py` (NEW file) with four exports — `RoleProtocol`, `IdentityProtocol`, `IdentityExtension`, and the `Identity` alias — extend `backend/app/platform/extensions/defaults.py` with `DefaultIdentityExtension`, and extend `backend/app/platform/extensions/__init__.py` with a `get_identity_extension()` typed accessor that mirrors the existing `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` accessors. Add unit-test coverage to `backend/tests/test_extensions.py` that verifies the default-fallback and registered-overlay paths.

Purpose: Realize ROADMAP SC#1 (`core/identity.py` defines `IdentityProtocol` capturing the surface 51 cross-domain call sites depend on) and SC#3 (extension system exposes a registration hook mirroring `get_branding_extension()` / `get_audit_extension()`) as pure-additive scaffolding. After this plan lands, the new file/symbols exist and are importable, but NO production caller imports them yet — Plan 02 retypes the FastAPI dep chain (consumer #1) and Plan 03 migrates ~42 cross-domain caller import + annotation sites. Splitting "create the contract" from "wire/migrate consumers" mirrors Phase 213's Plan 01 discipline — the diff is small, verifiable in isolation, and can ship even if Plans 02/03 stall.

Output: Three modified files (`core/identity.py` NEW, `platform/extensions/defaults.py` extended, `platform/extensions/__init__.py` extended) plus extended test coverage (`tests/test_extensions.py`). The `User` ORM at `auth/models.py` is untouched (D-06). Full pytest suite stays at the ≥1999-passing baseline because no consumer wires the new symbols yet.
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
@.planning/phases/213-catalog-authz-relocate/213-01-SUMMARY.md
@.planning/phases/212-core-settings-decouple/212-01-introduce-core-db-models-PLAN.md
@backend/app/modules/auth/models.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/defaults.py
@backend/app/platform/extensions/protocols.py
@backend/tests/test_extensions.py

<interfaces>
<!-- The exact code Plan 01 must produce. RESEARCH.md "Code Examples" lines 786-895 are the source of truth. Reproduced here so the executor does not need to chase external references. -->

#### File 1 — NEW: `backend/app/core/identity.py` (~50 lines)

```python
"""Cross-domain identity contract.

Defines structural Protocols that downstream code uses to type a request's
authenticated user without importing the concrete SQLAlchemy ORM. The
concrete ``app.modules.auth.models.User`` satisfies ``IdentityProtocol``
implicitly (structural subtyping / PEP 544); no inheritance is required.

Uses only stdlib types (plus ``fastapi.Request`` and SQLAlchemy's
``AsyncSession`` for the extension method signature) to avoid the
``core -> modules.auth`` import edge this milestone (Phase 214,
IDENT-01..03) is closing. ``Request`` and ``AsyncSession`` are
infrastructure types that do NOT live under ``app.modules.*`` so they
do not violate the layering rule.

Phase 217 (auth-saml-enterprise) is the first concrete consumer of
``IdentityExtension``: a SAML overlay registers an alternate backend
under the ``geolens.extensions`` entry-point group with key ``"identity"``
and ``get_identity_extension()`` returns it on subsequent requests.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class RoleProtocol(Protocol):
    """Slim role contract — ``name`` is the only attribute cross-domain code reads.

    Mirrors the discipline of ``platform/extensions/protocols.py``:
    typing ``IdentityProtocol.roles`` against this Protocol (instead of the
    concrete ``app.modules.auth.models.Role`` ORM class) keeps ``core/``
    free of the ``core -> modules.auth`` edge. The concrete ``Role`` ORM
    satisfies this Protocol structurally (``Role.name: Mapped[str]``).
    """

    name: str


@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface read by ~42 cross-domain call sites.

    The 6-field surface (D-01) covers every read of the concrete ``User``
    ORM made outside the ``auth/`` and ``admin/`` modules: ``id`` and
    ``email`` (audit + admin views), ``username`` (admin/router.py:52,
    audit/router.py:72,153,189, catalog/maps/router.py:252,
    catalog/datasets/api/router.py:450, catalog/sources/provenance.py:54,77),
    ``is_active`` (the ``get_current_active_user`` gate), ``roles`` (RBAC
    matrix), and ``created_at`` (admin/router.py:57). Sensitive fields
    (``password_hash``, ``auth_provider``, ``last_login_at``, ``status``)
    are deliberately NOT exposed — admin endpoints that read them keep
    importing the concrete ``User`` (allowlisted in the Phase 214
    architecture guard).
    """

    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime


# Shorter alias for caller annotations (Phase 214 D-05).
# Both names are exported; ``Identity`` reads cleaner in parameter
# annotations (matches the existing project convention of one-word type
# names) and ``IdentityProtocol`` is preferred in conformance assertions
# / runtime ``isinstance`` checks.
Identity = IdentityProtocol


@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends.

    The default community implementation (``DefaultIdentityExtension`` at
    ``platform/extensions/defaults.py``) returns ``None``, signalling
    "I don't recognize this token; fall through to the existing JWT path."
    Phase 217's SAML overlay implements this method to validate a SAML
    session token, run JIT provisioning through the existing
    ``find_or_create_oauth_user()`` pathway (per ROADMAP Phase 217 SC#3),
    and return an ``Identity``. The async signature is mandatory
    (Pitfall 8) — Phase 217 will perform DB lookups; ``await`` is required
    in the wire-in.
    """

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
```

#### File 2 — EXTEND: `backend/app/platform/extensions/defaults.py` (current 24 lines, becomes ~30)

Add the following class to the END of the file (preserve existing classes verbatim):

```python
class DefaultIdentityExtension:
    """Default identity: no alternate backend registered.

    Returning None from ``resolve_identity_from_token`` signals the
    auth dep chain to fall through to the existing JWT/API-key path.
    The async signature is intentional (Pitfall 8): Phase 217's
    SAML overlay will perform async DB lookups; the dep wire-in
    awaits this method, so all implementations — community and
    enterprise — MUST be async.
    """

    async def resolve_identity_from_token(
        self, token: str, request, db
    ):  # type: ignore[no-untyped-def]
        return None
```

The `# type: ignore[no-untyped-def]` is intentional and matches the existing default-extension style (the other Default* classes use bare types without imports too — they are kept dependency-free by design). The full type annotations live on the Protocol in `core/identity.py`; the Default impl just has to be a structural match.

#### File 3 — EXTEND: `backend/app/platform/extensions/__init__.py` (current 104 lines, becomes ~115)

ADD the new import next to the other DefaultExtension imports (line 14-18 block):

```python
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,  # NEW
)
```

ADD the new typed-accessor at the END of the file (after line 103, after `get_auth_extension()`), mirroring the existing trio verbatim. The return-type annotation imports `IdentityExtension` from `core/identity.py`:

```python
def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension or the community default.

    Phase 214 / IDENT-03 — mirrors ``get_branding_extension()``,
    ``get_audit_extension()``, ``get_auth_extension()`` exactly. Enterprise
    overlays register an implementation under the ``"identity"`` key via
    the ``geolens.extensions`` entry-point group; community edition gets
    the no-op ``DefaultIdentityExtension`` whose
    ``resolve_identity_from_token`` returns ``None`` (existing JWT
    path runs unchanged).
    """
    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]
```

The return-type is forward-referenced as a string `"IdentityExtension"` to avoid a runtime import cycle (the file already does this style for forward references where convenient). Add a TYPE_CHECKING-guarded import at the top of the file:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.identity import IdentityExtension
```

Place the TYPE_CHECKING block just after `from importlib.metadata import entry_points` (around line 10), after `import structlog` (line 12). Order:

```python
from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

import structlog

from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)
from app.platform.extensions.protocols import (
    AuditExtension,
    AuthExtension,
    BrandingExtension,
)

if TYPE_CHECKING:
    from app.core.identity import IdentityExtension
```

This avoids a `core -> platform.extensions` runtime import edge while letting pyright/IDE consumers see the right return type.

#### File 4 — EXTEND: `backend/tests/test_extensions.py` (current 199 lines, becomes ~250)

Add a new TestClass section at the END of the file:

```python
class TestGetIdentityExtension:
    """Tests for the get_identity_extension() typed accessor (Phase 214 D-13)."""

    def test_get_identity_extension_returns_default_when_unregistered(self):
        """No enterprise overlay registered -> returns DefaultIdentityExtension."""
        from app.platform.extensions import get_identity_extension
        from app.platform.extensions.defaults import DefaultIdentityExtension

        ext = get_identity_extension()

        assert isinstance(ext, DefaultIdentityExtension)

    def test_get_identity_extension_returns_registered_when_present(self):
        """An overlay registered under 'identity' is returned by the accessor."""
        from app.platform.extensions import _extensions, get_identity_extension

        sentinel = object()
        _extensions["identity"] = sentinel

        ext = get_identity_extension()

        assert ext is sentinel

    @pytest.mark.asyncio
    async def test_default_identity_extension_resolve_returns_none(self):
        """DefaultIdentityExtension.resolve_identity_from_token returns None for any input."""
        from app.platform.extensions.defaults import DefaultIdentityExtension

        ext = DefaultIdentityExtension()
        result = await ext.resolve_identity_from_token("any-token", None, None)
        assert result is None
```

The third test enforces the async-method contract (Pitfall 8): calling `await ext.resolve_identity_from_token(...)` must work with both `None` request/db (community-edition default doesn't dereference them).

If the test file does not currently use `pytest.mark.asyncio`, check the existing convention — `pyproject.toml` has `asyncio_mode = "strict"` per VALIDATION.md, so the marker is required. If the existing tests in `test_extensions.py` use a different style, match that; the third test is optional if it conflicts with existing fixture setup. The first two tests are non-negotiable.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 01-01: Create core/identity.py with the four Protocol exports</name>
  <files>backend/app/core/identity.py</files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-01..D-06; allowlist; "Module docstring wording" discretion)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 786-850 — complete `core/identity.py` reference; lines 297-350 — Pattern 1 attribute Protocol structure; lines 693-702 — Pitfall 3 `Sequence[RoleProtocol]` variance discussion)
    - backend/app/modules/auth/models.py (full file — verify the User ORM exposes the 6-field surface with matching types: `id: Mapped[uuid.UUID]`, `username: Mapped[str]`, `email: Mapped[str | None]`, `is_active: Mapped[bool]`, `roles: Mapped[list[Role]]`, `created_at: Mapped[datetime]`. Verify `Role.name: Mapped[str]`.)
    - backend/app/platform/extensions/protocols.py (29 lines — read end-to-end for the "stdlib-types-only" docstring discipline; replicate the same docstring pattern in `core/identity.py`)
    - backend/app/core/config.py (or any other existing `core/` file) (confirm the project uses `from __future__ import annotations` at the top — `core/identity.py` follows the same convention)
  </read_first>
  <action>
Create the new file at `backend/app/core/identity.py` with the EXACT content shown in `<interfaces>` File 1 above (~50 lines). Hard requirements:

- File path: `backend/app/core/identity.py` (NOT `backend/app/core/identity/__init__.py`, NOT `backend/app/identity.py`).
- The first non-docstring line MUST be `from __future__ import annotations` per the project convention.
- The three Protocols (`RoleProtocol`, `IdentityProtocol`, `IdentityExtension`) MUST each be decorated with `@runtime_checkable` (D-04). The decorator import comes from `typing` (`from typing import Protocol, Sequence, runtime_checkable`).
- `IdentityProtocol.roles` MUST be typed as `Sequence[RoleProtocol]` (NOT `list[Role]`, NOT `list[RoleProtocol]`, NOT `Sequence[Role]`). Per RESEARCH.md Pitfall 3, `Sequence` is covariant and `list[Role]` IS-A `Sequence[RoleProtocol]` provided `Role` IS-A `RoleProtocol` (which it does — `Role.name: Mapped[str]` satisfies `RoleProtocol.name: str`).
- `IdentityProtocol` exposes EXACTLY 6 attributes in this order: `id: uuid.UUID`, `username: str`, `email: str | None`, `is_active: bool`, `roles: Sequence[RoleProtocol]`, `created_at: datetime`. Do NOT add `is_admin` (D-02 — rejected; admins compute the predicate from `roles`). Do NOT add `tenant_id` (deferred to backlog 999.6). Do NOT add `password_hash`, `auth_provider`, `last_login_at`, `status`, `updated_at` (deliberately excluded — `User` admin/auth-internal callers keep importing concrete `User` per allowlist).
- `Identity = IdentityProtocol` is a top-level type alias on its own line. Both names are publicly importable; the alias is the preferred caller-side name (D-05).
- `IdentityExtension.resolve_identity_from_token` MUST be `async def` (D-12 + Pitfall 8). Signature: `async def resolve_identity_from_token(self, token: str, request: Request, db: AsyncSession) -> Identity | None: ...` — note the `: ...` body for the Protocol declaration.
- The `Request` parameter on the extension method MUST be retained per CONTEXT.md "Claude's Discretion" default (SAML overlay's likely needs include cookies and header introspection).
- Module docstring follows the discipline of `platform/extensions/protocols.py`: explicitly notes the stdlib-types-only rule, names the Phase (214) and the requirements it closes (IDENT-01..03), and references Phase 217 as the first concrete consumer. Use the docstring shown in `<interfaces>` verbatim.

Imports section (top-of-file, in this order):
```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
```

Do NOT import anything from `app.modules.*` — that would re-create the `core -> modules.auth` edge this milestone closes (and the Phase 214 Plan 04 architecture-guard test would fail). Do NOT import `app.modules.auth.models.Role` or `app.modules.auth.models.User`. The file is in `backend/app/core/` so it sits one layer below all `app.modules.*` packages.

After writing, verify:
1. `cd backend && python -c "from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity; print('ok')"` prints `ok` and exits 0.
2. `cd backend && python -c "from app.modules.auth.models import User, Role; from app.core.identity import IdentityProtocol, RoleProtocol; print(isinstance(User, type), isinstance(Role, type))"` returns `True True` (the ORM classes import cleanly alongside the Protocols).
3. `cd backend && uv run ruff check app/core/identity.py` exits 0.
4. `cd backend && uv run ruff format --check app/core/identity.py` exits 0.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -c "from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity; assert IdentityProtocol is Identity; print('ok')" && uv run ruff check app/core/identity.py && uv run ruff format --check app/core/identity.py</automated>
  </verify>
  <acceptance_criteria>
    - File exists at `backend/app/core/identity.py` (verify with `test -f backend/app/core/identity.py`).
    - File contains `from __future__ import annotations` (verify with `head -3 backend/app/core/identity.py | grep -q "from __future__ import annotations"`).
    - File exports four symbols importable in this exact form: `from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity`. Python execution of this import must exit 0.
    - `Identity is IdentityProtocol` evaluates to `True` (the alias is identity-equal, not a copy).
    - All three Protocol classes are decorated with `@runtime_checkable` (verify with `grep -c "^@runtime_checkable" backend/app/core/identity.py` — must equal 3).
    - `IdentityProtocol` declares EXACTLY 6 attributes in this order: `id`, `username`, `email`, `is_active`, `roles`, `created_at` (verify with `grep -c "^\s*\(id\|username\|email\|is_active\|roles\|created_at\):" backend/app/core/identity.py | grep -E '^[6-9]$|^1[0-9]$'` — must be ≥6).
    - `IdentityProtocol.roles` is annotated as `Sequence[RoleProtocol]` (verify with `grep "roles:" backend/app/core/identity.py | grep -q "Sequence\[RoleProtocol\]"`).
    - `IdentityExtension.resolve_identity_from_token` is `async def` (verify with `grep -A1 "class IdentityExtension" backend/app/core/identity.py | grep -q "async def"` OR grep for `async def resolve_identity_from_token` directly in the file).
    - File does NOT import from `app.modules.*` (verify with `grep -E "from app\.modules\." backend/app/core/identity.py | wc -l` must equal 0).
    - File contains EXACTLY one of `is_admin` references (verify with `grep -c "is_admin" backend/app/core/identity.py | grep -q "^0$"` — must be 0; D-02 rejection).
    - Ruff lint and format both pass on the new file.
  </acceptance_criteria>
  <done>
    `backend/app/core/identity.py` exists with the four Protocol exports, decorated `@runtime_checkable`, importable cleanly, ruff-clean, and contains no `app.modules.*` imports. The file is dormant — no production caller imports it yet.
  </done>
</task>

<task type="auto">
  <name>Task 01-02: Add DefaultIdentityExtension to extensions/defaults.py + register typed accessor in extensions/__init__.py</name>
  <files>
    backend/app/platform/extensions/defaults.py
    backend/app/platform/extensions/__init__.py
    backend/app/platform/extensions/protocols.py
  </files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-12, D-13, D-14, D-17 — extension hook decisions)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 370-432 — Pattern 2 Default extension community fallback, Pattern 3 typed-accessor for extension registry; lines 752-761 — Pitfall 8 async vs sync extension method consistency; lines 850-895 — full reference for the additions)
    - backend/app/platform/extensions/__init__.py (current 104-line file — read end-to-end; the new accessor mirrors `get_branding_extension` / `get_audit_extension` / `get_auth_extension` lines 82-103 verbatim)
    - backend/app/platform/extensions/defaults.py (current 24-line file — read end-to-end; new class follows the same minimalist style)
    - backend/app/platform/extensions/protocols.py (current 29-line file — read end-to-end; the existing AuthExtension Protocol confirms the @runtime_checkable + Protocol pattern that core/identity.py mirrors)
    - backend/app/core/identity.py (the new file from Task 01-01 — verify it imports cleanly so the typed accessor's TYPE_CHECKING return-type annotation resolves)
  </read_first>
  <action>
Make THREE additive changes to existing files. None of the changes alters or removes existing behavior; they only add new symbols.

**Change 1 — `backend/app/platform/extensions/defaults.py`:**

The file currently has 24 lines defining three sync Default classes (`DefaultBrandingExtension`, `DefaultAuditExtension`, `DefaultAuthExtension`). APPEND the following class at the END of the file (after `DefaultAuthExtension`, on a new line):

```python


class DefaultIdentityExtension:
    """Default identity: no alternate backend registered (Phase 214 D-14).

    Returning None from ``resolve_identity_from_token`` signals the auth
    dep chain (``get_optional_user`` / ``get_current_user``, retyped in
    Plan 02) to fall through to the existing JWT decode + DB lookup path.
    Community edition behavior is exactly today's behavior — one async
    method call returning None per request.

    The async signature is intentional (Pitfall 8). Phase 217's SAML
    overlay will perform DB lookups; the dep wire-in does
    ``await ext.resolve_identity_from_token(token, request, db)``, so
    all implementations — community and enterprise — MUST be async.
    """

    async def resolve_identity_from_token(
        self, token, request, db
    ):  # type: ignore[no-untyped-def]
        return None
```

The `# type: ignore[no-untyped-def]` matches the dependency-free style of the surrounding Default classes (no imports of `Request`, `AsyncSession`, or `Identity` are added — the structural match against `IdentityExtension` is established at the use site, not declared here). Use a single trailing newline at end of file (POSIX convention).

**Change 2 — `backend/app/platform/extensions/__init__.py`:**

Two surgical additions; no removals.

(a) Update the import block (lines 14-18) to include `DefaultIdentityExtension`. The block currently reads:

```python
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuthExtension,
    DefaultBrandingExtension,
)
```

Change it to (alphabetical order preserved):

```python
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)
```

(b) Add a TYPE_CHECKING-guarded import for `IdentityExtension`. The `IdentityExtension` Protocol lives in `core/identity.py` (Plan 01-01); a runtime import would create the `platform.extensions -> core` edge (which is allowed — core is a lower layer than platform), so we COULD do a runtime import. However, to keep `platform/extensions/__init__.py` minimally coupled to `core` and to match the typing-only-import convention used elsewhere in the codebase, use a `TYPE_CHECKING` block.

Add `from typing import TYPE_CHECKING` to the imports block (near `from importlib.metadata import entry_points`):

```python
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

import structlog
```

Then add the TYPE_CHECKING block AFTER the existing `from app.platform.extensions.protocols import (...)` block (around line 23):

```python
if TYPE_CHECKING:
    from app.core.identity import IdentityExtension
```

(c) APPEND the new typed accessor at the END of the file (after `get_auth_extension` at line 98-103). It mirrors the existing trio verbatim:

```python


def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension or the community default.

    Phase 214 / IDENT-03 — mirrors ``get_branding_extension()``,
    ``get_audit_extension()``, and ``get_auth_extension()`` exactly.
    Enterprise overlays register an implementation under the ``"identity"``
    key via the ``geolens.extensions`` entry-point group; community
    edition gets the no-op ``DefaultIdentityExtension`` whose
    ``resolve_identity_from_token`` returns ``None`` (existing JWT
    path runs unchanged).
    """
    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]
```

The return-type is forward-referenced as a string `"IdentityExtension"` because the `from app.core.identity import IdentityExtension` line is TYPE_CHECKING-guarded (no runtime import). The `# type: ignore[return-value]` on the second `return` matches the existing trio's style (lines 87, 95, 103).

Single trailing newline at end of file.

**Change 3 — `backend/app/platform/extensions/protocols.py`:**

NO CHANGES to this file. Per CONTEXT.md `<canonical_refs>` ("Code (extension scaffold to extend)"): "**Not modified** by Phase 214 — `IdentityExtension` lives in `core/identity.py` per D-12 (different layer; it returns `Identity` which lives in core, and putting the Protocol in core keeps the related types co-located)." Verify the file is unmodified after the plan: `git diff backend/app/platform/extensions/protocols.py` produces zero output.

After all three changes, verify:
1. `cd backend && python -c "from app.platform.extensions import get_identity_extension; ext = get_identity_extension(); from app.platform.extensions.defaults import DefaultIdentityExtension; assert isinstance(ext, DefaultIdentityExtension); print('ok')"` exits 0 with `ok`.
2. `cd backend && python -c "import asyncio; from app.platform.extensions.defaults import DefaultIdentityExtension; result = asyncio.run(DefaultIdentityExtension().resolve_identity_from_token('t', None, None)); assert result is None; print('ok')"` exits 0 with `ok` (Pitfall 8 — async-method contract enforced).
3. `cd backend && uv run ruff check app/platform/extensions/` exits 0.
4. `cd backend && uv run ruff format --check app/platform/extensions/` exits 0.
5. `cd backend && uv run pytest tests/test_extensions.py -v --tb=short` — all existing tests still pass (regression check; we have not yet ADDED the new tests — Task 01-03 does that).
6. `git diff backend/app/platform/extensions/protocols.py` produces zero output (no inadvertent edit).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -c "from app.platform.extensions import get_identity_extension; from app.platform.extensions.defaults import DefaultIdentityExtension; ext = get_identity_extension(); assert isinstance(ext, DefaultIdentityExtension); print('ok')" && python -c "import asyncio; from app.platform.extensions.defaults import DefaultIdentityExtension; result = asyncio.run(DefaultIdentityExtension().resolve_identity_from_token('t', None, None)); assert result is None; print('ok')" && uv run ruff check app/platform/extensions/ && uv run ruff format --check app/platform/extensions/ && uv run pytest tests/test_extensions.py -v --tb=short</automated>
  </verify>
  <acceptance_criteria>
    - `backend/app/platform/extensions/defaults.py` contains `class DefaultIdentityExtension` (verify with `grep -c "^class DefaultIdentityExtension" backend/app/platform/extensions/defaults.py` must equal 1).
    - `DefaultIdentityExtension.resolve_identity_from_token` is `async def` (verify with `grep -A1 "class DefaultIdentityExtension" backend/app/platform/extensions/defaults.py | grep -q "async def" || grep "async def resolve_identity_from_token" backend/app/platform/extensions/defaults.py | grep -q "async"`).
    - `backend/app/platform/extensions/__init__.py` imports `DefaultIdentityExtension` from defaults (verify with `grep -q "DefaultIdentityExtension" backend/app/platform/extensions/__init__.py`).
    - `backend/app/platform/extensions/__init__.py` defines `get_identity_extension` function (verify with `grep -c "^def get_identity_extension" backend/app/platform/extensions/__init__.py` must equal 1).
    - `get_identity_extension()` body uses `_extensions.get("identity")` and falls back to `DefaultIdentityExtension()` (verify with `grep -A5 "def get_identity_extension" backend/app/platform/extensions/__init__.py | grep -q '_extensions.get("identity")' && grep -A8 "def get_identity_extension" backend/app/platform/extensions/__init__.py | grep -q "DefaultIdentityExtension()"`).
    - `backend/app/platform/extensions/__init__.py` has a `TYPE_CHECKING` block importing `IdentityExtension` (verify with `grep -B1 "from app.core.identity import IdentityExtension" backend/app/platform/extensions/__init__.py | grep -q "TYPE_CHECKING"`).
    - `backend/app/platform/extensions/protocols.py` is UNCHANGED from main (verify with `git diff backend/app/platform/extensions/protocols.py | wc -l` must equal 0).
    - Python smoke import `from app.platform.extensions import get_identity_extension; isinstance(get_identity_extension(), DefaultIdentityExtension)` returns `True`.
    - `await DefaultIdentityExtension().resolve_identity_from_token('t', None, None)` returns `None` (Pitfall 8 verified — calling `await` on the method does not raise `TypeError`).
    - Ruff lint and format both pass on `app/platform/extensions/`.
    - Existing `tests/test_extensions.py` test suite passes unchanged (regression check).
  </acceptance_criteria>
  <done>
    `DefaultIdentityExtension` exists in defaults.py with an async `resolve_identity_from_token` returning None; `get_identity_extension()` typed accessor exists in `__init__.py` mirroring the existing trio; `protocols.py` is untouched. The default-fallback path works end-to-end.
  </done>
</task>

<task type="auto">
  <name>Task 01-03: Add unit-test coverage for get_identity_extension() default + registered paths</name>
  <files>backend/tests/test_extensions.py</files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-VALIDATION.md (Per-Task Verification Map row 214-01-02 — names the test `test_get_identity_extension_returns_default_when_unregistered`; Wave 0 Requirements list)
    - backend/tests/test_extensions.py (full 199-line file — read end-to-end to match the existing fixture and test-class structure; the new TestClass goes at END of file)
    - backend/pyproject.toml (verify pytest config — `asyncio_mode = "strict"` per VALIDATION.md; the third test uses `@pytest.mark.asyncio` if the existing tests use that decorator)
    - backend/app/platform/extensions/__init__.py (verify the new `get_identity_extension` is importable and behaves as expected)
    - backend/app/platform/extensions/defaults.py (verify `DefaultIdentityExtension` is importable)
  </read_first>
  <action>
APPEND a new test class to the END of `backend/tests/test_extensions.py`. Use the existing file's import/fixture conventions (the autouse `_clean_registry` fixture at the top of the file resets `_extensions` between tests — the new class does NOT need its own teardown; it inherits the autouse fixture).

Read the existing file first to confirm whether async tests use `@pytest.mark.asyncio` or rely on `anyio` (per VALIDATION.md `asyncio_mode = "strict"`, the marker is required). Match the existing convention.

If `@pytest.mark.asyncio` is the convention, add this class at end of file:

```python


class TestGetIdentityExtension:
    """Tests for the get_identity_extension() typed accessor (Phase 214 D-13)."""

    def test_get_identity_extension_returns_default_when_unregistered(self):
        """No enterprise overlay registered -> returns DefaultIdentityExtension."""
        from app.platform.extensions import get_identity_extension
        from app.platform.extensions.defaults import DefaultIdentityExtension

        ext = get_identity_extension()

        assert isinstance(ext, DefaultIdentityExtension)

    def test_get_identity_extension_returns_registered_when_present(self):
        """An overlay registered under 'identity' is returned by the accessor."""
        from app.platform.extensions import _extensions, get_identity_extension

        sentinel = object()
        _extensions["identity"] = sentinel

        ext = get_identity_extension()

        assert ext is sentinel

    @pytest.mark.asyncio
    async def test_default_identity_extension_resolve_returns_none(self):
        """DefaultIdentityExtension.resolve_identity_from_token returns None for any input.

        Enforces Pitfall 8: the method MUST be async — calling `await` on it
        must not raise TypeError. Phase 217's SAML overlay relies on this
        contract for its DB-lookup wire-in.
        """
        from app.platform.extensions.defaults import DefaultIdentityExtension

        ext = DefaultIdentityExtension()
        result = await ext.resolve_identity_from_token("any-token", None, None)

        assert result is None
```

If the existing convention is different (e.g., `pytest-asyncio` with implicit `auto` mode and no marker), match it for the third test. The first two tests are sync and unconditional — they go in regardless.

The `_clean_registry` autouse fixture (defined at module scope per the existing file lines 18-22) resets `_extensions.clear()` and `_loaded = False` before AND after each test. Test 2 mutates `_extensions["identity"] = sentinel`; the autouse teardown undoes this for the next test. Do NOT add a new teardown — rely on the existing one.

After writing:
1. `cd backend && uv run pytest tests/test_extensions.py::TestGetIdentityExtension -v --tb=short` — all three new tests pass.
2. `cd backend && uv run pytest tests/test_extensions.py -v --tb=short` — the FULL file passes (no regression in existing tests; the autouse fixture isolates state between TestClass instances).
3. `cd backend && uv run ruff check tests/test_extensions.py` exits 0.
4. `cd backend && uv run ruff format --check tests/test_extensions.py` exits 0.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_extensions.py::TestGetIdentityExtension -v --tb=short && uv run pytest tests/test_extensions.py -v --tb=short && uv run ruff check tests/test_extensions.py && uv run ruff format --check tests/test_extensions.py</automated>
  </verify>
  <acceptance_criteria>
    - `tests/test_extensions.py` contains a new class `TestGetIdentityExtension` (verify with `grep -c "^class TestGetIdentityExtension" backend/tests/test_extensions.py` must equal 1).
    - The class contains `test_get_identity_extension_returns_default_when_unregistered` (verify with `grep -q "def test_get_identity_extension_returns_default_when_unregistered" backend/tests/test_extensions.py`). VALIDATION.md row 214-01-02 names this exactly.
    - The class contains `test_get_identity_extension_returns_registered_when_present` (verify with `grep -q "def test_get_identity_extension_returns_registered_when_present" backend/tests/test_extensions.py`).
    - The class contains `test_default_identity_extension_resolve_returns_none` (verify with `grep -q "def test_default_identity_extension_resolve_returns_none" backend/tests/test_extensions.py`).
    - Running just `pytest tests/test_extensions.py::TestGetIdentityExtension -v` exits 0 with 3 passed.
    - Running the full `tests/test_extensions.py` exits 0 with no regression in existing test count.
    - Ruff lint and format both pass on the file.
  </acceptance_criteria>
  <done>
    Three new tests exist and pass: default fallback, registered overlay, async-method contract. The existing test corpus is untouched. Phase 214 Plan 01's three additions are now backed by automated unit-test coverage.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none introduced this plan) | This plan adds Protocols + a default Extension + a typed accessor. No request enters production code through these symbols yet (Plan 02 wires them); no new trust boundary is crossed. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-214-IL-01 | I (Information disclosure) — Protocol attribute leak | `core/identity.py:IdentityProtocol` | mitigate | The Protocol exposes EXACTLY 6 fields (id, username, email, is_active, roles, created_at). Sensitive fields (`password_hash`, `auth_provider`, `last_login_at`, `status`) are deliberately NOT on the Protocol surface. Cross-domain code annotated against `Identity` cannot access these even if the runtime object is a concrete `User` — pyright/IDE flags the access at lint time, and Plan 04's architecture-guard test prevents reintroduction of `User` imports outside the allowlist. |
| T-214-EH-01 | S (Spoofing) — async-method contract violation | `DefaultIdentityExtension.resolve_identity_from_token` | mitigate | Pitfall 8 — the method MUST be async. Task 01-03's third test (`test_default_identity_extension_resolve_returns_none`) calls `await` on the default impl; if a future contributor accidentally drops the `async` keyword, the test fails immediately with `TypeError: object NoneType can't be used in 'await' expression`. Plan 02's wire-in code does `await ext.resolve_identity_from_token(...)` so a sync impl would also fail at runtime on the first request. |
| T-214-EH-02 | E (Elevation of privilege) — extension hijack | `geolens.extensions` entry-point group | accept | The entry-point group is loaded from installed Python packages at startup. Untrusted packages must not be installed in production — same trust boundary as `pip install`. The community edition's `DefaultIdentityExtension` returns None (never a spoofed identity). Phase 217 owns the SAML overlay's signature-verification and assertion-validation logic; Phase 214 only provides the seam. |
| T-214-IL-02 | T (Tampering) — Protocol surface drift | `core/identity.py` over time | mitigate | The 6-field surface is locked by D-01. Future phases that need additional fields (e.g., `tenant_id` for backlog 999.6) must add them explicitly through a documented Protocol-extension exercise. Plan 04's architecture-guard tests do not check the Protocol field count, but the full pytest run + Plan 02's dep retype catch any surface mismatch at type-check / runtime. |
</threat_model>

<verification>
- IDENT-01 (`core/identity.py` defines `IdentityProtocol` capturing the 6-field surface) verified by Task 01-01's automated import + the 6-attribute count gate in `<acceptance_criteria>`.
- IDENT-03 (extension system exposes a registration hook mirroring `get_branding_extension()` / `get_audit_extension()`) verified by Task 01-02's automated import + Task 01-03's test that asserts `get_identity_extension()` returns `DefaultIdentityExtension` when nothing is registered AND the registered-overlay path returns the registered object.
- D-04 (`@runtime_checkable` on all three Protocols) verified by Task 01-01's grep gate (`grep -c "^@runtime_checkable" backend/app/core/identity.py` must equal 3).
- D-06 (`User` ORM unmodified) verified by `git diff backend/app/modules/auth/models.py` producing zero output across the plan's commit (Task 01-01 enforces this via `<read_first>` only — no Edit on `auth/models.py`).
- Pitfall 8 (async-method contract) verified by Task 01-02's runtime smoke (`asyncio.run(DefaultIdentityExtension().resolve_identity_from_token(...))`) AND Task 01-03's `pytest.mark.asyncio` test.
- The 1999-test backend baseline holds because no production caller imports any of the new symbols yet — Task 01-03 ADDS three new passing tests, raising the count to ≥2002 (1999 + 3 new tests). Plans 02-04 will exercise the new symbols in production paths.
- D-13 typed-accessor pattern matches the existing trio (`get_branding_extension`, `get_audit_extension`, `get_auth_extension`) verbatim — verified by reading the existing accessors in `<read_first>` for Task 01-02 and mirroring lines 82-103 of `__init__.py` exactly.
- The reconciliation note from `<planning_context>` is honored: RESEARCH.md Pitfall 1 means `audit/service.py:24` is NOT migrated (Plan 03's caller-migration sweep skips it; Plan 04's architecture-guard test adds `:!backend/app/modules/audit/service.py` to the pathspec exclusion list). This plan does not touch `audit/service.py`.
- The reconciliation note that the existing typed accessors DO exist on main (RESEARCH.md Pitfall 2 was wrong about that) is honored: Task 01-02's `<read_first>` references the existing trio at lines 82-103, and the new accessor mirrors them.
</verification>

<success_criteria>
- `backend/app/core/identity.py` exists, defines `IdentityProtocol` (6 attributes), `RoleProtocol` (1 attribute), `IdentityExtension` (1 async method), `Identity = IdentityProtocol` alias. All three Protocols decorated `@runtime_checkable`.
- `backend/app/platform/extensions/defaults.py` extended with `DefaultIdentityExtension` whose `resolve_identity_from_token()` is async and returns None.
- `backend/app/platform/extensions/__init__.py` extended with `get_identity_extension()` typed accessor mirroring the existing trio.
- `backend/app/platform/extensions/protocols.py` is UNTOUCHED (D-12 says `IdentityExtension` lives in `core/identity.py`, not here).
- `backend/tests/test_extensions.py` extended with three new tests covering the default-fallback, registered-overlay, and async-method-contract paths.
- All new symbols importable cleanly: `from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity` and `from app.platform.extensions import get_identity_extension` both succeed.
- The plan introduces ZERO behavior change in production paths: no caller imports the new symbols, the auth dep chain is unmodified, the JWT/API-key/OAuth/refresh-token flows run unchanged.
- Ruff lint + format pass on all four modified files.
- Phase 214 ROADMAP SC#1 ("`backend/app/core/identity.py` defines `IdentityProtocol` capturing the surface 51 cross-domain call sites depend on; the concrete `User` ORM model satisfies it") is verifiably scaffolded — implicit structural conformance of `User` against `IdentityProtocol` will be exercised by Plans 02-03's caller migration; this plan establishes the contract.
- Phase 214 ROADMAP SC#3 ("the extension system exposes a registration hook ... mirroring `get_branding_extension()` / `get_audit_extension()`") is verifiably scaffolded — `get_identity_extension()` exists, registered, and falls back to a Default impl. Plan 02 wires it into the dep chain; Phase 217 SAML overlay plugs into it.
</success_criteria>

<output>
After completion, create `.planning/phases/214-identity-protocol-extract/214-01-SUMMARY.md` documenting:
- Confirmation of the four file modifications (3 source + 1 test).
- The exact line counts of `core/identity.py` and the appended block in `defaults.py` / `__init__.py`.
- The grep-verifiable contract gates (6-attribute count, 3 `@runtime_checkable` decorators, `is_admin` count = 0, `app.modules.*` import count in `core/identity.py` = 0).
- Confirmation the three new tests pass and the existing `test_extensions.py` corpus has no regression.
- A note that the dormant scaffolding produces zero behavior change in production until Plan 02 wires the dep chain.
- Pointer to Plan 02 as the next plan in the phase (Wave 2 — depends on this plan).
</output>
</content>
