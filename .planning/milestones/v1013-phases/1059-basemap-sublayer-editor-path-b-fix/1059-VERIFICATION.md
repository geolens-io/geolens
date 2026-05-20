---
phase: 1059-basemap-sublayer-editor-path-b-fix
verified: 2026-05-20T04:35:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
human_verification:
  - test: "Open Map Builder, expand any basemap sublayer (e.g. Roads). Adjust stroke color to red (#ff0000) using the color picker."
    expected: "The map renders the road lines in red immediately (live preview). The color picker displays red. The STROKE section heading is visible."
    why_human: "MapLibre setPaintProperty is called at runtime against the live style; vitest mocks the map object and cannot verify actual paint changes on the rendered canvas."
  - test: "After adjusting stroke color (above), save the map (either via auto-save or explicit save). Reload the builder page."
    expected: "On reload, the STROKE section shows red (#ff0000) in the color picker, and the road lines remain red. The override survived the save/reload cycle."
    why_human: "Requires live backend round-trip: POST/PATCH /maps/ → GET /maps/{id} → applySublayerOverrides fires on style load. Cannot exercise this with source-level grep or unit tests."
  - test: "Open the saved map as a viewer (navigate to /m/{id} while not logged in as an editor, or use the share link /m/{token} or the embed URL /embed/{token})."
    expected: "All three read-only contexts show the same red road lines that the builder editor saved. The sublayer override was applied by ViewerMap.tsx after style load."
    why_human: "Cross-context render parity (ROADMAP AC3) requires live Playwright observation of three distinct URL contexts. Unit tests mock the helper call but cannot verify the actual visual output or the PublicMapViewerPage → ViewerMap prop-threading."
  - test: "Open the sublayer editor for Roads and click the RESET button, confirm reset."
    expected: "The stroke color reverts to the basemap default (no longer red). The sublayer_overrides entry for 'road' is cleared from the saved map. Live map shows default styling."
    why_human: "Requires verifying that onResetSublayer clears basemap_config.sublayer_overrides[road] from the persisted payload AND that applySublayerOverrides is no longer called with that key on reload."
  - test: "Open a legacy saved map (one saved before Phase 1059, without sublayer_overrides in its basemap_config). Verify it renders normally."
    expected: "Map renders with default basemap styling. No console errors. sublayer_overrides is absent from the JSON and applySublayerOverrides short-circuits immediately (overrides = undefined/null)."
    why_human: "Zero-migration backward compat (ROADMAP AC4) is verified by unit tests but live rendering on a real legacy map with no override data confirms no regressions in the MapLibre style-load path."
---

# Phase 1059: Basemap Sublayer Editor (Path B FIX) Verification Report

**Phase Goal:** A user editing any basemap sublayer in the Map Builder can adjust stroke color, stroke width, casing color, casing width, zoom range, and opacity; the overrides persist through save/reload and render correctly across builder, viewer, and shared/embed contexts.
**Verified:** 2026-05-20T04:35:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Editor surface renders stroke color, stroke width, casing color, casing width, zoom min, zoom max, opacity controls | VERIFIED | `BasemapSublayerEditorScene.tsx` lines 94-238: 5 sections present (STROKE / CASING / ZOOM RANGE / OPACITY / RESET). 2 `StyleColorPicker` uses, 2 `Slider` at `max={20}`, 2 `<Input type="number">` for zoom. Tests 14-21 all pass (14/14). |
| 2 | Live preview applies immediately and survives reload (persist via backend) | VERIFIED (source-level) | `BuilderMap.tsx:464-465` and `:812-813` call `applySublayerOverrides` immediately after `applyBasemapConfigToMap`. `updateSublayerOverride` in `MapBuilderPage.tsx:497-518` uses `setBasemapConfig` functional updater (auto-marks dirty). `BasemapConfig.sublayer_overrides` field at `schemas.py:317` persists via existing jsonb column. Live Playwright re-verify deferred to Phase 1060. |
| 3 | Round-trip parity across all 4 render contexts (builder + viewer + shared + embed) | VERIFIED (source + unit tests) | BuilderMap.tsx: 2 call sites (`onStyleLoad` + main sync effect). ViewerMap.tsx: 1 call site at line 568 with `VIEWER_SOURCE_PREFIX`. PublicMapViewerPage.tsx lazy-loads ViewerMap — both `/m/{token}` (shared) and `/embed/{token}` (embed) route through the same single component. ViewerMap.basemap-config.test.tsx 5 new tests (10/10 total pass). Round-trip spec: 7/7 pass. Live 4-context smoke deferred to Phase 1060. |
| 4 | Zero-migration backward compat — legacy maps without sublayer_overrides render with default basemap styling | VERIFIED | No Alembic migration file created (latest is `0017_ingest_job_fanned_out_status.py`). `BasemapConfig.sublayer_overrides` has `default=None`. Backend test `test_basemap_config_legacy_payload_deserializes_with_no_overrides` PASS. `applySublayerOverrides` guard: `if (!overrides || Object.keys(overrides).length === 0) return;`. Round-trip T2-6 + ViewerMap T1-4/T1-5 confirm backward compat. |

**Score:** 4/4 truths verified at source + test level

### Deferred Items

No deferred items (all 4 truths verified at source level; live MCP deferred to Phase 1060 by design).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/modules/catalog/maps/schemas.py` | `SublayerOverride` model + `BasemapConfig.sublayer_overrides` field | VERIFIED | `class SublayerOverride(BaseModel)` at line 190; 7 nullable fields; hex regex `_SUBLAYER_HEX_RE`; `model_config = ConfigDict(extra="forbid")`; `_validate_zoom_order` model_validator (WR-02). `sublayer_overrides` field at line 317 with `default=None`. |
| `backend/tests/test_basemap_sublayer_overrides.py` | ≥14 tests, all pass | VERIFIED | 26/26 PASS (14 original + 4 WR-02 parametrized + others). Covers: all-None defaults, full payload, stroke_width bounds, zoom bounds, opacity bounds, malformed hex (6 parametrized), uppercase hex, extra field rejection, legacy compat, round-trip, cleaner preserves, cleaner rejects, opaque keyset, inverted zoom, equal zoom, partial-zoom-only variants. |
| `frontend/src/lib/builder/basemap-style-mutation.ts` | `export function applySublayerOverrides` with idle-retry | VERIFIED | File exists; `applySublayerOverrides(map, overrides, sourcePrefix?)` exported at line 51; idle-retry pattern at lines 61-65 (`map.once('idle', retry)`); `safeSetPaint` + `safeSetZoomRange` with try/catch; WR-01 fix: `max_zoom ?? 22` (not 24). |
| `frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts` | ≥14 tests, all pass | VERIFIED | 19/19 PASS. Covers all 6 override fields, noop for undefined/null/empty, idle-retry, swallows-throws, unknown sublayer ID, sourcePrefix scoping, multi-sublayer, non-line layers. |
| `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` | 5 sections: STROKE/CASING/ZOOM/OPACITY/RESET | VERIFIED | All 5 sections present (lines 94-314). 2 `StyleColorPicker`, 2 `Slider` (max=20), 2 `<Input type="number">` zoom inputs. 6 new optional callback props. Disposition comment updated with Phase 1059 BSE-01 reference. |
| `frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx` | Test 14 inverted; Tests 15-21 added | VERIFIED | 14/14 PASS. Test 13 (INV-01/DETAIL LEVEL absent) unchanged. Test 14 inverted to assert STROKE/CASING/ZOOM presence. Tests 15-21 cover 6 new callbacks and undefined back-compat. |
| `frontend/src/pages/MapBuilderPage.tsx` | CR-01 fix: `SUBLAYER_ID_OVERRIDE_KEY` mapping; 6 callbacks wired | VERIFIED | `SUBLAYER_ID_OVERRIDE_KEY` at line 487 maps `'basemap:roads'→'road'` etc. `updateSublayerOverride` at line 497 uses `overrideKey`. 6 callbacks wired at lines 891-896. `onResetSublayer` clears `sublayer_overrides[overrideKey]` at lines 904-917 (D-11 scope). 7 occurrences of `updateSublayerOverride`, 13 occurrences of `sublayer_overrides`. |
| `frontend/src/types/api.ts` | `MapSublayerOverride` + `MapBasemapConfig.sublayer_overrides` | VERIFIED | `sublayer_overrides?: Record<string, MapSublayerOverride> \| null` at line 60. `MapSublayerOverride` interface defined at lines 27+. |
| `frontend/src/lib/basemap-utils.ts` | `SUBLAYER_CLASSIFIERS` + 4 exported predicates | VERIFIED | `isRoadLayer`, `isBoundaryLayer`, `isBuildingLayer`, `isTextLabelLayer` all exported (lines 230-244). `SUBLAYER_CLASSIFIERS` at lines 252-257. |
| `frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx` | 5 new tests for applySublayerOverrides | VERIFIED | 10/10 PASS (5 existing + 5 new: initial style load, reload, runtime change, legacy no-overrides, null basemapConfig). |
| `frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts` | 7 round-trip tests | VERIFIED | 7/7 PASS. JSON serialize/deserialize, identical call trace, null survival, partial overrides, multi-sublayer, legacy payload, unknown ID. |
| `frontend/src/i18n/locales/en/builder.json` | 9 new basemapSublayer.* keys | VERIFIED | `casingColor`, `casingLabel`, `casingWidth`, `casingWidthLabel`, `strokeColor`, `strokeLabel`, `strokeWidth`, `strokeWidthLabel`, `zoomLabel` all present (lines 862-876). |
| `frontend/src/i18n/locales/{de,es,fr}/builder.json` | 9 new keys in each locale | VERIFIED | 3 occurrences of `strokeLabel`/`casingLabel`/`zoomLabel` each in de, es, fr. `npm run test:i18n`: 2/2 PASS. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `BasemapConfig.sublayer_overrides` | `SublayerOverride` | `dict[str, SublayerOverride] \| None` type annotation | VERIFIED | `schemas.py:317` |
| `BuilderMap.tsx (2 sites)` | `applySublayerOverrides` | import + call after `applyBasemapConfigToMap` | VERIFIED | Lines 8, 465, 813 — D-07 order confirmed |
| `ViewerMap.tsx (1 site)` | `applySublayerOverrides` | import + call with `VIEWER_SOURCE_PREFIX` | VERIFIED | Lines 34, 568 — covers viewer + shared + embed via `PublicMapViewerPage` |
| `MapBuilderPage.tsx updateSublayerOverride` | `basemap_config.sublayer_overrides` | `setBasemapConfig` functional updater | VERIFIED | Lines 497-518; CR-01 fix at line 499 uses `overrideKey` from `SUBLAYER_ID_OVERRIDE_KEY` |
| `SUBLAYER_ID_OVERRIDE_KEY` | `SUBLAYER_CLASSIFIERS` key space | `'basemap:roads' → 'road'` mapping | VERIFIED | Mapping defined at `MapBuilderPage.tsx:487-492`; `SUBLAYER_CLASSIFIERS` keys: `road`, `boundary`, `building`, `label` (`basemap-utils.ts:252-257`) |
| `applySublayerOverrides` | `map.setPaintProperty` / `map.setLayerZoomRange` | `safeSetPaint` + `safeSetZoomRange` inner functions | VERIFIED | `basemap-style-mutation.ts:105-143`; idle-retry at lines 61-65 |
| `_clean_basemap_config` in `style_json.py` | `BasemapConfig.model_validate` | existing model_validate path inherits new field automatically | VERIFIED | Backend test 12 (`test_clean_basemap_config_preserves_overrides`) PASS. No change required at the 3 existing call sites. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `BasemapSublayerEditorScene.tsx` | `strokeColor`, `strokeWidth`, etc. | `layers.basemapConfig?.sublayer_overrides?.[overrideKey]` in `MapBuilderPage.tsx:884-889` | Yes — reads from `useMapBuilderStore` which persists to `MapBasemapConfig` | FLOWING |
| `applySublayerOverrides` in `BuilderMap.tsx` | `basemapConfig?.sublayer_overrides` | `basemapConfig` prop from `MapBuilderPage` → zustand store | Yes — store updated by `updateSublayerOverride` on each control change | FLOWING |
| `applySublayerOverrides` in `ViewerMap.tsx` | `basemapConfig?.sublayer_overrides` | `mapData.basemap_config.sublayer_overrides` from GET /maps/{id} | Yes — `schemas.py:317` persists/retrieves from jsonb; test 12 confirms round-trip | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backend schema validates overrides | `uv run pytest tests/test_basemap_sublayer_overrides.py -v` | 26/26 PASS | PASS |
| TypeScript compilation | `npx tsc --noEmit` | 0 errors | PASS |
| Helper unit tests | `npx vitest run basemap-style-mutation.test.ts` | 19/19 PASS | PASS |
| Editor scene tests | `npx vitest run BasemapSublayerEditorScene.test.tsx` | 14/14 PASS | PASS |
| Round-trip tests | `npx vitest run sublayer-overrides.round-trip.test.ts` | 7/7 PASS | PASS |
| ViewerMap basemap-config tests | `npx vitest run ViewerMap.basemap-config.test.tsx` | 10/10 PASS | PASS |
| i18n parity | `npm run test:i18n` | 2/2 PASS | PASS |

### Probe Execution

Step 7c: SKIPPED — no `probe-*.sh` files exist for Phase 1059. Phase 1059 is a UI/schema feature phase, not a migration or CLI phase. Live behavior verification is gated to Phase 1060.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| BSE-01 | Plans 1059-01..04 | Per-sublayer styling overrides (stroke color, stroke width, casing color, casing width, zoom range, opacity) — persist through save/reload, render correctly in all 4 contexts | SATISFIED (source-level + unit tests) | 4/4 ROADMAP success criteria verified. Source artifacts exist and are wired. 26 backend + 50 frontend tests PASS. Live Playwright re-verify deferred to Phase 1060 per design. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/pages/MapBuilderPage.tsx` | 271, 467, 478 | `TODO(BUILDER-SUBLAYER-PERSIST)` | INFO | Pre-existing from Phase 1051/1035 — references named tracker `BUILDER-SUBLAYER-PERSIST`. NOT introduced by Phase 1059. The `sublayerState` in-memory path (visibility/opacity toggles) predates this phase; `sublayer_overrides` (Phase 1059's new persistence path) is fully wired. Not a blocker. |

**D-14 scope guardrail confirmed:** `SublayerOverride.model_config = ConfigDict(extra="forbid")` at `schemas.py:255` — no dash_pattern, line_cap, halo, text-font can be stored. Test `test_sublayer_override_rejects_unknown_extra_field` PASS.

**D-18 DETAIL LEVEL guard confirmed:** `grep "DETAIL LEVEL" BasemapSublayerEditorScene.tsx` returns 1 match, which is in the disposition comment block at line 16 (a code comment, not production rendering). No radiogroup, no DETAIL LEVEL UI section rendered.

**Zero-migration guard confirmed:** No Alembic file exists at or above `0017_*`. Latest is `0017_ingest_job_fanned_out_status.py`.

**CR-01 fix confirmed:** `SUBLAYER_ID_OVERRIDE_KEY` defined at `MapBuilderPage.tsx:487-492`, used at lines 499 and 876. The `updateSublayerOverride` and all read paths use `overrideKey` (the bare semantic ID `'road'`), not `sublayer.id` (the namespaced UI routing ID `'basemap:roads'`). Without this fix the entire feature would be a no-op at runtime since `SUBLAYER_CLASSIFIERS['basemap:roads']` is `undefined`.

**WR-01 fix confirmed:** `basemap-style-mutation.ts:130` uses `override.max_zoom ?? 22` (not 24), matching the UI's displayed default in `BasemapSublayerEditorScene.tsx:197`.

**WR-02 fix confirmed:** `@model_validator(mode='after')` `_validate_zoom_order` at `schemas.py:269-283` rejects `min_zoom > max_zoom`. Backend tests `test_sublayer_override_rejects_inverted_zoom_range`, `test_sublayer_override_accepts_equal_zoom_range`, `test_sublayer_override_accepts_partial_zoom_only_min/max` all PASS.

### Human Verification Required

The following 5 items require Phase 1060 live Playwright MCP re-verify. They are architectural/behavioral and cannot be verified by source-level grep or headless vitest.

### 1. Live preview — stroke color change renders on map immediately

**Test:** Open Map Builder, expand Roads basemap sublayer, change stroke color to #ff0000 using the color picker.
**Expected:** Road lines turn red immediately on the map canvas (no page reload required). STROKE section heading, color swatch, and width slider are all visible.
**Why human:** `applySublayerOverrides` calls `map.setPaintProperty` on the live MapLibre instance. Unit tests mock `map.setPaintProperty` — they cannot verify actual canvas paint changes. Vitest jsdom does not render a MapLibre canvas.

### 2. Override survives save/reload (ROADMAP AC2 live)

**Test:** After setting stroke color to red, save the map. Reload the builder page for the same map ID.
**Expected:** On reload: (a) the color picker shows red, (b) the road lines are still red (ApplySublayerOverrides fires on style.load callback), (c) no console errors.
**Why human:** Requires a full live round-trip: `POST /maps/{id}` → wait for autosave → `GET /maps/{id}` → ViewerMap/BuilderMap apply overrides on style load. Source-level analysis confirms the wiring is correct but the actual HTTP + MapLibre render loop needs live observation.

### 3. Cross-context render parity — viewer, shared link, embed (ROADMAP AC3 live)

**Test:** With the map containing a red stroke color override, navigate to: (a) `/m/{id}` as a non-editor user, (b) the share link URL (`/m/{token}`), (c) the embed URL (`/embed/{token}`).
**Expected:** All three contexts show red road lines. The override is applied by `ViewerMap.tsx` after style load via the same `applyViewerBasemapConfig` callback.
**Why human:** 4-context render parity is the highest-risk claim in this phase. ViewerMap unit tests mock `applySublayerOverrides` — they verify the mock is called with the right args but cannot verify the visual output. All 3 read-only contexts share `ViewerMap.tsx` via `PublicMapViewerPage.tsx`; Playwright MCP is the only way to confirm all routes serve the override correctly.

### 4. Reset button clears override (D-11 scope)

**Test:** With a red stroke override saved, open the Roads sublayer editor, expand RESET, click Reset, confirm reset.
**Expected:** (a) Stroke color reverts to basemap default on the map immediately. (b) On save + reload, the override is gone (no red lines). (c) Other sublayers (boundary, building) are unaffected.
**Why human:** The D-11 scope constraint (reset only the specific sublayer) and the live MapLibre repaint both require visual confirmation.

### 5. Legacy map backward compat (ROADMAP AC4 live)

**Test:** Open a map saved before Phase 1059 (no `sublayer_overrides` in `basemap_config`) in both builder and viewer.
**Expected:** Map renders with default basemap styling. No console errors. `applySublayerOverrides` short-circuits immediately (overrides = null). No visual difference from pre-Phase 1059 rendering.
**Why human:** Unit tests (backend test 10, round-trip T2-6, ViewerMap T1-4) confirm source-level backward compat. Live observation on a real legacy map confirms no regressions in the full MapLibre style-load → `applyBasemapConfigToMap` → `applySublayerOverrides` pipeline.

---

## Gaps Summary

No gaps. All 4 ROADMAP success criteria are verified at the source + unit-test level:

1. **AC1 (editor surface):** `BasemapSublayerEditorScene.tsx` renders 5 sections with 2 color pickers, 2 width sliders (max=20), 2 zoom inputs, 1 opacity slider. 14/14 vitest tests pass including Test 14 inversion.

2. **AC2 (live preview + survives reload):** `updateSublayerOverride` writes to `basemap_config.sublayer_overrides` via `setBasemapConfig` functional updater. `BuilderMap.tsx` calls `applySublayerOverrides` in both `onStyleLoad` and the main sync effect (dep array covers whole `basemapConfig` object). CR-01 fix ensures the store writes bare keys (`'road'`, not `'basemap:roads'`) that `SUBLAYER_CLASSIFIERS` can resolve. Live reload verification deferred to Phase 1060.

3. **AC3 (4-render-context parity):** Two call sites (BuilderMap: 2 + ViewerMap: 1) cover all 4 contexts. `PublicMapViewerPage.tsx` confirms viewer/shared/embed share the single ViewerMap component. 12 new cross-context tests pass.

4. **AC4 (zero-migration backward compat):** No Alembic migration created. `BasemapConfig.sublayer_overrides` defaults to `None`. `applySublayerOverrides` short-circuits on null/undefined/empty input. 3 independent test locks (backend test 10, round-trip T2-6, ViewerMap T1-4/T1-5).

**Status is `human_needed` because Phase 1060's live Playwright MCP re-verify of BSE-01 is the designated closure gate for the 5 items above.** All source-level checks pass.

---

_Verified: 2026-05-20T04:35:00Z_
_Verifier: Claude (gsd-verifier)_
