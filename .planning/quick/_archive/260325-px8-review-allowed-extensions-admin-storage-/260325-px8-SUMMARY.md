# Quick Task 260325-px8: Allowed Extensions Alignment - Summary

**Completed:** 2026-03-25
**Status:** Complete

## What Changed

### Backend
1. **`UploadConfigResponse`** (`backend/app/ingest/schemas.py`): Added `allowed_extensions: str` field
2. **`get_upload_config`** (`backend/app/ingest/router.py`): Now reads `UPLOAD_ALLOWED_EXTENSIONS` from persistent config and includes it in response
3. **`validate_file_content`** (`backend/app/ingest/validation.py`): Added early return for extensions not in `EXTENSION_CONTENT_MAP` — unknown admin-added extensions skip magic-byte validation
4. **Test** (`backend/tests/test_upload_validation.py`): Added `test_unknown_extension_skips_validation`

### Frontend
1. **`file-utils.ts`** (`frontend/src/lib/file-utils.ts`): New utility with `buildAcceptMap()` (extensions → react-dropzone accept map) and `deriveFormatBadges()` (deduplicates aliases like .tif/.tiff)
2. **`FileDropzone.tsx`**: Removed hardcoded `ACCEPT` and `FORMAT_BADGES`. Now accepts `allowedExtensions?: string[]` prop, dynamically builds accept map and badges
3. **`UploadForm.tsx`**: Passes `uploadConfig.allowed_extensions` (parsed) to `FileDropzone`
4. **`ReuploadDialog.tsx`**: Removed hardcoded `ACCEPT`. Now builds accept map from `uploadConfig.allowed_extensions`
5. **`api.ts`**: Added `allowed_extensions: string` to `UploadConfig` interface

## End-to-End Flow
Admin settings → `app_settings` DB → `UPLOAD_ALLOWED_EXTENSIONS.get(db)` → `GET /ingest/upload/config/` → `useUploadConfig()` → `FileDropzone` / `ReuploadDialog`

## Issues Found & Fixed
- **ReuploadDialog was already out of sync**: Its hardcoded ACCEPT only had 4 types vs FileDropzone's 7. Both now use the same dynamic source.
- **Content validation bug**: `validate_file_content()` would reject unknown extensions (empty `EXTENSION_CONTENT_MAP` entry → mismatch). Fixed with early return.
