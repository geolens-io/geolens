---
phase: 214-identity-protocol-extract
plan: 02
subsystem: refactor
tags: [refactor, auth, fastapi, protocol, extension, identity, pep544]

# Dependency graph
requires:
  - phase: 214-identity-protocol-extract
    plan: 01
    provides: "core/identity.py with Identity/IdentityProtocol/IdentityExtension; get_identity_extension() typed accessor; DefaultIdentityExtension community fallback"
provides:
  - "Retyped FastAPI dependencies: get_optional_user / get_current_user / get_current_active_user now return Identity (alias of IdentityProtocol) instead of the concrete User ORM"
  - "Retyped factory inner closures: _role_checker (require_role) and _permission_checker (require_permission) take Identity and return Identity"
  - "Retyped get_cached_user_roles param `user` to Identity | None"
  - "Live extension consumer: IdentityExtension is now consulted on EVERY authenticated request via both get_optional_user and get_current_user (Pitfall 9 duplicated wire-in to preserve expired-token UX)"
affects: [214-03-migrate-cross-domain-callers, 214-04-architecture-guard-and-verification-gate, 217-auth-saml-enterprise]

# Tech tracking
tech-stack:
  added: []  # No new dependencies
  patterns:
    - "Bearer-token-only extension wire-in (D-17 — API keys remain a community concern)"
    - "Wire-in duplication across get_optional_user + get_current_user (Pitfall 9 / Plan 02 must_haves) — preserves RFC-6750 silent-refresh hint by leaving each function's distinct JWT-decode body intact"
    - "Structural subtyping cross-domain pass-through: User IS-A Identity (PEP 544), so existing call sites with `user: User` parameters continue to receive runtime-correct values until Plan 03 sweeps the annotations"

key-files:
  created: []
  modified:
    - "backend/app/modules/auth/dependencies.py — retyped 5 callable annotations + added 2 wire-in blocks (272 -> 297 lines)"

key-decisions:
  - "D-07 (part 1) honored: three FastAPI deps now return Identity instead of concrete User; runtime objects are still User instances (structural subtyping makes the assignment safe)"
  - "D-15 wire-in order honored exactly: (1) API key, (2) extension call when bearer token exists, (3) JWT decode + DB lookup, (4) None"
  - "D-15 + Pitfall 9 honored: wire-in DUPLICATED in get_optional_user AND get_current_user rather than refactoring get_current_user to delegate. Preserves the jwt.ExpiredSignatureError -> 401 with `WWW-Authenticate: Bearer error=\"invalid_token\"` UX (RFC 6750 silent-refresh hint at lines 165-177 of the new file)"
  - "D-16 honored AFTER reconciliation: get_current_active_user takes Annotated[Identity, Depends(get_current_user)] and returns Identity. CONTEXT.md D-16 originally implied get_current_user delegates to get_optional_user — that wording is INCORRECT for the live file (verified by reading auth/dependencies.py:105-166 pre-change); both deps have their own JWT-decode body and the wire-in is added to both. The plan's must_haves explicitly call out this reconciliation."
  - "D-17 honored: extension is NOT consulted in the API-key path. Wire-in is bearer-token-only (`if token is not None:` guard before await)."
  - "Behavior preservation: _resolve_api_key() body byte-identical; its return type stays User | None (it returns the concrete ORM via api_key_obj.user)"
  - "D-09 allowlist honored: internal `from app.modules.auth.models import ApiKey, User` retained — auth/** owns User. Plan 04's architecture-guard test will not flag this file."
  - "Pitfall 6 honored: the dep retype changes return types, but every endpoint annotated `user: User = Depends(get_current_active_user)` still works at runtime (structural subtyping). Plan 03 will sweep those caller annotations."
  - "Pitfall 8 honored: wire-in uses `await ext.resolve_identity_from_token(...)`; Plan 01's DefaultIdentityExtension.resolve_identity_from_token is `async def`, so the await chain returns a real coroutine."

patterns-established:
  - "Live-consumer pattern for extension hooks: instead of waiting for an enterprise overlay to demonstrate the seam, Plan 02 makes the production dep chain itself the first consumer. Default impl returns None -> bit-identical community behavior; Phase 217's SAML overlay simply registers a non-None implementation under `_extensions['identity']` and gets request-time interception for free."
  - "Pitfall 9 reconciliation discipline: when a CONTEXT.md decision oversimplifies the live code (D-16's claim that get_current_user 'builds on' get_optional_user), the executor reads the actual file and prefers the more conservative implementation — duplicating the 6-line wire-in across both deps preserves a documented product UX (RFC-6750 silent-refresh hint) without forcing a behavior-changing refactor of the JWT decode body."

requirements-completed: []  # Plans 02-04 jointly satisfy IDENT-02; Plan 02 alone is partial. IDENT-03 was already completed by Plan 01 (per Plan 01 SUMMARY).
requirements-partial: [IDENT-02]

# Metrics
duration: ~10 min (work) + ~6.5 min (full-suite regression run) = ~17 min total
completed: 2026-04-27
---

# Phase 214 Plan 02: Retype Deps and Wire Extension Summary

**Retyped the three FastAPI authentication dependencies in `backend/app/modules/auth/dependencies.py` (`get_optional_user`, `get_current_user`, `get_current_active_user`) to return `Identity` instead of concrete `User`, and wired `await get_identity_extension().resolve_identity_from_token(...)` between the API-key and JWT paths in BOTH deps (Pitfall 9 — duplicated to preserve the expired-token UX). The 1988-test baseline holds; community-edition behavior is bit-identical because `DefaultIdentityExtension.resolve_identity_from_token` returns `None` and control falls through to the unchanged JWT decode path.**

## Performance

- **Duration:** ~10 min (work) + ~6.5 min (full-suite regression run) = ~17 min total
- **Started:** 2026-04-27T17:35:17Z
- **Completed:** 2026-04-27 (immediately after, in the same execution session)
- **Tasks:** 1 (auto type, no checkpoints)
- **Files created:** 0
- **Files modified:** 1 (`backend/app/modules/auth/dependencies.py`, 272 -> 297 lines, +25 lines)
- **Edits applied:** 7 (1 import-block rewrite + 6 annotation/body changes)
- **Pre-existing failure:** 1 (`tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`, same `sqlalchemy.exc.MissingGreenlet` as logged in Plan 01's `deferred-items.md` — out of scope for Plan 02 per the executor scope-boundary rule)

## Accomplishments

- **Three FastAPI deps return Identity** (instead of concrete `User`):
  - `get_optional_user(...) -> Identity | None`
  - `get_current_user(...) -> Identity`
  - `get_current_active_user(...) -> Identity` (also retyped its `current_user` parameter to `Annotated[Identity, ...]`)
- **Two factory inner closures retyped** to `Identity`:
  - `require_role(...)._role_checker` parameter `current_user: Annotated[Identity, ...]`, return `Identity`
  - `require_permission(...)._permission_checker` parameter `current_user: Annotated[Identity, ...]`, return `Identity`
- **`get_cached_user_roles` parameter retyped** — `user: Identity | None = Depends(get_optional_user)`. The downstream call `get_user_roles(db, user)` works structurally; Plan 03 retypes the callee.
- **IdentityExtension wire-in** added between the API-key path and the JWT path in BOTH `get_optional_user` (line 85) AND `get_current_user` (line 141). Pitfall 9 duplication intentionally preserves the expired-token UX (RFC 6750 silent-refresh hint at the JWT-decode body of `get_current_user`). Both wire-in blocks are structurally identical (same comment header pattern, same `if token is not None: ext_identity = await ...; if ext_identity is not None: return ext_identity` body).
- **Imports section** re-sorted to ruff's isort convention (app.core → app.modules → app.platform; alphabetical within groups). Two new imports added:
  - `from app.core.identity import Identity`
  - `from app.platform.extensions import get_identity_extension`
- **Internal `User` import retained** (`from app.modules.auth.models import ApiKey, User`). Required for SQL queries (`select(User).where(User.id == user_id)`) inside `get_optional_user` / `get_current_user` AND for `_resolve_api_key`'s relationship traversal (`api_key_obj.user`). auth/** is allowlisted per D-09 — Plan 04's architecture-guard test will not flag this.
- **`_resolve_api_key()` body byte-identical** — Plan 02 leaves it alone per D-17 (extension consulted only on bearer tokens, never on API keys). Its return type stays `User | None`.

## Task Commits

Each task was committed atomically:

1. **Task 02-01: Retype get_optional_user + get_current_user + get_current_active_user; add IdentityExtension wire-in to both** — `6a0dfe8a` (refactor)

**Plan metadata commit:** to be created with this SUMMARY.md and updated STATE.md/ROADMAP.md.

## Files Created/Modified

- **`backend/app/modules/auth/dependencies.py`** (MODIFIED, 272 → 297 lines, +25 lines)
  - Imports re-sorted; `Identity` and `get_identity_extension` added.
  - `get_optional_user` return type: `User | None` → `Identity | None`. New ~9-line wire-in inserted between API-key path and `if token is None: return None` guard.
  - `get_current_user` return type: `User` → `Identity`. New ~9-line wire-in inserted between API-key short-circuit and `credentials_exception` setup. JWT decode body (including `jwt.ExpiredSignatureError` branch with the RFC-6750 silent-refresh hint) UNCHANGED.
  - `get_current_active_user` parameter `current_user`: `Annotated[User, ...]` → `Annotated[Identity, ...]`; return type `User` → `Identity`. Body unchanged.
  - `get_cached_user_roles` parameter `user`: `User | None` → `Identity | None`.
  - `require_role._role_checker` parameter and return: `User` → `Identity`. Body unchanged.
  - `require_permission._permission_checker` parameter and return: `User` → `Identity`. Body unchanged.
  - `_resolve_api_key()` body BYTE-IDENTICAL.

## Verification (grep-level acceptance gates)

| Gate | Expected | Actual |
|------|----------|--------|
| `from app.core.identity import Identity` count | 1 | 1 |
| `from app.platform.extensions import get_identity_extension` count | 1 | 1 |
| `from app.modules.auth.models import ApiKey, User` count (allowlisted retained) | 1 | 1 |
| `await get_identity_extension().resolve_identity_from_token` count (Pitfall 9 duplicated) | 2 | 2 |
| Wire-in line numbers | n/a | line 85 (`get_optional_user`), line 141 (`get_current_user`) |
| `Annotated[Identity, Depends(get_current_active_user)]` count | 2 | 2 |
| `get_optional_user` return annotation (resolved) | `IdentityProtocol \| None` | `app.core.identity.IdentityProtocol \| None` |
| `get_current_user` return annotation (resolved) | `IdentityProtocol` | `<class 'app.core.identity.IdentityProtocol'>` |
| `get_current_active_user` return annotation (resolved) | `IdentityProtocol` | `<class 'app.core.identity.IdentityProtocol'>` |
| Ruff lint on file | clean | clean |
| Ruff format on file | clean | clean |
| Ruff isort (`--select=I`) | clean | clean |
| Python smoke import (`from app.modules.auth.dependencies import ...`) | exit 0 | exit 0 |
| `tests/test_extensions.py` (Plan 01 regression) | 16/16 pass | 16/16 pass |
| Auth slice (`pytest -k "auth or jwt or api_key or login or refresh or oauth"`) | all pass | 219 passed, 1 skipped, 0 failed |
| Full suite (`pytest -m "not perf"`) | ≥1988 passing | 1988 passed, 17 skipped, 1 pre-existing failure |

## Decisions Made

None beyond plan execution — every plan-level decision (D-07, D-15, D-16-reconciled, D-17) was honored verbatim. The plan's `<interfaces>` section provided the exact code for each of the 7 edits; this plan implemented it as written.

One minor process note: the plan estimated `+16 lines` for the file growth budget; actual is `+25 lines` because ruff's wrapping convention split the wire-in's `await ...resolve_identity_from_token(token, request, db)` call across multiple lines (matching project format). Same logic, more verbose layout — not a deviation from intent.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

### Pre-existing flaky test (out-of-scope, deferred)

- **`tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`** fails with the SAME `sqlalchemy.exc.MissingGreenlet` signature already logged by Plan 01's `deferred-items.md`. Verified via direct re-run; the failure stack trace shows `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here` in HTTP-layer collection update code, completely orthogonal to identity-protocol scaffolding. Plan 02's edits cannot have introduced this — Plan 02 modifies only the dep return-type annotations and adds a wire-in that calls a no-op `DefaultIdentityExtension.resolve_identity_from_token` returning `None`. Continuing to defer per the executor scope-boundary rule.

## Threat Surface Verification

The plan's `<threat_model>` documented seven threat IDs (T-214-AB-01 through T-214-AB-06 + T-214-EH-03). All `mitigate` dispositions have been satisfied by the implementation:

- **T-214-AB-01** (E — extension overrides JWT path) — MITIGATED. The extension is gated behind `if token is not None:` in BOTH deps. The default `DefaultIdentityExtension.resolve_identity_from_token` returns `None`, so community-edition control flow falls through to the existing JWT decode path. Authorization downstream (`require_role`, `require_permission`) operates on the returned Identity; structural subtyping preserves all RBAC semantics. Verified by full pytest pass (1988 tests including all of `test_auth_*`, `test_jwt_*`, `test_oauth_*`, `test_refresh_*`, `test_api_key_*`).
- **T-214-AB-05** (T — refresh-token rotation regression) — MITIGATED. `pytest -k refresh` covered by the auth slice run (219 passed). The refresh endpoints inherit the wire-in via the FastAPI dep tree; default impl returns None → existing refresh logic runs unchanged.
- **T-214-EH-03** (T — extension wire-in skipped for one of the deps) — MITIGATED. Acceptance criterion `grep -c "await get_identity_extension().resolve_identity_from_token" == 2` passes. Both wire-in blocks are structurally identical (same comment header explaining the duplication's intent, same code body). A future contributor "deduplicating" by removing one would trip Plan 04's architecture-guard test (count drift) AND lose the expired-token UX in `get_current_user`.

`accept` dispositions (T-214-AB-02 spoofing, T-214-AB-03 token leakage, T-214-AB-04 DoS, T-214-AB-06 6-field surface drift) are out-of-scope per the threat-model rationale (Phase 217 SAML owns spoofing protection; bearer token already in scope of the request handler; per-extension timeouts deferred; runtime field access is defended at Plan 04's architecture-guard layer + IDE pyright warnings).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Plan 03 (`214-03-migrate-cross-domain-callers`).** Plan 03 will sweep the ~42 cross-domain caller files and rewrite:
- `from app.modules.auth.models import User` → `from app.core.identity import Identity`
- `user: User` parameter annotations → `user: Identity`
- `user: User | None` parameter annotations → `user: Identity | None`

Plan 03 keeps `Role` / `UserRole` imports concrete (D-08); only `User` is rewritten. After Plan 03, only allowlisted files (auth/**, admin/**, audit/models.py, api/main.py, processing/ingest/tasks_raster.py, oauth/models.py) will retain a concrete `User` import — and Plan 04 adds the architecture-guard test that locks this in place.

**Blockers for downstream plans:** None. The pre-existing `test_collections.py::test_update_collection` failure is unrelated and will need separate stability work (not part of Phase 214). Plan 03 will run the same auth + full-suite gates and is expected to keep the 1988-passing baseline intact.

## Self-Check: PASSED

All claimed files exist on disk and the claimed commit hash is present in git history:

- `backend/app/modules/auth/dependencies.py` — present (297 lines)
- `.planning/phases/214-identity-protocol-extract/214-02-SUMMARY.md` — this file
- Commit `6a0dfe8a` (Task 02-01) — present in `git log`

---
*Phase: 214-identity-protocol-extract*
*Completed: 2026-04-27*
