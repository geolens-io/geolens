---
phase: quick-260331-apr
plan: "01"
subsystem: frontend
tags: [raster, download, auth, fix]
dependency_graph:
  requires: []
  provides: [authenticated-cog-download]
  affects: [DatasetPage, JobProgress]
tech_stack:
  added: []
  patterns: [blob-download-with-auth]
key_files:
  created: []
  modified:
    - frontend/src/api/datasets.ts
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/components/import/JobProgress.tsx
decisions:
  - Reused downloadExport() pattern verbatim for downloadCog() to minimize divergence
metrics:
  duration: "2min"
  completed_date: "2026-03-31"
  tasks_completed: 1
  files_modified: 3
---

# Quick Task 260331-apr: Fix COG Download Buttons

## One-liner

Replaced unauthenticated `<a href>` COG download anchors with authenticated `downloadCog()` blob-fetch in DatasetPage and JobProgress.

## What Was Done

The `/api/datasets/{id}/download/cog` endpoint requires `require_permission("export")` which needs a JWT. Both `DatasetPage.tsx` and `JobProgress.tsx` were using plain `<Button asChild><a href="...">` anchor tags that bypass auth headers entirely, causing 401/403 errors on download.

### Changes

**`frontend/src/api/datasets.ts`**
- Added `downloadCog(id: string, title: string): Promise<void>` after `downloadExport` (line ~102)
- Reads token from `useAuthStore.getState().token`
- Sends `Authorization: Bearer <token>` header
- Downloads blob, creates object URL, triggers `<a download="${title}.tif">`, cleans up

**`frontend/src/pages/DatasetPage.tsx`**
- Imported `downloadCog` from `@/api/datasets`
- Replaced `<Button asChild variant="default" size="sm"><a href=...>` with `<Button variant="default" size="sm" onClick={() => downloadCog(dataset.id, dataset.title)}>`

**`frontend/src/components/import/JobProgress.tsx`**
- Imported `downloadCog` from `@/api/datasets`
- Replaced `<Button variant="outline" size="sm" asChild><a href=...>` with `<Button variant="outline" size="sm" onClick={() => downloadCog(job.dataset_id!, job.filename ?? 'download')}>`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 36fa3f74 | fix(quick-260331-apr-01): replace plain anchor COG download with authenticated fetch |

## Verification

- `grep -rn 'href.*download/cog' frontend/src/` returns zero matches
- `downloadCog` present in all three files
- TypeScript compiles cleanly (no errors)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- `frontend/src/api/datasets.ts` — modified, contains `downloadCog`
- `frontend/src/pages/DatasetPage.tsx` — modified, uses `downloadCog`
- `frontend/src/components/import/JobProgress.tsx` — modified, uses `downloadCog`
- Commit 36fa3f74 — verified in git log
