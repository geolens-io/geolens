---
phase: quick-260325-px8
verified: 2026-03-25T00:00:00Z
status: passed
score: 4/4 must-haves verified
re_verification: false
---

# Quick Task 260325-px8: Allowed Extensions Alignment — Verification Report

**Task Goal:** Review allowed extensions in admin storage settings page, align with import page dropzone, wire up dynamically so admin changes take effect on the import page
**Verified:** 2026-03-25
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Admin changes to allowed extensions in storage settings are reflected on the import dropzone without code changes | VERIFIED | `UploadForm.tsx` reads `uploadConfig.allowed_extensions` from `useUploadConfig()` hook and passes parsed array to `FileDropzone`. `uploadConfig` originates from `GET /ingest/upload/config/` which reads `UPLOAD_ALLOWED_EXTENSIONS.get(db)` — the same persistent config key admin settings write. No hardcoded list anywhere in the import path. |
| 2  | Import dropzone shows badges matching whatever extensions are configured in admin settings | VERIFIED | `FileDropzone.tsx` computes `badges = deriveFormatBadges(allowedExtensions)` via `useMemo` and renders them in JSX. Badges are derived entirely from the prop; no static `FORMAT_BADGES` constant exists in the file. |
| 3  | ReuploadDialog accepts the same extensions as the import dropzone | VERIFIED | `ReuploadDialog.tsx` imports `buildAcceptMap` from `@/lib/file-utils` and builds `reuploadAccept` from `uploadConfig.allowed_extensions` (same source as `UploadForm`). Passes it directly to `useDropzone({ accept: reuploadAccept })`. No hardcoded `ACCEPT` constant present. |
| 4  | Unknown extensions added by admin (e.g. `.parquet`) pass content validation on upload | VERIFIED | `validate_file_content()` in `backend/app/ingest/validation.py` has an early return at line 71–72: `if suffix not in EXTENSION_CONTENT_MAP: return`. Test `test_unknown_extension_skips_validation` in `backend/tests/test_upload_validation.py` covers a `.parquet` file with binary content — asserts no exception is raised. |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/lib/file-utils.ts` | `buildAcceptMap` and `deriveFormatBadges` utilities | VERIFIED | Exists, 36 lines, both functions exported with correct logic. `buildAcceptMap` maps known MIME types and falls back to `application/octet-stream`. `deriveFormatBadges` deduplicates `.tiff`→`.tif` and `.json`→skip if `.geojson` present. |
| `backend/app/ingest/schemas.py` | `UploadConfigResponse` with `allowed_extensions` field | VERIFIED | Line 149: `allowed_extensions: str` present in `UploadConfigResponse`. |
| `frontend/src/components/import/FileDropzone.tsx` | Dynamic dropzone reading extensions from props | VERIFIED | `allowedExtensions?: string[]` prop added; `accept` and `badges` derived via `useMemo` using `buildAcceptMap`/`deriveFormatBadges`. No hardcoded constants. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/ingest/router.py` | `UPLOAD_ALLOWED_EXTENSIONS.get(db)` | `get_upload_config` endpoint | VERIFIED | Lines 73–80: `allowed_exts = await UPLOAD_ALLOWED_EXTENSIONS.get(db)` then `allowed_extensions=allowed_exts` in response. |
| `frontend/src/components/import/UploadForm.tsx` | `FileDropzone` | `allowedExtensions` prop from `useUploadConfig` | VERIFIED | Line 236: `const allowedExtensions = uploadConfig?.allowed_extensions?.split(',').map(e => e.trim()).filter(Boolean)`. Line 239: `<FileDropzone ... allowedExtensions={allowedExtensions} />`. |
| `frontend/src/components/import/FileDropzone.tsx` | `buildAcceptMap` | import from `file-utils` | VERIFIED | Line 6: `import { buildAcceptMap, deriveFormatBadges } from '@/lib/file-utils'`. Both used in `useMemo` body. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `FileDropzone.tsx` | `allowedExtensions` prop | `uploadConfig.allowed_extensions` from `useUploadConfig()` | Yes — `getUploadConfig()` calls `apiFetch('/ingest/upload/config/')` which queries `UPLOAD_ALLOWED_EXTENSIONS.get(db)` (persistent DB config) | FLOWING |
| `ReuploadDialog.tsx` | `reuploadAccept` | `uploadConfig.allowed_extensions` from same hook | Yes — same API endpoint, same DB source | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TypeScript compiles clean | `npx tsc --noEmit` (in `frontend/`) | Exit 0, no output | PASS |
| No hardcoded `ACCEPT` constant in import/reupload components | `grep -rn "const ACCEPT" frontend/src/components/import/ frontend/src/components/dataset/ReuploadDialog.tsx` | No matches | PASS |
| No hardcoded `FORMAT_BADGES` anywhere in frontend | `grep -rn "FORMAT_BADGES" frontend/src/` | No matches | PASS |
| Backend test for unknown extension exists | `grep -n "test_unknown_extension_skips_validation" backend/tests/test_upload_validation.py` | Line 75, valid test body | PASS |
| Backend test execution | `python -m pytest backend/tests/test_upload_validation.py` | Cannot run outside container (missing deps) | SKIP — not runnable without Docker virtualenv |

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| EXT-01 | Dynamic extension list flowing from admin settings through API to both FileDropzone and ReuploadDialog | SATISFIED | Full end-to-end chain: DB persistent config → `/ingest/upload/config/` → `useUploadConfig()` → `UploadForm` → `FileDropzone` (and `ReuploadDialog` independently). Unknown extensions bypass magic-byte validation. |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | — |

No `TODO`, `FIXME`, `placeholder`, `return null`, hardcoded empty arrays, or stub patterns found in modified files.

---

### Human Verification Required

#### 1. Badge rendering when admin changes extensions

**Test:** In admin storage settings, change allowed extensions to `.geojson,.csv`. Navigate to the import page.
**Expected:** Dropzone badges show `.geojson` and `.csv` only (no `.zip`, `.gpkg`, etc.).
**Why human:** Badge rendering requires a live browser session with a populated upload config response.

#### 2. ReuploadDialog file filter enforcement

**Test:** Open a dataset's re-upload dialog. In the file picker, attempt to select a `.txt` file when extensions are limited to `.geojson,.csv`.
**Expected:** File picker or drag-and-drop rejects the `.txt` file.
**Why human:** Browser file picker filtering behavior requires visual confirmation.

---

### Gaps Summary

No gaps. All must-have truths are verified, all artifacts are substantive and wired, data flows from DB through API to both dropzone components. The only open items are two human verification checks for visual/browser behaviors.

---

_Verified: 2026-03-25_
_Verifier: Claude (gsd-verifier)_
