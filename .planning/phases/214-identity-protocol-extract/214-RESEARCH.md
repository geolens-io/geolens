# Phase 214: identity-protocol-extract - Research

**Researched:** 2026-04-27
**Domain:** Backend Python — structural typing (PEP 544 Protocol), FastAPI dependency injection, extension/registration seam
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Protocol surface (D-01..D-06):**
- **D-01:** `IdentityProtocol` exposes the **comprehensive 6-field surface**: `id: UUID`, `username: str`, `email: str | None`, `is_active: bool`, `roles: Sequence[RoleProtocol]`, `created_at: datetime`. The audit's minimal 4-field suggestion (id, email, is_active, roles) is REJECTED because it omits `username` (read in admin/router.py, audit/router.py, catalog/maps/router.py, catalog/datasets/api/router.py, catalog/sources/provenance.py) and `created_at` (admin/router.py).
- **D-02:** No `is_admin` derived property (audit-26-b §1 suggested it; rejected). Admin role checks stay where they are: `'admin' in {r.name for r in user.roles}`.
- **D-03:** `roles: Sequence[RoleProtocol]` where `class RoleProtocol(Protocol): name: str` lives in the SAME `core/identity.py` file. No `core → modules.auth` import edge.
- **D-04:** `IdentityProtocol` and `RoleProtocol` are decorated `@runtime_checkable` (matches existing extension Protocols).
- **D-05:** Type alias `Identity = IdentityProtocol` is the name caller files import. Both names exported.
- **D-06:** `User` ORM class is **NOT modified** — no inheritance from Protocol, no class-level conformance assertion, no TYPE_CHECKING annotation. Structural conformance is implicit.

**Caller migration (D-07..D-11):**
- **D-07:** Two coordinated changes: (1) retype `get_optional_user()`/`get_current_user()`/`get_current_active_user()` to return `Identity`; (2) rewrite ~42 cross-domain caller files (import + parameter annotation swap).
- **D-08:** Sites that import `Role`/`UserRole` for SQL-filter or junction-table use keep those concrete imports — only `User` becomes `Identity`. Architecture-guard regex matches `\bUser\b` specifically.
- **D-09:** Allowlist (sites that keep concrete `User`):
  - `backend/app/modules/auth/**` (owns the model)
  - `backend/app/modules/admin/router.py` + `backend/app/modules/admin/service.py` (CRUD User rows; reads `password_hash`, `auth_provider`, `last_login_at`, `status` — NOT on Identity)
  - `backend/app/modules/audit/models.py` (ORM relationship `Mapped["User"]` requires concrete class)
  - `backend/app/api/main.py` (Base.metadata population)
  - `backend/app/processing/ingest/tasks_raster.py:142` (worker `Base.metadata` registration, `# noqa: F401`)
  - `backend/app/modules/auth/oauth/models.py:92` (relationship registration ordering, `# noqa: E402, F401`)
  - `backend/tests/**` (entirely exempt; pathspec excludes test dir)
- **D-10:** No backward-compat re-export shim. Hard cutover.
- **D-11:** Mandatory step: re-run `git grep -nE "from app\.modules\.auth\.models import" -- backend/app/` at plan time and after edits — every hit must be in D-09 or migrated.

**Extension hook (D-12..D-17):**
- **D-12:** `IdentityExtension` Protocol lives in `core/identity.py` (not `platform/extensions/protocols.py`) with one method:
  ```python
  @runtime_checkable
  class IdentityExtension(Protocol):
      async def resolve_identity_from_token(
          self, token: str, request: Request, db: AsyncSession
      ) -> Identity | None: ...
  ```
- **D-13:** Typed accessor `get_identity_extension() -> IdentityExtension` in `backend/app/platform/extensions/__init__.py`. Falls back to `DefaultIdentityExtension()` when no overlay registers. Uses existing `geolens.extensions` entry-point group, key `"identity"`.
- **D-14:** `DefaultIdentityExtension` lives in `backend/app/platform/extensions/defaults.py`. `resolve_identity_from_token()` returns `None`.
- **D-15:** Wire-in inside `get_optional_user()`: order is (1) API key → (2) extract bearer token → (3) **NEW:** if token, call `await get_identity_extension().resolve_identity_from_token(token, request, db)`; if non-None, return it → (4) else fall through to existing JWT decode + DB lookup → (5) else None.
- **D-16:** `get_current_user()` and `get_current_active_user()` build on `get_optional_user()` per existing pattern; they inherit the wire-in for free.
- **D-17:** Extension is NOT consulted in the API-key resolution path. API keys remain a core/community concern.

**Architecture guard (D-18..D-22):**
- **D-18:** Add **two** new `@pytest.mark.architecture` tests to `backend/tests/test_layering.py`:
  1. `test_core_does_not_import_from_any_module()` — broaden Phase 212-03's settings-only guard to all `app.modules.*`.
  2. `test_cross_domain_does_not_import_user_from_auth_models()` — fail if any line under `backend/` (excluding allowlist) does `from app.modules.auth.models import .*\bUser\b`.
- **D-19:** Test 2's allowlist via git pathspec `:!` exclusions (mirrors Phase 213-03). Reuses `_has_git_metadata()` and `_has_pathspec_magic()` helpers.
- **D-20:** Update `test_layering.py` module docstring to credit Phases 212, 213, **214**.
- **D-21:** No runtime conformance test (`isinstance(User(), IdentityProtocol)`).
- **D-22:** No ruff-level boundary rule.

**Migration & verification (D-23..D-27):**
- **D-23:** No Alembic migration. Proof: `cd backend && uv run alembic check` returns no new operations.
- **D-24:** 1965-test backend baseline is the acceptance gate (live floor is ≥1999 per Phase 212-04 evidence; treat 1999 as the floor).
- **D-25:** ROADMAP SC#5 (`pyright`/`mypy` no new typing regressions) interpreted **softly** — the project uses ruff only in CI. No new pyright/mypy gate added in this phase.
- **D-26:** Frontend has zero involvement. No HTTP contract change.
- **D-27 [informational]:** Phase 214 is independent of 212 and 213; both prior phases are complete on the planning timeline.

### Claude's Discretion

- **Commit decomposition** — likely 4 atomic commits: (1) introduce `core/identity.py` + `DefaultIdentityExtension` + `get_identity_extension()` (additive, no behavior change); (2) retype dependencies + wire extension into `get_optional_user()`; (3) migrate ~42 cross-domain caller annotations; (4) extend `test_layering.py` + verification gate. Constraint: dep retype (commit 2) must land BEFORE caller migrations (commit 3); architecture-guard tests (commit 4) must land LAST.
- **Module docstring wording** in `core/identity.py` — keep the spirit of `platform/extensions/protocols.py`'s "Uses only stdlib types to avoid circular imports with domain models" plus a one-liner pointing to Phase 214 + IDENT-01..03 + Phase 217 as first concrete consumer.
- **Trivial dead-import cleanup** during the migration (default: no; only if a router imports `User` but never references it after annotation rewrite).
- **Whether to keep BOTH the narrow Phase 212 guard AND the broad Phase 214 guard** — default REPLACE the narrow one; planner picks based on diff cleanliness.
- **`Request` parameter on `IdentityExtension.resolve_identity_from_token`** — included for SAML's likely needs (cookies, header introspection); planner may drop if Phase 217 design will not need it. Default: keep `Request`.
- **Test marker** — both new architecture tests use `@pytest.mark.architecture` (already registered after Phase 212-03). No new marker.

### Deferred Ideas (OUT OF SCOPE)

- `is_admin` as a Protocol field (rejected per D-02).
- `IdentityExtension.provision_identity(claims)` JIT hook — Phase 217 reuses `find_or_create_oauth_user()`.
- `IdentityExtension.list_identity_methods() -> list[str]` (admin UI surfacing).
- API-key resolution via extension (D-17 deferred).
- Pyright/mypy CI gate (D-25 soft).
- Runtime conformance test (D-21 deferred).
- Migrating admin/ to Identity (admin reads non-Identity fields).
- `AuthProvider` Protocol + `AuthenticatedIdentity` dataclass unification with `IdentityProtocol`.
- `Identity.tenant_id` field for multi-tenancy (backlog 999.6).

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| IDENT-01 | `IdentityProtocol` is defined in `core/identity.py` capturing the surface 51 `User` import sites across 11 domains depend on. | Verified by live grep 2026-04-27: 53 import lines exist across `backend/app/`. Comprehensive 6-field surface (D-01) covers all cross-domain reads of `username` (provenance.py:54,77; maps/router.py:252; admin/router.py:52; audit/router.py:71,136,172; datasets/api/router.py:450), `created_at` (admin/router.py:57; datasets/api/router.py:456), `id`, `email`, `is_active`, `roles`. Non-Identity attribute access (`password_hash`, `auth_provider`, `last_login_at`, `status`, `updated_at`) is confined to allowlisted modules (auth/**, admin/**) per the audit. |
| IDENT-02 | Concrete `User` SQLAlchemy model satisfies `IdentityProtocol`; all 51 cross-domain import sites depend on the Protocol. 1965-test baseline passes. | The `User` ORM at `backend/app/modules/auth/models.py:18-59` already exposes all six fields with matching types: `id: Mapped[uuid.UUID]`, `username: Mapped[str]`, `email: Mapped[str \| None]`, `is_active: Mapped[bool]`, `created_at: Mapped[datetime]`, `roles: Mapped[list["Role"]]` (selectin-loaded). `Role` ORM (line 62-74) exposes `name: Mapped[str]` — satisfies `RoleProtocol` structurally. No ORM changes required. |
| IDENT-03 | Enterprise auth overlays can register custom identity backends through the extension system without modifying core code. | Existing extension scaffold at `backend/app/platform/extensions/__init__.py` already supports the `geolens.extensions` entry-point group with `_extensions: dict[str, object]`. Phase 214 adds the `IdentityExtension` Protocol (in core/identity.py per D-12), the `DefaultIdentityExtension` community fallback (defaults.py per D-14), the `get_identity_extension()` typed accessor (per D-13), and the wire-in inside `get_optional_user()` (per D-15). Phase 217 SAML overlay registers `_extensions["identity"] = SAMLIdentityExtension(...)` via its entry point. |

</phase_requirements>

---

## Project Constraints (from CLAUDE.md)

The repo `./CLAUDE.md` is **absent**; only the user-global `~/.claude/CLAUDE.md` applies. Active directives for this phase:

- **Version control:** Never indicate AI/Bot activity in commit messages.
- **Code style:** Prefer simple, readable code over clever abstractions. Follow existing project conventions when editing files. (The "no `is_admin` derived property" decision D-02 and the "no shim" discipline D-10 are consistent with this.)
- **Communication:** Direct and concise; ask before assuming.

From auto-memory `MEMORY.md`:
- Backend stack: FastAPI + SQLAlchemy + asyncpg + Alembic; tests via `docker compose exec api uv run pytest`.
- Active milestone: **v13.1 Open-Core Separation P1** with target audit grades Boundary B → A−, Seam Quality C → B, OSS Surface D → C. Phase 214 closes 42 cross-domain `core ⇆ modules.auth.User` coupling edges (Boundary uplift) and adds the IdentityExtension seam unblocking Phase 217 (Seam Quality uplift).

---

## Summary

Phase 214 is a Python-only structural-typing refactor with a small extension-registration extension. Three pieces ship together:

1. **New file `backend/app/core/identity.py`** defining four symbols: `RoleProtocol`, `IdentityProtocol`, `IdentityExtension`, and the alias `Identity = IdentityProtocol`. All Protocols are `@runtime_checkable` (Python 3.10+ requirement for `isinstance()` to work on data-only Protocols — see Context7 below). The file imports only stdlib types (`uuid.UUID`, `datetime.datetime`, `typing.Protocol`, `typing.Sequence`, `typing.runtime_checkable`) plus FastAPI's `Request` and SQLAlchemy's `AsyncSession` for the extension method signature; it imports nothing from `app.modules.*`.

2. **Extension scaffold extension** — `DefaultIdentityExtension` lands in `backend/app/platform/extensions/defaults.py` next to the existing three defaults; `get_identity_extension()` typed accessor lands in `backend/app/platform/extensions/__init__.py`. **Important codebase finding (LOW alignment with CONTEXT.md):** the existing `backend/app/platform/extensions/__init__.py` does NOT yet have `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` typed accessors — only the generic `get_extension(name)`. CONTEXT.md "Reusable Assets" claims those typed accessors exist; they do not. The planner should write `get_identity_extension()` from scratch following the typed-accessor *pattern* CONTEXT.md describes, not pattern-match against accessors that aren't there.

3. **FastAPI dependency retype + caller migration** — `get_optional_user()`/`get_current_user()`/`get_current_active_user()` in `backend/app/modules/auth/dependencies.py` change return type from `User` to `Identity`. The extension is wired into `get_optional_user()` between the API-key path and the JWT path (D-15). Then ~42 cross-domain caller files swap `from app.modules.auth.models import User` → `from app.core.identity import Identity` and rewrite `user: User` parameter annotations to `user: Identity`.

The architecture-guard test added to `backend/tests/test_layering.py` regresses any future `from app.modules.auth.models import User` outside the D-09 allowlist via a `git grep` with `:!` pathspec exclusions (the same pattern Phase 213-03 established and which Phase 213's WR-02 fix added a `_has_pathspec_magic()` skip guard for).

**Primary recommendation:** Execute in 4 atomic commits per Claude's Discretion. Constraints: dep retype (commit 2) must land BEFORE caller migration (commit 3) so callers can import `Identity` and have something concrete to annotate against; architecture-guard tests (commit 4) must land LAST because they fail until cross-domain User imports are gone.

**Three planner-must-fix CONTEXT.md errors discovered during research** (see Risk Surfaces / Pitfalls below):
1. **`backend/app/modules/audit/service.py:24` is NOT a TYPE_CHECKING-only import.** It is a function-scope deferred import that uses `User` at runtime to construct a SQL filter (`select(User.id).where(User.username.ilike(pattern))` at line 43). Protocols don't work for SQLAlchemy SQL-filter construction because `User.id` and `User.username` are SQLAlchemy InstrumentedAttribute descriptors. This site behaves like the `Role`/`UserRole` SQL-filter sites (D-08) and must KEEP concrete `User` — but it's NOT in the D-09 allowlist. Either add audit/service.py to the allowlist OR leave the import path as concrete `User` while migrating the function-parameter annotation only. The planner must reconcile this.
2. **CONTEXT.md `<canonical_refs>` says `audit/router.py:31`** but the actual import is at line 32. Off-by-one.
3. **CONTEXT.md says the typed accessors `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` exist** as reusable patterns. They DO NOT exist in the actual code (verified via `grep -rn "get_branding_extension\|get_audit_extension\|get_auth_extension" backend/`). Phase 214 still adds `get_identity_extension()` per D-13 — it is just creating the FIRST typed accessor of this shape, not the fourth.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Identity contract (structural type) | Backend / `app.core.identity` | — | Cross-domain code must depend on a stable abstraction; concrete ORM stays in `auth/`. |
| Identity ORM (`User`, `Role`, `UserRole`) | Backend / `app.modules.auth` | — | The SQLAlchemy model continues to own DB persistence semantics. Structural subtyping makes `User` satisfy `IdentityProtocol` for free. |
| FastAPI dependency wiring (request → Identity) | Backend / `app.modules.auth.dependencies` | — | The deps are auth-layer concerns; only their return type changes (D-15). |
| Identity backend registration seam | Backend / `app.platform.extensions` + `app.core.identity` (Protocol) | `importlib.metadata` entry-points (`geolens.extensions` group) | Mirrors existing branding/audit/auth extension pattern. The Protocol lives in core; the registry/accessor lives in platform/extensions. |
| Architecture enforcement | Backend / `tests/test_layering.py` | CI workflow | Pytest-runnable static check; no runtime side effects. Reuses Phase 212+213 helpers. |
| No-migration proof | `alembic check` CLI | — | Pure Python additions + annotation rewrites; no DB delta expected. |

## Standard Stack

### Core (no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | ≥3.13 | Language | `pyproject.toml requires-python = ">=3.13"`. `typing.Protocol`, `typing.Sequence`, `typing.runtime_checkable` are stdlib. [VERIFIED: pyproject.toml:5] |
| FastAPI | ≥0.115.0 | HTTP framework + Depends | The dep retype is purely a return-type change; FastAPI does not validate dep return types at runtime — it forwards them to the consuming function (Pydantic only validates request bodies/responses, not dependency outputs). [VERIFIED: pyproject.toml:9; FastAPI dep behavior CITED: tiangolo.com/fastapi/tutorial/dependencies/] |
| SQLAlchemy | ≥2.0.25 | ORM | `User`/`Role`/`UserRole` ORM unchanged. `User` already exposes the 6 fields IdentityProtocol requires. [VERIFIED: pyproject.toml:10; backend/app/modules/auth/models.py:18-59] |
| pyjwt | ≥2.12.0 | JWT decode | The JWT path inside `get_optional_user()` is unchanged after the extension wire-in. [VERIFIED: pyproject.toml:16] |
| pytest | ≥9.0.3 | Test runner | The two new architecture tests use `@pytest.mark.architecture` (registered in `backend/pyproject.toml` under markers since Phase 212-03). [CITED: f78b0981 commit shows marker registration in Phase 213-03] |
| ruff | dev dep | Lint + format | Canonical static check. Catches missed import-path updates as F401/F821. [VERIFIED: pyproject.toml:52] |
| alembic | ≥1.13.0 | Migration / drift check | `alembic check` subcommand confirmed available. [VERIFIED: pyproject.toml:12] |

**Version verification** (`npm view`-equivalent for Python is `pip index versions` or PyPI directly — the dependencies are pinned in `pyproject.toml` so no live registry check needed; ALL versions verified against existing pyproject.toml on 2026-04-27).

### No new packages required

Phase 214 is an additive structural-typing refactor; it does NOT introduce `import-linter`, `pydantic-protocol`, or any architecture-DSL tooling. Per CONTEXT.md "Established Patterns" — the project uses `subprocess git grep` for layering enforcement, not import-graph libraries.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `IdentityProtocol` in `core/identity.py` | Pydantic v2 `BaseModel` for Identity contract | Pydantic adds runtime validation overhead (every dep call would re-validate `User` against the model) and forces a heavier coupling between the ORM and the contract. Protocols are zero-cost at runtime when used purely for typing. [CITED: PEP 544; Context7 docs above] |
| Method-based Protocol (`def get_id() -> UUID`) | Attribute-based Protocol (chosen — `id: UUID`) | The User ORM exposes attributes, not methods. Method-based Protocol would force adapter classes everywhere. Attribute Protocols match SQLAlchemy ORM idioms and are explicitly supported by `@runtime_checkable`. [CITED: Python 3.10+ `runtime_checkable` docs — see Code Examples below] |
| Single `IdentityExtension.resolve_identity(...)` | Two methods (`resolve_identity_from_token` + `provision_identity(claims)`) | Two methods would over-design for Phase 217's SAML JIT-provisioning flow. ROADMAP §Phase 217 SC#3 says SAML reuses `find_or_create_oauth_user()` — JIT provisioning is internal to the extension's `resolve_identity_from_token()` implementation, not a separate Protocol method. (Deferred Ideas list captures this.) |
| Move FastAPI dep stubs to `core/identity.py` | Keep them in `auth/dependencies.py` (chosen) | Moving stubs to core would re-create the `core → modules.auth.models` import edge (the deps still need `User` to construct SQL queries). D-domain says "stubs stay in auth — only their return type changes." |

## Architecture Patterns

### System Architecture Diagram

```
BEFORE
─────────────────────────────────────────────────────────────────────
  app.core.identity  ── DOES NOT EXIST ──

  app.modules.auth.dependencies
    get_optional_user(request, token, db) -> User | None
                                              │
                                              └── concrete User from app.modules.auth.models

  ~42 cross-domain caller files (catalog/, processing/, platform/,
  modules/settings/router.py, modules/audit/router.py + service.py,
  modules/embed_tokens/, standards/ogc/router.py)
    └── from app.modules.auth.models import User    ← 51 import lines (audit count)
        async def endpoint(..., user: User = Depends(get_current_active_user))

  app.platform.extensions
    _extensions: dict[str, object]
    get_extension(name) -> object | None        ← generic accessor only

AFTER
─────────────────────────────────────────────────────────────────────
  app.core.identity (NEW)
    @runtime_checkable RoleProtocol(Protocol):     name: str
    @runtime_checkable IdentityProtocol(Protocol): id, username, email,
                                                    is_active, roles, created_at
    @runtime_checkable IdentityExtension(Protocol):
                                async def resolve_identity_from_token(...)
    Identity = IdentityProtocol  ← alias (D-05)

  app.platform.extensions.defaults
    DefaultIdentityExtension(): async def resolve_identity_from_token(...) -> None  ← NEW

  app.platform.extensions.__init__
    get_identity_extension() -> IdentityExtension  ← NEW typed accessor
    (registered under _extensions["identity"], falls back to DefaultIdentityExtension)

  app.modules.auth.dependencies
    get_optional_user(...) -> Identity | None   ← retyped (was User | None)
      ├── _resolve_api_key()    [unchanged path]
      ├── extract bearer token
      ├── ext = get_identity_extension()
      ├── if token: maybe_id = await ext.resolve_identity_from_token(token, request, db)
      │             if maybe_id is not None: return maybe_id   [NEW path D-15]
      ├── existing JWT decode + DB lookup → User              [unchanged path]
      └── None
    get_current_user(...) -> Identity            ← retyped
    get_current_active_user(...) -> Identity     ← retyped

  ~42 cross-domain caller files
    └── from app.core.identity import Identity   ← swap import
        async def endpoint(..., user: Identity = Depends(get_current_active_user))

  9 allowlisted sites (auth/**, admin/**, audit/models.py TYPE_CHECKING,
  api/main.py, ingest/tasks_raster.py, oauth/models.py)
    └── from app.modules.auth.models import User  ← KEEP concrete

  backend/tests/test_layering.py (4 tests → 6 tests)
    + test_core_does_not_import_from_any_module()       [broaden Phase 212]
    + test_cross_domain_does_not_import_user_from_auth_models()
                          [git grep with :! pathspec excluding allowlist]
```

### Recommended Project Structure

```
backend/
├── app/
│   ├── core/
│   │   ├── identity.py              # NEW — RoleProtocol, IdentityProtocol,
│   │   │                            #       IdentityExtension, Identity alias
│   │   ├── db/
│   │   │   └── models.py            # unchanged (Phase 212 owns AppSetting here)
│   │   └── ...
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── dependencies.py      # retyped to return Identity; extension wired
│   │   │   ├── models.py            # UNCHANGED (D-06)
│   │   │   ├── providers/__init__.py # UNCHANGED (different Protocol; AuthProvider for login flow)
│   │   │   └── ...
│   │   ├── admin/                   # ALLOWLISTED — keeps concrete User
│   │   ├── audit/
│   │   │   ├── models.py            # ALLOWLISTED — TYPE_CHECKING relationship
│   │   │   ├── router.py            # MIGRATE — line 32 import + parameter annotations
│   │   │   └── service.py           # ⚠ KEEP concrete User (SQL-filter use, not TYPE_CHECKING)
│   │   ├── catalog/                 # MIGRATE — many sites
│   │   ├── embed_tokens/            # MIGRATE
│   │   ├── settings/router.py       # MIGRATE — line 12
│   │   └── ...
│   ├── platform/
│   │   ├── extensions/
│   │   │   ├── __init__.py          # ADD get_identity_extension()
│   │   │   ├── defaults.py          # ADD DefaultIdentityExtension
│   │   │   └── protocols.py         # UNCHANGED (IdentityExtension lives in core/identity.py per D-12)
│   │   ├── jobs/router.py           # MIGRATE
│   │   ├── sandbox/                 # MIGRATE
│   │   └── config_ops/router.py     # MIGRATE
│   ├── processing/
│   │   ├── ai/                      # MIGRATE (4 files)
│   │   ├── export/router.py         # MIGRATE
│   │   ├── ingest/                  # MIGRATE (router.py, service.py); tasks_raster.py:142 ALLOWLISTED
│   │   └── tiles/router.py          # MIGRATE — line 20 (line 213 inner `UserRole` import keeps concrete)
│   └── standards/ogc/router.py      # MIGRATE — line 10
└── tests/
    └── test_layering.py             # +2 architecture tests, docstring updated
```

### Pattern 1: Attribute-based Protocol with `@runtime_checkable`

**What:** A `typing.Protocol` subclass declaring attributes (not methods) that downstream code reads. The `@runtime_checkable` decorator enables `isinstance()` checks at runtime if needed, but the primary use is as a type annotation for static checkers / IDE autocompletion.

**When to use:** When multiple concrete implementations may satisfy the same shape, but you don't want them to inherit from a common base. Especially valuable when one implementation is a SQLAlchemy ORM (which already has its own MRO) — Protocols allow structural subtyping without disturbing the ORM's inheritance.

**Example (the new file):**
```python
# backend/app/core/identity.py
"""Cross-domain identity contract.

Defines structural Protocols that downstream code uses to type a request's
authenticated user without importing the concrete SQLAlchemy ORM. The
concrete `app.modules.auth.models.User` satisfies `IdentityProtocol`
implicitly (structural subtyping / PEP 544).

Uses only stdlib types (plus FastAPI's Request and SQLAlchemy's
AsyncSession for the extension method signature) to avoid the
`core -> modules.auth` import edge that this milestone (Phase 214,
IDENT-01..03) is closing.

Phase 217 (auth-saml-enterprise) is the first concrete consumer of
`IdentityExtension` — its SAML overlay registers a backend that
validates SAML session tokens and returns an Identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class RoleProtocol(Protocol):
    """Slim role contract — `name` is the only attribute cross-domain code reads."""

    name: str


@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface used by ~42 cross-domain call sites.

    The concrete `app.modules.auth.models.User` satisfies this Protocol
    structurally — no inheritance, no class-level conformance assertion.
    """

    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime


# Shorter alias for caller annotations (D-05).
Identity = IdentityProtocol


@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract.

    A registered extension's `resolve_identity_from_token()` is called by
    `app.modules.auth.dependencies.get_optional_user()` between the API-key
    path and the JWT path. Returning a non-None Identity short-circuits the
    JWT flow; returning None falls through to the existing JWT decode + DB
    lookup. Phase 217 SAML implements this method to validate SAML session
    tokens and JIT-provision via `find_or_create_oauth_user()`.
    """

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
```
[CITED: existing `backend/app/platform/extensions/protocols.py` docstring discipline; Python typing.Protocol docs from Context7 above]

### Pattern 2: Default extension community fallback

**What:** A concrete class that satisfies the Protocol with no-op behavior, used when no enterprise overlay registers.

**When to use:** Anytime the typed-accessor pattern is in play — `get_<thing>_extension()` returns the registered extension or a Default if none registered.

**Example:**
```python
# backend/app/platform/extensions/defaults.py (additions)
class DefaultIdentityExtension:
    """Default identity backend: no enterprise overlay registered.

    Returns None from `resolve_identity_from_token()` so the existing JWT
    decode + DB lookup path in `get_optional_user()` runs unchanged in
    community edition.
    """

    async def resolve_identity_from_token(
        self,
        token: str,
        request: Request,  # noqa: ARG002 - kept for Protocol conformance
        db: AsyncSession,  # noqa: ARG002 - kept for Protocol conformance
    ) -> "Identity | None":
        return None
```

Note: this file's three existing Default classes (`DefaultBrandingExtension`, `DefaultAuditExtension`, `DefaultAuthExtension`) are sync methods returning literals. `DefaultIdentityExtension`'s method must be `async` to match `IdentityExtension.resolve_identity_from_token` (the SAML overlay's implementation will be `async` because it does network/DB work). FastAPI happily awaits async deps; the `async` here is required, not optional.

[CITED: `backend/app/platform/extensions/defaults.py` lines 1-24 read 2026-04-27]

### Pattern 3: Typed-accessor for extension registry

**What:** A function that returns the registered extension cast to its Protocol type, with a default fallback.

**When to use:** Whenever a downstream consumer wants type-safe access to a specific extension; avoids the generic `get_extension(name) -> object | None` cast site at every call.

**Example:**
```python
# backend/app/platform/extensions/__init__.py (additions at the end)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.identity import IdentityExtension


def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension, falling back to default.

    Phase 217's SAML overlay registers via `geolens.extensions` entry-point
    by setting `_extensions["identity"] = SAMLIdentityExtension(...)` in its
    loader. Until then, the default returns None from
    `resolve_identity_from_token()` and the existing JWT path always runs.
    """
    from app.platform.extensions.defaults import DefaultIdentityExtension

    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]
```

The `TYPE_CHECKING` import keeps `app.platform.extensions/__init__.py` from importing `app.core.identity` at runtime (avoids any chance of circular imports during application startup). The runtime-only `from app.platform.extensions.defaults import DefaultIdentityExtension` is inside the function body to avoid eager loading.

**Important:** the existing `backend/app/platform/extensions/__init__.py` does NOT have `get_branding_extension()`, `get_audit_extension()`, or `get_auth_extension()` despite CONTEXT.md "Reusable Assets" claiming they do. Phase 214 is creating the FIRST typed accessor of this shape — the planner should not look for prior art and pattern-match against accessors that aren't there.

### Pattern 4: FastAPI dependency retype (return-type only)

**What:** Change a FastAPI dependency's return type annotation without changing its body. FastAPI's runtime resolution does not validate dep return types — only static checkers / IDE autocomplete care.

**When to use:** When you want consumer-side typing to use a Protocol while the dep continues to return a concrete class that satisfies the Protocol structurally.

**Example:**
```python
# backend/app/modules/auth/dependencies.py (excerpt of the change)
async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> "Identity | None":  # was: User | None
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    if token is not None:
        from app.platform.extensions import get_identity_extension

        ext = get_identity_extension()
        maybe_identity = await ext.resolve_identity_from_token(token, request, db)
        if maybe_identity is not None:
            return maybe_identity

    if token is None:
        return None
    # ...existing JWT decode + DB lookup unchanged below...
```

The function-scope `from app.platform.extensions import get_identity_extension` avoids any startup-order import-cycle concern (the dep file already imports from `app.modules.auth.models`; `platform/extensions` should not need to import from `auth/models`, but using the function-scope import is the project's deferred-import convention for cycle insurance).

[CITED: `backend/app/modules/auth/dependencies.py:61-102` read 2026-04-27]

### Pattern 5: Architecture guard via `git grep` with allowlist exclusions

**What:** A pytest test that shells out to `git grep` to assert a specific import pattern is absent from a directory tree, with `:!` pathspec exclusions for legitimate exceptions.

**When to use:** When the project enforces a layering rule that has a small, enumerable allowlist of legitimate exceptions.

**Example:**
```python
# backend/tests/test_layering.py (new test added by Phase 214)
@pytest.mark.architecture
def test_cross_domain_does_not_import_user_from_auth_models() -> None:
    """No cross-domain code imports the concrete `User` ORM.

    Closes Phase 214 IDENT-02: the 51 cross-domain `User` import sites
    typed against `IdentityProtocol` (alias `Identity`) instead of the
    concrete SQLAlchemy class. Allowlist captures the 9 sites that
    legitimately keep `User` (auth/**, admin/**, audit/models.py
    TYPE_CHECKING, api/main.py, oauth/models.py and ingest worker
    side-effect imports for Base.metadata).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip("git < 2.13 lacks `:!` pathspec exclusion")

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b",
            "--",
            "backend/",
            ":!backend/app/modules/auth/",
            ":!backend/app/modules/admin/",
            ":!backend/app/modules/audit/models.py",
            ":!backend/app/modules/audit/service.py",  # see Pitfall 1 — SQL-filter use
            ":!backend/app/api/main.py",
            ":!backend/app/processing/ingest/tasks_raster.py",
            ":!backend/tests/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: cross-domain code still imports concrete `User` "
            "from `app.modules.auth.models`. Use `Identity` from "
            "`app.core.identity` instead. Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**Note:** the regex `import\s+.*\bUser\b` matches `import User`, `import Role, User, UserRole`, and `import User as UserModel` (the actual line at admin/service.py:296) but does NOT match `import UserRole` alone (the `\b` word boundary requires `User` to end at the boundary, and `UserRole` has `R` after the `r` in `User`, which is a word character — wait, let me re-verify this with care. `\bUser\b` matches `User` as a complete word, where word boundary is the transition between word and non-word character. `UserRole` is one word — the `R` after `User` is a word character — so `\bUser\b` does NOT match the `User` substring inside `UserRole`. Verified by the same regex shape used in Phase 213's `test_no_imports_from_auth_visibility`.)

[CITED: Phase 213 test_layering.py final state at commit `f78b0981`; WR-02 git-version skip at commit `bb6e53d9`]

### Pattern 6: `from __future__ import annotations` for forward references

**What:** PEP 563 deferred evaluation of annotations. With it, all type annotations are strings at runtime; runtime semantic effect is none. Forward references (`"Identity | None"`) work without quoting.

**When to use:** Any new module that uses Protocol types or class-level typing where the alternative would be quoting strings everywhere or restructuring imports.

The existing project files use this convention (`backend/app/platform/extensions/__init__.py:8` has `from __future__ import annotations`). New `core/identity.py` should too — keeps annotations cheap and avoids name-resolution surprises.

### Anti-Patterns to Avoid

- **Modify the `User` ORM class to inherit from `IdentityProtocol`** — explicitly forbidden by D-06. Protocols are structural; conformance is implicit. Adding inheritance complicates the SQLAlchemy MRO and is unnecessary.
- **Add an `is_admin` derived property** — D-02 rejected. Admin role checks compute the predicate from `roles` directly: `'admin' in {r.name for r in user.roles}`.
- **Define `IdentityExtension` Protocol in `platform/extensions/protocols.py`** — D-12 says it lives in `core/identity.py` because (a) it returns `Identity` (which lives in core), and (b) co-locating the consumer-facing types keeps the discoverability story simple. `protocols.py` is for non-identity extension surfaces.
- **Add `Identity` to `app.modules.auth.__init__.py` re-exports for backward compat** — D-10 says hard cutover, no shim. The migration is mechanical; ruff will catch missed import-path swaps.
- **Promote function-scope deferred imports to module-level during the migration** — out of scope (Phase 213 D-04 set this discipline; Phase 214 inherits). E.g., `embed_tokens/service.py:312` keeps its function-scope deferred import, just swaps the path.
- **Build a runtime conformance test** (`assert isinstance(User(), IdentityProtocol)`) — D-21 deferred. The full pytest run already exercises the dep chain end-to-end with the concrete `User`.
- **Pre-emptively add caching at the `IdentityExtension` layer** — Risk Surface item; that's Phase 217's design decision, not Phase 214's.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting missed `User` import migrations | Custom AST scanner | `ruff check` (F401/F811/F821) + the new architecture-guard test | Already in dev deps; fast; CI-enforced. The architecture-guard catches *layout* violations; ruff catches *unresolved* names. [VERIFIED: pyproject.toml:52] |
| Layering enforcement | Custom AST walker, `import-linter`, `import-graph` | `subprocess git grep` with `:!` pathspec exclusions | Established by Phases 212+213. CONTEXT.md "Established Patterns" is binding. Adding `import-linter` would duplicate machinery. |
| Runtime Protocol conformance check | Hand-rolled `validate_user_satisfies_protocol(...)` helper | `@runtime_checkable` + `isinstance(x, IdentityProtocol)` if ever needed | Stdlib already provides this (Python 3.10+). The Phase explicitly defers any runtime conformance test (D-21). |
| Per-call extension caching | Custom `lru_cache(_extensions.get("identity"))` | The existing `_extensions` dict is already a per-process cache | `_extensions` populated once at startup by `load_extensions()`; subsequent `get_identity_extension()` calls are O(1) dict lookup. [VERIFIED: backend/app/platform/extensions/__init__.py:21-41] |
| No-migration verification after the refactor | Generate a real Alembic migration and inspect | `cd backend && uv run alembic check` | Reports zero pending operations. Same gate Phase 212-04 and Phase 213-04 used. |
| Forward references in Protocol member types | Quote every reference (`"Identity | None"`) manually | `from __future__ import annotations` (PEP 563) | Defers all annotations to strings at runtime. Already the project convention. |

**Key insight:** Phase 214 is mostly *deletion of redundancy* via structural typing. Every "we could automate this" temptation has either an existing tool (ruff, alembic, git grep) or is too small to be worth automating (~42 caller files with a single import-line edit each).

## Caller Inventory (Authoritative — live grep 2026-04-27)

Live `git grep -nE "from app\.modules\.auth\.models import" -- backend/app/` 2026-04-27 returns **53 import lines** across the listed files. CONTEXT.md `<canonical_refs>` list of ~42 migrate + 9 allowlist matches the live grep with three caveats noted in Risk Surfaces.

### Migrate to `Identity` (cross-domain — current line numbers verified)

| File | Line | Imported names | Notes |
|------|------|----------------|-------|
| `backend/app/modules/settings/router.py` | 12 | `User` | single-line |
| `backend/app/modules/audit/router.py` | **32** | `User` | CONTEXT.md says line 31 — actual is 32 |
| `backend/app/modules/audit/service.py` | 24 | `User` | ⚠ FUNCTION-SCOPE deferred import for SQL filter — see Pitfall 1 |
| `backend/app/modules/embed_tokens/admin_router.py` | 10 | `User` | single-line |
| `backend/app/modules/embed_tokens/router.py` | 27 | `User` | single-line |
| `backend/app/modules/embed_tokens/service.py` | 312 | `User` | function-scope deferred import (rewrite path, keep deferral) |
| `backend/app/modules/catalog/maps/router.py` | 25 | `User` | single-line |
| `backend/app/modules/catalog/maps/service.py` | 19 | `User, UserRole` | KEEP `UserRole` concrete; only swap `User` → `Identity` |
| `backend/app/modules/catalog/records/router.py` | 10 | `User` | single-line |
| `backend/app/modules/catalog/layers/router.py` | 11 | `User` | single-line |
| `backend/app/modules/catalog/datasets/api/router.py` | 27 | `User` | single-line |
| `backend/app/modules/catalog/datasets/api/router_data.py` | 22 | `User` | single-line |
| `backend/app/modules/catalog/datasets/api/router_export.py` | 24 | `User` | single-line |
| `backend/app/modules/catalog/datasets/api/router_metadata.py` | 21 | `User` | single-line |
| `backend/app/modules/catalog/datasets/api/router_reupload.py` | 20 | `User` | single-line |
| `backend/app/modules/catalog/datasets/api/router_vrt.py` | 18 | `User` | single-line |
| `backend/app/modules/catalog/datasets/domain/service.py` | 28 | `User` | single-line |
| `backend/app/modules/catalog/datasets/domain/helpers.py` | 9 | `User` | single-line |
| `backend/app/modules/catalog/features/router.py` | 14 | `User` | single-line |
| `backend/app/modules/catalog/search/router.py` | 18 | `User` | single-line |
| `backend/app/modules/catalog/search/service.py` | 31 | `User` | single-line |
| `backend/app/modules/catalog/search/cache.py` | 12 | `User` | single-line |
| `backend/app/modules/catalog/sources/router.py` | 14 | `User` | single-line |
| `backend/app/modules/catalog/sources/stac_router.py` | 23 | `User` | single-line |
| `backend/app/modules/catalog/collections/router.py` | 15 | `User` | single-line |
| `backend/app/modules/catalog/collections/service.py` | 27 | `User` | single-line (CONTEXT.md says 26) |
| `backend/app/processing/ingest/service.py` | 19 | `User` | single-line |
| `backend/app/processing/ingest/router.py` | 22 | `User` | single-line |
| `backend/app/processing/tiles/router.py` | 20 | `User` | single-line |
| `backend/app/processing/tiles/router.py` | 213 | `UserRole` | KEEP concrete (SQL-filter use, no `User` here — D-08) |
| `backend/app/processing/ai/service.py` | 31 | `User` | single-line |
| `backend/app/processing/ai/router.py` | 41 | `User` | single-line |
| `backend/app/processing/ai/streaming.py` | 32 | `User` | single-line |
| `backend/app/processing/ai/chat_service.py` | 28 | `User` | single-line |
| `backend/app/processing/export/router.py` | 15 | `User` | single-line |
| `backend/app/platform/sandbox/__init__.py` | 17 | `User` | single-line |
| `backend/app/platform/sandbox/validator.py` | 17 | `User` | single-line |
| `backend/app/platform/jobs/router.py` | 13 | `User` | single-line |
| `backend/app/platform/config_ops/router.py` | 12 | `User` | single-line |
| `backend/app/standards/ogc/router.py` | 10 | `User` | single-line |

**Note:** `backend/app/modules/catalog/authorization.py` (Phase 213's relocation target) imports `Role, User, UserRole` from `auth.models`. CONTEXT.md `<canonical_refs>` lists it at line 21 inside the migrate set; the file does not exist on the planning branch (`plan-228-05-cross-repo-launch`) but exists in Phase 213's final commits (`82452cfd`, `0dd3269c`, `0007268d`). Planner runs the live grep at plan time on the post-Phase-213 working tree.

### KEEP concrete `User` (allowlist — verified by live grep 2026-04-27)

| File | Line | Imported names | Allowlist reason |
|------|------|----------------|------------------|
| `backend/app/modules/auth/dependencies.py` | 14 | `ApiKey, User` | auth/** owns the model; needs `User` for SQL `select(User).where(User.id == ...)` |
| `backend/app/modules/auth/router.py` | 13 | `ApiKey, User` | auth/** |
| `backend/app/modules/auth/service.py` | 12 | `ApiKey, RefreshToken, Role, User, UserRole` | auth/** |
| `backend/app/modules/auth/oauth/service.py` | 10 | `Role, User, UserRole` | auth/** |
| `backend/app/modules/auth/oauth/models.py` | 92 | `User` (`# noqa: E402, F401`) | side-effect for relationship registration |
| `backend/app/modules/auth/providers/local.py` | 9 | `User` | auth/**; `LocalAuthProvider.authenticate()` reads `password_hash` |
| `backend/app/modules/auth/visibility.py` | 20 | `Role, User, UserRole` | DELETED in Phase 213 — should be `catalog/authorization.py:21` after Phase 213 lands; auth/** was the original allowlist; `catalog/authorization.py` keeps Role/UserRole concrete (D-08) but `User` becomes `Identity`. |
| `backend/app/modules/admin/router.py` | 33 | `ApiKey, User` | admin/** — admin reads `User.password_hash`, `User.last_login_at` |
| `backend/app/modules/admin/service.py` | 14 | `ApiKey, Role, User, UserRole` | admin/** |
| `backend/app/modules/admin/service.py` | 296 | `User as UserModel` | admin/** function-scope import for SQL query |
| `backend/app/modules/audit/models.py` | 12 | `User` (TYPE_CHECKING block) | ORM relationship `Mapped["User"]` |
| `backend/app/api/main.py` | 26 | `Role, User, UserRole` | `Base.metadata` registration; uses `User(...)` constructor for `seed_initial_admin()` |
| `backend/app/processing/ingest/tasks_raster.py` | 142 | `User` (`# noqa: F401`) | Procrastinate worker `Base.metadata` registration |

### Deferred imports inside callers — keep deferred, rewrite path

Per the existing project convention (Phase 213 D-04), function-scope deferred imports stay deferred — only the path is rewritten:
- `backend/app/modules/embed_tokens/service.py:312` (function-scope inside admin list-tokens)
- `backend/app/processing/tiles/router.py:213` (function-scope; only `UserRole` here, not `User`)

### Indirect imports / function-scope (verified safe — KEEP concrete)

- `backend/app/modules/admin/service.py:296` — `from app.modules.auth.models import User as UserModel` — admin/** allowlisted.

### No test-file callers requiring migration

`backend/tests/**` is entirely exempt from the architecture guard via `:!backend/tests/`. Test fixtures construct `User(...)` directly; since `User` structurally satisfies `IdentityProtocol`, fixture-passing-to-functions still typechecks for callers that take `Identity`.

## Runtime State Inventory

> Phase 214 is a Python-only refactor with no DB changes, no relocation of any persistent entity, and no string rename of any externally-registered identifier.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | None — `users`, `roles`, `user_roles`, `api_keys`, `refresh_tokens` tables are unchanged. The User ORM class is unchanged (D-06). Existing rows persist verbatim. | None. |
| **Live service config** | None. The HTTP API contracts are unchanged at the wire level (D-26). FastAPI does not validate dep return types at runtime; only the consumer-side typing changes. OAuth config, JWT config, API-key config — all unchanged. | None. Frontend continues hitting the same endpoints with the same payload shape. |
| **OS-registered state** | None. The `geolens-api` and `geolens-worker` Docker services are unchanged. No systemd / pm2 / Task Scheduler / launchd registrations reference Python module paths. | None. |
| **Secrets and env vars** | None. `JWT_SECRET_KEY`, `GEOLENS_ADMIN_USERNAME`, OAuth client secrets, etc. are set via env, not via Python module paths. The `_resolve_api_key()` precedence (header > query `?api_key=` > JWT > anonymous) is preserved by D-15 / D-17. | None. |
| **Build artifacts / installed packages** | `backend/.venv/` and `backend/__pycache__/` may have stale `.pyc` for modules whose imports change. Stale .pyc could cause local pytest failures with `ImportError`. CI is unaffected (fresh checkout). | None for CI. Note in plan: "if any local pytest run fails strangely, run `find backend -type d -name __pycache__ -exec rm -rf {} +`." |

**Canonical question:** *After every file in the repo is updated, what runtime systems still have the old string cached, stored, or registered?* Answer: **nothing**. The `User` class is unchanged; cross-domain code now refers to it via `Identity` annotation; SQLAlchemy identifies tables by `__tablename__`+`__table_args__`. The extension registry `_extensions` is a process-local dict populated at startup — no persistence.

## Common Pitfalls

### Pitfall 1: ⚠ `audit/service.py:24` is NOT a TYPE_CHECKING import — keep concrete `User`

**What goes wrong:** CONTEXT.md `<code_context>` describes `audit/service.py:24` as "TYPE_CHECKING-only import that exists to type a function parameter" and says "that parameter becomes `Identity`, and the import becomes `if TYPE_CHECKING: from app.core.identity import Identity` (or just module-level — `Identity` is light, no runtime cost)." A planner following this verbatim would migrate the import path to `Identity`. The migration would break at runtime because `User` is used at line 43 to build a SQL filter:
```python
search_filter = (
    AuditLog.action.ilike(pattern)
    | AuditLog.resource_type.ilike(pattern)
    | AuditLog.user_id.in_(select(User.id).where(User.username.ilike(pattern)))
)
```
`User.id` and `User.username` are SQLAlchemy `InstrumentedAttribute` descriptors — not Python attributes. `Identity` is a `Protocol` whose `id` and `username` are class-level `Mapped[...]`-style annotations; they are NOT `InstrumentedAttribute` descriptors. `select(Identity.id)` would fail at runtime with `AttributeError` or generate invalid SQL.

**Why it happens:** The audit-26-b §10 directive talks about retypeing FastAPI deps; CONTEXT.md correctly captures that for parameter annotations, but `audit/service.py:24` is a **function-scope deferred import for runtime SQL use**, not a type annotation. The CONTEXT.md classification is wrong.

**How to avoid:** Two options the planner picks between:
- **(a)** Add `backend/app/modules/audit/service.py` to the architecture-guard allowlist (`:!backend/app/modules/audit/service.py`). This treats the SQL-filter use site like the SQL-filter use sites D-08 already exempts (`Role`, `UserRole` in catalog/maps/service.py:637 etc.).
- **(b)** Keep the function-scope `from app.modules.auth.models import User` import unchanged at line 24, and verify nothing in the function takes `User` as a parameter (read-only verification — no parameter migration needed for this file).

Option (a) is cleaner because it documents the exception in the architecture guard. Option (b) requires the planner to convince themselves no parameter annotation in the file uses `User`, which is fragile to future edits. **Recommend option (a).**

**Warning signs:** After the migration, running `cd backend && uv run pytest tests/test_audit_router.py -v` (or any test exercising audit search) returns `AttributeError: type object 'IdentityProtocol' has no attribute 'id'` or generates a broken SQL query that PostgreSQL rejects.

### Pitfall 2: CONTEXT.md typed-accessor pattern doesn't exist yet — create from scratch

**What goes wrong:** CONTEXT.md `<code_context>` "Reusable Assets" says "the existing typed-accessor pattern (`get_branding_extension()`, `get_audit_extension()`, `get_auth_extension()`)" exists and Phase 214 "adds `get_identity_extension()` next to these, identical shape." A planner following this verbatim would search `backend/app/platform/extensions/__init__.py` for those accessors to mirror their implementation — and find nothing.

**Why it happens:** The accessors are referenced in CONTEXT.md as if they exist; they do not. The actual extension registry has only the generic `get_extension(name) -> object | None`, `has_extension(name)`, `list_extensions()`, and `get_extension_routers()` — verified via `grep -rn "get_branding_extension\|get_audit_extension\|get_auth_extension" backend/` returning zero hits.

**How to avoid:** Phase 214 creates the FIRST typed accessor of this shape. Use Pattern 3 above (typed-accessor for extension registry) as the reference implementation. The accessor body is small (~10 lines including the Default fallback). The planner does NOT need to wait for the prior accessors to exist before adding `get_identity_extension()`.

**Warning signs:** Planner spending time grepping the codebase looking for `get_branding_extension` to copy from. (None to find.)

### Pitfall 3: `Sequence[RoleProtocol]` vs `list["Role"]` variance

**What goes wrong:** A pyright/mypy run flags `User.roles: Mapped[list[Role]]` as not satisfying `IdentityProtocol.roles: Sequence[RoleProtocol]` because `list[Role]` is invariant and `Sequence` is covariant in some interpreters' eyes. The fix: `Sequence[RoleProtocol]` should be a covariant ABC; in Python's typing module, `Sequence` IS covariant. `list` is invariant but `list[X]` IS-A `Sequence[X]` and `Sequence` is covariant in X, so `list[Role]` IS-A `Sequence[RoleProtocol]` provided `Role` IS-A `RoleProtocol`. `Role` has `name: Mapped[str]` — `name: str` at the SQLAlchemy level — so `Role` satisfies `RoleProtocol` structurally.

**Why it happens:** SQLAlchemy `Mapped[X]` has runtime semantics that confuse type checkers. The `@runtime_checkable` decorator only validates attribute *presence* at runtime, not type. Static checkers (pyright) try harder.

**How to avoid:** D-25 interprets SC#5 softly. `cd backend && uv run ruff check` is the only required gate. If the planner runs `pyright backend/app` ad-hoc and sees a Sequence/list variance complaint, the fix is to wrap the `roles` field annotation in a `Sequence[RoleProtocol]` cast at the use site OR adjust the Protocol's `roles` to `list[RoleProtocol]` (less idiomatic but matches `User.roles` exactly). **Recommend `Sequence[RoleProtocol]`** — covariance gives the right semantics; the project's lack of pyright/mypy in CI means the variance is academic.

**Warning signs:** Pyright reports "Type list[Role] is incompatible with Sequence[RoleProtocol]" in some IDE configurations. Not a CI blocker per D-25.

### Pitfall 4: Architecture guard self-positive (the Phase 212-03 / 213-03 bug)

**What goes wrong:** The new `test_cross_domain_does_not_import_user_from_auth_models()` includes a regex literal mentioning `from app.modules.auth.models import .*\bUser\b`. If the test file itself is not excluded from `git grep`, the docstring/error-message text in the test would match the regex and produce a self-positive failure on first run.

**Why it happens:** Phase 212-03 hit exactly this bug (commit `b0bd0c2c`). Phase 213-03 used `:!backend/tests/test_layering.py` as the fix.

**How to avoid:** Use `:!backend/tests/test_layering.py` in the new test's pathspec, AND/OR anchor the regex with `^\s*(from|import)\s+` so the regex literal in a docstring doesn't match. Both are defensive; the import-anchor alone may be sufficient (Phase 212-03's fix), but `:!backend/tests/` excludes the entire test dir which is desired anyway (D-19 explicitly excludes tests).

**Warning signs:** First pytest run after adding the new test fails with offending lines all coming from `test_layering.py`.

### Pitfall 5: `_has_pathspec_magic()` skip on git < 2.13

**What goes wrong:** The architecture guard test uses `:!path` pathspec exclusion. Git versions < 2.13 reject the `:!` syntax with a non-zero exit code that is NOT the standard "no matches" rc=1.

**Why it happens:** `:!` magic pathspec is supported from git 2.13 (May 2017). The default Docker base image's git version may be older.

**How to avoid:** Reuse the `_has_pathspec_magic()` helper Phase 213 added in commit `bb6e53d9` (WR-02 fix). The new test starts with:
```python
if not _has_git_metadata():
    pytest.skip("git metadata unavailable; arch test only runs on full clones")
if not _has_pathspec_magic():
    pytest.skip("git < 2.13 lacks `:!` pathspec exclusion")
```

**Warning signs:** Test fails inside an old container with `git grep` rc != 0 and != 1; stderr mentions "bad pathspec" or similar.

### Pitfall 6: FastAPI `Annotated[..., Depends(...)]` return-type mismatch warnings

**What goes wrong:** After retypeing `get_optional_user() -> Identity | None`, every endpoint that uses `Annotated[User, Depends(get_optional_user)]` (or `user: User = Depends(get_optional_user)`) keeps the consumer-side `User` annotation, which is now stricter than necessary but still valid. ruff F841 / type-checker warnings may flag the mismatch — but only if both sides are checked together. FastAPI's runtime resolution does not care.

**Why it happens:** FastAPI's `Depends()` does not propagate the dependency's return type to the consumer's annotation; the consumer's annotation is whatever the consumer wrote. Python typing is local.

**How to avoid:** Phase 214's caller-migration step does TWO things per file:
1. Swap `from app.modules.auth.models import User` → `from app.core.identity import Identity`.
2. Rewrite EVERY parameter annotation `user: User` → `user: Identity` (and `user: User | None` → `user: Identity | None`).
Both steps are required. Doing only step 1 leaves dangling `User` references that ruff F821 will flag immediately.

**Warning signs:** ruff reports `F821 undefined name 'User'` after the import swap but before annotation rewrites complete. This is the desired hard-error behavior — fix by completing the annotation rewrites in the same commit.

### Pitfall 7: Stale `__pycache__` after local file additions/edits

**What goes wrong:** Local pytest after the migration: tests pass weirdly because stale `.pyc` from a prior import path resolves through `__pycache__/`.

**Why it happens:** Python may resolve `__pycache__/<module>.pyc` for modules whose imports changed. Rare but documented.

**How to avoid:** First test run after the refactor: `find backend -type d -name __pycache__ -exec rm -rf {} +`. CI is unaffected (fresh checkout).

**Warning signs:** Local tests pass; CI fails with `ModuleNotFoundError` or `ImportError`.

### Pitfall 8: Async vs sync extension method consistency

**What goes wrong:** A planner copies `DefaultBrandingExtension`-style sync method definition for `DefaultIdentityExtension.resolve_identity_from_token()`, then the wire-in inside `get_optional_user()` does `await ext.resolve_identity_from_token(...)`. Calling `await` on a sync method that returns a non-awaitable raises `TypeError: object NoneType can't be used in 'await' expression`.

**Why it happens:** The other Default extensions (`DefaultBrandingExtension`, `DefaultAuditExtension`, `DefaultAuthExtension`) have sync methods returning literals. Pattern-matching against them would produce a sync `resolve_identity_from_token`.

**How to avoid:** `DefaultIdentityExtension.resolve_identity_from_token()` MUST be `async def`. Phase 217's SAML implementation will do async DB lookups, so the Protocol's method MUST be async. The default fallback's body is `return None` but the function signature is `async def`.

**Warning signs:** First request after wire-in raises `TypeError: object NoneType can't be used in 'await' expression`.

### Pitfall 9: Forgetting the extension wire-in lives in `get_optional_user()` only

**What goes wrong:** A planner adds the extension call into `get_current_user()` and `get_current_active_user()` directly, duplicating the logic.

**Why it happens:** All three FastAPI dependency functions look similar; the temptation to "add extension support to all three" is real.

**How to avoid:** D-15 says wire into `get_optional_user()` ONLY. D-16 says `get_current_user()` and `get_current_active_user()` build on `get_optional_user()` per the existing pattern. Read `auth/dependencies.py:105-178` — the existing `get_current_user()` does NOT delegate to `get_optional_user()` today; it has its own JWT-decode body. Phase 214 must EITHER:
- **(a)** Refactor `get_current_user()` to call `get_optional_user()` and raise on None (cleaner; one wire-in point), OR
- **(b)** Duplicate the extension call inside `get_current_user()`'s body before its JWT decode (less clean; two call sites for the extension).

**Recommend (a)** — it matches CONTEXT.md `<canonical_refs>` ("`get_current_user()` and `get_current_active_user()` build on `get_optional_user()` in the existing pattern (per `auth/dependencies.py:169-178`)"). Note this is a small behavior-preservation refactor inside `auth/dependencies.py`, not a no-op edit. It's safe because `get_optional_user()` and `get_current_user()` have identical post-extraction semantics — only the failure mode differs (None vs. raise).

**Warning signs:** Test failure pattern: anonymous-OK endpoints pass; required-auth endpoints regress because `get_current_user()` doesn't see the extension result.

### Pitfall 10: Extension changes the freshness contract

**What goes wrong:** A SAML overlay's `resolve_identity_from_token()` could in principle return an Identity whose `is_active=False` or whose `roles` are stale (cached at SAML session creation time). Endpoints that depend on `get_current_active_user()` get the `is_active` re-check (D-16); endpoints that depend on `get_optional_user()` directly don't.

**Why it happens:** The Protocol surface includes `is_active`, but the dep chain only checks it in `get_current_active_user()`.

**How to avoid:** This is Phase 217's responsibility (a SAML overlay's implementation must guarantee freshness or accept the documented contract). Phase 214 does NOT redesign the freshness contract. If a future bug surfaces, it's owned by the extension implementation, not the seam.

**Warning signs:** Phase 217 development surfaces stale-Identity bugs; that's their fix, not Phase 214's.

## Code Examples

Every code example here verified against the actual codebase or Context7-fetched docs.

### The new file: complete `core/identity.py`

```python
# backend/app/core/identity.py
"""Cross-domain identity contract.

Defines structural Protocols that downstream code uses to type a request's
authenticated user without importing the concrete SQLAlchemy ORM. The
concrete `app.modules.auth.models.User` satisfies `IdentityProtocol`
implicitly (structural subtyping / PEP 544).

Uses only stdlib types (plus FastAPI's Request and SQLAlchemy's
AsyncSession for the extension method signature) to avoid the
`core -> modules.auth` import edge that this milestone (Phase 214,
IDENT-01..03) is closing.

Phase 217 (auth-saml-enterprise) is the first concrete consumer of
`IdentityExtension`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class RoleProtocol(Protocol):
    """Slim role contract — `name` is the only attribute cross-domain code reads."""

    name: str


@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface used by ~42 cross-domain call sites."""

    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime


# Shorter alias for caller annotations (Phase 214 D-05).
Identity = IdentityProtocol


@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends."""

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
```

### The Default extension and typed accessor

```python
# backend/app/platform/extensions/defaults.py (additions to existing file)
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.identity import Identity


class DefaultIdentityExtension:
    """Community-edition default: no enterprise overlay registered."""

    async def resolve_identity_from_token(
        self,
        token: str,  # noqa: ARG002 — kept for Protocol conformance
        request: "Request",  # noqa: ARG002
        db: "AsyncSession",  # noqa: ARG002
    ) -> "Identity | None":
        return None
```

```python
# backend/app/platform/extensions/__init__.py (addition at end of file)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.identity import IdentityExtension


def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension, falling back to default."""
    from app.platform.extensions.defaults import DefaultIdentityExtension

    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]
```

### The dependency retype + extension wire-in

```python
# backend/app/modules/auth/dependencies.py (excerpt — get_optional_user changes)
from app.core.identity import Identity  # NEW
# (existing imports below unchanged: hashlib, uuid, datetime, jwt, FastAPI bits, etc.)
# from app.modules.auth.models import ApiKey, User  ← stays (User still used internally)


async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity | None:  # was: User | None
    """Try to extract the current user from API key, extension, or JWT token."""
    # Step 1: API key (unchanged)
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # Step 2: bearer token absent → anonymous
    if token is None:
        return None

    # Step 3 (NEW per Phase 214 D-15): consult registered IdentityExtension
    from app.platform.extensions import get_identity_extension

    ext = get_identity_extension()
    maybe_identity = await ext.resolve_identity_from_token(token, request, db)
    if maybe_identity is not None:
        return maybe_identity

    # Step 4: existing JWT decode + DB lookup (unchanged)
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

```python
# Refactor get_current_user to delegate to get_optional_user (Pitfall 9 option (a))
async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Decode a JWT Bearer token (or API key) and return the authenticated Identity."""
    user = await get_optional_user(request, token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_active_user(
    current_user: Annotated[Identity, Depends(get_current_user)],
) -> Identity:
    """Ensure the current user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user
```

**Important:** the original `get_current_user()` at `auth/dependencies.py:105-166` distinguishes `jwt.ExpiredSignatureError` from generic `jwt.PyJWTError` to drive a different `WWW-Authenticate` header (silent-refresh hint). Refactoring to delegate to `get_optional_user()` LOSES this distinction unless `get_optional_user()` itself raises the more specific exception. The planner has a choice:
- **(a)** Keep `get_current_user()`'s separate JWT-decode body so the expired-token signal survives. Wire-in the extension at the top of both functions (duplication, ~6 lines).
- **(b)** Bubble the expired-vs-invalid distinction up into `get_optional_user()` somehow. Probably not worth it — `get_optional_user()` returning None is the contract.

**Recommend (a)**. The extension wire-in is 6 lines duplicated; the expired-token UX is a real product behavior. Pitfall 9 stands but the recommended option is (a) (with duplication), not "delegate everything to get_optional_user." Verify this matches CONTEXT.md `<canonical_refs>` "`get_current_user()` and `get_current_active_user()` build on `get_optional_user()` in the existing pattern (per `auth/dependencies.py:169-178`)" — that line range covers `get_current_active_user` (which DOES delegate) and the comment seems to extrapolate. Re-read shows `get_current_active_user` at line 169-178 IS a thin wrapper over `get_current_user` (which itself does NOT delegate). So the existing pattern is one-level-of-delegation, not two. Phase 214's wire-in must be added to `get_optional_user()` AND to `get_current_user()` (or a refactor that delegates with expired-token preservation). Planner's call.

### Caller migration diff — the canonical pattern

```diff
 # backend/app/modules/catalog/maps/router.py
-from app.modules.auth.models import User
+from app.core.identity import Identity
 # ... other imports unchanged ...

 @router.get("/{map_id}", ...)
 async def get_map(
     map_id: uuid.UUID,
-    user: User | None = Depends(get_optional_user),
+    user: Identity | None = Depends(get_optional_user),
     db: AsyncSession = Depends(get_db),
 ) -> MapResponse:
     # body unchanged — user.id, user.username are on Identity
     ...
```

### Sites that import `User, UserRole` together — KEEP `UserRole` concrete

```diff
 # backend/app/modules/catalog/maps/service.py
-from app.modules.auth.models import User, UserRole
+from app.core.identity import Identity
+from app.modules.auth.models import UserRole

 async def list_maps_for_user(
     db: AsyncSession,
-    user: User,
+    user: Identity,
     ...
 ) -> ...:
     # The UserRole.user_id == user.id construct still works:
     # UserRole stays concrete (D-08), Identity exposes .id (D-01).
     stmt = select(...).join(UserRole, UserRole.user_id == user.id)
     ...
```

### The new architecture-guard tests

```python
# backend/tests/test_layering.py (additions)


@pytest.mark.architecture
def test_core_does_not_import_from_any_module() -> None:
    """`backend/app/core/` must never import from `app.modules.*` (Phase 214 broadening of Phase 212).

    Phase 212-03's `test_core_does_not_import_from_settings_module()` was deliberately
    narrow ("Phase 218 will broaden this guard to `from app.modules.<*>` once those
    phases land"). Phase 214 brings that broadening forward because `core/identity.py`
    is the new file that must respect it.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.",
        "backend/app/core/",
    )
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: backend/app/core/ contains imports from app.modules.* "
            "(modules must depend on core, not the reverse). Offending lines:\n"
            + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_cross_domain_does_not_import_user_from_auth_models() -> None:
    """Cross-domain code must not import the concrete `User` ORM (Phase 214 IDENT-02).

    Allowlist (D-09): auth/**, admin/**, audit/models.py (TYPE_CHECKING),
    audit/service.py (SQL-filter use — Pitfall 1), api/main.py (Base.metadata),
    ingest/tasks_raster.py (worker registration), oauth/models.py (relationship registration).
    Tests are excluded entirely.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip("git < 2.13 lacks `:!` pathspec exclusion")

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b",
            "--",
            "backend/",
            ":!backend/app/modules/auth/",
            ":!backend/app/modules/admin/",
            ":!backend/app/modules/audit/models.py",
            ":!backend/app/modules/audit/service.py",     # see Pitfall 1
            ":!backend/app/api/main.py",
            ":!backend/app/processing/ingest/tasks_raster.py",
            ":!backend/tests/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: cross-domain code imports concrete `User` from "
            "`app.modules.auth.models`. Use `Identity` from `app.core.identity` "
            "instead. Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

[CITED: existing helper signatures from Phase 213 final test_layering.py at commit `f78b0981` + `bb6e53d9` for `_has_pathspec_magic`]

### Verification commands (Phase 214 equivalents of Phase 212/213 gates)

```bash
# Gate 1: No remaining cross-domain User imports outside allowlist (SC#2)
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b" -- backend/ \
    ':!backend/app/modules/auth/' \
    ':!backend/app/modules/admin/' \
    ':!backend/app/modules/audit/models.py' \
    ':!backend/app/modules/audit/service.py' \
    ':!backend/app/api/main.py' \
    ':!backend/app/processing/ingest/tasks_raster.py' \
    ':!backend/tests/' ; test $? -eq 1

# Gate 2: New Identity import is now used by cross-domain callers (SC#1)
git grep -nE "^\s*from app\.core\.identity import (Identity|IdentityProtocol)" -- backend/app/ | wc -l
# Expected: ≥40 (the ~42 migrated sites)

# Gate 3: Architecture guard standalone (SC#1+#2 enforcement)
cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
# Expected: 6 passed (2 Phase 212 + 2 Phase 213 + 2 Phase 214)

# Gate 4: Alembic schema drift check (D-23)
cd backend && uv run alembic check
# Expected: same pre-existing procrastinate drift as Phase 212/213; zero auth-table changes

# Gate 5: Full backend test suite (SC#4)
docker compose exec api uv run pytest -m 'not perf' --tb=short -q
# Expected: ≥1999 passed, 0 failed (the post-Phase-213 floor)

# Gate 6: Ruff lint + format
cd backend && uv run ruff check app/ tests/ alembic/
cd backend && uv run ruff format --check app/ tests/ alembic/

# Gate 7: Optional pyright spot-check on the affected files (SC#5 soft per D-25)
cd backend && uv run pyright app/core/identity.py app/modules/auth/dependencies.py 2>&1 | head -30
# Expected: no new errors introduced by Phase 214 edits (pre-existing errors elsewhere are not blockers)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Cross-domain code imports concrete `User` SQLAlchemy ORM | Cross-domain code imports `Identity` (alias of `IdentityProtocol`) from `app.core.identity` | This phase (Phase 214) | 51 → 9 cross-domain coupling edges to the concrete ORM; removes a major obstacle to enterprise overlay distribution. |
| Identity backend hardcoded to JWT + DB lookup | `IdentityExtension` Protocol + entry-point seam allows alternate backends | This phase | Phase 217 SAML overlay registers without modifying core. |
| Layering guard covers settings + auth.visibility | Layering guard covers all `core → modules.*` AND cross-domain `User` imports | This phase | `test_layering.py` grows from 4 → 6 architecture tests. |

**Deprecated/outdated after this phase:**
- The pattern of typing FastAPI dep parameters as `User` from `app.modules.auth.models` in cross-domain code. The architecture guard makes any reintroduction visible.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The 1965-test baseline floor is actually ≥1999 (per Phase 212-04 evidence cited in Phase 213 RESEARCH). | D-24 / Validation Architecture | Low — the floor is a lower bound; if the live count drifted higher (more tests added by quick tasks), Phase 214's gate just needs to match the new floor. [VERIFIED via Phase 212-04 commit dc785da2 "PASS, 1999/1965 baseline" and Phase 213-04 commit 05a60c65 "PASS, 1999/1999 baseline"] |
| A2 | `Phases 212+213 land cleanly before Phase 214 plan execution.** Phase 214's caller list assumes `auth/visibility.py` is gone (Phase 213) and `app.core.db.models` exists (Phase 212). | Phase Requirements | If Phase 212/213 had not landed, the caller inventory (specifically the entries for `catalog/authorization.py` and any visibility-derived patterns) would be wrong. Live grep at plan time verifies. [VERIFIED: STATE.md confirms 212+213 complete; commits 4c1ff573, 25e1e072, 25a6b957 confirm Phase 212/213 verification passed] |
| A3 | `Sequence[RoleProtocol]` covariance allows `User.roles: Mapped[list[Role]]` to satisfy the Protocol structurally. | Pitfall 3 | If pyright/mypy considers `list[Role]` not-a-`Sequence[RoleProtocol]` (variance issue), one variance fix is needed. D-25 makes this soft. [ASSUMED — would need a real pyright run on `User` against `IdentityProtocol` to verify; based on Python typing semantics where `Sequence` is covariant in its type parameter and `list[X]` is-a `Sequence[X]`, the structural conformance should hold.] |
| A4 | No enterprise overlay repo (sibling `geolens-enterprise`) imports `from app.modules.auth.models import User`. | Caller Inventory | If a sibling repo imports `User`, our migration breaks that repo's CI. The phase brief scopes Phase 214 to this repo only; planner may grep the enterprise overlay if accessible. [ASSUMED — out of scope per phase brief; mirrors Phase 212/213's same assumption.] |
| A5 | `audit/service.py:24` is correctly classified as a SQL-filter use site (Pitfall 1), not a TYPE_CHECKING import. | Pitfall 1 | If the planner skips Pitfall 1's recommendation and treats audit/service.py as a normal migrate site, audit-search SQL queries will break at runtime. [VERIFIED — read audit/service.py:1-46 directly; confirmed line 24 import is in function body, used at line 43 for `select(User.id).where(User.username.ilike(pattern))`. CONTEXT.md misclassifies; this RESEARCH overrides.] |

**If this table is empty:** All claims would be verified or cited. Five assumptions/discoveries flagged above; planner should review them before locking the plan.

## Open Questions

1. **Replace narrow Phase 212 guard or supplement?**
   - What we know: D-18 / Claude's Discretion punts to the planner. The broader `test_core_does_not_import_from_any_module()` subsumes `test_core_does_not_import_from_settings_module()`. Keeping both produces redundant failures with redundant messages.
   - What's unclear: Whether the Phase 212 docstring update would be cleaner if the narrow test stays (it's a precise failure pointer for the LAYER-01 audit finding).
   - Recommendation: **REPLACE** the narrow with the broad. Update the docstring to credit Phases 212+214. The broader test's failure message mentions `app.modules.*` which is informative enough; if a future regression is specifically the settings module re-importing core, the failure shows `from app.modules.settings import ...` in the offending line, restoring the LAYER-01 specificity. Default per CONTEXT.md.

2. **Refactor `get_current_user()` to delegate to `get_optional_user()`?**
   - What we know: Pitfall 9 / Code Examples discuss this. The existing `get_current_user()` does NOT delegate today (it has its own JWT-decode body that distinguishes expired-token from invalid-token).
   - What's unclear: Whether preserving the expired-token UX (which raises a different `WWW-Authenticate` header for silent refresh) is worth the duplicated extension wire-in.
   - Recommendation: **Duplicate the wire-in** (~6 lines in two functions) to preserve the expired-token UX. Phase 214's scope is structural typing + extension seam, not auth-flow refactoring. A unified-flow refactor is a separate concern.

3. **`audit/service.py` allowlist vs. import-keep?**
   - What we know: Pitfall 1 above — line 24 is a SQL-filter use site, not a TYPE_CHECKING import.
   - What's unclear: Whether to add `audit/service.py` to the architecture-guard `:!` exclusion list (option a) or leave the import unchanged but document why (option b).
   - Recommendation: **Option (a) — add to allowlist.** Option (b) is fragile to future edits; option (a) makes the exception visible in the test.

4. **`Sequence[RoleProtocol]` vs `list[Role]` variance — is the structural conformance actually verified?**
   - What we know: SQLAlchemy `Mapped[list[Role]]` and `Sequence[RoleProtocol]` should be compatible by Python's typing semantics, but the project lacks pyright in CI.
   - What's unclear: Whether a real pyright run flags the variance.
   - Recommendation: Run `cd backend && uv run pyright app/core/identity.py app/modules/auth/models.py app/modules/auth/dependencies.py 2>&1 | head -50` ad-hoc as part of the verification gate. If a variance complaint surfaces, switch the Protocol's `roles` from `Sequence[RoleProtocol]` to `list[RoleProtocol]` (less idiomatic but exactly matches the ORM). Per D-25 (soft), this is not a CI blocker.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | ≥3.13 | — |
| `uv` | Build / test invocation | ✓ | 0.10.2 (per CI workflow) | — |
| `alembic` (in `backend/.venv/`) | D-23 drift check | ✓ | ≥1.13.0; `check` subcommand confirmed in Phase 212 | — |
| `ruff` | Lint + format | ✓ | dev dep | — |
| `pytest` ≥9.0.3 | Test suite + new arch tests | ✓ | dev dep; `architecture` marker registered after Phase 212-03 | — |
| `git` CLI | Architecture guard tests (subprocess) | ✓ on host (2.50.1 — `git --version` 2026-04-27); absent inside container by default | 2.50.1 host | `_has_git_metadata()` skip guard (designed-in); `_has_pathspec_magic()` skip for git < 2.13 |
| Docker Compose | `docker compose exec api uv run pytest` | ✓ | project standard | Direct `cd backend && uv run pytest` on host |
| `pyright` (optional) | D-25 soft / Open Question 4 | unknown | — | Not in CI; not installed by default; `npx --yes pyright` works ad-hoc |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `pyright` is optional (D-25 soft). If installed locally, run on the changed files; if not, the verification gate skips it without failing.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥9.0.3 with `anyio_mode = "auto"` / `asyncio_mode = "strict"` |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command (architecture-only, ~50ms) | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` |
| Quick run command (auth-affected slice) | `cd backend && uv run pytest tests/test_auth_*.py tests/test_layering.py tests/test_admin_*.py tests/test_audit_router.py -v --tb=short` |
| Full suite command | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` (or in CI: `uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-fail-under=58.5`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IDENT-01 (a) — `core/identity.py` defines IdentityProtocol with the 6-field surface | Static — file existence + Protocol attribute set | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module -v` (validates file exists; the broad guard would flag any `core/` regression) | ❌ Wave 0 (new test in existing file) |
| IDENT-02 (a) — All 51 cross-domain User import sites type against IdentityProtocol | Static — git grep for cross-domain `User` imports | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models -v` | ❌ Wave 0 |
| IDENT-02 (b) — User ORM still satisfies IdentityProtocol; existing flows unchanged | Full RBAC + auth regression | integration (full suite) | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | ✅ existing 1999+ tests |
| IDENT-02 (c) — JWT path unchanged | JWT login → access endpoint | integration | `cd backend && uv run pytest tests/test_auth_login.py tests/test_auth_jwt.py -v` (or whichever auth tests exist) | ✅ existing |
| IDENT-02 (d) — API key path unchanged | header / query API key resolution | integration | `cd backend && uv run pytest tests/test_auth_api_key.py -v` | ✅ existing |
| IDENT-02 (e) — OAuth/OIDC path unchanged | OAuth callback → user resolution | integration | `cd backend && uv run pytest tests/test_auth_oauth.py -v` | ✅ existing |
| IDENT-02 (f) — Refresh-token path unchanged | refresh-token rotation | integration | `cd backend && uv run pytest tests/test_auth_refresh.py -v` | ✅ existing |
| IDENT-03 (a) — Extension hook callable on every request | Default returns None; existing JWT path runs | integration | full suite (extension is silent) | ✅ existing |
| IDENT-03 (b) — `get_identity_extension()` typed accessor returns IdentityExtension | Direct unit test on the accessor | unit | `cd backend && uv run pytest tests/test_extensions.py::test_get_identity_extension -v` (NEW) | ❌ Wave 0 (small new test) |
| SC#5 (soft) — pyright reports no new errors | Optional ad-hoc | manual | `cd backend && npx --yes pyright app/core/identity.py app/modules/auth/dependencies.py` | manual |
| Schema drift check (D-23) | `alembic check` exits 0 with no auth-table changes | smoke (CLI) | `cd backend && uv run alembic check` | ✅ alembic CLI exists |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_layering.py tests/test_extensions.py -v` (~30s — covers arch guards + new accessor unit test if added)
- **Per wave merge:** `cd backend && uv run pytest tests/test_layering.py tests/test_auth_*.py tests/test_admin_*.py tests/test_audit_*.py tests/test_extensions.py -v --tb=short` (~3-5min — auth + admin + audit + extensions slice)
- **Phase gate:** Full suite green (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q`) AND `cd backend && uv run alembic check` returns no auth-table changes AND `git grep` Gate 1 returns rc=1 BEFORE `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] Two new tests in `backend/tests/test_layering.py` — `test_core_does_not_import_from_any_module` and `test_cross_domain_does_not_import_user_from_auth_models` (Pattern 5 + Code Example above). Added in Wave 4 (architecture-guard plan), not Wave 1.
- [ ] One small new test in `backend/tests/test_extensions.py` — `test_get_identity_extension_returns_default_when_unregistered` (verifies typed accessor falls back to `DefaultIdentityExtension`). Optional but cheap.
- [ ] `test_layering.py` module docstring update (D-20) — credits Phase 214.
- [ ] No new pytest markers required. `architecture` already registered.

*(Existing test infrastructure covers all auth-flow behavior parity requirements — no Wave 0 gaps for IDENT-02 (c)/(d)/(e)/(f).)*

## Security Domain

> Phase touches the auth dep chain and the extension registration seam. Security domain is in scope.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | **yes** (extension seam introduced) | The default extension returns None → existing JWT/API-key/OAuth flows unchanged. The extension hook is bearer-token only (D-17). |
| V3 Session Management | no | No session-handling changes. |
| V4 Access Control | no | RBAC matrix unchanged. `require_permission()` / `require_role()` build on `get_current_active_user()` which now returns `Identity`; structural subtyping preserves all access-control semantics. |
| V5 Input Validation | no | Token decode unchanged in default path. |
| V6 Cryptography | no | No crypto code added. JWT secret + algorithm unchanged. |

### Known Threat Patterns for FastAPI / SQLAlchemy / Python backend

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Stale Identity from extension cache | Spoofing / Elevation of Privilege | The extension's contract documents a freshness expectation. Phase 214's wire-in calls `get_current_active_user()` which re-checks `is_active` for any path that requires an active user. Any extension implementation owns its own freshness semantics. |
| Extension hijack — overlay returns spoofed Identity | Spoofing | The `geolens.extensions` entry-point group is loaded at startup from installed Python packages. Untrusted packages should not be installed in production. Same trust boundary as `pip install`. The community edition's default returns None, never a spoofed identity. |
| Authorization bypass via missed `User → Identity` migration | Elevation of Privilege | Three-layer defense: ruff F821 (unresolved name) → architecture-guard test (`test_cross_domain_does_not_import_user_from_auth_models`) → full pytest run (RBAC integration tests pass). All three must pass for CI green. |
| Information disclosure via Protocol attribute leak | Information Disclosure | `IdentityProtocol` exposes only the 6 fields cross-domain code reads. Sensitive fields (`password_hash`, `auth_provider`, `last_login_at`) are NOT on the Protocol; cross-domain code that tries to read them gets a typing error at lint time (`Identity` does not have attribute `password_hash`) — would also fail at runtime since the Protocol declares only the 6 attributes. |
| Async-vs-sync extension method mismatch | DoS (request hangs) | Pitfall 8 above — `DefaultIdentityExtension.resolve_identity_from_token` MUST be `async def`. CI test catches this on first request. |

**Specific note:** the `_resolve_api_key()` precedence (header > query > JWT > anonymous) is preserved by D-15 (extension is consulted only in the bearer-token branch, AFTER API-key resolution). The CLAUDE.md note about the API-key query-param fallback (`?api_key=<key>` excluded from property filters in OGC and Features routers) is unaffected — Phase 214 doesn't touch the API-key code path.

## Sources

### Primary (HIGH confidence)
- [`backend/app/modules/auth/models.py`] full file (137 lines) read 2026-04-27 — confirms `User` exposes 6-field surface with matching types, `Role.name: Mapped[str]` exposed.
- [`backend/app/modules/auth/dependencies.py`] full file (272 lines) read 2026-04-27 — confirms `_resolve_api_key()` precedence, JWT decode body, expired-token UX, `get_cached_user_roles()` request-state caching, `require_role()` / `require_permission()` factories.
- [`backend/app/modules/auth/providers/__init__.py`] full file read 2026-04-27 — confirms `AuthProvider` Protocol + `AuthenticatedIdentity` dataclass are DIFFERENT surface from `IdentityProtocol`.
- [`backend/app/modules/auth/oauth/service.py`] lines 1-150 read 2026-04-27 — confirms `find_or_create_oauth_user()` at line 138 returns `User` (concrete).
- [`backend/app/platform/extensions/__init__.py`] full file (62 lines) read 2026-04-27 — confirms `_extensions: dict[str, object]`, `load_extensions()`, `get_extension()`, `has_extension()`. **CONFIRMS `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` DO NOT EXIST** (zero hits in `grep -rn "get_branding_extension\|get_audit_extension\|get_auth_extension" backend/`). [VERIFIED: 2026-04-27]
- [`backend/app/platform/extensions/protocols.py`] full file (29 lines) read 2026-04-27 — confirms "Uses only stdlib types to avoid circular imports with domain models" docstring discipline; `BrandingExtension`, `AuditExtension`, `AuthExtension` Protocols are `@runtime_checkable`.
- [`backend/app/platform/extensions/defaults.py`] full file (24 lines) read 2026-04-27 — confirms three sync Default extensions; Phase 214 adds an async one.
- [`backend/app/api/main.py`] full file (476 lines) read 2026-04-27 — confirms startup chain: `load_extensions()` (line 125) → `init_edition()` (line 126) → mount routers (line 134-135). `User`, `Role`, `UserRole` imported at line 26 for `Base.metadata` + `seed_initial_admin()`.
- [`backend/app/modules/audit/service.py`] lines 1-50 read 2026-04-27 — **CONFIRMS line 24 is a function-scope import for SQL-filter use, not TYPE_CHECKING.** `User.id` and `User.username` used at line 43 inside `select(User.id).where(User.username.ilike(pattern))`. [VERIFIED — overrides CONTEXT.md classification]
- [`backend/app/modules/audit/router.py`] lines 28-95 read 2026-04-27 — confirms line 32 (NOT 31 as CONTEXT.md says) is the `from app.modules.auth.models import User` import; line 51, 94 use `user: User = Depends(...)` parameter annotations.
- [`backend/app/modules/audit/models.py`] lines 5-12 read 2026-04-27 — confirms `if TYPE_CHECKING:` block contains `from app.modules.auth.models import User` for the `Mapped["User"]` relationship.
- [`backend/app/modules/embed_tokens/service.py`] lines 305-320 read 2026-04-27 — confirms function-scope deferred import at line 312.
- [`backend/app/processing/tiles/router.py`] lines 208-220 read 2026-04-27 — confirms function-scope deferred `from app.modules.auth.models import UserRole` at line 213 (NOT `User`).
- [`backend/app/modules/admin/service.py`] lines 290-300 read 2026-04-27 — confirms function-scope `from app.modules.auth.models import User as UserModel` at line 296.
- [`backend/pyproject.toml`] lines 1-95 read 2026-04-27 — confirms Python 3.13+, FastAPI ≥0.115.0, SQLAlchemy ≥2.0.25, pytest ≥9.0.3, ruff dev dep, no pyright/mypy. **Architecture marker NOT registered on this branch** (the marker is registered on the post-Phase-212-03 branch — verified via `git show f78b0981:backend/pyproject.toml`).
- [`backend/tests/test_layering.py`] from Phase 213 final commit `f78b0981` (180 lines) read 2026-04-27 — confirms `_has_git_metadata()`, `_has_pathspec_magic()`, `_git_grep()` helpers; 4 existing architecture tests; `:!` pathspec exclusion pattern.
- [Live grep] `git grep -nE "from app\.modules\.auth\.models import" -- backend/app/` 2026-04-27 — returns 53 import lines across the files listed in Caller Inventory.
- [Live grep] `grep -rn "user\.\(password_hash\|auth_provider\|last_login_at\|status\|updated_at\)" backend/app/` 2026-04-27 — confirms non-Identity attribute access is confined to allowlisted modules (auth/**, admin/**).
- [audit] `docs-internal/audits/oc-separation-audit-20260426.md` lines 271, 330 — primary directive (51 cross-domain User import sites, Protocol with 4-field minimum surface).
- [audit] `docs-internal/audits/oc-separation-audit-20260426-b.md` lines 24, 266, 325 — supplementary directive (mentions `is_admin` — rejected per D-02; mentions retypeing FastAPI deps — implemented per D-07).
- [audit] `docs-internal/audits/oc-separation-deferred-items-20260426.md` line 12 — P1 spec row.
- [Phase 212-04 commit `dc785da2`] "PASS, 1999/1965 baseline" — confirms live test floor is 1999.
- [Phase 213-04 commit `05a60c65`] "PASS, 1999/1999 baseline, 4 arch guards" — confirms test count + architecture-guard count after Phase 213.

### Secondary (MEDIUM confidence)
- [Context7 / `/python/cpython`] "typing.Protocol - Runtime Checkability" — confirms `@runtime_checkable` requirement for data-only Protocols since Python 3.10. [CITED 2026-04-27]
- [Context7 / `/python/cpython`] "@runtime_checkable Decorator" usage examples — confirms attribute-based Protocols work with `isinstance()` after `@runtime_checkable`. [CITED 2026-04-27]
- [Context7 / `/fastapi/fastapi`] "Declare dependency with Annotated and Depends" — confirms FastAPI uses `Depends()` argument for resolution and the type annotation is for editor support / static checkers. Dependency return-type retype does not affect runtime. [CITED 2026-04-27]
- [PEP 544 — Protocols: Structural subtyping (static duck typing)] — the canonical reference for the typing semantics Phase 214 relies on. Implicit conformance, attribute-based protocols, runtime-checkable extension. [CITED via stdlib typing docs]
- [PEP 563 — Postponed evaluation of annotations] — the `from __future__ import annotations` convention. [CITED via Python typing docs]
- [Phase 212 RESEARCH.md] (commit `e8bc9cb8`) — pitfall list and codebase-pattern survey reused (Pitfall 4 `_has_git_metadata`, Pitfall 6 stale `__pycache__`).
- [Phase 213 RESEARCH.md] (commit `d1709bdd`) — pitfall list and `:!` pathspec pattern reused (Pitfall 3 self-positive bug, Pitfall 5 git-version skip).

### Tertiary (LOW confidence)
- A4 (enterprise overlay assumption) — not verified against sibling repo.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies verified in `pyproject.toml`; Python typing.Protocol semantics verified via Context7.
- Architecture: HIGH — caller inventory from live grep 2026-04-27, file shapes from direct reads, extension scaffold pattern from direct read.
- Pitfalls: HIGH for 1, 2, 4, 5, 6, 7, 8 (all backed by direct code reads or prior-phase commit evidence); MEDIUM for 3 (Sequence variance — depends on a real pyright run); HIGH for 9, 10 (read directly from `auth/dependencies.py`).
- Caller inventory: HIGH — live grep 2026-04-27 returned 53 lines; allowlist verified against actual file content; three CONTEXT.md errors documented (audit/router line number, audit/service classification, missing typed accessors).
- Validation Architecture: HIGH — framework + test-corpus assumptions verified by Phase 212-04 / 213-04 evidence.
- Security Domain: HIGH — STRIDE table grounded in actual code paths.

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (30 days; codebase is stable, but the live test floor could drift higher from concurrent quick tasks; planner re-runs `git grep` at plan-execution time per D-11).

---

## RESEARCH COMPLETE

**Phase:** 214 - identity-protocol-extract
**Confidence:** HIGH

### Key Findings

1. **Three CONTEXT.md errors discovered that the planner MUST reconcile:**
   - **`audit/service.py:24` is a SQL-filter use site, NOT a TYPE_CHECKING import.** Migrating it to `Identity` would break `select(Identity.id).where(Identity.username.ilike(...))` at runtime because `Identity` is a Protocol (no `InstrumentedAttribute` descriptors). Recommend adding `audit/service.py` to the architecture-guard allowlist (Pitfall 1, Open Question 3).
   - **`audit/router.py` import is at line 32, not line 31** as CONTEXT.md says.
   - **The typed accessors `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` DO NOT EXIST** in the actual codebase — verified via `grep -rn`. CONTEXT.md "Reusable Assets" describes an aspirational pattern. Phase 214 creates the FIRST typed accessor of this shape (Pitfall 2).

2. **`User` ORM already exposes the exact 6-field surface IdentityProtocol requires** with matching types: `id: Mapped[uuid.UUID]`, `username: Mapped[str]`, `email: Mapped[str | None]`, `is_active: Mapped[bool]`, `created_at: Mapped[datetime]`, `roles: Mapped[list["Role"]]` (selectin-loaded). `Role.name: Mapped[str]` satisfies `RoleProtocol` structurally. ZERO ORM modifications required (D-06).

3. **Cross-domain access to non-Identity User attributes (`password_hash`, `auth_provider`, `last_login_at`, `status`, `updated_at`) is confined to allowlisted modules** (auth/**, admin/**) — verified by live grep. Migration is safe; the Protocol surface is sufficient.

4. **Live caller inventory: 53 import lines** across `backend/app/`, of which ~42 migrate to `Identity` and ~11 are allowlisted. Two function-scope deferred imports (`embed_tokens/service.py:312`, `audit/service.py:24`) — the first migrates with path-only rewrite, the second stays concrete per Pitfall 1.

5. **Architecture guard pattern is fully established** by Phases 212+213. Phase 214 reuses `_has_git_metadata()`, `_has_pathspec_magic()`, `_git_grep()` helpers verbatim. The `architecture` pytest marker is registered after Phase 212-03 (verified via `git show f78b0981:backend/pyproject.toml`).

6. **Refactoring `get_current_user()` to delegate to `get_optional_user()` is risky** — would lose the expired-token vs. invalid-token UX distinction (different `WWW-Authenticate` headers for silent-refresh hints). Recommend duplicating the extension wire-in (~6 lines) in both functions instead (Pitfall 9, Open Question 2).

### File Created
`.planning/phases/214-identity-protocol-extract/214-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | All deps verified in pyproject.toml; Protocol semantics from Context7. |
| Architecture | HIGH | Live grep + direct file reads; CONTEXT.md errors caught and documented. |
| Pitfalls | HIGH | 9 of 10 backed by direct code reads or prior-phase evidence; one (Pitfall 3 variance) is MEDIUM. |
| Caller Inventory | HIGH | Live grep 2026-04-27; 53 lines confirmed; line numbers re-verified against actual files. |
| Validation Architecture | HIGH | Test corpus + commands verified by Phase 212-04 / 213-04 evidence. |
| Security Domain | HIGH | STRIDE table grounded in real code paths. |

### Open Questions

1. Replace narrow Phase 212 guard or supplement? (Recommend REPLACE per default.)
2. Refactor `get_current_user()` to delegate to `get_optional_user()`? (Recommend NO — duplicate the wire-in to preserve expired-token UX.)
3. Add `audit/service.py` to architecture-guard allowlist? (Recommend YES per Pitfall 1.)
4. `Sequence[RoleProtocol]` vs `list[RoleProtocol]` variance — verified by pyright? (Recommend ad-hoc pyright spot-check; soft per D-25.)

### Ready for Planning
Research complete. Planner can now create PLAN.md files. The three CONTEXT.md error reconciliations (Key Finding #1) should be the planner's first review action; everything else flows from D-01..D-27 as documented.
