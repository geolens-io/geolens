---
phase: quick-260322-mb0
verified: 2026-03-22T20:30:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Quick Task 260322-mb0: Excel Ingestion Verification Report

**Task Goal:** Excel non-spatial ingestion support (.xlsx/.xls)
**Verified:** 2026-03-22T20:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can upload .xlsx and .xls files via the import page | VERIFIED | `FileDropzone.tsx` ACCEPT map includes both MIME types; FORMAT_BADGES includes `.xlsx` |
| 2 | Single-sheet Excel files ingest into PostGIS as non-spatial tables (like CSV) | VERIFIED | `run_ogr2ogr` passes `layer_name=None` by default; `is_non_spatial` path applies when geometry_type is None |
| 3 | Multi-sheet Excel files show a sheet selector; user picks which sheet to ingest | VERIFIED | `BulkReviewList.tsx` renders `<select>` when `layers.length > 1`; `onSheetChange` re-fetches preview via `?layer_name=` |
| 4 | Preview endpoint returns columns and sample rows for Excel files | VERIFIED | `run_ogrinfo_preview` accepts `layer_name`; router passes it through; `PreviewResponse.layers` populated from `all_layers` |
| 5 | Ingested Excel data appears as a table dataset with correct columns and row count | VERIFIED | `tasks.py` reads `layer_name` from `user_metadata` and passes it to both `run_ogrinfo` and `run_ogr2ogr`; non-spatial path creates table without geometry column |

**Score:** 5/5 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/config.py` | Allowed extensions include .xlsx,.xls | VERIFIED | Line 30: `.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls` |
| `backend/app/ingest/validation.py` | Content validation for xlsx/xls via puremagic | VERIFIED | Lines 30-31: `.xlsx` → `{".xlsx", ".zip", ".docx"}`, `.xls` → `{".xls", ".doc"}` |
| `backend/app/ingest/ogr.py` | Multi-layer ogrinfo + layer_name param on ogr2ogr | VERIFIED | `run_ogrinfo(layer_name=None)` line 84, `run_ogrinfo_preview(layer_name=None)` line 172, `run_ogr2ogr(layer_name=None)` line 275; `all_layers` built when `len(layers) > 1 and not layer_name` |
| `backend/app/ingest/schemas.py` | PreviewResponse with layers list and CommitRequest with layer_name | VERIFIED | `PreviewResponse.layers: list[dict] \| None = None` line 24; `CommitRequest.layer_name: str \| None = None` line 57 |
| `frontend/src/components/import/FileDropzone.tsx` | Accept map and badges for xlsx/xls | VERIFIED | Lines 17-18 in ACCEPT map; `FORMAT_BADGES` line 21 includes `.xlsx` |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `ogr.py:run_ogrinfo` all_layers return | `router.py:preview_file` | `layers=info.get("all_layers")` | WIRED | `router.py` line 398: `layers=info.get("all_layers")` passed to `PreviewResponse` |
| `schemas.py:CommitRequest.layer_name` | `tasks.py:ingest_file` | `um.get("layer_name")` → `run_ogr2ogr(layer_name=layer_name)` | WIRED | `tasks.py` line 107 reads layer_name; line 145 passes to `run_ogr2ogr`; line 110 passes to `run_ogrinfo` |
| `FileDropzone.tsx` ACCEPT .xlsx/.xls | `config.py` upload_allowed_extensions | Matching .xlsx/.xls extensions | WIRED | Both frontend and backend declare .xlsx/.xls |
| `UploadForm.tsx:handleSheetChange` | `api/ingest.ts:previewFile(jobId, layerName)` | Calls `previewFile` with layerName param | WIRED | `UploadForm.tsx` line 192: `previewFile(entry.jobId, layerName)`; `ingest.ts` line 47-53 appends `?layer_name=` |
| `BulkReviewList.tsx` sheet selector onChange | `UploadForm.tsx:handleSheetChange` | `onSheetChange` prop callback | WIRED | `BulkReviewList.tsx` line 92 calls `onSheetChange?.(entry.id, e.target.value)`; `UploadForm.tsx` line 221 passes `handleSheetChange` |
| `BulkReviewList.tsx` onCommit | `CommitImportRequest.layer_name` | `layer_name` injected from `previewData.layer_name` when multi-sheet | WIRED | Lines 118-120 in BulkReviewList: `layerName` extracted from `previewData.layer_name` and spread into commit request |

---

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| EXCEL-INGEST | Excel (.xlsx/.xls) upload and non-spatial ingestion | SATISFIED | Full pipeline: upload → preview → sheet selection → commit → ogr2ogr ingestion |

---

## Anti-Patterns Found

No blockers or warnings detected. No TODO/FIXME/placeholder patterns in modified files. No stub return values in the critical ingestion path.

---

## Human Verification Required

### 1. Multi-sheet Excel upload end-to-end

**Test:** Upload a multi-sheet .xlsx workbook via the import page.
**Expected:** Sheet selector dropdown appears with all sheets listed. Selecting a different sheet re-fetches preview with updated column/row data. Committing ingests the selected sheet into PostGIS as a non-spatial table.
**Why human:** Sheet selector UI behavior and re-preview flow require a running app with an actual multi-sheet Excel file.

### 2. Single-sheet Excel upload (parity with CSV)

**Test:** Upload a single-sheet .xlsx file.
**Expected:** No sheet selector appears. Preview shows columns and sample rows. Commit creates a table dataset with correct columns and row count.
**Why human:** Requires running app and actual .xlsx file to confirm no extra UI renders and data ingests correctly.

### 3. puremagic content validation for .xlsx

**Test:** Upload a valid .xlsx file.
**Expected:** Upload succeeds without a content mismatch error (puremagic may detect OOXML as .zip or .docx, both of which are in the allowed set).
**Why human:** Magic byte detection behavior can vary by file; permissive set is correct but should be confirmed with a real file.

---

## Summary

All five observable truths are verified. The full pipeline is wired end-to-end:

- Backend config and validation both accept .xlsx/.xls.
- `run_ogrinfo`, `run_ogrinfo_preview`, and `run_ogr2ogr` all accept `layer_name`.
- `all_layers` is discovered when multiple layers exist and no specific layer is requested, and is passed through the router to `PreviewResponse.layers`.
- Frontend dropzone accepts .xlsx/.xls MIME types and displays the `.xlsx` badge.
- `FilePreviewResponse` and `CommitImportRequest` types include `layers` and `layer_name` respectively.
- Sheet selector in `BulkReviewList` renders conditionally for multi-sheet files, triggers re-preview via `?layer_name=`, and injects the selected sheet name into the commit payload.
- TypeScript compiles without errors.

Three human verification items cover UI behavior and real-file testing that cannot be verified statically.

---

_Verified: 2026-03-22T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
