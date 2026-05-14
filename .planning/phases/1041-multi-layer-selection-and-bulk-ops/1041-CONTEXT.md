---
phase: 1041
phase_name: multi-layer-selection-and-bulk-ops
status: ready_for_planning
generated: auto (workflow.skip_discuss=true)
date: 2026-05-14
---

# Phase 1041: multi-layer-selection-and-bulk-ops — Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Let users select multiple stack rows via mouse and keyboard, see a clear selection state, and run atomic bulk operations (visibility, opacity, group, ungroup, delete) with single optimistic update + single rollback on failure — without allowing cross-boundary selection between the basemap group and overlay layers.

**Requirements:** POL-06, POL-07, POL-08, POL-09, POL-10, POL-11

**Success Criteria:**
1. cmd-click toggles individual; shift-click selects contiguous range; keyboard equivalents (Space toggle, Shift+ArrowUp/Down extend).
2. Visual distinction: single-selection focus (row that opens flyout) vs multi-selection (background tint + checkbox + `aria-selected="true"`).
3. With 2+ rows selected, bulk action bar (header or footer anchored) shows: visibility toggle, opacity slider, group, ungroup, delete.
4. Bulk op = single optimistic update across all selected layers; per-layer failure → single error toast + rollback. Selection clears on Escape, outside-click, route change.
5. Cannot co-select basemap group/sublayers with overlay layers — combination refused; bulk delete on basemap unreachable.

**Depends on:** Phase 1040 (DnD primitives shipped; stack architecture stable).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, codebase conventions, and `sketch-findings-geolens` tokens.

### Hard Constraints (v1009 milestone)
- No saved-map shape changes (Phase 1033 normalizer is locked).
- No public viewer / shared / embed surface changes.
- All work uses the `sketch-findings-geolens` token set; no new tokens introduced.
- POL-09 bulk operations use existing per-layer PATCH endpoints — no new backend endpoints.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during pattern mapping. Known relevant surfaces:
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — receives selection model
- `frontend/src/components/builder/StackRow.tsx` — selection state per row
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — bulk op mutations
- Per-layer PATCH endpoints from v1008 (visibility, opacity)
- Group/ungroup logic from v1008 folder-group support
- Basemap group separation already established — selection model refines existing boundary

</code_context>

<specifics>
## Specific Ideas

- Selection model is a Set<layerId> in component state or zustand
- Bulk action bar anchors to stack footer (or header — designer call)
- Optimistic batched mutation: dispatch all PATCH calls in parallel, on first failure rollback all
- Modifier-key handling: cmd/ctrl-click + shift-click + plain click

</specifics>

<deferred>
## Deferred Ideas

None — discuss skipped.

</deferred>
