---
phase: 1059-basemap-sublayer-editor-path-b-fix
plan: "04"
subsystem: frontend-tests-i18n
tags: [basemap, sublayer-overrides, vitest, i18n, round-trip, backward-compat]
dependency_graph:
  requires: ["1059-01", "1059-02", "1059-03"]
  provides:
    - "ViewerMap.basemap-config.test.tsx extended with applySublayerOverrides assertions"
    - "sublayer-overrides.round-trip.test.ts — 7 round-trip parity tests"
    - "de/es/fr builder.json with 9 new basemapSublayer.* keys"
  affects:
    - frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx
    - frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
tech_stack:
  added: []
  patterns:
    - "vi.mock('@/lib/builder/basemap-style-mutation') alongside existing map-sync mock"
    - "JSON.parse(JSON.stringify()) round-trip equality proof pattern"
    - "Fake map factory with getLayer returning layer from style.layers array so safeSetPaint proceeds"
key_files:
  created:
    - frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts
  modified:
    - frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "No production code changes — this plan is verification-only"
  - "Round-trip test placed under builder/__tests__/ because it exercises the helper from lib/builder/"
  - "casingWidth/strokeWidth German/Spanish/French translations use 'Breite'/'Ancho'/'Largeur' (same word as the field label — mirrors the en pattern where both casingWidth and strokeWidth are 'Width')"
  - "Fake map getLayer returns layer object from the style layers array, making safeSetPaint proceed to setPaintProperty (matching production behavior when layer exists)"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-20"
  tasks: 3
  files: 5
---

# Phase 1059 Plan 04: Cross-Context Tests + i18n Parity Summary

Locked cross-context round-trip parity with 12 new vitest tests and brought de/es/fr i18n locales to key parity with English. No production code changed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend ViewerMap.basemap-config.test.tsx | 04c38c59 | ViewerMap.basemap-config.test.tsx |
| 2 | Add sublayer-overrides.round-trip.test.ts | fce0d1b3 | sublayer-overrides.round-trip.test.ts |
| 3 | i18n parity de/es/fr | 7e1a4c4d | de/builder.json, es/builder.json, fr/builder.json |

## New Test Count

**Task 1 — ViewerMap.basemap-config.test.tsx (5 new cases):**

| # | Test name | Acceptance Criterion |
|---|-----------|---------------------|
| T1-1 | applies sublayer_overrides after initial style load | AC3 cross-context |
| T1-2 | reapplies sublayer_overrides on style.load reload | AC3 cross-context |
| T1-3 | passes updated overrides on runtime basemapConfig change | AC2 live preview |
| T1-4 | legacy basemap_config without sublayer_overrides passes null | **AC4 backward compat** |
| T1-5 | null basemapConfig still calls helper with null overrides | AC4 backward compat |

**Task 2 — sublayer-overrides.round-trip.test.ts (7 new cases):**

| # | Test name | Acceptance Criterion |
|---|-----------|---------------------|
| T2-1 | payload survives JSON.parse(JSON.stringify()) | AC3 round-trip |
| T2-2 | helper apply yields identical call trace for direct vs round-tripped input | AC3 round-trip |
| T2-3 | null values survive round-trip | AC3 data fidelity |
| T2-4 | partial overrides produce no phantom mutation calls | AC2 correctness |
| T2-5 | multi-sublayer dict applies to all known sublayer IDs | AC3 cross-context |
| T2-6 | legacy payload without sublayer_overrides renders without crashing | **AC4 backward compat** |
| T2-7 | unknown sublayer ID is silently ignored | D-01 forward-compat |

**Total: 12 new tests. All passing.**

## ROADMAP.md Phase 1059 Acceptance Criteria Coverage Map

| AC | Criterion | Evidence |
|----|-----------|----------|
| AC1 | Editor scene renders 6 controls (stroke/casing/zoom) | Plan 03 Tests 14-21 (8 tests) |
| AC2 | Live preview — each control change triggers MapLibre paint update | Plan 02 Tests 4-8 + Plan 03 Tests 16/18/19/20 + Plan 04 T1-3 (runtime change retest) |
| AC3 | Cross-context round-trip parity (builder/viewer/shared/embed) | Plan 04 T1-1/T1-2/T2-1/T2-2/T2-5 — payload survives save→load; helper called correctly in ViewerMap (shared by viewer+shared+embed) |
| AC4 | Zero-migration backward compat (legacy maps render safely) | Plan 01 Test 10 + Plan 04 T1-4 + Plan 04 T2-6 — three independent locks |

## i18n Parity Status

All 4 locales aligned on the `basemapSublayer` key set:

| Key | en | de | es | fr |
|-----|----|----|----|----|
| breadcrumbLabel | ✓ | ✓ | ✓ | ✓ |
| casingColor | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| casingLabel | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| casingWidth | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| casingWidthLabel | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| footerBack | ✓ | ✓ | ✓ | ✓ |
| resetConfirmAction | ✓ | ✓ | ✓ | ✓ |
| resetConfirmCancel | ✓ | ✓ | ✓ | ✓ |
| resetConfirmMessage | ✓ | ✓ | ✓ | ✓ |
| resetHint | ✓ | ✓ | ✓ | ✓ |
| resetLabel | ✓ | ✓ | ✓ | ✓ |
| strokeColor | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| strokeLabel | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| strokeWidth | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| strokeWidthLabel | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |
| zoomLabel | ✓ | ✓ (NEW) | ✓ (NEW) | ✓ (NEW) |

**i18n parity gate:** `npm run test:i18n` — 2/2 PASS

## Test Results

- ViewerMap.basemap-config.test.tsx: 10/10 PASS (5 existing + 5 new)
- sublayer-overrides.round-trip.test.ts: 7/7 PASS (all new)
- Regression sweep (87 test files, 1051 tests): 1051/1051 PASS
- TypeScript: 0 new errors
- i18n parity: 2/2 PASS (`npm run test:i18n`)

## Production Code Changes

None. This plan is verification-only. All changes are:
- Test extensions/additions
- i18n locale JSON files

## Phase 1059 Complete

Phase 1059 (Basemap Sublayer Editor Path B FIX) is complete across all 4 plans:
- Plan 01 (backend persistence) — `SublayerOverride` Pydantic model, jsonb-additive
- Plan 02 (frontend MapLibre integration) — `applySublayerOverrides` helper + 4-context wire-up
- Plan 03 (frontend editor UI) — STROKE/CASING/ZOOM sections restored in BasemapSublayerEditorScene
- Plan 04 (cross-context tests + i18n) — 12 new vitest tests + 4-locale key parity

Ready for Phase 1060 close gate (live Playwright MCP re-verify of all 4 render contexts — MCP currently disconnected; reconnect required).

## Cross-References

- Plan 01 SUMMARY: `.planning/phases/1059-basemap-sublayer-editor-path-b-fix/1059-01-SUMMARY.md`
- Plan 02 SUMMARY: `.planning/phases/1059-basemap-sublayer-editor-path-b-fix/1059-02-SUMMARY.md`
- Plan 03 SUMMARY: `.planning/phases/1059-basemap-sublayer-editor-path-b-fix/1059-03-SUMMARY.md`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All test assertions verify the actual wire-up from Plans 01-03. No placeholder/stub code introduced.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes. Test and i18n files only.

## Self-Check: PASSED

Files exist:
- `frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx` — FOUND
- `frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts` — FOUND
- `frontend/src/i18n/locales/de/builder.json` — FOUND
- `frontend/src/i18n/locales/es/builder.json` — FOUND
- `frontend/src/i18n/locales/fr/builder.json` — FOUND

Commits exist:
- `04c38c59` — FOUND (test(1059-04): extend ViewerMap.basemap-config test)
- `fce0d1b3` — FOUND (test(1059-04): add sublayer_overrides round-trip vitest spec)
- `7e1a4c4d` — FOUND (feat(1059-04): add 9 new basemapSublayer i18n keys)

Grep assertions:
- `grep -c "applySublayerOverridesMock" ViewerMap.basemap-config.test.tsx` = 13 ✓ (>= 8)
- `grep -c "^  it(" sublayer-overrides.round-trip.test.ts` = 7 ✓ (>= 7)
- `wc -l sublayer-overrides.round-trip.test.ts` = 220 ✓ (>= 100)
- 9 new keys in de, es, fr builder.json each ✓
- All tests passing: 10/10 + 7/7 + 1051/1051 + 2/2 i18n ✓
- TypeScript 0 errors ✓
