# Phase 213: catalog-authz-relocate - Context

**Gathered:** 2026-04-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Move dataset visibility/authorization logic out of `auth/` and into `catalog/`, where it belongs. After this phase:

- `backend/app/modules/auth/visibility.py` is **deleted**.
- A new module `backend/app/modules/catalog/authorization.py` exposes the same public surface verbatim: `DatasetVisibility`, `apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous`.
- All 26 import lines across 23 files (15 module-level imports + 11 inside multi-import blocks; 4 of which are function-scope deferred imports) resolve to `app.modules.catalog.authorization`.
- The `auth → catalog` cycle smell at `auth/visibility.py:148` (`from app.modules.catalog.datasets.domain.models import DatasetGrant`, deferred to break the cycle) is removed: `catalog.authorization` can import `DatasetGrant` at module level because it lives in the same package.
- Observable behavior is **unchanged** — same RBAC matrix, same SQL filters, same exception types and statuses, same admin/anon shortcuts.
- The 1965-test backend baseline stays green.

In scope: relocate the module verbatim, migrate every importer in one shot, delete the source file, extend the architecture guard test from Phase 212.

Out of scope: any change to RBAC semantics, role model, grant model, dataset visibility states, exception classes, or the public/restricted/private/published lifecycle. No new `AuthorizationProtocol` extension seam (rejected — see decisions). No re-export shim left behind in `auth/`. No frontend changes.

</domain>

<decisions>
## Implementation Decisions

### Target location
- **D-01 (auto-selected):** New file at `backend/app/modules/catalog/authorization.py` — single flat file, **not** `catalog/_authz/visibility.py`. Reason: the ROADMAP success criterion 1 names `catalog/authorization.py` explicitly; the audit's `_authz/visibility.py` suggestion was a sketch, not a contract. A flat single file matches every other catalog peer (`catalog/sources/`, `catalog/search/`, …) which use `<concern>.py` not `_<concern>/<concern>.py`. No directory-level separation needed for one module.
- **D-02:** The new module keeps the **exact public surface** of today's `auth/visibility.py`: `DatasetVisibility` (enum), `apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous`. No renames, no signature changes, no docstring rewrites beyond updating the module docstring's location reference. Reason: the phase is a relocation, not a refactor; renames create review noise and compounding scope risk. Audit success-criterion: "no behavior change to dataset-visibility semantics."
- **D-03:** The relocated module's imports change in two ways and only those:
  - It still imports `Role, User, UserRole` from `app.modules.auth.models` — that direction (catalog → auth.User) is correct and not the cycle being fixed; Phase 214 introduces `IdentityProtocol` to abstract `User`, but this phase does NOT pre-empt that work.
  - The function-scope deferred import `from app.modules.catalog.datasets.domain.models import DatasetGrant` at line 148 is **promoted to module level** — the cycle reason disappears once the file lives inside `catalog/`. Reason: the deferred import was a code smell flagged by the audit ("auth/visibility.py imports DatasetGrant via deferred import — architectural smell"); fixing it is the cleanup that justifies the relocation.

### Caller migration
- **D-04 (auto-selected):** Migrate **all** importers in one shot, **no backward-compat re-export shim** left in `app.modules.auth.visibility` or `app.modules.auth.__init__`. Same pattern as Phase 212 D-04. The repo is a closed set; every importer is in this codebase; ruff/pyright/CI catches missed migrations as hard errors. Known caller sites the planner must touch (mechanically migrate each `from app.modules.auth.visibility import ...` → `from app.modules.catalog.authorization import ...`):

  Module-level imports (22 sites, 15 unique single-line + 7 multi-import blocks):
  - `backend/app/modules/auth/dependencies.py:15`
  - `backend/app/modules/catalog/collections/router.py:16`
  - `backend/app/modules/catalog/collections/service.py:28`
  - `backend/app/modules/catalog/datasets/api/router.py:28` (multi-line block)
  - `backend/app/modules/catalog/datasets/api/router_data.py:23` (multi-line block)
  - `backend/app/modules/catalog/datasets/api/router_export.py:26` (multi-line block)
  - `backend/app/modules/catalog/datasets/api/router_metadata.py:22` (multi-line block)
  - `backend/app/modules/catalog/datasets/api/router_vrt.py:19`
  - `backend/app/modules/catalog/datasets/domain/service.py:29` (module-level)
  - `backend/app/modules/catalog/features/router.py:15`
  - `backend/app/modules/catalog/maps/router.py:26`
  - `backend/app/modules/catalog/maps/service.py:20`
  - `backend/app/modules/catalog/records/router.py:11`
  - `backend/app/modules/catalog/search/router.py:19` (multi-line block)
  - `backend/app/modules/catalog/search/service.py:33`
  - `backend/app/platform/sandbox/validator.py:18`
  - `backend/app/processing/ai/router.py:42`
  - `backend/app/processing/ai/service.py:33`
  - `backend/app/processing/export/router.py:16`
  - `backend/app/processing/ingest/service.py:20`
  - `backend/app/processing/tiles/router.py:21`
  - `backend/app/standards/ogc/router.py:11`

  Function-scope (deferred) imports (4 sites — keep them deferred at the call site, just rewrite the path; do NOT promote to module level since the original deferral was for cycle/lazy-load reasons inside those modules, not auth-cycle reasons):
  - `backend/app/modules/catalog/datasets/domain/service.py:470`
  - `backend/app/platform/jobs/router.py:124`
  - `backend/app/platform/jobs/router.py:254`
  - `backend/app/platform/jobs/router.py:319`

  Mandatory planner step: run `git grep -nE "auth\.visibility|from app\.modules\.auth\.visibility" -- backend/` and confirm every hit corresponds to one of the above. If new hits appear (e.g., a recently-added test), migrate them too.

- **D-05:** `backend/app/modules/auth/visibility.py` is **deleted**. The file is removed, not emptied or stubbed. `app.modules.auth.__init__.py` does not currently re-export `visibility` (verified — it's a one-line docstring), so no `__init__.py` edit is needed. If a re-export is found during planning it is also removed.
- **D-06:** No backward-compat aliases. The `from app.modules.auth.visibility import X` path becomes a hard `ModuleNotFoundError` after this phase. That is the intended state — see SC#4 (`git grep` returns zero matches).

### Regression prevention
- **D-07 (auto-selected):** Extend the existing `backend/tests/test_layering.py` (created in Phase 212-03) rather than adding a new test file. Reason: the project already has the architecture-guard pattern with a registered `@pytest.mark.architecture` marker; one more test in the same file is the cheapest, most discoverable place. Add two new tests:
  1. `test_no_imports_from_auth_visibility` — `git grep -E "^\s*(from|import)\s+app\.modules\.auth\.visibility"` across `backend/` returns zero matches. Maps directly to ROADMAP SC#4.
  2. `test_no_auth_visibility_module_referenced` — broader `git grep -E "app\.modules\.auth\.visibility|auth\.visibility"` excluding `backend/tests/test_layering.py` itself (so docstrings and the regex literal don't self-match) returns zero matches. Catches future "convenience" re-exports in `__init__.py` files that the import-shaped guard would miss.
- **D-08:** Both new tests follow Phase 212's pattern: `_has_git_metadata()` skip guard for non-git environments, `subprocess.run(["git", "grep", "-n", "-E", ...])` invocation, exit-code 0 = fail with offending lines, exit-code 1 = pass, exit-code >1 = unexpected git error → fail. Use the existing `_git_grep` helper from `test_layering.py` if one exists; the planner verifies and either reuses or extracts.
- **D-09:** Update the module-level docstring of `test_layering.py` to document the broadened scope (was Phase 212 LAYER-01-only; now also covers Phase 213 LAYER-02). The existing comment "Scope (Phase 212): NARROW — only `from app.modules.settings`. Phases 213 (catalog-authz-relocate) and 214 (identity-protocol-extract) close additional core->modules edges; Phase 218 will broaden this guard..." anticipates this expansion — update it accordingly.

### Migration & verification
- **D-10 (auto-selected):** No Alembic migration. The relocation is pure Python; the `app_settings`/`catalog.users`/`catalog.dataset_grants`/`catalog.records` tables are unchanged. Proof step in the phase plan: after the refactor, run `cd backend && uv run alembic check` (or the project's `make migrations-check` equivalent) and confirm "no new operations." If it ever reports a diff, the relocation accidentally touched `__tablename__`/`__table_args__` somewhere and the planner stops.
- **D-11:** The 1965-test backend baseline (per STATE.md, restored 2026-04-26 by quick task `260425-sl1`) is the acceptance gate. The phase plan's verification gate runs full pytest; any non-baseline failure is a defect introduced by the refactor.
- **D-12:** RBAC behavior parity is the most load-bearing acceptance check. The existing test corpus already exercises visibility filters across search, datasets, features, tiles, STAC, OGC Records, maps, collections, jobs, AI, export, ingest, and sandbox — see ROADMAP SC#2 ("RBAC-filtered search, tile, feature, STAC, and OGC Records endpoints return identical results for the same user/role pairs as before the relocation"). No new tests are required; if existing tests pass, parity is proven. The planner does NOT add speculative new visibility tests — that's scope creep into a dedicated RBAC-coverage phase.
- **D-13:** Frontend has zero involvement. No HTTP contract change, no error-shape change, no schema change. `make openapi-check` continues to pass without regenerating `backend/openapi.json`.
- **D-14 [informational]:** Independent of Phase 212 and Phase 214 — ROADMAP says they may run in parallel. They do not share files (Phase 212 touches `core/`, `core/db/`, `modules/settings/models.py`; Phase 213 touches `auth/visibility.py`, the new `catalog/authorization.py`, and 23 caller files; Phase 214 touches `core/identity.py` (new) and 51 `User` import sites). Phase 213's caller-migration set will overlap with Phase 214's `User`-import set in the same files (same routers/services), but on different import lines — no merge conflict expected, but the planner notes in the merge-strategy section if 214 starts before 213 lands.

### Claude's Discretion
- **Commit decomposition** — likely 3 atomic commits + a verification gate plan, mirroring Phase 212's structure: (1) introduce `catalog/authorization.py` with the verbatim code (+ promoted `DatasetGrant` import), (2) migrate all 26 caller import lines + delete `auth/visibility.py`, (3) extend `test_layering.py` with the two new architecture guard tests + update its docstring, (4) phase verification gate (alembic check + full pytest + ruff + ROADMAP SC verification, mirroring 212-04). Planner may collapse or split based on file-size budgets and dependency ordering.
- **Module docstring wording** in the new `catalog/authorization.py` — keep the existing visibility.py docstring's intent ("Dataset visibility enforcement") but update the SEC-04 reference if needed and add a one-liner noting the relocation source. Planner picks exact wording.
- **Whether to refactor any internal helpers** during the move — default is NO. If the planner sees a trivial dead-import or unused-name cleanup along the way, it's allowed; anything bigger is deferred. Pure relocation is the discipline.
- **Test marker reuse** — the new architecture tests use `@pytest.mark.architecture` (already registered in Phase 212-03). If the planner thinks a more specific marker like `@pytest.mark.layering` makes sense, that's a judgment call but adds noise; default is reuse.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 bucket, row "Refactor `auth/visibility.py` → `catalog/authorization.py`". This is the source spec. Names the source path, target path, file count (23), and effort estimate.
- `docs-internal/audits/oc-separation-audit-20260426.md` §5 — full audit body. Notes the architectural smell ("`auth/visibility.py:148` does `from app.modules.catalog.datasets.domain.models import DatasetGrant` (deferred import to break a cycle). This is logically a **catalog authorization** concern, not a generic identity concern, and it sits in the wrong package."). Decoupling Recommendation #1 names this exact refactor.
- `.planning/REQUIREMENTS.md` §LAYER-02 — the requirement this phase closes.
- `.planning/ROADMAP.md` §Phase 213 — goal statement and 4 success criteria. The wording "`catalog/authorization.py`" (not `_authz/visibility.py`) is binding.

### Project / state
- `.planning/PROJECT.md` — milestone overview; v13.1 is audit-driven with target grades Boundary B → A−, Seam Quality C → B, OSS Surface D → C. Phase 213 contributes to Boundary and Seam.
- `.planning/STATE.md` — confirms 1965/1965 backend test baseline (restored 2026-04-26 by quick task `260425-sl1`) and Phase 212 verification status.
- `.planning/phases/212-core-settings-decouple/212-CONTEXT.md` — companion phase, same pattern (mechanical relocation, all-callers-in-one-shot, no shim, architecture-guard test). Phase 213 deliberately mirrors this structure.
- `.planning/phases/212-core-settings-decouple/212-RESEARCH.md` — Phase 212's RESEARCH.md (Pitfall 4: `_has_git_metadata()` skip guard for the architecture test). Reuse that pattern.

### Code (current location)
- `backend/app/modules/auth/visibility.py` — the file being relocated (183 lines, 4 public functions + 1 enum). Read end-to-end before planning so the planner can confirm zero behavior changes line-for-line.
- `backend/app/modules/auth/models.py` — defines `User`, `Role`, `UserRole`. Stays put; the relocated module imports from here (catalog → auth.User direction is the correct one).
- `backend/app/modules/catalog/datasets/domain/models.py` — defines `DatasetGrant`. After relocation, the new `catalog/authorization.py` imports this at module level (currently deferred at `visibility.py:148`).

### Code (target location and structure)
- `backend/app/modules/catalog/__init__.py` — currently `"""Catalog module namespace."""` only. Phase 213 does NOT add re-exports here (callers import the submodule directly); but if the planner discovers code that does `from app.modules.catalog import authorization`, that's fine and supported by Python's package model.
- `backend/app/modules/catalog/collections/`, `backend/app/modules/catalog/datasets/`, `backend/app/modules/catalog/features/`, `backend/app/modules/catalog/maps/`, `backend/app/modules/catalog/records/`, `backend/app/modules/catalog/search/`, `backend/app/modules/catalog/sources/`, `backend/app/modules/catalog/validation/`, `backend/app/modules/catalog/layers/` — existing peer subpackages. The new `authorization.py` is a peer module sitting next to these, not nested under any of them.

### Architecture guard
- `backend/tests/test_layering.py` — Phase 212-03's architecture guard test. Phase 213 extends this same file with two new `@pytest.mark.architecture` tests (D-07). Read end-to-end to understand the `_has_git_metadata()` skip pattern, the `_git_grep` helper, and the docstring conventions.
- `backend/pyproject.toml` — registers the `architecture` pytest marker. Already done by Phase 212-03; no change needed.

### Caller files (all 23, for the planner's grep+migrate sweep)
Already enumerated in D-04 above; the planner re-runs the grep at plan time to catch any post-discussion drift.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backend/tests/test_layering.py` `_has_git_metadata()` + `_git_grep` helpers** (Phase 212-03): the exact regex/skip-guard pattern Phase 213's two new tests should reuse. No new helper is needed. The test file should grow from 2 architecture tests to 4.
- **`@pytest.mark.architecture` marker registered in `backend/pyproject.toml`**: Phase 213's new tests use it directly. No marker changes.
- **`DatasetVisibility` enum**: stays the same enum, just at a new import path. Callers reference `DatasetVisibility.PUBLIC`/`RESTRICTED`/`PRIVATE` in 4 places (visibility.py itself, and via `record.visibility == "public"` string-compares elsewhere — no caller imports the enum class today; only the helpers).
- **Phase 212-04's verification-gate plan structure**: `212-04-phase-verification-gate-PLAN.md` is a clean template for "no source modifications, run alembic + pytest + ruff + SC verification, write evidence summary." Phase 213's verification plan should mirror it 1:1 with the SC list swapped.

### Established Patterns
- **All-callers-in-one-shot with no shim**: Phase 212 D-04 established this for the `AppSetting` move. Phase 213 inherits it verbatim. The safety net is ruff + pyright + the full pytest run; missed callers fail loudly, not silently.
- **Architecture-guard test as the regression seal**: Phase 212-03 chose `git grep` over import-graph libraries (e.g., `import-linter`) because the project doesn't have one and `git grep` is cheap and explicit. Phase 213 inherits this. Do NOT introduce `import-linter` or any architecture-DSL dependency.
- **Deferred imports as cycle-breakers**: 103 function-scope imports exist in the codebase (per audit §5). Phase 213 removes one (`auth/visibility.py:148` → `DatasetGrant`) by relocating; it does NOT touch the other 4 deferred imports of `auth.visibility` itself in callers (D-04: rewrite the path, keep the deferral). Reason: those deferrals exist for unrelated reasons (e.g., `platform/jobs/router.py` defers many imports for slow-startup mitigation; Phase 213 is not in the business of changing that).
- **`SEC-04: All dataset access paths use these shared functions`** (visibility.py module docstring): the project's RBAC-centralization invariant. Phase 213 preserves it — the shared functions still exist, just at a new import path. The docstring should be updated to reflect the move but the invariant statement stays.

### Integration Points
- **Alembic env**: `alembic/env.py` does not import `app.modules.auth.visibility` (no ORM models in that file). Verified by the absence of `auth.visibility` in any non-`backend/app` paths in the grep above. No alembic-level change needed.
- **OpenAPI snapshot (`backend/openapi.json`)**: unaffected — relocation is pure-Python internal. `make openapi-check` continues to pass without regenerating.
- **`app.modules.auth.__init__.py`**: contains only `"""Auth module namespace."""` — no re-export to remove, no `__all__` to prune. Phase 213 leaves this file untouched.
- **`backend/tests/`**: no test imports from `app.modules.auth.visibility` directly (verified by the full grep above — every importer is under `backend/app/`, none under `backend/tests/`). Therefore the relocation does not require touching any test files except `test_layering.py` (where the new arch tests are added).
- **Function-level deferred imports in callers** (`platform/jobs/router.py:124,254,319` and `catalog/datasets/domain/service.py:470`): these stay deferred — Phase 213 only rewrites the path. If the planner notices that one of them could trivially promote to module level without introducing a cycle, that's fine; default is "minimum change wins."

### Risk surfaces
- **Catalog → auth.User direction (kept)**: the relocated module still imports `User, Role, UserRole` from `app.modules.auth.models`. This is the *correct* direction (modules depending on auth's identity types) and Phase 214 will replace `User` with `IdentityProtocol` in `core/`. Phase 213 does NOT pre-empt 214; it leaves the imports as `from app.modules.auth.models import User, Role, UserRole`. When Phase 214 lands, it will rewrite this single line in `catalog/authorization.py` along with 50 other `User` import sites.
- **Multi-line import blocks** (router.py, router_data.py, router_export.py, router_metadata.py, search/router.py): the planner's mechanical migration must preserve the block shape (`from X import (\n  A,\n  B,\n)`) when rewriting `X`. A naive `sed` over `import\s+X` will work because only the path on line 1 of the block changes; the imported-names lines below are untouched.

</code_context>

<specifics>
## Specific Ideas

- **Audit phrasing chosen, in their words:** Recommendation #1 in §5: "Move `auth/visibility.py` into a catalog-facing authorization module (e.g., `app/modules/catalog/_authz/visibility.py`). Already imports `DatasetGrant` via deferred import — relocating removes the cycle and lets enterprise overlay swap visibility rules without touching `auth/`." We adopt the relocation but use the ROADMAP-canonical filename `catalog/authorization.py`, not the audit's parenthetical sketch.
- **Phase 218 is the proof:** success isn't just "tests pass," it's "Boundary grade rises from B to A− and the audit's `auth.visibility` smell row no longer reproduces." Phase 218 reruns `/oc-audit`. Phase 213's contribution is removing the deferred `DatasetGrant` import smell and the `auth → catalog` business-logic arrow; the regression guard (D-07/D-08) ensures both stay removed.
- **Independent of Phase 212 and 214:** ROADMAP says 212/213/214 may run in parallel. Phase 213 does not share files with Phase 212 (settings/core); it overlaps with Phase 214's `User` import sites in the same files but on different lines (Phase 214 rewrites `from app.modules.auth.models import User` → `from app.core.identity import IdentityProtocol`; Phase 213 rewrites `from app.modules.auth.visibility import ...` → `from app.modules.catalog.authorization import ...`). The planner notes this in merge strategy if 214 starts before 213 lands.
- **No `AuthorizationProtocol` extension seam in this phase:** the audit calls out enterprise-overlay swap potential ("lets enterprise overlay swap visibility rules without touching `auth/`"). That swap requires a Protocol seam. We deliberately do NOT introduce one here — Phase 217 (auth-saml-enterprise) is the right place to design the auth-extension hook (and Phase 214 introduces the analogous `IdentityProtocol`). Phase 213's job is to put the file in the right place; making it pluggable is a separate decision driven by a real consumer.
- **No `DatasetGrant` Protocol either:** same logic — the relocated `catalog/authorization.py` imports `DatasetGrant` concretely. If a future phase wants pluggable grant backends, it adds a Protocol then. Closed-set codebase, YAGNI.

</specifics>

<deferred>
## Deferred Ideas

- **`AuthorizationProtocol` / `VisibilityExtension` seam**: the audit's "enterprise overlay can swap visibility rules" pitch. Not needed for v13.1; revisit when Phase 217 (auth-saml-enterprise) actually designs the auth-extension contract, or when a real second visibility implementation is on the table.
- **RBAC test coverage expansion**: the existing test corpus exercises visibility on search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox — but coverage isn't audited in this phase. If Phase 218's audit flags coverage gaps, that's a separate phase.
- **Promoting the 4 remaining function-scope deferred imports of `auth.visibility` to module level in callers**: tempting cleanup, but those deferrals exist for reasons unrelated to auth (slow-import mitigation in `platform/jobs/router.py`, function-local helpers in `catalog/datasets/domain/service.py`). Out of scope.
- **`catalog/__init__.py` re-exports**: tempting to add `from .authorization import apply_visibility_filter, ...` to `catalog/__init__.py`. Out of scope — every importer already uses the submodule path; introducing re-exports is a separate concern.
- **Splitting `catalog/authorization.py` into smaller modules** (`visibility.py` + `access_check.py` + `roles.py`): the file is 183 lines, well under any size budget. No split.
- **Centralized `_get_user_roles()` cleanup**: the visibility module's docstring notes that `get_user_roles()` "Replaces the per-router `_get_user_roles()` duplicates." Audit if any per-router duplicates linger. If they exist, that's a quick-task or a separate phase, not Phase 213.
- **Phase 218 audit closing**: Phase 213's contribution to Boundary B → A− and Seam Quality C → B is one row in the closing audit; Phase 218 owns the re-run.
- **Phase 214 `IdentityProtocol` migration of the relocated module**: when 214 lands, `catalog/authorization.py`'s `from app.modules.auth.models import User, Role, UserRole` line is rewritten to `from app.core.identity import IdentityProtocol` (or similar). That rewrite is Phase 214's responsibility; Phase 213 leaves the concrete import in place.

</deferred>

---

*Phase: 213-catalog-authz-relocate*
*Context gathered: 2026-04-27*
