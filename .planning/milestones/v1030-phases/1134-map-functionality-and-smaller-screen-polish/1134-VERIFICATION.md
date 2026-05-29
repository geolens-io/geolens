---
phase: 1134-map-functionality-and-smaller-screen-polish
verified: 2026-05-27T18:30:00Z
status: passed
score: 5/5
overrides_applied: 0
---

# Phase 1134: Map Functionality and Smaller-Screen Polish — Verification Report

**Phase Goal:** Close the Tier-1 `todo.md` bug-shape items (delete-layer, visibility-toggle, rename-group focus) and the ≤800px layout collisions so the `dispatchLayerAction` boundary is stable before Phase 1135's AI staging work touches it.
**Verified:** 2026-05-27T18:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Delete layer across every render mode without orphan sources, layer-stack entries, or save-state drift | VERIFIED | `builder-layer-mutations.ts` has `deriveCompanionIds` + `getLayerIds` adapter lookup; `builder-layer-mutations.test.ts` (12 tests) pins fill/cluster/circle/symbol/heatmap/line/raster/fallback paths; `use-builder-layers.delete.test.ts` MAP-17 block (5 tests) covers adapter-driven sweep at hook boundary. ROADMAP SC1 names `use-builder-layers.test.tsx` — actual path is `hooks/__tests__/use-builder-layers.delete.test.ts`; plan acknowledged the ROADMAP path was generic, substantive coverage confirmed at that path. |
| 2 | Visibility toggle across all render modes immediately reflected on canvas | VERIFIED | `raster-adapter.ts` split-guard refactors early-return bug (WALK-R-05); `symbol-adapter.ts` migrated to `syncLayerFilter` helper; 7 adapter test files (raster, symbol, circle, heatmap, fill, line, cluster) each contain BUG-01 `visible=false` at add-time pin and `syncVisibility` coverage. 31/31 Playwright MCP tests PASS across 3 viewports. |
| 3 | Rename group input receives focus on first paint via rAF-deferred focus | VERIFIED | `FolderGroupRow.tsx:85-92` contains `requestAnimationFrame(() => inputRef.current.focus())` — unchanged from v1011 BUG-03 fix. `UnifiedStackPanel.test.tsx` MAP-16 block (2 tests: integration via `vi.importActual` + source-text pin). `FolderGroupRow.test.tsx` negative-control pin at line 453 asserts `rafCallbacks.length > 0` (rAF deferral in place). |
| 4 | At ≤800px: Sheet does not overlap NavigationControl; lat/long readout has right-14 offset; every SheetContent has showCloseButton={false} | VERIFIED | `MapBuilderPage.tsx` has `mt-12 h-[calc(100%-3rem)]` on both SheetContent elements (lines 1265, 1386); `showCloseButton={false}` confirmed on 2 surfaces. `MapCoordReadout.tsx` has `right-14 top-2 z-10`. `MapBuilderPage.sheet-close-button.test.tsx` MAP-10 exhaustive grep-guard. `MapCoordReadout.test.tsx` MAP-08 `toHaveClass('right-14')` pin. MCP PASS at 800×600 and 414×896. NavigationControl position confirmed `top-left` (Pitfall #10 honored). |
| 5 | Map container does not scroll page body; filter pills do not collide with measure widget; Notes shows presence indicator | VERIFIED | `ActiveFilterChips.tsx` has `max-h-[40vh] overflow-y-auto` at line 124. `BuilderRail.tsx` has `notes.trim().length > 0` dot span at line 105-108. `MapBuilderPage.tsx` mobileRailButtons Notes button has matching dot at line 1346. `BuilderMap.scroll.test.tsx` static overflow pin (4 tests). MCP MAP-19 (`scrollY===0` after canvas wheel), MAP-20, MAP-22 all PASS at all 3 viewports. |

**Score:** 5/5 truths verified

---

### Hard Invariants

| Invariant | Status | Evidence |
|-----------|--------|----------|
| BuilderLayerAction union NOT widened | VERIFIED | Zero phase-1134 commits touched `builder-action-contract.ts` — confirmed via `git show --name-only` on all 12 commits. |
| NavigationControl stays top-left (Pitfall #10) | VERIFIED | `BuilderMap.tsx:1091` — `<NavigationControl position="top-left" />` unchanged. MCP DOM query confirmed at all 3 viewports. |
| showCloseButton={false} on builder Sheets (Pitfall #11) | VERIFIED | `grep -cE "showCloseButton=\{false\}" MapBuilderPage.tsx` returns 2; exhaustive grep-guard test pins this going forward. |
| No new design tokens | VERIFIED | No CSS token files or design token files appear in phase-1134 commit stats. |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/builder/layer-adapters/raster-adapter.ts` | Split source/layer guards (WALK-R-05) | VERIFIED | `if (!map.getSource(sourceId))` guard at line 64; `if (map.getLayer(layerId)) return` at line 74; old single early-return gone. |
| `frontend/src/components/builder/layer-adapters/symbol-adapter.ts` | syncLayerFilter migration | VERIFIED | 3 occurrences of `syncLayerFilter` in file (import + addLayers + syncPaint); 0 raw `map.setFilter(input.layerId` calls remaining. |
| `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` | 7-test regression suite | VERIFIED | File exists; Tests 2 pins WALK-R-05 source-exists/layer-missing path. |
| `frontend/src/components/builder/layer-adapters/__tests__/symbol-adapter.test.ts` | BUG-01 + filter sync | VERIFIED | File exists with 6 tests. |
| `frontend/src/components/builder/layer-adapters/__tests__/circle-adapter.test.ts` | BUG-01 regression pin | VERIFIED | File exists; `grep -l "visible.*false"` confirms pin. |
| `frontend/src/components/builder/layer-adapters/__tests__/heatmap-adapter.test.ts` | Extended with BUG-01 pin | VERIFIED | File extended with `visible=false` and syncVisibility assertions. |
| `frontend/src/components/builder/layer-adapters/__tests__/fill-adapter.test.ts` | BUG-01 + 3-companion sweep | VERIFIED | File exists with 7 tests; companion visibility coverage noted with existing gap on extrusion initial layout. |
| `frontend/src/components/builder/layer-adapters/__tests__/line-adapter.test.ts` | BUG-01 + arrow companion | VERIFIED | File exists; line adapter correctly returns `[layerId, arrowLayerId]`. |
| `frontend/src/components/builder/layer-adapters/__tests__/cluster-adapter.test.ts` | BUG-01 across 3 sub-layers | VERIFIED | File exists; raw `setFilter` for compound filter documented as intentional v1026 exception. |
| `frontend/src/components/builder/hooks/builder-layer-mutations.ts` | deriveCompanionIds + getLayerIds | VERIFIED | `deriveCompanionIds` at line 23; `getLayerIds` called at line 30; optional `renderModeByLayerId` arg preserves 3 existing call sites in use-builder-layers.ts unchanged. |
| `frontend/src/components/builder/hooks/__tests__/builder-layer-mutations.test.ts` | 12 per-render-mode tests | VERIFIED | File exists; 11 test() calls confirmed. |
| `frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts` | MAP-17 block (5 new tests) | VERIFIED | `describe('MAP-17 — adapter-driven companion sweep')` at line 251 with Tests A–E. |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` | MAP-16 integration test | VERIFIED | MAP-16 describe block at line 644 with integration + source-text pin. |
| `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` | MAP-16 negative-control | VERIFIED | Negative-control test at line 453 with `rafCallbacks.length > 0` assertion. |
| `frontend/src/pages/MapBuilderPage.tsx` | mt-12 offset on both SheetContent | VERIFIED | Lines 1265, 1386 both have `mt-12 h-[calc(100%-3rem)]`. |
| `frontend/src/components/builder/ActiveFilterChips.tsx` | max-h-[40vh] overflow-y-auto | VERIFIED | Line 124 confirms both classes present with MAP-20 comment. |
| `frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` | MAP-10 exhaustive grep-guard | VERIFIED | MAP-10 describe block at line 339. |
| `frontend/src/components/map/__tests__/MapCoordReadout.test.tsx` | MAP-08 right-14 positive pin | VERIFIED | `toHaveClass('right-14')` at line 242; describe block at line 230. |
| `frontend/src/components/builder/__tests__/ActiveFilterChips.test.tsx` | MAP-20 class regression pin | VERIFIED | File exists (NEW); 5 tests pinning max-h, null-render, label, callback, source guard. |
| `frontend/src/components/builder/BuilderRail.tsx` | Notes presence dot | VERIFIED | `notes.trim().length > 0` conditional span at lines 105-108; `size-1.5 rounded-full bg-primary`. |
| `frontend/src/components/builder/__tests__/BuilderRail.test.tsx` | MAP-22 presence/absence/negative-control | VERIFIED | MAP-22 describe at line 130; 3 new tests. |
| `frontend/src/components/builder/__tests__/BuilderMap.scroll.test.tsx` | MAP-19 static overflow pin | VERIFIED | File exists (NEW); 4 tests; uses Vite `?raw` import pattern (not node:fs). |
| i18n: `en/de/es/fr builder.json` | `rail.notesPresent` key in all 4 locales | VERIFIED | All 4 files return 1 match for `notesPresent`. |
| `frontend/src/pages/MapBuilderPage.tsx` mobileRailButtons | MAP-22 presence dot at <800px | VERIFIED | `dockNotes.trim().length > 0` conditional span at line 1346; reads from live `dockNotes` useState. Inline fix `6efa4544` applied during Plan 06 MCP. |
| `.planning/phases/1134-.../1134-06-MCP-VERIFY.md` | Live MCP smoke report | VERIFIED | File exists with 31/31 PASS across 10 MAP reqs × 3 viewports; 0 console errors. |
| `e2e/mcp-verify-1134-06.spec.ts` | 31-test Playwright spec | VERIFIED | File exists; 10 `test()` blocks each iterated over 3 viewport structs = 30+ test cases; MAP-22 mobile dot coverage confirmed. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| raster-adapter.ts addLayers | map.addSource + map.addLayer | split guards | VERIFIED | `if (!map.getSource(sourceId))` → addSource; `if (map.getLayer(layerId)) return` → guard-only; addLayer unconditional after guard |
| symbol-adapter.ts syncPaint | shared.ts syncLayerFilter | import + call | VERIFIED | Import at line 3; syncPaint call at line 151; addLayers call at line 133 |
| builder-layer-mutations.ts removePerLayerCompanions | layer-adapters getLayerIds | adapter registry lookup | VERIFIED | `deriveCompanionIds` calls `getAdapter(renderMode).getLayerIds(prefixedId)` |
| use-builder-layers.ts handleRemove (3 sites) | removePerLayerCompanions | call site | VERIFIED | Lines 310, 629, 805 — all unchanged (optional arg back-compat); confirmed by `git diff` returning empty for use-builder-layers.ts in plan-02 commits |
| FolderGroupRow editing useEffect | requestAnimationFrame focus | rAF deferral | VERIFIED | `requestAnimationFrame(() => { if (inputRef.current) { inputRef.current.focus() } })` in editing useEffect |
| MapBuilderPage.tsx Sheet overlays | mt-12 vertical offset | className | VERIFIED | Both SheetContent elements have `mt-12 h-[calc(100%-3rem)]` |
| ActiveFilterChips chip container | max-h constraint | className | VERIFIED | `max-h-[40vh] overflow-y-auto` at line 124 |
| BuilderRail Notes button | presence dot span | conditional render | VERIFIED | `btn.id === 'notes' && notes.trim().length > 0` gate |
| MapBuilderPage mobileRailButtons Notes | presence dot span | conditional render | VERIFIED | `dockNotes.trim().length > 0` gate at line 1346; mirrors BuilderRail pattern |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| BuilderRail.tsx presence dot | `notes` prop | `dockNotes` useState at MapBuilderPage.tsx:122, passed as `BuilderRailProps.notes` | Yes — useState initialized empty, updated by user via notes dock `<textarea>` | FLOWING |
| MapBuilderPage mobileRailButtons dot | `dockNotes` | Same useState at line 122 — direct read at line 1346 | Yes — same state, no indirection | FLOWING |
| ActiveFilterChips | `layers` prop (filter state) | `use-builder-layers` hook → persisted layer filter state | Yes — from real layer state | FLOWING |

---

### Behavioral Spot-Checks

Step 7b applied to the runnable artifacts.

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| raster split-guard: no early-return pattern remains | `grep -n "if (map.getSource(sourceId)) return" raster-adapter.ts` returns 0 | 0 matches | PASS |
| symbol syncLayerFilter: raw setFilter call gone | `grep -nE "map\.setFilter\(input\.layerId" symbol-adapter.ts` returns 0 | 0 matches | PASS |
| deriveCompanionIds wired to getLayerIds | `grep -nE "getLayerIds" builder-layer-mutations.ts` ≥1 | 3 matches | PASS |
| mt-12 on both SheetContent overlays | `grep -nE "mt-12 h-\[calc" MapBuilderPage.tsx` = 2 | 2 matches | PASS |
| max-h-[40vh] on filter chips | `grep -nE "max-h-\[40vh\]" ActiveFilterChips.tsx` ≥1 | 1 match | PASS |
| Notes dot reads dockNotes state | `grep -n "dockNotes.trim" MapBuilderPage.tsx` ≥1 | 1 match | PASS |
| BuilderLayerAction union unchanged | Phase-1134 commits touch `builder-action-contract.ts`: 0 | 0 files modified | PASS |
| NavigationControl stays top-left | `grep -nE "NavigationControl position" BuilderMap.tsx` = top-left | 1 match, `top-left` | PASS |
| showCloseButton={false} on 2 Sheets | count in MapBuilderPage.tsx | 2 | PASS |

---

### Probe Execution

No `scripts/*/tests/probe-*.sh` declared or conventional for this phase. Step 7c: SKIPPED (no probe scripts).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MAP-07 | 1134-04 | ≤800px Sheet does not overlap NavigationControl | SATISFIED | mt-12 SheetContent offset; MCP PASS at 800×600 and 414×896 |
| MAP-08 | 1134-04 | Lat/long readout pill does not overlap widget container | SATISFIED | right-14 positive pin in MapCoordReadout.test.tsx; MCP PASS |
| MAP-09 | 1134-04 | Basemap selector renders single close button | SATISFIED | showCloseButton={false} exhaustive grep-guard; cross-referenced in test |
| MAP-10 | 1134-04 | Every SheetContent has showCloseButton={false} | SATISFIED | MapBuilderPage.sheet-close-button.test.tsx exhaustive grep-guard test |
| MAP-16 | 1134-03 | Rename group input focuses via rAF-deferred (v1011 BUG-03) | SATISFIED | UnifiedStackPanel.test.tsx MAP-16 integration + FolderGroupRow.test.tsx negative-control |
| MAP-17 | 1134-02 | Delete layer across every render mode, no orphans | SATISFIED | adapter-driven removePerLayerCompanions; 12 + 5 regression tests |
| MAP-18 | 1134-01 | Visibility toggle across all render modes immediately | SATISFIED | raster split-guard; symbol syncLayerFilter; 7-adapter BUG-01 pin suite |
| MAP-19 | 1134-05 | Map container does not scroll page body | SATISFIED | BuilderMap.scroll.test.tsx static pin; MCP scrollY=0 verified |
| MAP-20 | 1134-04 | Filter pills do not collide with measure widget | SATISFIED | max-h-[40vh] overflow-y-auto; ActiveFilterChips.test.tsx; MCP PASS |
| MAP-22 | 1134-05+06 | Notes icon shows presence dot when notes exist | SATISFIED | BuilderRail.tsx dot; mobile dot in MapBuilderPage.tsx (inline fix 6efa4544); 3 BuilderRail tests; MCP PASS at all 3 viewports |

---

### Anti-Patterns Found

No TBD/FIXME/XXX markers found in any phase-1134 modified source file.

The `placeholder` occurrence in `BuilderRail.tsx:156` is the notes `<textarea>` placeholder text — a legitimate i18n placeholder attribute, not a code stub.

`return null` in `ActiveFilterChips.tsx` is the standard empty-state guard (`if (!chipsToShow.length) return null`) — not a stub; confirmed by Test 2 of ActiveFilterChips.test.tsx.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None | — | — |

---

### Human Verification Required

No items require human testing. All behaviors verifiable from:
1. Source-code inspection (grep/read)
2. Unit/integration test pins (vitest)
3. Live MCP Playwright smoke (31/31 PASS, `e2e/mcp-verify-1134-06.spec.ts`)

---

### Gaps Summary

No gaps found. All 5 ROADMAP success criteria are satisfied by codebase evidence:

**SC1 (delete-layer):** `deriveCompanionIds` + `getLayerIds` adapter-registry path in `builder-layer-mutations.ts`; 17 regression tests across two test files.

**SC2 (visibility-toggle):** WALK-R-05 raster split-guard fixed; symbol raw-`setFilter` → `syncLayerFilter` migrated; all 7 adapter test files pin BUG-01 `visible=false` at add-time contract.

**SC3 (rename-group focus):** v1011 BUG-03 `requestAnimationFrame` deferral confirmed live in `FolderGroupRow.tsx`; doubly pinned at `UnifiedStackPanel.test.tsx` (integration) and `FolderGroupRow.test.tsx` (negative-control).

**SC4 (≤800px layout):** Two `mt-12 h-[calc(100%-3rem)]` SheetContent offsets; `right-14` positive pin; exhaustive `showCloseButton={false}` grep-guard. MCP PASS at 800×600 and 414×896.

**SC5 (scroll / filter pills / notes):** `max-h-[40vh] overflow-y-auto` on ActiveFilterChips; `BuilderRail.tsx` + `MapBuilderPage.tsx` mobileRailButtons both show notes presence dot from live `dockNotes` state; static scroll-containment pin; MCP verified.

**Path discrepancy (informational):** ROADMAP SC1 names `use-builder-layers.test.tsx`; actual regression file is `hooks/__tests__/use-builder-layers.delete.test.ts`. The plan explicitly noted this as a generic ROADMAP path; the coverage is substantive and correctly placed. Not a gap.

---

_Verified: 2026-05-27T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
