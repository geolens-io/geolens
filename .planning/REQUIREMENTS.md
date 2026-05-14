---
milestone: v1009
milestone_name: Map Builder v1.5 (Polish)
status: draft
created: 2026-05-14
---

# Map Builder v1.5 (Polish) — Requirements

**Milestone:** v1009 Map Builder v1.5 (Polish)
**Started:** 2026-05-14

**Goal:** Polish the v1008 unified-stack Map Builder — add the two highest-value v1008 deferrals (drag-from-catalog, multi-layer selection), sweep the entire builder surface for modern, sleek, intuitive presentation, and close out pre-existing builder test drift.

**Naming convention:** Requirement IDs use the `POL-NN` prefix (POLish).

---

## v1 Requirements

### Drag-from-Catalog-into-Stack

The user can drag a dataset row from the Add Dataset modal directly onto the unified layer stack to add it as a layer, without click-through.

- [ ] **POL-01** — Vector, raster, and basemap rows in the Add Dataset modal expose a drag affordance (cursor change + grab handle on hover) and are draggable via `@dnd-kit` to the unified stack.
- [ ] **POL-02** — Dropping onto the unified stack adds the layer at the drop position; the in-stack insertion line (already implemented in v1008 phase 1038-02) renders during the drag.
- [ ] **POL-03** — Dropping onto a folder-group row or its expanded children adds the layer as a child of that group (assigns `parent_group_id`).
- [ ] **POL-04** — Dropping a basemap row swaps the basemap rather than creating a new layer (matches the in-modal "swap" CTA).
- [ ] **POL-05** — The Add Dataset modal stays open after a successful drag-drop so the user can add multiple layers in one session; a toast confirms each add.

### Multi-Layer Selection / Bulk Operations

The user can select multiple stack rows and perform bulk operations atomically.

- [ ] **POL-06** — Stack rows support multi-selection via `cmd-click` (toggle) and `shift-click` (contiguous range), with clear keyboard equivalents (Space toggles, Shift+ArrowUp/Down extends).
- [ ] **POL-07** — Selected rows render a distinct selection state (background tint + optional `aria-selected="true"` + visible checkbox); the single-selection focus state for the layer editor remains visually distinguishable from multi-selection.
- [ ] **POL-08** — When 2+ rows are selected, a bulk action bar appears (anchored to the stack header or footer) exposing: bulk visibility toggle, bulk opacity slider, group selection, ungroup, delete.
- [ ] **POL-09** — Bulk operations execute atomically (single optimistic update, single API write per affected layer); failure surfaces a single error toast and rolls back optimistically updated state.
- [ ] **POL-10** — Selection clears on `Escape`, on outside-click of the stack, and on route change.
- [ ] **POL-11** — Multi-selection does NOT cross the basemap-group boundary (the basemap row + sublayers cannot be co-selected with overlay layers — bulk delete on basemap is non-sensical).

### General Map Builder UI/UX Sweep

A modern, sleek, intuitive review across the entire builder surface — audit-first, then targeted polish.

- [ ] **POL-12** — A `BUILDER-UX-AUDIT.md` document is produced enumerating findings across the builder (UnifiedStackPanel, LayerEditorPanel, Add Dataset modal, Settings scene, SidebarRail, EmptyStackState) with severity (P0/P1/P2) and a fix-priority recommendation.
- [ ] **POL-13** — Spacing and density tokens are normalized across the builder surfaces (UnifiedStackPanel, LayerEditorPanel, Add Dataset modal, Settings) using the `sketch-findings-geolens` token set; visual regressions caught by Playwright snapshots where added.
- [ ] **POL-14** — Hover, focus-visible, pressed, and active states are unified across the builder using the same token palette; microinteractions (transitions, drag affordance, expand/collapse) use consistent timing (`--motion-fast`/`--motion-base` tokens).
- [ ] **POL-15** — Loading affordances (skeletons for column lists, spinners for async previews, optimistic UI for stack reorder) are present everywhere an async fetch occurs in the builder.
- [ ] **POL-16** — Error states are present and recoverable: every async failure point surfaces a localized error message with a retry affordance (no silent failure into the error boundary).
- [ ] **POL-17** — Empty states are polished beyond v1008's catalog-first treatment — Filter section "no conditions yet", Labels section "labels off", Source section "no columns indexed", and the LayerEditorPanel itself when basemap-group has zero customization all receive intentional empty-state copy + iconography.
- [ ] **POL-18** — Information architecture cleanup: section ordering inside `LayerEditorPanel` is consistent across vector/raster/DEM/basemap layer types; scene transitions (default → basemap-group → basemap-sublayer → back) preserve scroll position and focus.

### Builder Test Debt Closeout

Pre-existing builder test drift surfaced during the v1008 smoke-test sweep is closed out.

- [ ] **POL-19** — All 5 pre-existing builder vitest failures pass: `EmptyStackState.integration` Test 2/3/5, `StackRow` "Delete layer" kebab, `UnifiedStackPanel` "calls onAddDataClick when ＋ Add data button is clicked".
- [ ] **POL-20** — `src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts` runs to completion without `Worker exited unexpectedly` / `Timeout terminating forks worker`; root cause is identified (likely fixture cleanup leak) and documented in the phase summary.
- [ ] **POL-21** — `npx vitest run src/components/builder/` reports 0 failures and 0 unhandled worker errors at milestone close; CI green.

### Cross-Cutting Closeout

- [ ] **POL-22** — i18n locales (en / de / fr / es) updated for every new builder string introduced in v1.5 (drag-from-catalog affordances, bulk action labels, audit-driven copy refinements); `i18n-check` smoke green.
- [ ] **POL-23** — Accessibility verified for new interactions: drag-from-catalog supports keyboard-only path (Space to pick up, Arrow to navigate stack, Space to drop, Escape to cancel — mirrors v1008 in-stack drag); multi-select supports Shift+ArrowUp/Down + Space; selection state announced via `aria-multiselectable` on the stack `role="listbox"`.
- [ ] **POL-24** — A Playwright UAT spec (`e2e/builder-v1-5.spec.ts`) exercises the drag-from-catalog happy path, multi-select bulk-delete happy path, and one negative-path each (cancel via Escape during drag; bulk delete with mixed basemap + overlay selection blocked).
- [ ] **POL-25** — Builder smoke (`npm run e2e:smoke:builder`) remains green at milestone close; all 21 existing tests pass + the new UAT spec from POL-24 is added.

---

## Future Requirements

_(Deferred to a later milestone; not in scope for v1.5)_

- Mobile-specific `<800px` drill-down polish beyond what POL-12's audit surfaces (gesture handling, sheet snap points, touch-target sizing audit)
- Full Add Data modal redesign (incremental polish only via POL-13/14)
- `/api/datasets/suggested` backend endpoint (still hand-curated v1)
- Drag-from-catalog with multi-rendering bulk-add (drop one row, get N renderings)
- Drag-to-reorder within the Add Dataset modal results list

---

## Out of Scope

- Re-architecting the unified stack or layer editor flyout (v1008 foundation is locked)
- Backend API changes to the maps router (v1.5 is a frontend polish milestone — POL-09 bulk ops use existing per-layer PATCH endpoints)
- New layer types or render modes (v1004 / v1005 / v1006 scope is closed)
- Saved-map normalizer changes (v1008 phase 1033 is the canonical migration; no shape changes in v1.5)
- Public viewer / shared / embed surface changes (parity guarantee from v1008 carries forward)

---

## Traceability

_(Filled by gsd-roadmapper after phase definition)_

| REQ-ID | Phase | Notes |
|---|---|---|
