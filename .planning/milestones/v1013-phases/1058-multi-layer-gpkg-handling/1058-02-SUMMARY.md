---
phase: 1058-multi-layer-gpkg-handling
plan: "02"
subsystem: frontend-reupload-dialog
tags: [reupload, gpkg, multi-layer, preview-pane, schema-diff, advisory-banner, i18n, ui]

requires:
  - phase: 1058-multi-layer-gpkg-handling
    plan: "01"
    provides: "selectedFileLayer state + all_layers/previous_source_layer in preview response (Plan 02 reads selectedFileLayer to render Layer: line)"

provides:
  - "ReuploadDialog preview step: File + Layer lines stacked for multi-layer files (parity with Service URL path)"
  - "schemaChangeAdvisory banner above SchemaDiffView when columns_added + columns_removed > 0"
  - "i18n key reupload.schemaChangeAdvisory in en/de/es/fr locales"
  - "4 new vitest tests covering Layer line presence/absence and banner show/hide"
  - "1 service URL guard test confirming no cross-wiring with file-path layer state"

affects:
  - 1060-close-gate (live MCP re-verify will exercise GPKG-02 preview pane surfaces)

tech-stack:
  added: []
  patterns:
    - "Two-line preview header: conditional render — sourceType=file + selectedFileLayer != null yields File: + Layer: <p> pair; otherwise falls through to single previewSourceLabel/previewSourceValue line (clean state machine pattern, no new props needed)"
    - "hasSchemaChange = schemaChangeCount > 0 derived client-side per D-07 — no new wire field; additive to existing hasWarning derivation without merging or replacing it"
    - "data-testid=schema-change-advisory on advisory banner div enables test assertions without text-only matching (guards against i18n interpolation variation)"

key-files:
  created: []
  modified:
    - "frontend/src/components/dataset/ReuploadDialog.tsx — schemaChangeCount/hasSchemaChange derivation; step=preview two-line header; schemaChangeAdvisory banner JSX; GPKG-02 comment markers"
    - "frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx — 4 new GPKG-02 tests + 1 service URL guard"
    - "frontend/src/i18n/locales/en/dataset.json — reupload.schemaChangeAdvisory key"
    - "frontend/src/i18n/locales/de/dataset.json — reupload.schemaChangeAdvisory key"
    - "frontend/src/i18n/locales/es/dataset.json — reupload.schemaChangeAdvisory key"
    - "frontend/src/i18n/locales/fr/dataset.json — reupload.schemaChangeAdvisory key"

key-decisions:
  - "Two-line header via explicit conditional JSX (not refactoring previewSourceLabel into an array) — simpler and clearer for maintenance"
  - "Advisory banner uses data-testid=schema-change-advisory instead of text-only assertion — makes tests robust to i18n and interpolation differences"
  - "schemaChangeAdvisory placed ABOVE warningSchemaChanges in all locale files — visual grouping of related keys for editors"
  - "Reused reupload.service.layerLabel for the Layer: label in file-path preview (D-14 parity requirement) — no new i18n key for Layer:"
  - "hasSchemaChange and hasWarning remain independent derivations — advisory covers adds+removes; warning covers removes+type_changes (destructive-only)"

requirements-completed:
  - GPKG-02

duration: 20min
completed: 2026-05-20
---

# Phase 1058 Plan 02: GPKG-02 P1 Reupload Preview Pane Parity Summary

**Preview pane now surfaces the chosen layer name as an explicit "Layer: {name}" line for multi-layer file reuploads, plus a schema-change advisory banner when columns differ — bringing File path to parity with the Service URL design reference**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-20T02:23:00Z
- **Completed:** 2026-05-20T02:43:00Z
- **Tasks:** 1
- **Files modified:** 6

## Accomplishments

- ReuploadDialog preview step (step === 'preview') conditionally renders two header lines (File: + Layer:) when `sourceType === 'file'` and `selectedFileLayer !== null` — single-layer files continue to show only one File: line (no regression)
- New `schemaChangeAdvisory` banner (advisory, `bg-warning/10`) renders ABOVE SchemaDiffView when `columns_added.length + columns_removed.length > 0`; independent of existing `hasWarning` (destructive, triggered by removes/type-changes only)
- i18n: `reupload.schemaChangeAdvisory` key with `{{added}}`/`{{removed}}` interpolation added to en/de/es/fr locales above `warningSchemaChanges`
- Tests: 4 new vitest tests covering Layer line presence/absence and banner show/hide; 1 service URL guard test ensures no cross-wiring between file-path and service-URL layer state

## Task Commits

1. **Task 1: JSX + i18n + tests** — `2153be31` (feat)

## Files Created/Modified

- `frontend/src/components/dataset/ReuploadDialog.tsx` — `schemaChangeCount`/`hasSchemaChange` derivation above preview block; two-line conditional header in `step === 'preview'`; advisory banner JSX with `data-testid="schema-change-advisory"`
- `frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx` — 4 new GPKG-02 tests + 1 service URL guard
- `frontend/src/i18n/locales/en/dataset.json` — `reupload.schemaChangeAdvisory` key
- `frontend/src/i18n/locales/de/dataset.json` — `reupload.schemaChangeAdvisory` key
- `frontend/src/i18n/locales/es/dataset.json` — `reupload.schemaChangeAdvisory` key
- `frontend/src/i18n/locales/fr/dataset.json` — `reupload.schemaChangeAdvisory` key

## Decisions Made

- **Two-line header via conditional JSX:** When `sourceType === 'file' && selectedFileLayer !== null`, the preview renders a `<>` fragment with two `<p>` lines (File: and Layer:). For all other cases (single-layer file, service URL), the existing single `previewSourceLabel`/`previewSourceValue` line is unchanged. This avoids refactoring previewSourceLabel into an array, keeping the JSX structure simple.
- **Reuse `reupload.service.layerLabel` for file-path Layer: label:** D-14 requires parity between file and service URL paths. Both use the same i18n key. No new `reupload.file.layerLabel` needed.
- **`data-testid="schema-change-advisory"` on advisory banner div:** Test assertions use testid rather than text matching alone, making tests robust to i18n interpolation and rendering order.
- **Advisory and destructive warnings remain independent:** `hasSchemaChange` (advisory, any add or remove) and `hasWarning` (red, removes or type-changes) are computed separately. Both can coexist in the same preview pane — this is by design (D-05, D-07).

## Deviations from Plan

None — plan executed exactly as written. The JSX refactor approach (explicit two-line fragment rather than previewSourceLabel array) was an allowed discretionary choice per plan "Pick whichever produces cleaner JSX."

## Threat Surface Scan

Changes are pure frontend rendering of payloads already validated by Pydantic on the backend (Plan 1058-01). React JSX text interpolation auto-escapes all string values. No `dangerouslySetInnerHTML` introduced. No new network endpoints, auth paths, or file-access patterns. T-1058B-01 and T-1058B-02 dispositions from the plan threat model are satisfied.

## Known Stubs

None — all new render paths are fully wired. `schemaChangeCount` reads directly from `preview.schema_diff.columns_added.length + columns_removed.length`; `selectedFileLayer` is wired from state (set in Plan 01's `selecting-file-layer` step → `handleFileLayerPreview`).

## Test Results

| Gate | Result | Count |
|------|--------|-------|
| Frontend vitest `ReuploadDialog` | PASS | 19/19 (9 pre-existing + 5 Plan-01 + 4 new + 1 service guard) |
| TypeScript (`tsc --noEmit`) | PASS | 0 errors |
| i18n parity (`npm run test:i18n`) | PASS | 2/2 |
| Static contract: `schemaChangeAdvisory` in ReuploadDialog.tsx | PASS | line 839 |
| Static contract: `schemaChangeAdvisory` in all 4 locale files | PASS | en:264, de:302, es:302, fr:302 |
| Static contract: `GPKG-02 Phase 1058` comment markers | PASS | lines 457, 815, 833 |

## Self-Check

**Created files:**
- `/Users/ishiland/Code/geolens/.planning/phases/1058-multi-layer-gpkg-handling/1058-02-SUMMARY.md` — (this file)

**Commits:**
- `2153be31` — FOUND (feat 1058-02)

## Self-Check: PASSED

## Next Phase Readiness

- Plan 1058-03 (GPKG-03): Already shipped — BulkReviewList "Ingest all layers" fan-out. Unblocked by this plan.
- Phase 1060 close gate: Live MCP re-verify will exercise GPKG-02 surfaces (preview pane Layer: line + advisory banner) against `localhost:8080`.

---
*Phase: 1058-multi-layer-gpkg-handling*
*Completed: 2026-05-20*
