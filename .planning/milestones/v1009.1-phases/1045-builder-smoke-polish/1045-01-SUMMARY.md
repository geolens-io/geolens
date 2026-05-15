---
phase: 1045-builder-smoke-polish
plan: 01
subsystem: builder
tags: [builder, smoke-polish, multi-select, layer-editor, coord-readout]
requirements: [SP-01, SP-02, SP-03, SP-04, SP-05]
metrics:
  duration_minutes: ~75
  tasks_completed: 5
  commits: 5
  test_count_delta: +24 (4 SP-02, 11 SP-04 helper, 5 SP-05 + 1 helper, 1 SP-01 + 3 SP-01 test rewrites)
  files_created:
    - frontend/src/components/builder/selection-utils.ts
    - frontend/src/components/builder/__tests__/selection-utils.test.ts
    - frontend/src/components/map/__tests__/MapCoordReadout.test.tsx
    - .planning/phases/1045-builder-smoke-polish/VERIFICATION.md
    - .planning/phases/1045-builder-smoke-polish/deferred-items.md
  files_modified:
    - frontend/src/components/builder/BulkActionBar.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/map/MapCoordReadout.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/__tests__/BulkActionBar.test.tsx
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
    - frontend/src/i18n/locales/{en,de,es,fr}/builder.json
---

# Phase 1045 Plan A: Builder Smoke Polish — SP-01..SP-05

5 tasks closed: 1 BLOCKER (SP-01) + 3 MAJORs (SP-02, SP-04, SP-05) + 1 verification
(SP-03 via B-01 entanglement).

## Task A.1 / SP-01 — Unclip BulkActionBar via overflow menu

**Outcome:** Group / Ungroup / Delete are now reachable inside the 340px sidebar at 1440x900.
Visibility + Opacity remain inline; Group / Ungroup / Delete moved into a `…`
overflow DropdownMenu (Radix-portaled so the `<aside class="overflow-hidden">` clip is
no longer a factor).

**Files changed:**
- `frontend/src/components/builder/BulkActionBar.tsx` — rewrite of trailing button cluster
  as `<DropdownMenu>` + `<DropdownMenuItem>`s with `data-testid="bulk-action-{group,ungroup,delete}"`
  and `data-bulk-action-menu="true"` on the menu content.
- `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — added `bulkActions.moreActions`
  and `bulkActions.moreActionsAriaLabel` across all 4 locales (namespace parity).
- `frontend/src/components/builder/__tests__/BulkActionBar.test.tsx` — updated 9 tests to
  open the overflow menu first; introduced `openDeleteConfirm()` helper for the 6
  confirmation-state-machine tests; added `data-bulk-action-menu` presence assertion.

**Commit:** `bbde1a5d`
**Verification:** vitest 23/23 PASS

## Task A.2 / SP-05 — Gate "Pending style preview" banner on real dirty state

**Outcome:** Banner no longer appears on first-open of a freshly-added layer's editor.
It appears only when the editor draft's paint / layout / style_config diverges from the
server-state baseline. Reset action remains scoped to layer style only.

**Files changed:**
- `frontend/src/components/builder/LayerStyleEditor.tsx` —
  - Exported `hasUnsavedStyleChanges(draft, saved)` helper with inline deep-equal.
  - Added `savedLayer?: MapLayerResponse` prop.
  - Gated `<StylePreview>` render on `useMemo(() => hasUnsavedStyleChanges(layer, savedLayer), [layer, savedLayer])`.
- `frontend/src/components/builder/LayerEditorPanel.tsx` — threads `savedLayer` to both
  LayerStyleEditor mount points (section-based body + legacy tabbed body).
- `frontend/src/pages/MapBuilderPage.tsx` — added `editingSavedLayer = useMemo(...)` that
  looks up the baseline by id from `layers.savedLayerBaseline`; passes to both
  `LayerEditorPanel` mounts (default + drill-down).
- `frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx` — replaced the
  "shows banner unconditionally" test with 4 SP-05 dirty-tracking cases + 5 direct
  `hasUnsavedStyleChanges` unit tests covering paint / layout / style_config divergence
  and identity short-circuits.

**Commit:** `88b75216`
**Verification:** vitest 49/49 PASS

## Task A.3 / SP-04 — Shift-click range-selection

**Outcome:** Shift-click on a layer row extends the selection from the last anchor to the
clicked row in both directions, matching macOS Finder semantics. Cmd/Ctrl-click toggles
individuals. Plain click clears + sets the anchor.

**Files changed:**
- `frontend/src/components/builder/selection-utils.ts` (new) — pure helper
  `computeNextSelection(rows, clickedId, modifiers, current, anchor) → {selection, anchor}`.
- `frontend/src/components/builder/__tests__/selection-utils.test.ts` (new) — 11 unit tests:
  plain click, cmd/ctrl toggle, shift-down, shift-up, no-anchor fallback,
  shift-after-extend-keeps-anchor, range-replaces-not-adds, unknown-row fallback,
  stale-anchor fallback.
- `frontend/src/pages/MapBuilderPage.tsx` — replaced inline cmd-click / shift-click logic
  with calls into `computeNextSelection`. Added `handlePlainSelectAnchor(id)` invoked from
  `handleSelectLayer` so plain row clicks record the anchor; basemap-boundary ids are
  excluded from anchor recording.

**Plan deviation:** the plan listed `UnifiedStackPanel.tsx` + `StackRow.tsx` as the files,
but the selection state (selectedIds, lastToggleAnchor) lives in MapBuilderPage. Helper is
still extracted as planned; logic rewired there. No StackRow / UnifiedStackPanel code change.

**Commit:** `5deb2187`
**Verification:** vitest 95/95 PASS (UnifiedStackPanel + StackRow + selection-utils + others)

## Task A.4 / SP-02 — Coord readout subscribes to maplibre `move` events

**Outcome:** Top-right `lat° N · lng° W · z` readout updates on every camera change
(programmatic flyTo, fitBounds, drag-pan, inertial pan). No longer stale at the initial map
center when the user never hovers the canvas.

**Files changed:**
- `frontend/src/components/map/MapCoordReadout.tsx` — added `map.on('move', onMove)`
  subscription with rAF throttling; `mouseleave` now updates from `map.getCenter()` via
  the same `updateFromCenter()` helper; `zoomend` retained for back-compat and updates
  zoom only.
- `frontend/src/components/map/__tests__/MapCoordReadout.test.tsx` (new) — 4 tests:
  initial render, `move` subscription presence, programmatic-move update, unmount cleanup.

**Plan deviation:** the plan listed `MapBuilderPage.tsx` + `BuilderMap.tsx` as the files.
The actual readout lives in `MapCoordReadout.tsx` (mounted by BuilderMap line 864). Fix
went to the real source. No BuilderMap code change.

**Commit:** `05daacc0`
**Verification:** vitest 4/4 PASS; existing BuilderMap + MapBuilderPage tests 24/24 PASS

## Task A.5 / SP-03 — DEM auto-add verification

**Outcome:** **PENDING-USER-VERIFY** — see `VERIFICATION.md`. Code-level audit of the B-01
fix at commit `85738f1c` shows it semantically closes M-02 (DEM auto-add):
- B-01 replaced a racy `isLoading` boolean gate with per-dataset `tokenMap.has(dataset_id)`
  presence checks in BOTH the main sync effect AND the `style.load` handler.
- DEM rasters share the same `tokenMap` path as vector layers — the fix is dataset-type
  agnostic.
- `tokenMap` is now a primary effect dependency, so the effect re-runs the moment tokens
  land for any newly added layer (vector or raster).

Live browser confirmation could not be performed from this execution context (no Playwright
MCP tools in the executor agent's function set). Per the plan's ESCALATE branch, this is
surfaced to the user to perform the 5-step manual check listed in
`.planning/phases/1045-builder-smoke-polish/VERIFICATION.md`.

**No commit — verification-only task.**

## Code review

Self-review caught one regression: Radix portals the `BulkActionBar` overflow menu out of
the `UnifiedStackPanel` `stackPanelRef` subtree. The panel's `document.mousedown`
outside-click guard treated menuitem clicks as "outside" and cleared the selection before
the menuitem's `onSelect` ran — Delete confirmation would not appear; Group / Ungroup
would fire against an emptied set.

**Fix:** added `data-bulk-action-menu="true"` to the DropdownMenuContent; UnifiedStackPanel's
outside-click handler now skips when `event.target.closest('[data-bulk-action-menu="true"]')`
matches. Test added.

**Commit:** `7aba7cd9`

`gsd-code-reviewer` agent could not be spawned from the executor agent's function set; the
above is a self-review reading the HEAD~5..HEAD diff. No other findings.

## Deviations from Plan

### Auto-fixed

1. **[Rule 1 — Bug] BulkActionBar overflow menu cleared selection on item click.**
   Found during self-review. Fix: data-attribute marker + outside-click guard.
   Commit `7aba7cd9`.

2. **[File-path correction]** Plan A.3 listed `UnifiedStackPanel.tsx` + `StackRow.tsx`;
   actual logic lived in `MapBuilderPage.tsx`. Helper still extracted as planned.

3. **[File-path correction]** Plan A.4 listed `MapBuilderPage.tsx` + `BuilderMap.tsx`;
   actual readout lived in `MapCoordReadout.tsx` (mounted by BuilderMap). Fix went to the
   real source.

### Out of scope (deferred)

5 pre-existing lint errors in `EmptyStackState.tsx` (4) and `UnifiedStackPanel.test.tsx`
(1) were detected by `npx eslint src/`. Confirmed pre-existing on `main` before plan A
commits. Logged to `.planning/phases/1045-builder-smoke-polish/deferred-items.md`.

## Post-task gates

| Gate | Result |
| ---- | ------ |
| `cd frontend && npx tsc --noEmit` | clean (0 errors) |
| `cd frontend && npx eslint src/` | 5 errors **all pre-existing on main**; 0 errors in plan A diff |
| `cd frontend && npm test -- --run BulkActionBar LayerStyleEditor UnifiedStackPanel StackRow BuilderMap MapBuilderPage selection-utils MapCoordReadout` | 195/195 PASS |

## Commits

| Hash | Subject |
| ---- | ------- |
| `bbde1a5d` | fix(builder): unclip BulkActionBar Group/Ungroup/Delete via overflow menu |
| `88b75216` | fix(builder): gate Pending style preview banner on real dirty state |
| `5deb2187` | feat(builder): shift-click extends layer selection as range |
| `05daacc0` | fix(builder): subscribe coord readout to maplibre move events |
| `7aba7cd9` | fix(review): keep selection alive when bulk overflow menu is open |

## Self-Check: PASSED

- All 4 code-changing commits present in `git log`.
- All listed files exist and were modified by the commits above.
- VERIFICATION.md, deferred-items.md, selection-utils.ts, selection-utils.test.ts,
  MapCoordReadout.test.tsx all created.
- tsc + plan-test scope is clean; full-tree lint errors are pre-existing.
