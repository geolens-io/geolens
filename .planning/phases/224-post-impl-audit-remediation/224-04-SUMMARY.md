---
phase: 224-post-impl-audit-remediation
plan: "04"
subsystem: frontend
tags: [quicklook, error-boundary, type-alignment, performance, resilience]
dependency_graph:
  requires: [224-02]
  provides: [native-img-quicklook, dataset-map-error-boundary, map-visibility-unlisted]
  affects: [frontend/src/components/search/SearchResultCard.tsx, frontend/src/pages/DatasetPage.tsx, frontend/src/types/api.ts]
tech_stack:
  added: []
  patterns: [native-img-lazy-loading, MapErrorBoundary-wrapping, union-type-extension]
key_files:
  created: []
  modified:
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/hooks/use-quicklook.ts
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/types/api.ts
decisions:
  - "P0-2: Use api_key query param (not Authorization header) for <img src> — no alternative for native img auth; already supported by backend"
  - "P1-14: No fallback prop passed to MapErrorBoundary — default built-in fallback (AlertCircle + retry button) is sufficient for dataset detail"
  - "P1-9: unlisted not added to VISIBILITY_OPTIONS picker in SharePanel — the value can come from the backend but is not an option users set via the builder UI"
metrics:
  duration_minutes: 10
  completed_date: "2026-04-12T15:28:26Z"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 4
---

# Phase 224 Plan 04: Frontend Audit Remediation Summary

**One-liner:** Replaced 20+ parallel base64 quicklook fetches with native img lazy loading, wrapped DatasetMap in MapErrorBoundary, and extended MapVisibility type to include 'unlisted'.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | P0-2: Replace base64 quicklook fetch with native img lazy loading | f769d1b6 | SearchResultCard.tsx, use-quicklook.ts |
| 2 | P1-14: Wrap DatasetMap in MapErrorBoundary on DatasetPage | e462b28b | DatasetPage.tsx |
| 3 | P1-9 frontend: Add 'unlisted' to MapVisibility type | aab69ad8 | api.ts |

## What Was Done

### Task 1 — P0-2: Native img lazy loading (f769d1b6)

`SearchResultCard` previously called `useQuicklook()` which fired an authenticated `fetch()` → blob → FileReader → base64 data URL pipeline per card. With 10-20 search results, this meant 10-20 parallel unauthenticated-looking requests that bypassed browser HTTP caching entirely.

The fix:
- Removed `useQuicklook` import and the `Loader2` spinner import
- Added `useAuthStore` to read the JWT token
- Constructed a direct URL: `/api/datasets/${id}/quicklook?size=256&api_key=${token}`
- Replaced the base64 `<img src>` + loading spinner with a single `<img loading="lazy" src={quicklookUrl}>` native element
- The browser now handles lazy loading natively (only fetches images in/near viewport)
- Images are cacheable by the browser (backend returns `Cache-Control: public, max-age=3600`)
- `use-quicklook.ts` marked deprecated with comment — no other components reference it

### Task 2 — P1-14: MapErrorBoundary on DatasetPage (e462b28b)

`DatasetPage` rendered `<DatasetMap>` without any error boundary. A JS exception inside the map component (e.g., WebGL initialization failure, invalid tile URL) would propagate and crash the entire dataset detail view.

The fix:
- Added `import { MapErrorBoundary } from '@/components/error'`
- Wrapped the `<DatasetMap>` block with `<MapErrorBoundary>` using the same pattern as `MapBuilderPage`, `PublicViewerPage`, and `PublicMapViewerPage`
- The built-in fallback shows an AlertCircle icon with a retry button — no custom fallback needed here

### Task 3 — P1-9 frontend: MapVisibility type extension (aab69ad8)

The backend enum and SQL CHECK constraint already included `unlisted` (added by Plan 224-02). The frontend type `MapVisibility = 'private' | 'internal' | 'public'` was stale — it would cause TypeScript to treat `unlisted` values from the API as type errors.

The fix: added `| 'unlisted'` to the union. No exhaustive switches on visibility values exist in the codebase, so no case handling needed to be added.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

- TypeScript (`tsc --noEmit`): passes cleanly (0 errors)
- Acceptance criteria for all 3 tasks met:
  - `loading="lazy"` present in SearchResultCard
  - `useQuicklook` count in SearchResultCard: 0
  - `quicklookUrl` constructed in SearchResultCard
  - `MapErrorBoundary` import + JSX usage (3 lines) in DatasetPage
  - `unlisted` present in MapVisibility type in api.ts

## Known Stubs

None.

## Threat Flags

None beyond what the plan's threat model already covered (T-224-14: api_key in URL for img src is accepted disposition; T-224-15: mitigated by MapErrorBoundary in Task 2).

## Self-Check: PASSED

- f769d1b6 — confirmed in git log
- e462b28b — confirmed in git log
- aab69ad8 — confirmed in git log
- frontend/src/components/search/SearchResultCard.tsx — modified
- frontend/src/pages/DatasetPage.tsx — modified
- frontend/src/types/api.ts — modified
