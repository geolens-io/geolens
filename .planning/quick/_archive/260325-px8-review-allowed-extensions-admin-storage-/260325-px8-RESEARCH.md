# Quick Task 260325-px8: Allowed Extensions Alignment - Research

**Researched:** 2026-03-25
**Domain:** Settings API, react-dropzone accept format, extension validation
**Confidence:** HIGH

## Summary

The admin storage settings page already persists `upload_allowed_extensions` via `PersistentConfig` and the backend reads it correctly at upload time. The gap is entirely frontend: `FileDropzone.tsx` and `ReuploadDialog.tsx` both hardcode their `ACCEPT` maps and `FORMAT_BADGES` instead of reading from the API. The existing `useUploadConfig` hook (via `/ingest/upload/config/`) does NOT include allowed extensions -- it only returns presigned upload info and max file size. Extensions must be added to that endpoint or fetched separately.

**Primary recommendation:** Add `allowed_extensions` to the existing `UploadConfigResponse` / `UploadConfig` type, then build a small extension-to-MIME utility in the frontend to convert `[".zip", ".gpkg", ...]` into a react-dropzone `accept` map.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Dropzone must dynamically read `upload_allowed_extensions` from the settings API at render time
- Admin changes to allowed extensions take effect immediately on the import page
- Remove the hardcoded `ACCEPT` map in `FileDropzone.tsx`
- Derive format badges automatically from the current allowed extensions list
- No separate curated `FORMAT_BADGES` array -- badges reflect whatever is configured

### Claude's Discretion
- Content (magic-byte) validation for admin-added extensions: skip magic-byte validation for extensions not in the known `EXTENSION_CONTENT_MAP`. Extension check is sufficient for unknown types.
</user_constraints>

## Current State of Affairs

### Backend -- Already Correct
1. **Config default** (`backend/app/config.py:30`): `upload_allowed_extensions: str = ".zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls"`
2. **Persistent config** (`backend/app/persistent_config.py:413-418`): `UPLOAD_ALLOWED_EXTENSIONS` reads from DB, falls back to env default.
3. **Upload validation** (`backend/app/ingest/router.py:99-103`, `backend/app/datasets/router.py:1275-1279`): All upload endpoints read `UPLOAD_ALLOWED_EXTENSIONS.get(db)` and pass to `validate_file_extension()`. Already dynamic.
4. **Content validation** (`backend/app/ingest/validation.py:75`): `EXTENSION_CONTENT_MAP.get(suffix, set())` returns empty set for unknown extensions. When `allowed` is empty and `detected` is any string, the function falls through to the mismatch log + ValueError. This means unknown extensions WILL be rejected by content validation even if they pass extension validation.

**Backend fix needed:** `validate_file_content()` should return early (skip) when the extension has no entry in `EXTENSION_CONTENT_MAP`, rather than treating it as a mismatch. This aligns with the CONTEXT.md discretion note.

### Backend -- Missing from Upload Config Endpoint
The `/ingest/upload/config/` endpoint (`UploadConfigResponse`) only returns:
- `presigned_uploads: bool`
- `presigned_threshold_bytes: int`
- `max_file_size_bytes: int`

It does NOT include `allowed_extensions`. Must add it.

### Frontend -- Hardcoded in Two Places

1. **`FileDropzone.tsx`** (lines 11-21): Hardcoded `ACCEPT` map and `FORMAT_BADGES` array.
2. **`ReuploadDialog.tsx`** (lines 62-67): Separate hardcoded `ACCEPT` map (smaller -- missing `.tif`, `.xlsx`, `.xls`). Already out of sync with the import dropzone.

Both components currently ignore settings entirely.

### Frontend -- Existing Hooks Available
- `useUploadConfig()` in `frontend/src/hooks/use-ingest.ts` -- already used by both `UploadForm.tsx` and `ReuploadDialog.tsx`. Best place to add `allowed_extensions`.
- `UploadConfig` type in `frontend/src/types/api.ts:1044` -- needs `allowed_extensions` field added.

## react-dropzone Accept Format

The `accept` prop takes `Record<string, string[]>` where keys are MIME types and values are extension arrays. Example:
```typescript
{ 'application/zip': ['.zip'], 'text/csv': ['.csv'] }
```

react-dropzone also supports extension-only format: keys can be extensions directly:
```typescript
{ '.zip': [], '.csv': [] }
```

However, using MIME types is preferred because it enables drag-and-drop file type detection via the browser's `DataTransferItem.type`. Extension-only accept works for the file picker dialog but drag rejection may not work as reliably.

**Recommendation:** Use a static MIME mapping for known extensions, fall back to extension-only for unknown admin-added extensions.

## Extension-to-MIME Mapping Utility

Small utility needed in frontend:

```typescript
const EXT_MIME_MAP: Record<string, string> = {
  '.zip': 'application/zip',
  '.gpkg': 'application/geopackage+sqlite3',
  '.geojson': 'application/geo+json',
  '.json': 'application/geo+json',
  '.csv': 'text/csv',
  '.tif': 'image/tiff',
  '.tiff': 'image/tiff',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.xls': 'application/vnd.ms-excel',
};

export function buildAcceptMap(extensions: string[]): Record<string, string[]> {
  const accept: Record<string, string[]> = {};
  for (const ext of extensions) {
    const mime = EXT_MIME_MAP[ext] ?? 'application/octet-stream';
    if (!accept[mime]) accept[mime] = [];
    if (!accept[mime].includes(ext)) accept[mime].push(ext);
  }
  return accept;
}
```

For unknown extensions added by admin (e.g., `.parquet`), `application/octet-stream` is the correct fallback MIME. react-dropzone will still match by extension in the file picker dialog.

## Changes Required

### Backend (2 changes)
1. **Add `allowed_extensions` to `UploadConfigResponse`** in `backend/app/ingest/schemas.py` and populate it in `backend/app/ingest/router.py:64-78` from `UPLOAD_ALLOWED_EXTENSIONS.get(db)`.
2. **Fix `validate_file_content()`** in `backend/app/ingest/validation.py`: when `EXTENSION_CONTENT_MAP.get(suffix)` returns `None` (not empty set -- currently impossible since `.get()` defaults to `set()`), skip validation. Actually, the current code returns empty set for unknown extensions, which means `detected in allowed` is False, and then it checks the text-content fallback only for `.geojson/.json/.csv`. **Fix:** Add early return when `suffix not in EXTENSION_CONTENT_MAP` before the magic byte check.

### Frontend (3 changes)
1. **Add `allowed_extensions: string` to `UploadConfig`** type in `frontend/src/types/api.ts`.
2. **Create `buildAcceptMap()` utility** -- small function, can live in `frontend/src/lib/file-utils.ts` or inline in `FileDropzone.tsx`.
3. **Update `FileDropzone.tsx`**: Accept `allowedExtensions?: string[]` prop, use `buildAcceptMap()` for the `accept` prop, derive badges from the extensions list.
4. **Update `UploadForm.tsx`**: Pass `uploadConfig.allowed_extensions` parsed as array to `FileDropzone`.
5. **Update `ReuploadDialog.tsx`**: Same pattern -- use `uploadConfig.allowed_extensions` instead of hardcoded `ACCEPT`.

## Common Pitfalls

### Pitfall 1: ReuploadDialog Already Out of Sync
The ReuploadDialog has a smaller `ACCEPT` map (missing `.tif`, `.xlsx`, `.xls`). This is an existing bug that this task fixes.

### Pitfall 2: Loading State
`useUploadConfig` may not have data yet on first render. FileDropzone should handle `undefined` extensions gracefully -- either show loading state or fall back to permissive (accept all) until config loads.

### Pitfall 3: Comma-Separated String vs Array
Backend stores extensions as comma-separated string (`".zip,.gpkg,.geojson"`). Frontend needs to split and trim: `ext.split(',').map(e => e.trim()).filter(Boolean)`.

### Pitfall 4: Content Validation Rejects Unknown Extensions
If admin adds `.parquet` to allowed extensions, extension validation passes but `validate_file_content()` will reject it because `.parquet` is not in `EXTENSION_CONTENT_MAP` and the detected type won't match the empty set. Must fix backend.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all referenced files
- `backend/app/ingest/validation.py` -- EXTENSION_CONTENT_MAP behavior verified
- `backend/app/ingest/router.py` -- UploadConfigResponse construction verified
- `frontend/src/components/import/FileDropzone.tsx` -- hardcoded ACCEPT verified
- `frontend/src/components/dataset/ReuploadDialog.tsx` -- second hardcoded ACCEPT verified
- react-dropzone accept format from existing working code in the codebase
