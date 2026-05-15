---
phase: 1040
phase_name: drag-from-catalog-into-stack
status: ready_for_planning
generated: auto (workflow.skip_discuss=true)
date: 2026-05-14
---

# Phase 1040: drag-from-catalog-into-stack — Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Let users drag vector, raster, or basemap rows from the Add Dataset modal directly onto the unified layer stack to add a layer (or swap a basemap) without click-through, while keeping the modal open for repeated adds and supporting a keyboard-only fallback.

**Requirements:** POL-01, POL-02, POL-03, POL-04, POL-05

**Success Criteria:**
1. Hovering a dataset row in the Add Dataset modal shows grab cursor + grab handle affordance; dragging shows the in-stack 2px insertion line.
2. Dropping at a position adds the layer at that position; dropping onto a folder-group row (or expanded children) adds as a child with `parent_group_id` set.
3. Dragging a basemap row and dropping swaps the current basemap (no new overlay layer); matches in-modal "swap" CTA.
4. Modal stays open after a successful drag-drop; toast confirms each add; multiple adds can be chained in one modal session.

**Depends on:** Phase 1039 (ux-audit + test debt closeout — shipped).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, codebase conventions, and `sketch-findings-geolens` tokens.

### Hard Constraints (from v1009 milestone)
- No saved-map shape changes (Phase 1033 normalizer is locked).
- No public viewer / shared / embed surface changes (parity guarantee).
- All work uses the `sketch-findings-geolens` token set; no new tokens introduced.
- POL-09 bulk operations use existing per-layer PATCH endpoints — no backend API changes (this phase predates 1041 but the same rule applies — no new backend endpoints).

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Known relevant surfaces:
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — unified drag-orderable layer stack
- `frontend/src/components/builder/StackRow.tsx` — row component
- `frontend/src/components/builder/AddDatasetModal.tsx` (or similar) — Add Dataset modal
- `frontend/src/hooks/use-builder-layers.ts` — layer mutation hook (add/remove/reorder)
- DnD primitives — already in use for intra-stack reorder per v1008 shipped work

</code_context>

<specifics>
## Specific Ideas

- Reuse existing intra-stack DnD primitives where possible
- 2px insertion line is the existing v1008 insertion-line component
- Toast confirmation pattern — match existing add-layer success toast
- Keyboard fallback — "Add at top / Add at bottom / Add to group X" affordance on dataset row (POL-05)

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. Planner has full discretion within success criteria.

</deferred>
