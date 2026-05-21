---
phase: quick-260331-apr
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/api/datasets.ts
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/components/import/JobProgress.tsx
autonomous: true
requirements: [FIX-COG-DOWNLOAD]

must_haves:
  truths:
    - "Download COG button works for authenticated users (sends JWT)"
    - "Download COG button triggers file save dialog with .tif filename"
    - "Both DatasetPage and JobProgress COG download buttons use authenticated fetch"
  artifacts:
    - path: "frontend/src/api/datasets.ts"
      provides: "downloadCog() function"
      contains: "downloadCog"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Authenticated COG download button"
      contains: "downloadCog"
    - path: "frontend/src/components/import/JobProgress.tsx"
      provides: "Authenticated COG download button"
      contains: "downloadCog"
  key_links:
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/api/datasets.ts"
      via: "downloadCog() import and onClick handler"
      pattern: "downloadCog"
    - from: "frontend/src/components/import/JobProgress.tsx"
      to: "frontend/src/api/datasets.ts"
      via: "downloadCog() import and onClick handler"
      pattern: "downloadCog"
---

<objective>
Fix COG "Download COG" buttons that fail because plain `<a href>` tags make unauthenticated browser requests against a protected endpoint.

Purpose: The `/api/datasets/{id}/download/cog` endpoint requires `require_permission("export")` which needs a JWT. Plain anchor tags don't send auth headers.
Output: Authenticated blob-download function + updated button components.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/api/datasets.ts (downloadExport pattern at line 63-100)
@frontend/src/api/client.ts (apiFetchBlob at line 122)
@frontend/src/pages/DatasetPage.tsx (line 458-465 — broken <a href> button)
@frontend/src/components/import/JobProgress.tsx (line 138-143 — broken <a href> button)
</context>

<interfaces>
<!-- Existing patterns to reuse -->

From frontend/src/api/datasets.ts:
```typescript
// Pattern: downloadExport (lines 63-100) — fetches with Bearer token, creates blob URL, triggers download
export async function downloadExport(id: string, format: string, filename: string): Promise<void>;
```

From frontend/src/stores/auth-store.ts:
```typescript
// Non-React access: useAuthStore.getState().token
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Add downloadCog() and replace anchor tags with authenticated download buttons</name>
  <files>frontend/src/api/datasets.ts, frontend/src/pages/DatasetPage.tsx, frontend/src/components/import/JobProgress.tsx</files>
  <action>
1. In `frontend/src/api/datasets.ts`, add a `downloadCog` function after `downloadExport` (line ~100). Follow the exact same pattern as `downloadExport` (lines 63-100):
   - Signature: `export async function downloadCog(id: string, title: string): Promise<void>`
   - Get token from `useAuthStore.getState().token`
   - Build URL: `${API_BASE}/datasets/${id}/download/cog`
   - Set `Authorization: Bearer ${token}` header if token exists
   - Fetch, check `response.ok`, parse error detail on failure (same error handling as downloadExport)
   - Convert to blob, create object URL, create anchor element with `download` attribute set to `${title}.tif`, click it, cleanup

2. In `frontend/src/pages/DatasetPage.tsx`:
   - Add `downloadCog` to the import from `@/api/datasets`
   - Replace the `<Button asChild>` + `<a href>` pattern (lines 459-464) with a plain `<Button>` that has an `onClick` handler calling `downloadCog(dataset.id, dataset.title)`. Keep the same variant="default", size="sm", and the Download icon + text inside.
   - Remove `asChild` prop since we no longer wrap an anchor.

3. In `frontend/src/components/import/JobProgress.tsx`:
   - Add `downloadCog` import from `@/api/datasets`
   - Replace the `<Button asChild>` + `<a href>` pattern (lines 138-142) with a plain `<Button>` with `onClick` calling `downloadCog(job.dataset_id, job.filename ?? 'download')`. Keep variant="outline", size="sm", Download icon + text.
   - Remove `asChild` prop.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>Both COG download buttons use authenticated fetch via downloadCog(). No plain anchor tags remain for the COG download endpoint. TypeScript compiles cleanly.</done>
</task>

</tasks>

<verification>
- `grep -rn 'href.*download/cog' frontend/src/` returns zero matches (no plain anchor tags left)
- `grep -rn 'downloadCog' frontend/src/api/datasets.ts` shows the new function
- `grep -rn 'downloadCog' frontend/src/pages/DatasetPage.tsx frontend/src/components/import/JobProgress.tsx` shows both callers
- TypeScript compiles without errors
</verification>

<success_criteria>
- downloadCog() function exists in datasets.ts following the downloadExport pattern
- Both DatasetPage and JobProgress use onClick + downloadCog instead of <a href>
- No unauthenticated <a href> tags pointing to /download/cog remain
- TypeScript compiles cleanly
</success_criteria>

<output>
After completion, create `.planning/quick/260331-apr-fix-cog-download-cog-buttons-error-file-/260331-apr-01-SUMMARY.md`
</output>
