# Phase 224: catalog-god-module-split — Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Source:** Derived from `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 + §7 P0 (action item #1) — treating the audit findings as the de facto PRD. ROADMAP.md draft success criteria preserved verbatim.

<domain>
## Phase Boundary

This phase splits one specific file — `backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC orchestration god-module) — into 4 cohesive sub-modules behind a thin re-export façade. **Pure refactor: zero behavior change.** Every public symbol importable from `service.py` must remain importable from the same path post-split. No tests rewrite, no API contract change, no business logic change.

**In scope:**
- Decompose `service.py` into `service_create.py`, `service_query.py`, `service_lifecycle.py`, `service_grants.py` along responsibility lines.
- Make the original `service.py` a thin façade (~250 LOC) that re-exports the public surface from the 4 sub-modules.
- Add architecture-guard test preventing external modules from importing the 4 sub-modules directly (must go through the façade) — mirror the Phase 222 `test_layering.py::test_no_log_action_calls_outside_audit_service` pattern.

**Out of scope:**
- Behavior changes, signature changes, new features.
- Other large modules in `catalog/` (e.g., `maps/service.py`, `layers/service.py`) — separate phases if needed.
- Catalog ↔ processing cycle inversion (that's Phase 999.7, depends on this phase landing first).
- Façade test changes — existing tests must pass without modification.

</domain>

<decisions>
## Implementation Decisions

### Module split (LOCKED — derived from audit recommendation)

The 1407-LOC orchestrator splits along these 4 responsibility lines:

1. **`service_create.py`** — Dataset creation paths (upload, source-import, registration). Targets ~300-400 LOC.
2. **`service_query.py`** — Read-side helpers (lookups, filters, pagination, search-helper composition). Targets ~300-400 LOC.
3. **`service_lifecycle.py`** — State transitions (status changes, soft-delete, restore, archival). Consumes the existing `ALLOWED_TRANSITIONS` dict at `router_data.py:210`. Targets ~300-400 LOC.
4. **`service_grants.py`** — Authorization/visibility/grants helpers (DatasetGrant manipulation, share-link helpers). Targets ~200-300 LOC.

**Acceptable deviation:** the planner may rebalance LOC between modules if cohesion suggests a different cut. The 4 buckets are the goal, not the LOC targets. If the planner finds a 5th cohesive responsibility (e.g., versioning/snapshots), splitting further is acceptable, provided each module is still <500 LOC and the façade remains <300 LOC.

### Façade pattern (LOCKED)

`service.py` after the refactor:
- Pure re-exports via `from .service_create import *` (or explicit named re-exports if `__all__` is preferred — planner picks based on existing module conventions in the repo).
- Module-level docstring describes the split + lists each sub-module's responsibility.
- One short paragraph note: "External callers MUST import from `app.modules.catalog.datasets.domain.service` (not from the sub-modules) — see `test_no_external_imports_of_dataset_service_submodules` in `test_layering.py`."
- Façade target: <250 LOC.

### Architecture guard test (LOCKED — mirrors Phase 222)

Add to `backend/tests/test_layering.py`:
- `test_no_external_imports_of_dataset_service_submodules` — fails if any module under `backend/app/` (excluding the 4 sub-modules themselves and `service.py` itself) imports from `app.modules.catalog.datasets.domain.service_{create,query,lifecycle,grants}`.
- Allowlist: the 4 sub-modules may cross-import from each other (e.g., `service_create.py` may import a helper from `service_query.py`). The façade may import from all 4.
- Documented allowlist comment in the test mirrors Phase 222's `_AUDIT_INTERNAL` allowlist style.

### Public surface preservation (LOCKED)

Run a `grep -rn "from app.modules.catalog.datasets.domain.service import\|from app.modules.catalog.datasets.domain import service" backend/` BEFORE the split, capturing all current import paths. Verify the same symbols are still importable from the same paths AFTER the split. **Zero churn outside the 4-file split + façade + test guard.**

### Test discipline (LOCKED)

- All existing catalog tests pass without modification.
- No new behavior tests added (this is a pure refactor).
- The new architecture guard is the only new test.
- Run `make test-backend` (or equivalent) before each commit to verify zero behavior drift.

### Atomic commit shape (LOCKED — GSD convention)

Per the project's GSD discipline, the split should land as multiple atomic commits, not one mega-commit:
- One commit per sub-module extraction (4 commits).
- One commit for the façade conversion + import-surface verification.
- One commit for the architecture guard test.
- Total: 6 atomic commits across 5-6 plans.

### Claude's Discretion

- Exact LOC distribution between sub-modules (planner judges based on cohesion).
- Whether to use `from .service_create import *` or explicit named re-exports in the façade (match repo convention — check `backend/app/modules/audit/__init__.py` and `platform/extensions/__init__.py` for existing façade patterns).
- Exact name of the architecture guard test (within reason).
- Order of sub-module extractions (planner sequences to minimize churn — e.g., extract least-coupled first).
- Whether to introduce a `_internal.py` shared-helpers module if the 4 sub-modules need shared private helpers.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit source (the de-facto PRD for this phase)
- `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 (Coupling Health — coupling matrix and 1407-LOC god-module identification) and §7 P0 #1 (the action item being executed)

### Reference architecture-guard pattern (template to mirror)
- `backend/tests/test_layering.py` (Phase 222 architecture-guard pattern, especially `test_no_log_action_calls_outside_audit_service` at line 333)
- `.planning/phases/222-audit-sink-protocol/222-05-SUMMARY.md` — for the AUDIT-02 invariant + Makefile target precedent

### Existing façade pattern examples in the repo
- `backend/app/platform/extensions/__init__.py` — accessor + re-export pattern (Phase 214/222/223)
- `backend/app/modules/audit/__init__.py` (if it has a façade-style export) — local example

### Target file
- `backend/app/modules/catalog/datasets/domain/service.py` — the 1407-LOC file being split

### Adjacent surfaces (read for context, NOT to modify)
- `backend/app/modules/catalog/datasets/api/router_data.py` (lines 210-260 — `ALLOWED_TRANSITIONS` dict consumed by lifecycle)
- `backend/app/modules/catalog/authorization.py` — visibility/authz chokepoint that grants helpers will work alongside

### Project discipline
- `CLAUDE.md` (root + user global) — code style, atomic commits, no AI commit footers
- `.planning/STATE.md` — current milestone state

</canonical_refs>

<specifics>
## Specific Ideas

- **LOC ground truth:** `wc -l backend/app/modules/catalog/datasets/domain/service.py` should currently report **1407** (audit baseline). Verify before split begins.
- **Existing usage map:** `grep -rln "from app.modules.catalog.datasets.domain" backend/app/ | wc -l` — capture baseline import count; verify unchanged after refactor (or with diffs only inside the 4 sub-modules).
- **Test count baseline:** capture pytest test count for `backend/tests/test_*.py` before refactor; should be N+1 after (only the new architecture guard added).
- **Phase 999.7 (ProcessingPort Protocol) prerequisite:** This phase MUST land first because cycle inversion is easier against a focused module surface than a 1407-LOC orchestrator. Note this dependency in PLAN.md.

</specifics>

<deferred>
## Deferred Ideas

- **Catalog ↔ processing cycle inversion** — Phase 999.7 (3-5 days). Depends on this phase landing first.
- **Other catalog god-modules** (`maps/service.py`, `layers/service.py` if oversized) — separate phases if needed.
- **Behavior tests for the split modules** — not in scope; this is a pure refactor.
- **CatalogReadPort Protocol** (P1 from audit §7 #4) — separate future work to reduce catalog inbound count from 47.

</deferred>

---

*Phase: 224-catalog-god-module-split*
*Context derived: 2026-04-30 from `docs-internal/audits/oc-separation-audit-20260430-b.md` (audit-as-PRD pathway, GSD `--prd` analog)*
