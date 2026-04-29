# Phase 219: oc-audit-remediate-idp-mapping - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-29
**Phase:** 219-oc-audit-remediate-idp-mapping
**Mode:** `--auto --chain` (Claude selected recommended defaults across all gray areas; auto-advance to plan-phase enabled)
**Areas discussed:** Schema gate placement, Service gate placement, Test split strategy, Audit re-run + close-doc handling, Plan structure & commit granularity

---

## Schema gate placement (write-path)

| Option | Description | Selected |
|--------|-------------|----------|
| Inline `@model_validator(mode="after")` on each schema class | Two validators (Create + Update); raises ValueError when group_claim set OR group_role_mapping non-empty AND not enterprise. Matches existing `_validate_per_type` precedent at schemas.py:145. | ✓ |
| Shared helper imported into both schema classes | Single `_check_idp_mapping_gate(values)` helper called from each validator. Less duplication. | |
| FastAPI dependency on the router endpoint | Gate at `oauth/router.py` POST/PUT endpoints via a `Depends(...)` rather than schema-level. | |

**Auto-selected:** Inline validator on each class (matches existing oauth/schemas.py pattern; small enough that abstraction adds no value; gate co-locates with the fields it governs).

**Notes:** D-02 carve-out: `group_role_mapping={}` (clear-mapping) is allowed in community per the existing `OAuthProviderUpdate` field documentation. Only non-empty mapping triggers the gate.

---

## Service gate placement (runtime application)

| Option | Description | Selected |
|--------|-------------|----------|
| Gate at call site `service.py:261-263` (audit recommendation) | Wrap `_resolve_role(...)` invocation in `if is_enterprise(): ... else: role_name = provider.default_role`. Keeps `_resolve_role` a pure helper. | ✓ |
| Gate inside `_resolve_role()` itself | Add edition check at top of `_resolve_role`; return `default` if not enterprise. Centralizes the gate in the helper. | |
| FastAPI dependency on OAuth login endpoint | Inject `is_enterprise()` at the request boundary; pass through to `find_or_create_oauth_user`. | |

**Auto-selected:** Gate at call site per the audit's exact prescription. `_resolve_role` stays pure; orchestration-level edition awareness is the right level.

**Notes:** D-06 chose silent runtime gate (no log) — schema gate prevents new bad data, so the runtime branch is defense-in-depth for legacy/direct-DB rows. Optional logger.info noted as Claude's Discretion flip.

---

## Test split strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Split into community + enterprise variants of the runtime test, plus dedicated schema-validator tests in a `TestIdpRoleMappingGate` class | 5 new/refactored tests: 2 runtime variants (community ignores, enterprise applies) + 4 schema validator tests (reject Create with group_claim, reject Create with mapping, accept enterprise, reject Update) + 1 carve-out test (empty dict allowed in community). | ✓ |
| Update existing `test_group_role_mapping` to enterprise-mode only | Keep one runtime test; mark community behavior as covered by the schema gate alone. | |
| Move all group-mapping tests to the enterprise test repo | Eliminates community coverage of the runtime gate. | |

**Auto-selected:** Split into community + enterprise variants + dedicated validator class. Both branches of the gate (schema rejection AND service-side default-role application) need explicit coverage.

**Notes:** D-10 — edition-state isolation between tests via `try/finally` or shared fixture. `test_saml_overlay.py:239` is the reference for `init_edition(["enterprise"])` test setup.

---

## Audit re-run + close-doc handling

| Option | Description | Selected |
|--------|-------------|----------|
| Amend `oc-separation-audit-v13.1-close.md` in place; replace BLOCKED banner with VERIFIED; preserve BLOCKED narrative as "Pre-remediation state" subsection | Single canonical close artifact; git history preserves prior state. | ✓ |
| Produce a new `oc-separation-audit-v13.1.1-close.md` | Two close artifacts — one for the BLOCKED state, one for the VERIFIED state. | |
| Produce a new `oc-separation-audit-v13.1-close-amended.md` (sibling file) | Splits the close story across two files. | |

**Auto-selected:** Amend in place. Phase 218 D-02 establishes v13.1-close.md as a milestone-bound artifact; fragmenting into two files would split the milestone-close story across artifacts that future readers would have to reconcile.

**Notes:** D-12 specifies the exact edits — banner swap, scorecard update, Section 1 row flip, Section 8 grade-delta update, P1 triage row closure marker. Date-named output of the audit re-run (`oc-separation-audit-{YYYYMMDD}.md`) is discarded — only the milestone-close artifact is committed.

---

## Plan structure & commit granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Single plan, 4 atomic commits (schema → service → tests → audit re-run + doc amendment) | Sequential, tightly coupled, ~1d. Mirrors Phase 218 D-09 single-plan logic. | ✓ |
| Multi-plan: separate plans for code change + audit re-run/doc amendment | Allows parallel review of code vs doc commit. | |
| Single plan, single commit | Simpler git history; harder to revert one piece. | |

**Auto-selected:** Single plan with 4 atomic commits. Each commit is independently revertable; commit 4 (doc-only) can ship after a quick audit verification without re-running tests.

**Notes:** Phase scope is essentially one tightly-bound deliverable; multi-plan would only help if commits could happen in parallel, which they can't (audit re-run depends on code commits landing).

---

## Claude's Discretion

- **Validator method name** — planner chooses `_validate_enterprise_features` / `_validate_idp_mapping_gate` / similar.
- **`init_edition` test fixture vs inline patch** — planner may consolidate into a `conftest.py` fixture if it cleans up D-10 boilerplate.
- **Audit re-run timing** — planner may run `/oc-audit` after commit 3 (before commit 4) or after commit 4.
- **Optional `logger.info` on runtime community-side gate** — D-06 chose silence; planner may flip to a single-line log if observability is judged useful.
- **`provider_type='saml'` community-write rejection** — could be added to the same validator as a consistent extension; out of audit-driven scope but a low-cost adjacency.

## Deferred Ideas

- Removing `group_claim` / `group_role_mapping` columns from core `oauth/models.py` (kept as forward-compat scaffolding).
- Tenant-scoped edition (multi-tenant; v14+ concern).
- v13.2 baseline audit.
- Re-grading already-green findings outside the IdP-mapping cluster.
