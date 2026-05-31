---
phase: 1158-builder-layer-visibility-dem-consolidation
verified: 2026-05-30T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
deferred:
  - truth: "Live visual confirmation: raster basemap at position='top' keeps data visible"
    addressed_in: "Phase 1160"
    evidence: "Phase 1160 QA-01 SC#1: 'Live MCP confirms: BLDR-01 raster basemap at position='top' keeps data visible'"
  - truth: "Live visual confirmation: terrain DEM eye toggles 3D on/off (getTerrain() null/set)"
    addressed_in: "Phase 1160"
    evidence: "Phase 1160 QA-01 SC#1: 'BLDR-02 terrain DEM eye toggles 3D on/off (getTerrain() null/set)'"
  - truth: "Live visual confirmation: hiding a hypso-tinted DEM hides the tint"
    addressed_in: "Phase 1160"
    evidence: "Phase 1160 QA-01 SC#1: 'BLDR-04 hiding a hypso-tinted DEM hides the tint'"
human_verification:
  - test: "Raster basemap ordering — open the builder with an imagery/raster basemap at position='top', add a data layer, confirm the data layer is visible (not occluded by the basemap)"
    expected: "Data layer renders on top of the raster basemap"
    why_human: "BLDR-01 fix is unit-tested (moveLayer not called for raster type) but actual visual occlusion requires a live map render. Deferred to Phase 1160 QA-01 item b."
  - test: "Terrain DEM eye toggle — open the builder with a terrain-mode DEM layer, toggle the visibility eye off and on, confirm 3D terrain disappears and reappears"
    expected: "map.getTerrain() returns null when hidden; returns the terrain source object when shown"
    why_human: "BLDR-02 fix is unit-tested via BuilderMap.terrain-visibility.test.tsx but live terrain render requires a running map. Deferred to Phase 1160 QA-01 item c."
  - test: "Hypsometric tint companion hide — open the builder with a hillshade DEM that has hypsometric tint enabled, toggle the DEM layer off, confirm tint disappears"
    expected: "The -colorrelief companion layer becomes invisible when the parent DEM is hidden"
    why_human: "BLDR-04 fix is unit-tested (layout.visibility in addLayer mock) but live MapLibre render of the color-relief companion requires a running map. Deferred to Phase 1160 QA-01 item d."
---

# Phase 1158: Builder Layer Visibility & DEM Consolidation Verification Report

**Phase Goal:** The map builder renders basemap/data ordering, DEM rows, and DEM/terrain visibility toggles the way users expect — raster basemaps never occlude data, the terrain eye actually toggles 3D, one DEM row replaces the confusing triple stack, and hypsometric tint hides with its parent.
**Verified:** 2026-05-30
**Status:** human_needed (all automated checks pass; three live visual confirmations deferred to Phase 1160 QA-01 close-gate per plan design)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A raster/imagery basemap at `basemap_position='top'` does NOT occlude data layers (it is never lifted above them) | VERIFIED | `map-sync.ts:321` — `if (layer.type === 'raster') continue;` guard in `reorderBasemapAboveData` after the `isLandLayer/isWaterLayer` check. Test 12 in `UnifiedStackPanel.basemap-drag.test.tsx:351-368` pins `moveLayer` NOT called with `imagery-basemap` |
| 2 | Toggling the visibility eye on a terrain-mode DEM layer turns 3D terrain off (`getTerrain()===null`) and back on (`getTerrain()` set) | VERIFIED | `BuilderMap.tsx:396-401` — `effectiveTerrainEnabled = currentTerrainConfig.enabled === true && demLayerVisible`; guard `if (!demLayer \|\| token?.kind !== 'raster' \|\| !effectiveTerrainEnabled)` calls `map.setTerrain(null)`. `terrainLayerKey:419` encodes `:${String(layer.visible)}`. Three tests in `BuilderMap.terrain-visibility.test.tsx` pin attach/detach |
| 3 | The builder layer stack does not render a separate row for the synthetic terrain-mode DEM layer | VERIFIED | `UnifiedStackPanel.tsx:790-793` — `visibleStackLayers = layers.filter((l) => !isDemTerrainVisualSuppressed(l))`. `sortableIds`, `childrenByGroup`, and JSX render loop all use `visibleStackLayers`. Three tests in `UnifiedStackPanel.dem-rows.test.tsx` assert `[data-row-id="dem-terrain"]` is null while hillshade row is present |
| 4 | Hiding a hillshade DEM layer that has hypsometric tint enabled also hides its color-relief companion layer | VERIFIED | `color-relief-sync.ts:105` — `layout: { visibility: input.visible ? 'visible' : 'none' }` in the `addLayer` call. Call site `map-sync.ts:939` sets `visible: layer.visible` on `adapterInput` before `syncColorReliefLayer(map, adapterInput)` at line 961. Two BLDR-04 tests in `color-relief-sync.test.ts:305-334` assert `layout.visibility` |
| 5 | `e2e:smoke:builder` and vitest stay green | VERIFIED | SUMMARY 02 gate results: `npm run typecheck` 0 errors; `npm test -- --run` 241 files, 2634 tests passed; `e2e:smoke:builder` 26/26. Commits `80e3d2da`, `3428c117`, `1d6d48f0`, `b7c8ff1a`, `9d7e7ddd` all confirmed in git log |

**Score:** 5/5 truths verified (automated/static checks)

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Live visual: raster basemap at position='top' keeps data visible (BLDR-01) | Phase 1160 | QA-01 SC#1: "BLDR-01 raster basemap at position='top' keeps data visible" |
| 2 | Live visual: terrain DEM eye toggles 3D on/off via getTerrain() | Phase 1160 | QA-01 SC#1: "BLDR-02 terrain DEM eye toggles 3D on/off (getTerrain() null/set)" |
| 3 | Live visual: hiding a hypso-tinted DEM hides the tint | Phase 1160 | QA-01 SC#1: "BLDR-04 hiding a hypso-tinted DEM hides the tint" |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/builder/map-sync.ts` | BLDR-01 raster-basemap skip guard | VERIFIED | Line 321: `if (layer.type === 'raster') continue;` with comment. Positioned after `isLandLayer/isWaterLayer` guard at line 318 |
| `frontend/src/components/builder/color-relief-sync.ts` | BLDR-04 `layout.visibility` from `input.visible` on companion addLayer | VERIFIED | Line 105: `layout: { visibility: input.visible ? 'visible' : 'none' }` before `paint` in addLayer object |
| `frontend/src/components/builder/BuilderMap.tsx` | BLDR-02 `effectiveTerrainEnabled` gate + `terrainLayerKey` encodes `visible` | VERIFIED | Lines 396-401: `effectiveTerrainEnabled` computed from `enabled AND demLayerVisible`; line 419: key string ends `:${String(layer.visible)}` |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | BLDR-03 terrain-mode DEM rows filtered via `isDemTerrainVisualSuppressed` | VERIFIED | Lines 790-793: `visibleStackLayers` memo; lines 803, 813, 997 use `visibleStackLayers`; line 1114 activeLayer lookup uses raw `layers` |
| `frontend/src/pages/MapBuilderPage.tsx` | CR-01 fix: `selectableRowIds` excludes suppressed terrain-DEM IDs | VERIFIED | Lines 500-512: `for` loop with `if (isDemTerrainVisualSuppressed(layer)) continue;`. `isDemTerrainVisualSuppressed` imported at line 81 |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` | BLDR-01 Test 12 raster-skip pin | VERIFIED | Lines 351-368: Test 12 asserts `not.toHaveBeenCalledWith('imagery-basemap')` and `toHaveBeenCalledWith('road-primary')` |
| `frontend/src/components/builder/__tests__/color-relief-sync.test.ts` | BLDR-04 two tests asserting `layout.visibility` | VERIFIED | Lines 305-334: Two tests asserting `layout.visibility === 'none'` / `=== 'visible'` from `addLayer` mock calls |
| `frontend/src/components/builder/__tests__/BuilderMap.terrain-visibility.test.tsx` | BLDR-02 terrain attach/detach on visibility | VERIFIED | Three tests (A/B/C): attach with source, null when hidden, null when disabled — all use `setTerrain` mock spy |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.dem-rows.test.tsx` | BLDR-03 terrain-row suppression | VERIFIED | Three tests asserting `[data-row-id="dem-terrain"]` is null; hillshade/image rows present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `map-sync.ts:961` `syncColorReliefLayer(map, adapterInput)` | `color-relief-sync.ts` `layout.visibility` | `adapterInput.visible = layer.visible` at line 939 | WIRED | Call site sets `visible: layer.visible` at :939 before invoking `syncColorReliefLayer` at :961; confirmed in source |
| `BuilderMap.tsx terrainLayerKey` memo | `applyTerrainConfig` effect dep array | `:${String(layer.visible)}` appended to per-layer key string | WIRED | `terrainLayerKey` at line 416-421 encodes `visible`; effect dep array at line 914 includes `terrainLayerKey` |
| `UnifiedStackPanel.tsx` `layers` prop | `isDemTerrainVisualSuppressed` filter | `visibleStackLayers` memo at lines 790-793 feeds `sortableIds`, `childrenByGroup`, render loop | WIRED | Three consumers confirmed using `visibleStackLayers`; raw `layers` still used at line 1114 (drag-overlay) as required |
| `MapBuilderPage.tsx selectableRowIds` | `isDemTerrainVisualSuppressed` | `for` loop with `if (isDemTerrainVisualSuppressed(layer)) continue` at lines 500-512 | WIRED | CR-01 fix confirmed; import at line 81; `selectableRowIds` passed to `UnifiedStackPanel` at line 1319 |

### Data-Flow Trace (Level 4)

Not applicable — this phase modifies MapLibre rendering logic (map.setTerrain, moveLayer, addLayer visibility, DOM row filtering). No new data fetch paths introduced; all fixes operate on state already flowing through the component tree.

### Behavioral Spot-Checks

Step 7b: SKIPPED — fixes are MapLibre rendering/visibility operations; correctness requires a live browser map instance. Vitest unit tests serve as the closest available automated checks and all pass (2634/2634). Live verification is the Phase 1160 QA-01 close-gate.

### Probe Execution

Step 7c: No probes declared in PLAN files. No conventional `scripts/*/tests/probe-*.sh` files registered for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| BLDR-01 | 1158-01-PLAN.md | Raster basemap stays below data at `basemap_position='top'` | SATISFIED | `map-sync.ts:321` guard + Test 12; REQUIREMENTS.md marked `[x]` |
| BLDR-02 | 1158-01-PLAN.md | Terrain eye toggles 3D on/off via `effectiveTerrainEnabled` | SATISFIED | `BuilderMap.tsx:396-401` + `BuilderMap.terrain-visibility.test.tsx`; REQUIREMENTS.md marked `[x]` |
| BLDR-03 | 1158-01-PLAN.md | Single DEM row (terrain-mode suppressed via `isDemTerrainVisualSuppressed`) | SATISFIED | `UnifiedStackPanel.tsx:790-793` + `UnifiedStackPanel.dem-rows.test.tsx`; ROADMAP SC#3 updated to reflect approved narrowing (no "Copy N of M" badge); REQUIREMENTS.md marked `[x]` |
| BLDR-04 | 1158-01-PLAN.md | Color-relief companion hides with parent DEM | SATISFIED | `color-relief-sync.ts:105` + `color-relief-sync.test.ts` BLDR-04 tests; REQUIREMENTS.md marked `[x]` |

**Orphaned requirements check:** REQUIREMENTS.md also lists QA-01 for this milestone — it is assigned to Phase 1160 (not Phase 1158), not orphaned.

**BLDR-03 scope note:** The REQUIREMENTS.md original text mentions "Copy N of M" duplicate-badge. The ROADMAP SC#3 was updated to reflect the approved narrowing: terrain-mode suppression via `isDemTerrainVisualSuppressed` is the deliverable; the duplicate-badge is explicitly out of scope for this fixes-only phase. The plan frontmatter `must_haves` match the updated SC. No discrepancy.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `BuilderMap.tsx` | 247 | `"placeholder background style"` in comment | Info | Pre-existing comment from Phase 1051 WR-06 describing a fallback background style (not an unimplemented stub). Not introduced by Phase 1158. No impact. |

No `TBD`, `FIXME`, or `XXX` markers found in any of the five files modified by this phase.

**Code review WR-01** (isEmpty shows empty-state when only terrain DEM present): accepted as intentional behavior per the comment added at `UnifiedStackPanel.tsx:837-841` — terrain is a map-level setting, not a data row, so a terrain-only map intentionally shows the "add data" empty state.

**Code review IN-01** (BLDR-02 Test A loose assertion `length > 0`): info-only, no corrective action required per the review. The assertion still proves the correct attach path runs for the current implementation.

### Human Verification Required

The three items below are live visual checks that require a running browser map. They are not gaps — the source fixes are fully implemented and unit-tested. They are deferred to the Phase 1160 Playwright MCP close-gate per the plan design documented in both PLAN files and the ROADMAP.

#### 1. BLDR-01 — Raster basemap does not occlude data

**Test:** Open the builder with an imagery/raster basemap configured at `basemap_position='top'`, add a vector data layer, confirm the data layer renders visibly on top of the basemap imagery.
**Expected:** Data layer is fully visible; basemap does not paint over it.
**Why human:** Unit test confirms `moveLayer` is not called for the raster basemap. Live occlusion behavior requires a running MapLibre instance in a browser.

#### 2. BLDR-02 — Terrain eye toggles 3D terrain on/off

**Test:** Open the builder with a terrain-mode DEM layer. Toggle the visibility eye off, confirm 3D terrain disappears (`map.getTerrain()` returns null). Toggle it back on, confirm terrain re-attaches.
**Expected:** Terrain enables and disables in sync with the layer visibility eye.
**Why human:** `BuilderMap.terrain-visibility.test.tsx` pins the `setTerrain` call sequence. Actual 3D terrain rendering and visual confirmation of the toggle requires a live map.

#### 3. BLDR-04 — Hypsometric tint hides with parent DEM

**Test:** Open the builder with a hillshade DEM that has hypsometric tint (color-relief) enabled. Toggle the DEM visibility off, confirm the tint disappears. Toggle it back on, confirm tint reappears.
**Expected:** The `-colorrelief` companion layer becomes invisible/visible in sync with the parent DEM.
**Why human:** Unit test confirms `addLayer` carries `layout.visibility`. Live rendering of the `color-relief` layer type and its visual appearance requires a running MapLibre 5.24+ map instance.

### Gaps Summary

No gaps. All five ROADMAP success criteria are verified in the codebase:

1. SC#1 (BLDR-01 raster skip) — guard at `map-sync.ts:321`, Test 12 pin.
2. SC#2 (BLDR-02 terrain toggle) — `effectiveTerrainEnabled` at `BuilderMap.tsx:397`, `terrainLayerKey` visibility encoding at line 419, three test pins.
3. SC#3 (BLDR-03 DEM row suppression) — `visibleStackLayers` memo at `UnifiedStackPanel.tsx:790-793`, three test pins.
4. SC#4 (BLDR-04 color-relief companion) — `layout.visibility` at `color-relief-sync.ts:105`, two test pins.
5. SC#5 (test suites green) — confirmed: typecheck 0, vitest 2634/2634, e2e:smoke:builder 26/26.

Code-review CR-01 BLOCKER (accidental terrain-DEM bulk-delete via `selectableRowIds`) was fixed inline at commit `9d7e7ddd` and is verified at `MapBuilderPage.tsx:500-512`.

The three human verification items above are not gaps — they are live visual checks explicitly designed into the phase and deferred to the Phase 1160 Playwright MCP close-gate.

---

_Verified: 2026-05-30_
_Verifier: Claude (gsd-verifier)_
