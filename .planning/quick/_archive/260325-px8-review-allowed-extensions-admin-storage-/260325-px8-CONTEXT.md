# Quick Task 260325-px8: Review allowed extensions admin storage vs import page alignment - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Task Boundary

Review the allowed extensions in the admin settings/storage page, check alignment with the import page dropzone, and ensure it's wired up correctly end-to-end.

</domain>

<decisions>
## Implementation Decisions

### Dropzone sync behavior
- Dropzone must dynamically read `upload_allowed_extensions` from the settings API at render time
- Admin changes to allowed extensions take effect immediately on the import page
- Remove the hardcoded `ACCEPT` map in `FileDropzone.tsx`

### Badge display
- Derive format badges automatically from the current allowed extensions list
- No separate curated `FORMAT_BADGES` array — badges reflect whatever is configured

### Claude's Discretion
- Content (magic-byte) validation for admin-added extensions: skip magic-byte validation for extensions not in the known `EXTENSION_CONTENT_MAP`. Extension check is sufficient for unknown types.

</decisions>

<specifics>
## Specific Ideas

- FileDropzone needs to accept an `allowedExtensions` prop (or fetch from settings hook)
- Need a MIME-type mapping utility to convert extensions to react-dropzone `accept` format
- Backend `EXTENSION_CONTENT_MAP` already gracefully handles unknowns (no entry = skip content validation)

</specifics>

<canonical_refs>
## Canonical References

- Backend defaults: `backend/app/config.py:30` — `upload_allowed_extensions`
- Settings persistence: `backend/app/persistent_config.py:413-418` — `UPLOAD_ALLOWED_EXTENSIONS`
- Frontend settings API: `frontend/src/api/settings.ts` + `frontend/src/hooks/use-settings.ts`
- Dropzone component: `frontend/src/components/import/FileDropzone.tsx`
- Admin storage tab: `frontend/src/components/admin/settings/SettingsStorageTab.tsx`

</canonical_refs>
