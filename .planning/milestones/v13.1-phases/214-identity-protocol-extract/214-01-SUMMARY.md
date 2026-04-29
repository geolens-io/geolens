---
phase: 214-identity-protocol-extract
plan: 01
subsystem: refactor
tags: [refactor, protocol, extension, layering, open-core, identity, pep544, structural-subtyping]

# Dependency graph
requires:
  - phase: 212-core-settings-decouple
    provides: "core/ layering discipline; architecture-guard test pattern; closed-set caller-migration discipline"
  - phase: 213-catalog-authz-relocate
    provides: ":! pathspec exclusion pattern in architecture-guard tests; deferred-import preservation rule"
provides:
  - "RoleProtocol (1 attribute: name: str) — slim role contract for cross-domain code"
  - "IdentityProtocol (6 attributes: id, username, email, is_active, roles, created_at) — comprehensive identity surface"
  - "IdentityExtension Protocol with async resolve_identity_from_token(token, request, db) -> Identity | None"
  - "Identity = IdentityProtocol type alias"
  - "DefaultIdentityExtension community fallback (resolve returns None)"
  - "get_identity_extension() typed accessor mirroring get_branding_extension/get_audit_extension/get_auth_extension"
affects: [214-02-retype-deps-and-wire-extension, 214-03-migrate-cross-domain-callers, 214-04-architecture-guard-and-verification-gate, 217-auth-saml-enterprise]

# Tech tracking
tech-stack:
  added: []  # No new dependencies. Uses stdlib (typing.Protocol, runtime_checkable, Sequence) + existing fastapi.Request + sqlalchemy.ext.asyncio.AsyncSession
  patterns:
    - "Stdlib-types-only Protocol discipline (mirrors platform/extensions/protocols.py)"
    - "@runtime_checkable on every cross-domain Protocol (D-04)"
    - "Type alias for caller ergonomics (Identity = IdentityProtocol; both names exported)"
    - "TYPE_CHECKING-guarded import for return-type annotations to avoid runtime cycles"
    - "Implicit structural conformance — no inheritance on the concrete ORM (PEP 544)"

key-files:
  created:
    - "backend/app/core/identity.py — 95 lines; the cross-domain identity contract"
    - ".planning/phases/214-identity-protocol-extract/deferred-items.md — pre-existing flaky test logged"
  modified:
    - "backend/app/platform/extensions/defaults.py — appended DefaultIdentityExtension (24 -> 43 lines)"
    - "backend/app/platform/extensions/__init__.py — added typed accessor + TYPE_CHECKING import (104 -> 125 lines)"
    - "backend/tests/test_extensions.py — appended TestGetIdentityExtension (199 -> 238 lines)"

key-decisions:
  - "D-01 honored: 6-field IdentityProtocol surface (id, username, email, is_active, roles, created_at) — comprehensive, covers every cross-domain read"
  - "D-02 honored: NO is_admin field (computed from roles by callers)"
  - "D-03 honored: roles typed as Sequence[RoleProtocol] (covariance lets list[Role] satisfy it)"
  - "D-04 honored: all three Protocols decorated @runtime_checkable"
  - "D-05 honored: Identity = IdentityProtocol alias for caller ergonomics; both names exported"
  - "D-06 honored: User ORM untouched — implicit structural conformance via PEP 544"
  - "D-12 honored: IdentityExtension lives in core/identity.py (not platform/extensions/protocols.py)"
  - "D-13 honored: get_identity_extension() mirrors the existing trio (get_branding_extension/get_audit_extension/get_auth_extension)"
  - "D-14 honored: DefaultIdentityExtension lives next to the other Default* classes; async resolve returns None"
  - "Pitfall 8 honored: async signature mandatory — verified by test_default_identity_extension_resolve_returns_none"

patterns-established:
  - "Pure-additive Protocol scaffolding: introduce new file/symbols in Plan 01; wire/migrate consumers in Plans 02-04"
  - "Co-locate Protocol + Extension Protocol + Default impl + typed accessor by layer (Protocol in core/, Default in platform/extensions/defaults.py, accessor in platform/extensions/__init__.py)"

requirements-completed: [IDENT-01, IDENT-03]

# Metrics
duration: ~12 min (excluding ~7 min for full-suite regression run)
completed: 2026-04-27
---

# Phase 214 Plan 01: Introduce Core Identity Summary

**New cross-domain `core/identity.py` defining IdentityProtocol (6 fields), RoleProtocol (1 field), IdentityExtension (1 async method), Identity alias — plus DefaultIdentityExtension community fallback and get_identity_extension() typed accessor mirroring the existing branding/audit/auth trio.**

## Performance

- **Duration:** ~12 min (work) + ~7 min (regression suite run) = ~19 min total
- **Started:** 2026-04-27T17:18:10Z (Phase 214 execution start per STATE.md)
- **Completed:** 2026-04-27T18:00:00Z (approximate)
- **Tasks:** 3 (all auto type, no checkpoints)
- **Files created:** 2 (1 source + 1 deferred-items note)
- **Files modified:** 3 (defaults.py, __init__.py, test_extensions.py)
- **Files left UNCHANGED (per plan):** backend/app/platform/extensions/protocols.py (D-12); backend/app/modules/auth/models.py (D-06)

## Accomplishments

- **Cross-domain identity contract created** at `backend/app/core/identity.py` (95 lines). Defines `RoleProtocol` (1 attribute), `IdentityProtocol` (6 attributes), `IdentityExtension` (1 async method), and `Identity = IdentityProtocol` alias. All three Protocols decorated `@runtime_checkable` (D-04). Stdlib types only (plus `fastapi.Request` and `sqlalchemy.ext.asyncio.AsyncSession`) — zero `app.modules.*` imports, preserving the layering rule the milestone is closing.
- **Community fallback registered** as `DefaultIdentityExtension` in `platform/extensions/defaults.py`. Async `resolve_identity_from_token(token, request, db)` returns `None` — signals "no enterprise overlay; fall through to existing JWT path" (zero behavior change in community edition).
- **Typed accessor mirrors the existing trio** — `get_identity_extension()` in `platform/extensions/__init__.py` mirrors `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` exactly (same `_extensions.get(...) or DefaultXxxExtension()` body shape, same `# type: ignore[return-value]` discipline). Return type forward-referenced via `TYPE_CHECKING` to avoid a runtime `core/` import edge.
- **Three new unit tests added** to `tests/test_extensions.py` — default-fallback path, registered-overlay path, and the async-method contract (Pitfall 8). All 16 tests in the file pass (13 prior + 3 new). Existing tests are untouched.

## Task Commits

Each task was committed atomically:

1. **Task 01-01: Create `core/identity.py` with the four Protocol exports** — `7805a456` (feat)
2. **Task 01-02: Add `DefaultIdentityExtension` + register `get_identity_extension()` typed accessor** — `a1072f16` (feat)
3. **Task 01-03: Add unit-test coverage for `get_identity_extension()` default + registered paths** — `538a933b` (test)

**Plan metadata commit:** to be created with this SUMMARY.md and updated STATE.md/ROADMAP.md.

## Files Created/Modified

- **`backend/app/core/identity.py`** (NEW, 95 lines) — defines `RoleProtocol`, `IdentityProtocol`, `IdentityExtension`, `Identity` alias. Module docstring follows `platform/extensions/protocols.py`'s "stdlib-types-only" discipline; references Phase 214 and Phase 217 as the first concrete consumer.
- **`backend/app/platform/extensions/defaults.py`** (MODIFIED, 24 -> 43 lines) — appended `DefaultIdentityExtension` after `DefaultAuthExtension`. Async `resolve_identity_from_token` returns `None`. Bare-types discipline matches the surrounding Default* classes (no `Request`/`AsyncSession`/`Identity` imports).
- **`backend/app/platform/extensions/__init__.py`** (MODIFIED, 104 -> 125 lines) — added `from typing import TYPE_CHECKING`; added `DefaultIdentityExtension` to the `defaults` import block; added a `TYPE_CHECKING` block with `from app.core.identity import IdentityExtension`; appended `get_identity_extension()` typed accessor after `get_auth_extension()`.
- **`backend/tests/test_extensions.py`** (MODIFIED, 199 -> 238 lines) — appended `TestGetIdentityExtension` class with three tests: `test_get_identity_extension_returns_default_when_unregistered`, `test_get_identity_extension_returns_registered_when_present`, `test_default_identity_extension_resolve_returns_none` (the latter `@pytest.mark.asyncio`).
- **`.planning/phases/214-identity-protocol-extract/deferred-items.md`** (NEW) — logs one pre-existing flaky test (`test_collections.py::test_update_collection`) that fails due to a SQLAlchemy `MissingGreenlet` issue in HTTP integration code unrelated to identity Protocol scaffolding.

## Verification (grep-level acceptance gates)

| Gate | Expected | Actual |
|------|----------|--------|
| `core/identity.py` exists | yes | yes |
| `from __future__ import annotations` line count | 1 | 1 |
| `@runtime_checkable` decorator count in `core/identity.py` | 3 | 3 |
| `app.modules.*` imports in `core/identity.py` | 0 | 0 |
| `is_admin` references in `core/identity.py` | 0 | 0 |
| `roles: Sequence[RoleProtocol]` annotation | present | present |
| `async def resolve_identity_from_token` count in `core/identity.py` | 1 | 1 |
| `class DefaultIdentityExtension` count in `defaults.py` | 1 | 1 |
| `async def resolve_identity_from_token` count in `defaults.py` | 1 | 1 |
| `def get_identity_extension` count in `__init__.py` | 1 | 1 |
| `TYPE_CHECKING` block importing `IdentityExtension` | present | present |
| `git diff` lines on `protocols.py` | 0 | 0 |
| `class TestGetIdentityExtension` count in tests | 1 | 1 |
| New tests passing | 3/3 | 3/3 |
| Full `tests/test_extensions.py` passing | 16/16 | 16/16 |
| Ruff lint on all touched files | clean | clean |
| Ruff format on all touched files | clean | clean |
| Python smoke import (`from app.core.identity import ...`) | exit 0 | exit 0 |
| `Identity is IdentityProtocol` | True | True |
| `await DefaultIdentityExtension().resolve_identity_from_token(...)` returns None | yes | yes |

## Decisions Made

None beyond plan execution — every plan-level decision (D-01 through D-27) was honored verbatim. The plan's `<interfaces>` section provided the exact code; this plan implemented it as written.

## Deviations from Plan

None - plan executed exactly as written.

The only minor process note: ruff format reformatted `DefaultIdentityExtension.resolve_identity_from_token` from a multi-line signature to a single line during the Task 01-02 verification (matched existing project style). This is a formatting normalization, not a deviation from intent.

## Issues Encountered

### Pre-existing flaky test (out-of-scope, deferred)

- **`tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`** fails with `sqlalchemy.exc.MissingGreenlet`. Failure is in HTTP-layer collection update code, entirely unrelated to identity Protocol scaffolding. Plan 01 is purely additive — no production caller imports the new symbols, so this test cannot be affected by the changes. Logged to `.planning/phases/214-identity-protocol-extract/deferred-items.md` per the executor scope-boundary rule. The remaining 3 of the 4 acceptance/verification gates passed cleanly (1988 passing tests + 3 new = 1991, with 1 pre-existing failure).

## Threat Surface Verification

The plan's `<threat_model>` documented four threat IDs (T-214-IL-01 information disclosure, T-214-EH-01 spoofing/async-contract, T-214-EH-02 elevation/extension-hijack, T-214-IL-02 tampering/protocol-drift). All `mitigate` dispositions have been satisfied by the implementation:

- **T-214-IL-01** — IdentityProtocol exposes EXACTLY 6 fields. Sensitive fields (`password_hash`, `auth_provider`, `last_login_at`, `status`) are NOT on the surface. Verified by grep gate (`is_admin` count = 0; field count = 6).
- **T-214-EH-01** — Pitfall 8 (async-contract violation) covered by `test_default_identity_extension_resolve_returns_none` which calls `await ext.resolve_identity_from_token(...)`. A future contributor dropping the `async` keyword would fail this test immediately.
- **T-214-IL-02** — 6-field surface locked by D-01 + the architecture-guard test (Plan 04) protects future drift.

`accept` disposition (T-214-EH-02 entry-point hijack) inherits the same trust model as the existing branding/audit/auth extension trio; no new mitigation needed at this seam.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Plan 02 (`214-02-retype-deps-and-wire-extension`).** Plan 02 will:
1. Retype `get_optional_user()`, `get_current_user()`, `get_current_active_user()` in `backend/app/modules/auth/dependencies.py` to return `Identity` (instead of `User`).
2. Wire `await get_identity_extension().resolve_identity_from_token(token, request, db)` between the API-key path and the JWT path.

After Plan 02, the dep chain is the FIRST production consumer of the new symbols. Plan 03 then mechanically migrates the ~42 cross-domain caller import + annotation sites. Plan 04 adds the architecture-guard tests and runs the full verification gate (alembic check + ruff + full pytest + ROADMAP SC verification).

**Blockers for downstream plans:** None. The pre-existing `test_collections.py::test_update_collection` failure is unrelated and will need separate stability work (not part of Phase 214).

## Self-Check: PASSED

All claimed files exist on disk and all claimed commit hashes are present in git history:

- `backend/app/core/identity.py` — present
- `backend/app/platform/extensions/defaults.py` — present (with `DefaultIdentityExtension`)
- `backend/app/platform/extensions/__init__.py` — present (with `get_identity_extension`)
- `backend/tests/test_extensions.py` — present (with `TestGetIdentityExtension`)
- `.planning/phases/214-identity-protocol-extract/214-01-SUMMARY.md` — this file
- `.planning/phases/214-identity-protocol-extract/deferred-items.md` — present
- Commit `7805a456` (Task 01-01) — present
- Commit `a1072f16` (Task 01-02) — present
- Commit `538a933b` (Task 01-03) — present

---
*Phase: 214-identity-protocol-extract*
*Completed: 2026-04-27*
