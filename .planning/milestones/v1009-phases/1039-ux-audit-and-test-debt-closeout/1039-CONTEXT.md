# Phase 1039: ux-audit-and-test-debt-closeout - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss=true)

<domain>
## Phase Boundary

Produce the `BUILDER-UX-AUDIT.md` finding/severity/priority document that the rest of the milestone executes against, and close the 5 pre-existing builder vitest failures + the `use-builder-layers.add-dataset.test.ts` worker timeout in the same pass — co-locating test repair with audit because both surfaces touch `EmptyStackState`, `StackRow`, `UnifiedStackPanel`, and `use-builder-layers`.

**Requirements:** POL-12, POL-19, POL-20, POL-21

**Success criteria (from ROADMAP):**
1. `.planning/phases/1039-.../BUILDER-UX-AUDIT.md` enumerates findings across `UnifiedStackPanel`, `LayerEditorPanel`, Add Dataset modal, Settings scene, `SidebarRail`, and `EmptyStackState` — each tagged P0/P1/P2 with a fix-priority recommendation.
2. `npx vitest run src/components/builder/` reports 0 failures and 0 unhandled worker errors — including the previously-failing `EmptyStackState.integration` Tests 2/3/5, the `StackRow` "Delete layer" kebab test, and the `UnifiedStackPanel` "calls onAddDataClick" test.
3. `use-builder-layers.add-dataset.test.ts` runs to completion (no `Worker exited unexpectedly` / `Timeout terminating forks worker`); root cause documented in phase summary.
4. Phase summary names the audit's P0 items so Phase 1042 / Phase 1043 can scope their plans against an explicit priority list.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, the v1009 PROJECT.md "Locked context" block, and codebase conventions to guide decisions.

### Carried from v1008 (hard constraints)
- Only the `sketch-findings-geolens` token set; no new tokens introduced.
- No saved-map shape changes (the Phase 1033 normalizer is locked).
- No public viewer / shared / embed surface changes.
- Audit is read-only against the live codebase; no implementation work in the audit itself — that's scoped to Phase 1042 / 1043.

### Audit deliverable shape
`BUILDER-UX-AUDIT.md` lives inside the phase directory and follows a per-surface section model: one `## {Surface}` heading per builder surface (six surfaces total), each with a flat `| ID | Finding | Severity | Fix priority |` table. Finding IDs use the prefix `AUD-{NN}` so Phase 1042/1043 plans can cite specific findings without re-reading the audit prose.

### Test fix scope
The five vitest failures are functional regressions (not type drift — that was cleared in commit `76017c22`). The root cause for each is identified, fixed in the source/test code as appropriate (per `/Users/ishiland/.claude/CLAUDE.md` style: simple, readable, follow existing conventions), and the test left passing. The worker-timeout root cause must be documented in the phase summary even if the fix is a one-liner.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Key files known to be in scope:

- `frontend/src/components/builder/UnifiedStackPanel.tsx` + `__tests__/UnifiedStackPanel.test.tsx`
- `frontend/src/components/builder/StackRow.tsx` + `__tests__/StackRow.test.tsx`
- `frontend/src/components/builder/EmptyStackState.tsx` + `__tests__/EmptyStackState.integration.test.tsx`
- `frontend/src/components/builder/hooks/use-builder-layers.ts` + `__tests__/use-builder-layers.add-dataset.test.ts`
- `frontend/src/components/builder/LayerEditorPanel.tsx` (audit only)
- `frontend/src/components/builder/SidebarRail.tsx` (audit only)
- `frontend/src/components/builder/DatasetSearchPanel.tsx` (audit — Add Dataset modal)
- `frontend/src/components/builder/BasemapGroupEditorScene.tsx` (audit — Settings scene)

</code_context>

<specifics>
## Specific Ideas

- The audit document is the canonical artifact downstream phases plan against — treat its priority list as a hard contract: if a P0 finding is filed but Phase 1042/1043 has no plan touching it, that's a milestone gap.
- `EmptyStackState.integration` Tests 2/3/5 all failed during the TS-error sweep in `260514-ajo`; this phase must verify those are real product-coverage failures (not just stale assertions) before fixing.
- The worker-timeout in `use-builder-layers.add-dataset.test.ts` was confirmed pre-existing on commit `8cab335e`; rule out test isolation issues (fixture cleanup, mock leak) before touching production code.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.

</deferred>
</content>
