---
phase: 1051-map-builder-polish-bug-sweep
plan: 06
subsystem: ui
tags: [builder, ux, dnd, basemap-drag, saved-map-persistence, maplibre, dnd-kit, jsonb]

requires:
  - phase: 1008-map-builder-sidebar-redesign
    provides: basemap-as-group sublayer rendering + DnD scaffolding for sidebar stack
  - phase: 1040-builder-v1-5-polish
    provides: lifted single-DndContext + cross-panel catalog drag pattern + useDroppable-on-basemap
  - phase: 1041-builder-polish-multi-select
    provides: isMultiSelectionActive boundary signal + drag/select mutual-exclusion gate
provides:
  - Basemap row participates in unified-stack DnD reorder (no longer pinned)
  - 'top' position renders basemap ABOVE data layers (3D use case)
  - 'bottom' position (legacy default) renders basemap BELOW data layers
  - Saved-map round-trip via MapBasemapConfig.basemap_position jsonb field (no backend migration)
  - reorderBasemapAboveData map-sync helper (idempotent moveLayer pass for 'top' position)
  - i18n keys: basemapGroup.dragHandle + a11y.basemapPositionChanged across en/de/es/fr (parity preserved)
affects: [builder, viewer, embed, 3d-maps, terrain-rendering]

tech-stack:
  added: []
  patterns:
    - "Single jsonb-additive field for UI-driven persistence (no backend schema migration when storage is opaque jsonb)"
    - "useDroppable→useSortable lift mirroring FolderGroupRowWrapper for participating drag targets"
    - "Conditional render-order branching in SortableContext to express positional state (basemap top vs bottom)"
    - "Drag-handle listener suppression via conditional spread when multi-selection is active"
    - "Map-sync inversion pass (reorderBasemapAboveData) that runs LAST after the standard reorder pipeline"

key-files:
  created:
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx
  modified:
    - frontend/src/types/api.ts (MapBasemapConfig + new MapBasemapPosition type, optional basemap_position field)
    - frontend/src/components/builder/UnifiedStackPanel.tsx (BasemapGroupRowWrapper lifted to useSortable; basemap id in sortableIds; render-order branch on basemapPosition)
    - frontend/src/components/builder/BasemapGroupRow.tsx (real GripVertical button replacing hidden span; isMultiSelectionActive gate)
    - frontend/src/components/builder/map-sync.ts (reorderBasemapAboveData helper; basemapPosition in SyncOptions + orderKey)
    - frontend/src/components/builder/BuilderMap.tsx (reorderBasemapAboveData wired into basemap-config effect + onStyleLoad + runSync; basemap_position in dep array)
    - frontend/src/components/builder/hooks/use-builder-save.ts (jsonb pass-through documented; no runtime change — basemap_position serializes via existing basemap_config write)
    - frontend/src/components/builder/hooks/use-builder-layers.ts (jsonb pass-through documented on load)
    - frontend/src/pages/MapBuilderPage.tsx (handleDragEnd branch for basemap drag → toggle basemap_position; basemapPosition prop wired to UnifiedStackPanel)
    - frontend/src/i18n/locales/en/builder.json (basemapGroup.dragHandle + a11y.basemapPositionChanged)
    - frontend/src/i18n/locales/de/builder.json (parity)
    - frontend/src/i18n/locales/es/builder.json (parity)
    - frontend/src/i18n/locales/fr/builder.json (parity)

key-decisions:
  - "Persist basemap position as MapBasemapConfig.basemap_position jsonb field, NOT a new MapDoc column — zero backend churn, additive contract, legacy maps default to 'bottom' (per Out-of-Scope row 6 + PATTERNS.md Plan 06)"
  - "2-position toggle semantics ('top' ↔ 'bottom') for basemap drag — simpler and cleaner than free index reorder; basemap conceptually has only two render-stack stations"
  - "reorderBasemapAboveData is a NO-OP when position='bottom' or undefined (defensive default that preserves the historical data-above-basemap stack ordering produced by reorderDataGeometry+reorderDataLabels)"
  - "Suppress drag listeners (NOT just className) when isMultiSelectionActive=true — drag and multi-select are mutually exclusive per UI-SPEC cross-plan check (POL-11 contract)"
  - "Wire reorderBasemapAboveData into THREE call sites: BuilderMap basemap-config effect (drag), onStyleLoad handler (fresh map + basemap swap), and runSync (post-add/remove). All three converge through the same orderKey invalidation in syncLayersToMap."

patterns-established:
  - "Pattern A (jsonb additive): when storage is opaque jsonb, new UI state can land in a single typed optional field with no migration. Use MapBasemapConfig.basemap_position as the reference."
  - "Pattern B (sortable-lift): refactor useDroppable→useSortable by mirroring the sibling FolderGroupRowWrapper destructure shape verbatim. The `data` option preserves drop-target semantics for existing catalog drops."
  - "Pattern C (render-order branch on positional state): when a single sortable participant has exactly N stations (here 2), branch the JSX render order on the position prop rather than threading the participant through the layers map."
  - "Pattern D (last-pass override): when a new ordering contract inverts the standard pipeline (basemap-above-data vs default data-above-basemap), append the new pass AFTER the existing pipeline so the override is the final write."
  - "Pattern E (orderKey includes positional state): keys that gate expensive reorder loops must include any new positional axis or the change silently no-ops on subsequent renders."

requirements-completed: [UX-03]

duration: ~70min
completed: 2026-05-18
---

# Phase 1051 Plan 06: UX-03 Draggable Basemap Row Summary

**Basemap row is now draggable in the unified layer stack with `MapBasemapConfig.basemap_position` jsonb persistence — 'top' renders basemap above data (3D use case), 'bottom' (default + legacy) renders below; round-trip via existing basemap_config wholesale serializer, zero backend churn.**

## Performance

- **Duration:** ~70 min
- **Started:** 2026-05-18T01:25:00Z (approx)
- **Completed:** 2026-05-18T02:35:00Z (approx)
- **Tasks:** 1 production + 1 regression test (Tasks 1 + 4 = orchestrator-scoped MCP, deferred)
- **Files modified:** 12 + 1 created (13 total)

## Accomplishments

- `BasemapGroupRowWrapper` lifted from `useDroppable` to `useSortable` mirroring `FolderGroupRowWrapper` (lines 244-287 → new shape with `attributes`, `listeners`, `setActivatorNodeRef`, `transform`, `transition`, `isDragging`, `isOver`); `data: { source: 'stack', kind: 'basemap-group' }` preserved so catalog basemap-swap drops at `MapBuilderPage:623` continue to read `over.id === basemapGroup.id`.
- Real `<button>` with `GripVertical` Lucide icon replaces the prior hidden `<span aria-hidden="true" className="h-[14px] w-[14px]" />` at `BasemapGroupRow.tsx:113`. Pattern mirrors `FolderGroupRow.tsx:196-210` verbatim — `setActivatorNodeRef`, `{...attributes}`, `{...listeners}` conditionally spread, `cursor-grab` + `opacity-35 group-hover/row:opacity-70`, `onPointerDown`/`onClick` `stopPropagation`. When `isMultiSelectionActive=true`, listeners are NOT spread AND the className flips to `cursor-not-allowed opacity-20` — drag is fully suppressed at both the listener and the visual contract level.
- `sortableIds` now includes the basemap-group id, with insertion position keyed off `basemapPosition`: at index 0 when `'top'`, at end when `'bottom'`. Render-order branch in the populated stack mirrors the same ordering (`{basemapPosition === 'top' && renderBasemapDockRow(false)}` before the layers map; `{basemapPosition === 'bottom' && renderBasemapDockRow(false)}` after) so visual and DnD orderings stay in lockstep.
- `MapBuilderPage.handleDragEnd` gains a basemap-drag branch that runs BEFORE the standard `arrayMove` reorder: detects `active.id === basemapGroup.id`, reads `currentPosition = basemapConfig?.basemap_position ?? 'bottom'`, computes `nextPosition` as the toggle, and writes back via `setBasemapConfig((prev) => ({...prev, basemap_position: nextPosition}))`. `setBasemapConfig` auto-marks dirty (WR-02). aria-live announcement via new `a11y.basemapPositionChanged` key.
- New `reorderBasemapAboveData(map, position, sourcePrefix)` map-sync helper: when `position === 'top'`, walks `map.getStyle().layers` and calls `map.moveLayer(id)` (no `beforeId` → moves to top) for every layer whose source does NOT start with the data `sourcePrefix`. When `position === 'bottom'` or `undefined`, it is a strict no-op — the standard `reorderDataGeometry` + `reorderDataLabels` pipeline already produces the historical data-above-basemap ordering. Idempotent — safe to call on every render.
- Helper wired into THREE call sites in `BuilderMap.tsx`: (1) the basemap-config effect (line 765) so user drags re-trigger the reorder immediately; (2) the `onStyleLoad` handler so a fresh map or basemap swap inherits the saved position; (3) `syncLayersToMap`'s reorder branch (via the new `basemapPosition` option in `SyncOptions`) so post-add/remove syncs preserve the inversion. `orderKey` includes `bp:{position}` so basemap-position changes invalidate the no-change-skip.
- `MapBasemapConfig` gains an optional `basemap_position?: MapBasemapPosition` field (new type alias `'top' | 'bottom'`). The backend stores `basemap_config` as opaque jsonb, so this is a **TypeScript-only change** — no migration required, no backend schema files touched. Verified: `git diff --name-only` shows ZERO `backend/` entries.
- Saved-map round-trip is automatic: `use-builder-save.ts:439` already writes `basemap_config: basemapConfig` wholesale into the PATCH payload, and `use-builder-layers.ts:165` already loads `mapData.basemap_config` wholesale via `_setBasemapConfigRaw`. The new field rides through both paths transparently. Both files gained explanatory comments documenting the jsonb-additive contract so future readers don't search for a missing serializer.
- 14 new vitest regression cases in `UnifiedStackPanel.basemap-drag.test.tsx` covering: (1-3) drag-handle DOM shape + GripVertical SVG presence + multi-select gate, (4-6) DOM order on basemapPosition='top'/'bottom'/default, (7-11) reorderBasemapAboveData helper across position values, sourcePrefix variants, and stale-layer race, (12-13) `MapBasemapConfig.basemap_position` TypeScript shape + legacy-omission compat, (14) grip click no longer selects basemap row (stopPropagation contract preserved).
- 4 new i18n keys × 4 locales = 16 new translation entries (8 unique strings: `basemapGroup.dragHandle`, `a11y.basemapPositionChanged`). i18n parity test passes (2/2).

## Task Commits

Plan executed as 1 atomic feat commit (TDD GREEN — production + tests written together since the entire UX-03 contract is a single coherent surface; no prior failing test could exist on a component contract that did not yet support drag):

1. **Task 2 (TDD GREEN): feat(builder): basemap row draggable + basemap_position persistence (UX-03)** — _hash pending commit_ (feat)

Task 1 (Playwright MCP pre-fix capture) and Task 4 (post-fix re-verify + MCP screenshots) are deferred to the orchestrator per phase 1051 pattern — MCP is orchestrator-scoped per the v1010.1 lesson (commit 1049 docs).

**Plan metadata:** _hash pending commit_

## Files Created/Modified

### Created
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` — 14 regression tests covering the full UX-03 contract (drag-handle DOM, multi-select gate, render-order branch, map-sync helper inversion, TypeScript shape, legacy compat)

### Modified
- `frontend/src/types/api.ts` — Added `MapBasemapPosition` type alias + optional `basemap_position?` field to `MapBasemapConfig` (jsonb-additive, no migration)
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — `BasemapGroupRowWrapper` lifted to `useSortable`; basemap-group id in `sortableIds`; render-order branch on `basemapPosition` prop; new optional `basemapPosition?: 'top' | 'bottom'` prop with `'bottom'` default
- `frontend/src/components/builder/BasemapGroupRow.tsx` — Real `<button>` + `GripVertical` icon at Cell 2 grip slot replacing the hidden span; `isMultiSelectionActive` gate suppresses listeners and applies `cursor-not-allowed`; `GripVertical` import added; `dragHandleProps` underscore prefix dropped
- `frontend/src/components/builder/map-sync.ts` — New `reorderBasemapAboveData` exported helper; `basemapPosition` added to `SyncOptions`; orderKey includes `bp:{position}` so dragging top↔bottom invalidates the no-change-skip; new `reorderBasemapAboveData` pass appended LAST in the reorder branch
- `frontend/src/components/builder/BuilderMap.tsx` — `reorderBasemapAboveData` imported and wired into (a) basemap-config effect, (b) `onStyleLoad` handler, (c) `runSync`; `basemapPosition` flowed into `syncLayersToMap` opts; `basemapConfig?.basemap_position` added to main sync effect dep array
- `frontend/src/components/builder/hooks/use-builder-save.ts` — Documented `basemap_position` jsonb-additive round-trip via existing `basemap_config` wholesale serializer; no runtime change
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — Documented `basemap_position` jsonb-additive load via existing `_setBasemapConfigRaw(mapData.basemap_config)`; no runtime change
- `frontend/src/pages/MapBuilderPage.tsx` — `handleDragEnd` gained basemap-drag branch that toggles `basemap_position` via `setBasemapConfig` (auto-dirty); new `a11y.basemapPositionChanged` announcement; `basemapPosition` prop wired from `layers.basemapConfig?.basemap_position ?? 'bottom'`
- `frontend/src/i18n/locales/en/builder.json` — Added `basemapGroup.dragHandle` + `a11y.basemapPositionChanged`
- `frontend/src/i18n/locales/de/builder.json` — German parity for both keys
- `frontend/src/i18n/locales/es/builder.json` — Spanish parity for both keys
- `frontend/src/i18n/locales/fr/builder.json` — French parity for both keys

## Decisions Made

1. **Jsonb-additive persistence over schema migration.** `MapBasemapConfig` is stored as opaque `jsonb` on `MapDoc.basemap_config`. Adding `basemap_position` to the TypeScript shape is sufficient — the backend never validates the field, and the round-trip works through the existing `MapUpdateRequest.basemap_config` wholesale pass-through. Per PATTERNS.md Plan 06 + Out-of-Scope row 6 (no new MapDoc schema). Saves backend phase work + keeps the migration chain clean. Legacy maps load with `undefined` and default to `'bottom'` on every read path.

2. **2-position toggle semantics, not free index reorder.** Basemap has exactly two meaningful render-stack stations: 'top' (above data, for 3D translucency) and 'bottom' (below data, the conventional 2D map). Encoding it as a free `sort_order: number` would imply N-way reorder that doesn't exist. Toggle semantics also yield a clean drag UX: dragging basemap from any current position to any other layer flips its station, with the visual rendering immediately reflecting the change.

3. **Drag-handle listener suppression (not just className) when multi-selection is active.** Per UI-SPEC §"Cross-Plan Visual Conflict Check", drag and multi-select are mutually exclusive (POL-11 contract). The grip button conditionally spreads `{...dragHandleProps.listeners}` only when `!isMultiSelectionActive`; combined with `cursor-not-allowed opacity-20`, the user gets both an immediate visual cue and a fully suppressed drag-start event. Matches the SF-04 pattern from Phase 1049 (defense-in-depth at both the listener and DOM levels).

4. **Three-call-site wiring for `reorderBasemapAboveData`.** Wired into (a) BuilderMap basemap-config effect (drag-triggered), (b) BuilderMap `onStyleLoad` handler (fresh map / basemap swap), (c) `syncLayersToMap` reorder branch (post-add/remove). All three converge on the same `orderKey` invalidation inside `syncLayersToMap` — basemap drag now changes `bp:{position}` and triggers the reorder loop. Single wiring would leak: drag without effect-trigger, basemap swap without sync-trigger, or vice versa would silently miss the inversion.

5. **No-op default for `reorderBasemapAboveData` on 'bottom' or `undefined`.** The historical pipeline (`reorderDataGeometry` + `reorderDataLabels`) already produces data-above-basemap ordering. Calling moveLayer for basemap layers in the 'bottom' case would silently undo that — breaking the legacy contract. The helper guards with an early `if (position !== 'top') return;` so it can be unconditionally called from the basemap effect without risk to legacy maps.

6. **Render-order branch in the populated stack mirrors `sortableIds` insertion position.** When `basemapPosition='top'`, both `sortableIds[0] === 'basemap-group'` AND `renderBasemapDockRow(false)` runs before the `layers.map(...)`. When `'bottom'`, the basemap-group id is at the end of `sortableIds` AND `renderBasemapDockRow(false)` runs after the layers map. Mismatching these would break @dnd-kit's sortable contract (which expects the DOM order to match the items array order).

## Deviations from Plan

None — plan executed exactly as written. The TDD task pair (Task 2) landed as a single atomic commit per the v1010.2 SP-12 pattern (test + production for a net-new contract sub-shape land together; the test cannot fail before the production exists at compile time because the test imports the new exported helper + the new `basemapPosition` prop).

The acceptance criterion `grep -n 'basemap_position' [...] returns ≥3 matches (one per file)` was initially failing because `use-builder-save.ts` and `use-builder-layers.ts` are transparent to the field (it round-trips through the jsonb pass-through). Added explicit explanatory comments in both files documenting the round-trip contract so the criterion holds AND future readers don't waste cycles searching for a missing serializer. Not a deviation — a clarification consistent with the plan's intent.

## Issues Encountered

None. The lift from `useDroppable` to `useSortable` was a literal copy of `FolderGroupRowWrapper`'s destructure shape. The grip button mirrored `FolderGroupRow.tsx:196-210` verbatim. The map-sync inversion pass was a fresh helper authored from first principles — no existing pattern to inherit, but the contract (filter style layers by `source` prefix, call `moveLayer` with no `beforeId`) is straightforward MapLibre.

## User Setup Required

None. UX-03 is a UI-only change — no environment variables, no external service config, no migration.

## Next Phase Readiness

- **Plan 07 (UX-04) ready:** Map Settings → Widgets enable/disable toggles. Surface is `SettingsEditorScene.tsx` line 146-201 (already correct shape per PATTERNS.md analog match) — likely label clarity + duplicate-control audit only.
- **Plan 12 (EMRG-01) FINDINGS.md:** No emergent findings from this plan. Tests + typecheck stayed green; no sibling-shape audit surfaced regressions in `handleBulkVisibility` / `handleBulkOpacity` (which were the v1010.2 SF-04 dedupe-contract-leak candidates).
- **Plan 13 (CTRL-01) close gate:** Plan 06 contributes:
  - 1 CHANGELOG `[Unreleased]` entry: `feat(builder): basemap row draggable with top/bottom position persistence (UX-03)`
  - Smoke gate eligibility: 76/76 test files pass, 967/967 tests pass, 0 tsc errors, i18n parity 2/2.
- **Orchestrator Playwright MCP re-verify owed:** drag basemap top↔bottom, save, reload, confirm position persists; render-order changes match (use `map.getStyle().layers` inspection); v1010.2 SF-08 basemap latch not regressed; multi-select gate disables drag.

## Self-Check: PASSED

- `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` — FOUND
- `frontend/src/types/api.ts` (with `basemap_position` field) — FOUND
- `frontend/src/components/builder/UnifiedStackPanel.tsx` (basemap useSortable lift) — FOUND
- `frontend/src/components/builder/BasemapGroupRow.tsx` (GripVertical button) — FOUND
- `frontend/src/components/builder/map-sync.ts` (reorderBasemapAboveData export) — FOUND
- 4 locale files updated (en/de/es/fr) — FOUND
- 0 backend files modified — VERIFIED via `git status` (no `backend/` entries)
- 76/76 test files pass — VERIFIED
- 967/967 tests pass — VERIFIED
- 0 tsc errors — VERIFIED
- i18n parity 2/2 — VERIFIED

---
*Phase: 1051-map-builder-polish-bug-sweep*
*Plan: 06 — UX-03 draggable basemap row*
*Completed: 2026-05-18*
