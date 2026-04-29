# Phase 213: catalog-authz-relocate - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 213-catalog-authz-relocate
**Mode:** `--auto --chain` (Claude auto-selected recommended defaults; no interactive prompts)
**Areas discussed:** Target file location, Caller migration strategy, Architecture-guard test, Migration & verification scope

---

## Target file location

| Option | Description | Selected |
|--------|-------------|----------|
| `catalog/authorization.py` (single flat file) | ROADMAP-canonical wording; matches every other catalog peer (`catalog/sources/`, `catalog/search/`, …) | ✓ |
| `catalog/_authz/visibility.py` (nested package) | Audit doc's parenthetical sketch; useful only if multiple authz files anticipated | |
| `catalog/datasets/authorization.py` (nested under datasets) | Tightest cohesion with DatasetGrant | |

**Auto-selected:** `catalog/authorization.py` — ROADMAP success criterion 1 names this exact path. The audit's `_authz/visibility.py` was illustrative, not contractual. Single flat file matches catalog peer structure.
**Notes:** No directory-level separation needed for one module. If a second authz module appears later, splitting is cheap.

---

## Caller migration strategy

| Option | Description | Selected |
|--------|-------------|----------|
| All callers in one shot, no shim | Mirrors Phase 212 D-04. Closed-set codebase; ruff/CI catch missed migrations. | ✓ |
| Backward-compat re-export in `auth/visibility.py` | Leaves a thin `from app.modules.catalog.authorization import *` shim during a deprecation window | |
| Two-stage migration (introduce new path, deprecate old over multiple phases) | More cautious for very large refactors | |

**Auto-selected:** All callers in one shot, no shim. Matches Phase 212's pattern; ROADMAP SC#4 explicitly requires `git grep "auth.visibility"` returns zero across the repo — incompatible with a shim.
**Notes:** 23 caller files / 26 import lines is a closed set; no external consumers exist. Function-scope deferred imports (4 sites in `platform/jobs/router.py` + `catalog/datasets/domain/service.py:470`) keep their deferral — only the path is rewritten.

---

## Architecture-guard test

| Option | Description | Selected |
|--------|-------------|----------|
| Extend existing `backend/tests/test_layering.py` with two new tests | Reuses Phase 212-03's `_has_git_metadata` skip + `_git_grep` helpers + `@pytest.mark.architecture` marker | ✓ |
| Create new `test_catalog_authz_layering.py` | One concern per file; cleaner separation | |
| Use `import-linter` or another arch-DSL dependency | Declarative, but adds a dependency the project doesn't have | |

**Auto-selected:** Extend `test_layering.py`. The architecture-guard pattern is already established; one more file in the same module is the cheapest, most discoverable place. Two tests added: (1) no `from app.modules.auth.visibility` imports across `backend/`, (2) no `auth.visibility` references anywhere in the repo (excluding the test itself).
**Notes:** Update the module docstring to broaden the guard's scope from Phase 212 LAYER-01 to also cover Phase 213 LAYER-02. Phase 218 will broaden further to `from app.modules.<*>` once 214 lands.

---

## Migration & verification scope

| Option | Description | Selected |
|--------|-------------|----------|
| No alembic migration, no new tests, full pytest as the gate | Pure Python relocation — preserves baseline 1965-test green | ✓ |
| Add new RBAC parity tests | Belt-and-suspenders for visibility correctness | |
| Defer pytest gate to Phase 218 audit close | Riskier; trusts later audit to catch regressions | |

**Auto-selected:** No alembic, no new RBAC tests, full pytest gate inside this phase. RBAC behavior is exercised by ~50+ existing tests across search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox — if those pass, parity is proven. New speculative tests are scope creep.
**Notes:** Phase 213 mirrors Phase 212-04's verification-gate plan structure: alembic check + full pytest + ruff + ROADMAP SC verification + evidence summary. No source files modified by the verification plan; it's a check-only step.

---

## Claude's Discretion

- Commit decomposition (likely 3 atomic commits + 1 verification gate, mirroring Phase 212).
- Module docstring wording for the new `catalog/authorization.py`.
- Trivial cleanups discovered en route (only if pure relocation discipline isn't violated).
- Reuse of the `@pytest.mark.architecture` marker vs. introducing `@pytest.mark.layering` (default: reuse).

## Deferred Ideas

- `AuthorizationProtocol` / `VisibilityExtension` seam → revisit with Phase 217 (auth-saml-enterprise).
- RBAC test coverage expansion → separate phase if Phase 218 audit flags it.
- Promoting the 4 remaining function-scope deferred imports of `auth.visibility` in callers to module level → out of scope.
- `catalog/__init__.py` re-exports → out of scope.
- `catalog/authorization.py` `User`/`Role`/`UserRole` import rewrite → Phase 214's responsibility (`IdentityProtocol`).
- Centralized `_get_user_roles()` audit (look for per-router duplicates that the visibility docstring claims to replace) → quick-task if needed.
