---
milestone: v1009
milestone_name: Map Builder v1.5 (Polish)
status: roadmapped
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

- [x] **POL-01** — Vector, raster, and basemap rows in the Add Dataset modal expose a drag affordance (cursor change + grab handle on hover) and are draggable via `@dnd-kit` to the unified stack.
- [x] **POL-02** — Dropping onto the unified stack adds the layer at the drop position; the in-stack insertion line (already implemented in v1008 phase 1038-02) renders during the drag.
- [x] **POL-03** — Dropping onto a folder-group row or its expanded children adds the layer as a child of that group (assigns `parent_group_id`).
- [x] **POL-04** — Dropping a basemap row swaps the basemap rather than creating a new layer (matches the in-modal "swap" CTA).
- [x] **POL-05** — The Add Dataset modal stays open after a successful drag-drop so the user can add multiple layers in one session; a toast confirms each add.

### Multi-Layer Selection / Bulk Operations

The user can select multiple stack rows and perform bulk operations atomically.

- [x] **POL-06** — Stack rows support multi-selection via `cmd-click` (toggle) and `shift-click` (contiguous range), with clear keyboard equivalents (Space toggles, Shift+ArrowUp/Down extends).
- [x] **POL-07** — Selected rows render a distinct selection state (background tint + optional `aria-selected="true"` + visible checkbox); the single-selection focus state for the layer editor remains visually distinguishable from multi-selection.
- [x] **POL-08** — When 2+ rows are selected, a bulk action bar appears (anchored to the stack header or footer) exposing: bulk visibility toggle, bulk opacity slider, group selection, ungroup, delete.
- [x] **POL-09** — Bulk operations execute atomically (single optimistic update, single API write per affected layer); failure surfaces a single error toast and rolls back optimistically updated state.
- [x] **POL-10** — Selection clears on `Escape`, on outside-click of the stack, and on route change.
- [x] **POL-11** — Multi-selection does NOT cross the basemap-group boundary (the basemap row + sublayers cannot be co-selected with overlay layers — bulk delete on basemap is non-sensical).

### General Map Builder UI/UX Sweep

A modern, sleek, intuitive review across the entire builder surface — audit-first, then targeted polish.

- [ ] **POL-12** — A `BUILDER-UX-AUDIT.md` document is produced enumerating findings across the builder (UnifiedStackPanel, LayerEditorPanel, Add Dataset modal, Settings scene, SidebarRail, EmptyStackState) with severity (P0/P1/P2) and a fix-priority recommendation.
- [x] **POL-13** — Spacing and density tokens are normalized across the builder surfaces (UnifiedStackPanel, LayerEditorPanel, Add Dataset modal, Settings) using the `sketch-findings-geolens` token set; visual regressions caught by Playwright snapshots where added.
- [x] **POL-14** — Hover, focus-visible, pressed, and active states are unified across the builder using the same token palette; microinteractions (transitions, drag affordance, expand/collapse) use consistent timing (`--motion-fast`/`--motion-base` tokens).
- [x] **POL-15** — Loading affordances (skeletons for column lists, spinners for async previews, optimistic UI for stack reorder) are present everywhere an async fetch occurs in the builder.
- [x] **POL-16** — Error states are present and recoverable: every async failure point surfaces a localized error message with a retry affordance (no silent failure into the error boundary).
- [x] **POL-17** — Empty states are polished beyond v1008's catalog-first treatment — Filter section "no conditions yet", Labels section "labels off", Source section "no columns indexed", and the LayerEditorPanel itself when basemap-group has zero customization all receive intentional empty-state copy + iconography.
- [x] **POL-18** — Information architecture cleanup: section ordering inside `LayerEditorPanel` is consistent across vector/raster/DEM/basemap layer types; scene transitions (default → basemap-group → basemap-sublayer → back) preserve scroll position and focus.

### Builder Test Debt Closeout

Pre-existing builder test drift surfaced during the v1008 smoke-test sweep is closed out.

- [ ] **POL-19** — All 5 pre-existing builder vitest failures pass: `EmptyStackState.integration` Test 2/3/5, `StackRow` "Delete layer" kebab, `UnifiedStackPanel` "calls onAddDataClick when ＋ Add data button is clicked".
- [ ] **POL-20** — `src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts` runs to completion without `Worker exited unexpectedly` / `Timeout terminating forks worker`; root cause is identified (likely fixture cleanup leak) and documented in the phase summary.
- [ ] **POL-21** — `npx vitest run src/components/builder/` reports 0 failures and 0 unhandled worker errors at milestone close; CI green.

### Cross-Cutting Closeout

- [ ] **POL-22** — i18n locales (en / de / fr / es) updated for every new builder string introduced in v1.5 (drag-from-catalog affordances, bulk action labels, audit-driven copy refinements); `i18n-check` smoke green.
- [x] **POL-23** — Accessibility verified for new interactions: drag-from-catalog supports keyboard-only path (Space to pick up, Arrow to navigate stack, Space to drop, Escape to cancel — mirrors v1008 in-stack drag); multi-select supports Shift+ArrowUp/Down + Space; selection state announced via `aria-multiselectable` on the stack `role="listbox"`.
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

| REQ-ID | Phase | Notes |
|---|---|---|
| POL-01 | 1040 drag-from-catalog-into-stack | Drag affordance on Add Dataset modal rows |
| POL-02 | 1040 drag-from-catalog-into-stack | Drop on stack adds at position; reuses 1038-02 insertion line |
| POL-03 | 1040 drag-from-catalog-into-stack | Drop on folder-group sets `parent_group_id` |
| POL-04 | 1040 drag-from-catalog-into-stack | Basemap drop = swap, not add |
| POL-05 | 1040 drag-from-catalog-into-stack | Modal stays open + per-add toast |
| POL-06 | 1041 multi-layer-selection-and-bulk-ops | cmd/shift-click + Space / Shift+ArrowUp/Down |
| POL-07 | 1041 multi-layer-selection-and-bulk-ops | Selection visual state distinct from single-selection focus |
| POL-08 | 1041 multi-layer-selection-and-bulk-ops | Bulk action bar (visibility / opacity / group / ungroup / delete) |
| POL-09 | 1041 multi-layer-selection-and-bulk-ops | Atomic bulk ops via existing per-layer PATCH endpoints |
| POL-10 | 1041 multi-layer-selection-and-bulk-ops | Selection clears on Escape / outside-click / route change |
| POL-11 | 1041 multi-layer-selection-and-bulk-ops | Basemap-group boundary blocks mixed selection |
| POL-12 | 1039 ux-audit-and-test-debt-closeout | `BUILDER-UX-AUDIT.md` with P0/P1/P2 priorities — drives 1042/1043 |
| POL-13 | 1042 spacing-density-states-polish | Spacing/density token normalization on existing token set |
| POL-14 | 1042 spacing-density-states-polish | Hover/focus/pressed/active state unification + motion tokens |
| POL-15 | 1042 spacing-density-states-polish | Loading affordances everywhere async occurs |
| POL-16 | 1043 error-empty-states-and-ia-cleanup | Recoverable error states with localized retry |
| POL-17 | 1043 error-empty-states-and-ia-cleanup | Filter/Labels/Source/basemap-group empty-state copy + iconography |
| POL-18 | 1043 error-empty-states-and-ia-cleanup | Section ordering consistency + scene-transition focus/scroll preservation |
| POL-19 | 1039 ux-audit-and-test-debt-closeout | 5 pre-existing vitest failures (EmptyStackState ×3, StackRow ×1, UnifiedStackPanel ×1) |
| POL-20 | 1039 ux-audit-and-test-debt-closeout | use-builder-layers.add-dataset.test.ts worker timeout root cause |
| POL-21 | 1039 ux-audit-and-test-debt-closeout | `npx vitest run src/components/builder/` 0 failures + 0 worker errors |
| POL-22 | 1044 cross-cutting-closeout | i18n locale fill en/de/fr/es for all new v1.5 strings |
| POL-23 | 1044 cross-cutting-closeout | a11y verification for drag-from-catalog + multi-select keyboard paths |
| POL-24 | 1044 cross-cutting-closeout | `e2e/builder-v1-5.spec.ts` happy + negative paths |
| POL-25 | 1044 cross-cutting-closeout | Builder smoke green at close (21 existing + new UAT) |

**Coverage:** 25/25 v1 requirements mapped (POL-01..25). No orphans. No duplicates.
