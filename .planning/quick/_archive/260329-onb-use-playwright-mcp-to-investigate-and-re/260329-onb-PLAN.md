---
phase: 260329-onb
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/api/client.ts
  - frontend/src/hooks/use-map-thumbnail.ts
  - frontend/src/components/maps/MapCard.tsx
  - frontend/src/components/maps/MapCardGrid.tsx
  - frontend/src/components/maps/__tests__/MapCard.test.tsx
autonomous: true
requirements: [THUMB-AUTH]

must_haves:
  truths:
    - "Private map thumbnails load for authenticated users without 404 errors"
    - "Public map thumbnails still load correctly"
    - "Maps with no thumbnail show the MapIcon placeholder"
    - "No blob URL memory leaks on unmount or thumbnail URL change"
  artifacts:
    - path: "frontend/src/api/client.ts"
      provides: "apiFetchBlob() for raw blob responses with auth"
      exports: ["apiFetchBlob"]
    - path: "frontend/src/hooks/use-map-thumbnail.ts"
      provides: "useMapThumbnail hook returning object URL from authenticated fetch"
      exports: ["useMapThumbnail"]
    - path: "frontend/src/components/maps/MapCard.tsx"
      provides: "List-view map card using authenticated thumbnail"
    - path: "frontend/src/components/maps/MapCardGrid.tsx"
      provides: "Grid-view map card using authenticated thumbnail"
  key_links:
    - from: "frontend/src/hooks/use-map-thumbnail.ts"
      to: "frontend/src/api/client.ts"
      via: "apiFetchBlob()"
      pattern: "apiFetchBlob"
    - from: "frontend/src/components/maps/MapCard.tsx"
      to: "frontend/src/hooks/use-map-thumbnail.ts"
      via: "useMapThumbnail(map.thumbnail_url)"
      pattern: "useMapThumbnail"
    - from: "frontend/src/components/maps/MapCardGrid.tsx"
      to: "frontend/src/hooks/use-map-thumbnail.ts"
      via: "useMapThumbnail(map.thumbnail_url)"
      pattern: "useMapThumbnail"
---

<objective>
Fix private map thumbnail 404 errors by fetching thumbnails through the authenticated API client.

Purpose: `<img src>` tags cannot send JWT auth headers, so private map thumbnails return 404. The visual fallback (placeholder icon) works, but authenticated users should see their private map thumbnails.

Output: An `apiFetchBlob()` utility, a `useMapThumbnail()` hook, and updated MapCard/MapCardGrid components that fetch thumbnails with auth.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/api/client.ts
@frontend/src/components/maps/MapCard.tsx
@frontend/src/components/maps/MapCardGrid.tsx
@frontend/src/components/maps/__tests__/MapCard.test.tsx

<interfaces>
From frontend/src/api/client.ts:
```typescript
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number);
}
export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T>;
```

From frontend/src/components/maps/MapCard.tsx:
```typescript
export interface MapCardProps {
  map: MapSummaryResponse;
  onDelete: (id: string) => void;
}
```

MapSummaryResponse has `thumbnail_url: string | null`.

Auth token access: `useAuthStore.getState().token` for non-React contexts.
API_BASE: from `@/lib/constants`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add apiFetchBlob and useMapThumbnail hook</name>
  <files>frontend/src/api/client.ts, frontend/src/hooks/use-map-thumbnail.ts</files>
  <action>
1. In `frontend/src/api/client.ts`, add an `apiFetchBlob()` export below the existing `apiFetch()`. It should:
   - Accept `path: string` and optional `options: RequestInit`
   - Reuse the same auth header logic as `apiFetch()` (read token from `useAuthStore.getState()`, proactive refresh if expiring within 30s)
   - Call `fetch()` with auth headers and `Accept: 'image/*'` default
   - On 401, attempt refresh + retry (same pattern as `apiFetch`)
   - On success, return `response.blob()`
   - On error, throw `ApiError`
   - Do NOT duplicate the refresh logic — extract the header-building and refresh into a shared helper if it keeps things clean, or just inline it (the function is small enough)

2. Create `frontend/src/hooks/use-map-thumbnail.ts`:
   - Export `useMapThumbnail(thumbnailUrl: string | null): string | null`
   - If `thumbnailUrl` is null/undefined, return null immediately
   - Use `useEffect` keyed on `thumbnailUrl` to:
     - Call `apiFetchBlob(thumbnailUrl)`
     - On success, create object URL via `URL.createObjectURL(blob)` and set state
     - On error (e.g. 404 for truly missing thumbnails), set state to null
     - Use a `cancelled` flag to prevent state updates after unmount
   - Cleanup: `URL.revokeObjectURL()` the previous object URL when thumbnailUrl changes or component unmounts
   - Return the object URL string (or null while loading / on error)
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit --pretty 2>&1 | head -30</automated>
  </verify>
  <done>apiFetchBlob exported from client.ts, useMapThumbnail hook created, both type-check cleanly</done>
</task>

<task type="auto">
  <name>Task 2: Wire MapCard and MapCardGrid to use useMapThumbnail</name>
  <files>frontend/src/components/maps/MapCard.tsx, frontend/src/components/maps/MapCardGrid.tsx, frontend/src/components/maps/__tests__/MapCard.test.tsx</files>
  <action>
1. In both `MapCard.tsx` and `MapCardGrid.tsx`:
   - Import `useMapThumbnail` from `@/hooks/use-map-thumbnail`
   - Remove the `API_BASE` import (no longer needed for thumbnail)
   - Call `const thumbnailSrc = useMapThumbnail(map.thumbnail_url);`
   - Replace the condition `map.thumbnail_url && !imgError` with `thumbnailSrc && !imgError`
   - Replace `src={`${API_BASE}${map.thumbnail_url}`}` with `src={thumbnailSrc}`
   - Keep the existing `onError` fallback (handles cases where blob URL is somehow invalid)

2. Update `frontend/src/components/maps/__tests__/MapCard.test.tsx`:
   - Mock the `useMapThumbnail` hook at the module level: `vi.mock('@/hooks/use-map-thumbnail', () => ({ useMapThumbnail: vi.fn() }))`
   - Import the mocked hook
   - For "renders img when thumbnail is present" tests: mock returns `'blob:http://localhost/fake-thumb'`
   - For "renders MapIcon placeholder when thumbnail_url is null" tests: mock returns `null`
   - For "renders MapIcon placeholder when img fires onError" tests: mock returns a blob URL, then fire error event
   - This decouples the tests from fetch internals and tests the component behavior correctly
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/components/maps/__tests__/MapCard.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>MapCard and MapCardGrid use authenticated thumbnail fetch; all 6 existing tests pass with mocked hook; no direct img src to API_BASE for thumbnails</done>
</task>

</tasks>

<verification>
1. `cd frontend && npx tsc --noEmit` — no type errors
2. `cd frontend && npx vitest run src/components/maps/__tests__/MapCard.test.tsx` — all tests pass
3. Manual: Log in as admin, navigate to /maps, open browser DevTools Network tab — thumbnail requests should go through fetch (XHR) with Authorization header, not as plain img requests. Private map thumbnails should display the actual image, not the placeholder icon.
</verification>

<success_criteria>
- Private map thumbnails render for authenticated users (no more 404 in console)
- Public map thumbnails continue to work
- Maps without thumbnails show MapIcon placeholder
- No memory leaks from blob URLs (cleanup on unmount)
- All existing MapCard tests pass (updated to mock the hook)
</success_criteria>

<output>
After completion, create `.planning/quick/260329-onb-use-playwright-mcp-to-investigate-and-re/260329-onb-SUMMARY.md`
</output>
