---
phase: 260329-onb
plan: 01
subsystem: frontend/maps
tags: [thumbnails, auth, blob-url, hooks]
dependency_graph:
  requires: []
  provides: [apiFetchBlob, useMapThumbnail]
  affects: [MapCard, MapCardGrid]
tech_stack:
  added: [useMapThumbnail hook, apiFetchBlob utility]
  patterns: [blob URL pattern for auth-gated image resources]
key_files:
  created:
    - frontend/src/hooks/use-map-thumbnail.ts
  modified:
    - frontend/src/api/client.ts
    - frontend/src/components/maps/MapCard.tsx
    - frontend/src/components/maps/MapCardGrid.tsx
    - frontend/src/components/maps/__tests__/MapCard.test.tsx
decisions:
  - Added apiFetchBlob() as a sibling to apiFetch() rather than extending apiFetch() with a flag to keep the APIs clean and avoid overloading one function with dual behaviors
  - useMapThumbnail uses a cancelled flag + objectUrl local variable for safe cleanup — prevents both state updates after unmount and blob URL leaks
  - Tests mock the hook at module level via vi.mock() to decouple component behavior tests from fetch internals
metrics:
  duration: 8min
  completed: 2026-03-29
  tasks_completed: 2
  files_changed: 5
---

# Phase 260329-onb Plan 01: Authenticated Map Thumbnails Summary

**One-liner:** JWT-authenticated blob URL fetch for private map thumbnails using `apiFetchBlob()` and `useMapThumbnail()` hook.

## What Was Built

Private map thumbnails were returning 404 because `<img src>` tags cannot send JWT auth headers. The fix fetches thumbnails through the authenticated API client, converts to blob URLs, and manages lifecycle (cleanup on unmount).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add apiFetchBlob and useMapThumbnail hook | 3edc16be | client.ts, use-map-thumbnail.ts |
| 2 | Wire MapCard and MapCardGrid to useMapThumbnail | 94ba1f31 | MapCard.tsx, MapCardGrid.tsx, MapCard.test.tsx |

## Changes

### `frontend/src/api/client.ts`

Added `apiFetchBlob(path, options?)` — mirrors `apiFetch()` auth flow (proactive refresh, 401 retry) but returns `response.blob()` instead of `response.json()`. Sets `Accept: image/*` by default.

### `frontend/src/hooks/use-map-thumbnail.ts` (new)

`useMapThumbnail(thumbnailUrl)` hook:
- Returns `null` immediately if `thumbnailUrl` is null/undefined
- Calls `apiFetchBlob()` in `useEffect` keyed on `thumbnailUrl`
- Creates object URL via `URL.createObjectURL(blob)`, returns it as `src`
- Cleans up via `URL.revokeObjectURL()` on URL change or unmount
- Uses `cancelled` flag to prevent state updates after unmount

### `frontend/src/components/maps/MapCard.tsx` and `MapCardGrid.tsx`

- Replaced `import { API_BASE }` with `import { useMapThumbnail }`
- Call `const thumbnailSrc = useMapThumbnail(map.thumbnail_url)`
- Replaced `map.thumbnail_url && !imgError` with `thumbnailSrc && !imgError`
- Replaced `src={\`${API_BASE}${map.thumbnail_url}\`}` with `src={thumbnailSrc}`

### `frontend/src/components/maps/__tests__/MapCard.test.tsx`

- Added `vi.mock('@/hooks/use-map-thumbnail', ...)` module mock
- Tests use `mockUseMapThumbnail.mockReturnValue('blob:http://localhost/fake-thumb')` for image-present cases
- Tests use `mockUseMapThumbnail.mockReturnValue(null)` for placeholder cases
- All 6 tests pass

## Verification

- `tsc --noEmit` — no errors
- `vitest run MapCard.test.tsx` — 6/6 tests pass
- Manual: Authenticated users can now see private map thumbnails (fetched via XHR with Authorization header, not raw img src)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- `frontend/src/hooks/use-map-thumbnail.ts` — FOUND
- `frontend/src/api/client.ts` — modified, FOUND
- Commit 3edc16be — FOUND
- Commit 94ba1f31 — FOUND
