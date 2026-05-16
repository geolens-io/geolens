# Phase 1046 — Plan 01: Builder Code Audit

**Phase:** 1046 builder-perf-and-code-audit
**Plan:** 01 of 02
**Requirement:** CODE-01
**Status:** Pending
**Owner:** Claude (executor: spawned analyst agent)
**Deliverable:** `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md`

## Goal

Produce a structured code-quality audit of the Map Builder surface with every finding classified P0/P1/P2 and tagged with file/line evidence + recommended fix, so Phase 1047 plan authors can implement remediations without additional investigation.

## Scope

### In scope (audit these directories)
- `frontend/src/components/builder/**/*.{ts,tsx}` (all 40+ files in the builder surface)
- `frontend/src/components/builder/hooks/**/*.ts` (use-builder-layers, use-builder-save, use-builder-layout, use-builder-dialogs + tests)
- `frontend/src/lib/basemap-utils.ts` (paint helpers consumed by builder)
- `frontend/src/lib/adapters/fill-adapter.ts` (paint adapter consumed by builder — if exists)
- `frontend/src/lib/normalize-saved-map.ts` + `frontend/src/lib/normalize-style-config.ts` (saved-map normalizer chain)
- `frontend/src/lib/popup-template.ts`, `frontend/src/lib/layer-capabilities.ts` (builder-adjacent helpers)
- `frontend/src/pages/MapBuilderPage.tsx` (route entry)

### Out of scope
- Backend code
- Non-builder frontend (Search, Dataset detail, admin pages)
- Test fixtures (`__tests__` subdirectories are referenced for coverage gaps but not audited as deliverables)
- Dependency / package-level audits (handled by /dep-audit)

## Audit Dimensions

Each finding MUST be classified into one of these dimensions and tagged P0 (must fix in 1047), P1 (should fix in 1047), or P2 (defer / future milestone).

### Dimension A — Duplication
- Repeated paint-property stamping logic across components
- Duplicate filter/condition-builder logic
- Repeated MapLibre source/layer creation paths
- Duplicate i18n key handling
- Shared logic that lives in 2+ components instead of a hook/util

### Dimension B — File-size offenders
- Files > 500 LOC (P0 if also high-complexity, else P1)
- Files 350-500 LOC (P1 if single-concern, P2 otherwise)
- Components with >5 concerns per file
- Threshold rationale: existing arch-guard has a 1500-LOC cap on backend routers; frontend builder components should not exceed 500 LOC unless explicitly justified

### Dimension C — Dead code
- Exports never imported elsewhere (excluding entry points + lazy chunks)
- Props declared but never read
- Commented-out code blocks > 5 lines
- TODO/FIXME tags older than 30 days
- Conditional branches that can never fire (e.g., dead enum cases)

### Dimension D — Complexity hotspots
- Functions with cyclomatic complexity > 15 (P0 if user-facing handler, else P1)
- React components with > 10 useState/useEffect/useMemo hooks
- Functions > 50 LOC (P1 if logic-dense, P2 if mostly conditional rendering)
- Nesting depth > 4 levels
- Deeply nested ternaries / inline conditionals

### Dimension E — Test coverage gaps
- Builder files without co-located `__tests__/` coverage
- `it.todo` items in builder test files (count + locations — feeds FOLLOWUP-03 in Phase 1048)
- Functions in builder/hooks/ without any unit test

## Deliverable Structure (`1046-BUILDER-CODE-AUDIT.md`)

```markdown
---
phase: 1046
audit: builder-code
status: draft
generated: 2026-05-16
findings_total: <N>
findings_by_severity: { p0: <n>, p1: <n>, p2: <n> }
findings_by_dimension: { duplication: <n>, file_size: <n>, dead_code: <n>, complexity: <n>, test_coverage: <n> }
---

# BUILDER-CODE-AUDIT — Map Builder Code Quality (Phase 1046)

## Methodology

(tooling used: ripgrep, ts-prune or equivalent, eslint with complexity rule, manual code read)

## Summary Table

| ID | Dimension | Severity | File | Lines | One-liner |
|----|-----------|----------|------|-------|-----------|
| CA-01 | Duplication | P0 | path/to/file.tsx | 120-180 | Brief description |
| ... | ... | ... | ... | ... | ... |

## Findings

### CA-01 — <Title>
- **Dimension:** Duplication
- **Severity:** P0
- **File(s):** `path/to/file.tsx:120-180`, `path/to/other.tsx:45-95`
- **Why:** What's wrong / what it costs the codebase
- **Recommended fix:** Concrete proposal (extract helper / collapse to hook / etc.)
- **Est. effort:** S / M / L
- **Phase 1047 mapping:** CODE-02 or CODE-03

(repeat for each finding, grouped by severity then dimension)

## Deferred (P2 — future milestone)

(brief list of P2 items not targeted by 1047)

## Closing Notes

(audit author notes — surprises, anti-patterns observed, recommended cross-cutting refactors)
```

## Tasks

1. Spawn `Explore` agent (read-only, very thorough breadth) to:
   - Enumerate every file in scope
   - For each, compute LOC + scan for the 5 audit dimensions
   - Aggregate findings per dimension
   - Classify each finding P0/P1/P2 with rationale
   - Write `1046-BUILDER-CODE-AUDIT.md` per the structure above
2. Verify the file:
   - Frontmatter present with all required fields
   - At least one finding per dimension OR explicit "no findings in dimension X" note
   - Every finding has file/line + recommended fix + est. effort + Phase 1047 mapping
3. Atomic commit: `docs(1046): produce BUILDER-CODE-AUDIT.md`

## Success Criteria (verifiable post-execution)

- [ ] `1046-BUILDER-CODE-AUDIT.md` exists at the deliverable path
- [ ] Audit covers all in-scope directories (verifiable by file path coverage in findings table)
- [ ] Every finding tagged P0/P1/P2
- [ ] Every finding has file/line + recommended fix + est. effort
- [ ] Frontmatter `findings_total` matches actual count of findings
- [ ] At least one P0 OR one P1 finding (audits with zero high-severity findings are suspicious — re-run or document why)

## Non-goals

- No code changes (audit only)
- No perf measurements (that's Plan 02)
- No fix implementation (deferred to Phase 1047)
