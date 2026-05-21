---
phase: quick-260325-bsk
verified: 2026-03-25T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
human_verification:
  - test: "Open a table dataset detail page (e.g. http://localhost:8080/datasets/97fafb8a-8eaa-4a70-a46b-3193bca792fd)"
    expected: "Orange 'Table' badge visible in stats line; no 'Add to Map' button; no 'Connect' dropdown; stats line reads 'X rows' not 'X features'"
    why_human: "Conditional rendering and badge label depend on live record_type value from API response"
  - test: "Open Overview tab on a table dataset"
    expected: "No 'Geometry Type' row visible; feature count field labelled 'Row Count' not 'Feature Count'"
    why_human: "Label conditional on dataset.record_type value at runtime"
  - test: "Check tab bar on a table dataset detail page"
    expected: "No 'Data' tab visible in tab bar (hero grid is the data view)"
    why_human: "Tab conditional rendering verified in code but requires browser to confirm no tab renders"
  - test: "Open Access tab on a table dataset, check Export section"
    expected: "Export format dropdown does not include 'Shapefile' option"
    why_human: "Client-side filter depends on recordType prop value flowing through at runtime"
---

# Quick Task 260325-bsk: Non-Spatial Data Page UI/UX Verification Report

**Task Goal:** Review the non-spatial data page UI/UX and general functionality. Fix easy wins and document larger recommendations.
**Verified:** 2026-03-25
**Status:** human_needed (all automated checks passed; runtime UI behavior needs human confirmation)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Non-spatial table datasets show a 'Table' type badge in stats line and search cards | VERIFIED | `RecordTypeBadge.tsx` line 26-30: `table` entry added to TYPE_CONFIG with `Table2` icon, orange className, `card.table` labelKey. `en/search.json` line 87: `"table": "Table"` present in `card` object. |
| 2 | No spatial-only UI controls appear for table datasets (no tile URL, no Add to Map, no geometry type field) | VERIFIED | `DatasetPage.tsx` lines 598, 607: `AddToMapButton` and `ConnectDropdown` both wrapped in `{!isTable && ...}`. `OverviewTab.tsx` line 186: geometry type field gated on `dataset.geometry_type` truthiness (null for tables). |
| 3 | Stats line and overview use 'rows' terminology instead of 'features' for table datasets | VERIFIED | `DatasetPage.tsx` line 476: `{isTable ? 'rows' : 'features'}` conditional. `OverviewTab.tsx` line 193: label switches to `t('metadata.rowCount', { defaultValue: 'Row Count' })` when `dataset.record_type === 'table'`. |
| 4 | Data tab in VectorDetailPanel is hidden for table datasets since the hero IS the data view | VERIFIED | `VectorDetailPanel.tsx` lines 50, 57, 93-97: `isTable` derived from `dataset.record_type`; both `TabsTrigger` and `TabsContent` for "data" are conditionally hidden with `{!isTable && ...}`. |
| 5 | Export formats for table datasets exclude Shapefile (geometry-dependent format) | VERIFIED | `ExportButton.tsx` lines 10, 25: accepts optional `recordType` prop; `formats` variable filters out `shp` when `recordType === 'table'`. `AccessTab.tsx` line 101 and `AccessSharingTab.tsx` line 101: both pass `recordType={dataset.record_type}`. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/search/RecordTypeBadge.tsx` | Table type badge config | VERIFIED | `table` entry in TYPE_CONFIG with Table2 icon and orange styling; i18n wired via `card.table` key |
| `frontend/src/pages/DatasetPage.tsx` | Table-aware stats line, hidden AddToMap, hidden ConnectDropdown | VERIFIED | `isTable` at line 417; `{!isTable && ...}` guards on lines 598 and 607; `{isTable ? 'rows' : 'features'}` at line 476 |
| `frontend/src/components/dataset/tabs/OverviewTab.tsx` | Hidden geometry field for tables, row count label | VERIFIED | Line 186: `dataset.geometry_type &&` guard added; line 193: conditional label for Row Count |
| `frontend/src/components/dataset/panels/VectorDetailPanel.tsx` | Conditional Data tab visibility | VERIFIED | `isTable` at line 50; tab trigger at line 57 and content at lines 93-97 both gated |
| `frontend/src/components/dataset/ExportButton.tsx` | Filtered export formats for non-spatial | VERIFIED | `recordType` prop at line 10; filter logic at line 25; `formats.map(...)` at line 55 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `DatasetPage.tsx` | `RecordTypeBadge.tsx` | `isTable` condition in statsLine | VERIFIED | `RecordTypeBadge` rendered at line 464 inside statsLine; `isTable` condition at line 476 affects text adjacent to it |
| `DatasetPage.tsx` | `ConnectDropdown.tsx` | conditional rendering gated on isTable | VERIFIED | Line 607: `{!isTable && <ConnectDropdown dataset={dataset} />}` — pattern `!isTable.*ConnectDropdown` confirmed |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| QUICK-BSK | 260325-bsk-PLAN.md | Review non-spatial data page UI/UX; fix easy wins; document larger recommendations | SATISFIED | All 7 code fixes applied; REVIEW.md exists with 4 remaining recommendations documented |

### Anti-Patterns Found

None detected. No TODO/FIXME markers, empty handlers, or placeholder returns found in modified files.

### Human Verification Required

#### 1. Table badge and spatial control visibility

**Test:** Navigate to a table dataset detail page in a running instance (e.g. `http://localhost:8080/datasets/97fafb8a-8eaa-4a70-a46b-3193bca792fd`).
**Expected:** Orange "Table" badge in stats line; "Add to Map" button absent; "Connect" dropdown absent; stats line shows "X rows".
**Why human:** Conditional rendering verified in source, but badge display and button suppression depend on live `record_type` value from API.

#### 2. Overview tab field labels

**Test:** Open the Overview tab on a table dataset.
**Expected:** No "Geometry Type" row present; the row count field is labelled "Row Count" not "Feature Count".
**Why human:** Label conditional on runtime `record_type` value; can't verify rendered output statically.

#### 3. Data tab hidden from tab bar

**Test:** Inspect the tab bar on a table dataset detail page.
**Expected:** No "Data" tab visible; only Overview, Metadata, Structure, Access tabs are shown.
**Why human:** Tab conditional rendering is in code, but visual confirmation needed to rule out CSS or state issues.

#### 4. Export format dropdown excludes Shapefile

**Test:** Open Access tab on a table dataset, locate the Export section.
**Expected:** Export dropdown shows only GeoPackage, GeoJSON, CSV — no Shapefile option.
**Why human:** Client-side filter depends on `recordType` prop reaching ExportButton at runtime.

### Gaps Summary

No gaps found. All five must-have truths are implemented substantively and wired correctly. The review report (`260325-bsk-REVIEW.md`) exists with 8 fixed items documented and 4 remaining recommendations catalogued. Four items require human browser testing to confirm runtime behavior matches the verified source code.

---

_Verified: 2026-03-25_
_Verifier: Claude (gsd-verifier)_
