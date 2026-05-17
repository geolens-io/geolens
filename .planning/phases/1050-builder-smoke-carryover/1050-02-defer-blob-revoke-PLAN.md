---
phase: 1050-builder-smoke-carryover
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/maps/hooks/use-map-thumbnail.ts
  - frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts
autonomous: true
requirements: [SMOKE-09]

must_haves:
  truths:
    - "Post-login redirect to `/` produces zero `blob:` `net::ERR_FILE_NOT_FOUND` console errors"
    - "Thumbnails that were visible pre-login remain visible / re-render cleanly post-login redirect (no broken-image placeholders)"
    - "The revoke still fires eventually — no permanent blob-URL leak on unmount of the owning component"
  artifacts:
    - path: "frontend/src/components/maps/hooks/use-map-thumbnail.ts"
      provides: "Blob URL lifecycle cleanup on data-change + unmount"
      contains: "revokeObjectURL"
    - path: "frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts"
      provides: "Test asserting revokeObjectURL fires on data change AND unmount"
      contains: "revokeObjectURL.*toHaveBeenCalledWith"
  key_links:
    - from: "use-map-thumbnail.ts:useQuery callback"
      to: "useEffect cleanup on [data]"
      via: "URL.revokeObjectURL"
      pattern: "URL\\.revokeObjectURL\\(data\\)"
---

<objective>
Eliminate the 4× `net::ERR_FILE_NOT_FOUND` `blob:` console errors that fire on post-login redirect to `/`. Closes SF-05.

Purpose: Per SF-05 evidence (`browser_console_messages` Pass A, 2026-05-17), `Failed to load resource: net::ERR_FILE_NOT_FOUND @ blob:http://localhost:8080/<uuid>:0` fires immediately after the login form POST and redirect. Root cause: `useMapThumbnail` creates blob URLs via `URL.createObjectURL(blob)` (line 21-30) but has NO `URL.revokeObjectURL` cleanup. On post-login redirect, React Query refetches `/api/maps/` → re-creates blob URLs → old blobs are GC'd from cache → `<img>` elements still pointing at the old URL fire `ERR_FILE_NOT_FOUND`.

Sibling hook `use-quicklook.ts:67-74` already has the correct pattern — copy it.

Output:
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts` — add `useEffect` cleanup that calls `URL.revokeObjectURL(data)` on `data` change AND unmount
- `frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts` — test asserting `revokeObjectURL` fires on data change AND on unmount
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/1050-builder-smoke-carryover/1050-CONTEXT.md
@.planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md
@.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md

@frontend/src/components/maps/hooks/use-map-thumbnail.ts
@frontend/src/components/maps/hooks/use-quicklook.ts

<interfaces>
<!-- Sibling-hook analog. Executor copies this shape exactly. -->

From use-quicklook.ts:67-74 (the EXACT pattern to copy):
```typescript
// Revoke blob URL when data changes (new dataset) or on unmount
useEffect(() => {
  if (typeof data === 'string') {
    return () => {
      URL.revokeObjectURL(data);
    };
  }
}, [data]);
```

From use-quicklook.ts:26-28 (doc comment to mirror):
```
 * Blob URL lifecycle: URL.revokeObjectURL is called on unmount AND on
 * datasetId change (via the useEffect cleanup on [data]) to prevent memory
 * leaks.
```

From use-quicklook.test.ts:153, 173-174 (test analog):
```typescript
expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/quicklook');
// revokeObjectURL was called when the query key changed (data changed)
```

Existing spy in use-map-thumbnail.test.ts:28:
```typescript
vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
```

Imports to add in use-map-thumbnail.ts (current file already imports useQuery):
```typescript
import { useEffect } from 'react';
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add blob URL lifecycle cleanup to use-map-thumbnail.ts</name>
  <files>frontend/src/components/maps/hooks/use-map-thumbnail.ts, frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts</files>
  <read_first>
    - frontend/src/components/maps/hooks/use-map-thumbnail.ts (full file — confirm current `URL.createObjectURL` usage at lines ~21-30 and verify NO existing cleanup)
    - frontend/src/components/maps/hooks/use-quicklook.ts:1-90 (sibling analog — copy the useEffect cleanup at lines 67-74 + doc comment at lines 26-28)
    - frontend/src/components/maps/hooks/__tests__/use-quicklook.test.ts:140-180 (test prototype for revokeObjectURL assertion)
    - frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts (full file — confirm existing spy at line ~28 and current test conventions)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 02 section — touch points + analog #1)
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md SF-05 (Observed evidence + Recommended fix)
  </read_first>
  <behavior>
    - Test 1 (NEW or extended in use-map-thumbnail.test.ts): When the query key changes (new mapId), `URL.revokeObjectURL` is called with the previous blob URL.
    - Test 2 (NEW): When the consuming component unmounts, `URL.revokeObjectURL` is called with the active blob URL.
    - Test 3 (NEW): When `data` is undefined (query loading/error), the useEffect does NOT call `URL.revokeObjectURL`.
    - Test 4 (regression): Existing test cases for the hook's return shape continue to pass.
  </behavior>
  <action>
    In `frontend/src/components/maps/hooks/use-map-thumbnail.ts`:

    1. Add `useEffect` to the React imports at the top of the file:
       ```typescript
       import { useEffect } from 'react';
       ```
       If `useEffect` is already imported, leave the import alone.

    2. After the `useQuery({ ... })` block (which produces `data` as the blob URL string), add the cleanup useEffect — exact shape from `use-quicklook.ts:67-74`:
       ```typescript
       // Revoke blob URL when data changes (new mapId) or on unmount
       useEffect(() => {
         if (typeof data === 'string') {
           return () => {
             URL.revokeObjectURL(data);
           };
         }
       }, [data]);
       ```
       Place it before the `return` statement of the hook.

    3. Update the hook's JSDoc-style doc comment at the top of the file to mirror `use-quicklook.ts:26-28`:
       ```
        * Blob URL lifecycle: URL.revokeObjectURL is called on unmount AND on
        * mapId change (via the useEffect cleanup on [data]) to prevent memory
        * leaks and post-redirect ERR_FILE_NOT_FOUND console errors (SF-05).
       ```

    4. In `frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts`, add 3 NEW tests mirroring `use-quicklook.test.ts:140-180`:
       - "calls revokeObjectURL when the query key changes" (rerender with a new mapId, assert spy called with the prior URL)
       - "calls revokeObjectURL on unmount" (unmount via testing-library's `unmount()`, assert spy called with the active URL)
       - "does NOT call revokeObjectURL when data is undefined" (query in loading state, assert spy not called)

    5. DO NOT touch the other createObjectURL call sites listed in PATTERNS.md as "out of scope for the SF-05 noise":
       - `frontend/src/api/datasets.ts:87-94`
       - `frontend/src/components/admin/ExportSplitButton.tsx:24-31`
       - `frontend/src/components/admin/saml/SamlProvidersSection.tsx:230-237`
       - `frontend/src/components/builder/StyleJsonDialog.tsx:33-38`
       - `frontend/src/components/builder/hooks/use-builder-save.ts:486-493`
       - `frontend/src/hooks/use-config-ops.ts:24-31`
       These already use the synchronous-revoke-after-`a.click()` pattern which is correct for one-shot download flows.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts src/components/maps/hooks/__tests__/use-quicklook.test.ts && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "URL.revokeObjectURL" frontend/src/components/maps/hooks/use-map-thumbnail.ts` returns ≥ 1.
    - `grep -c "useEffect" frontend/src/components/maps/hooks/use-map-thumbnail.ts` returns ≥ 1.
    - All 3 new tests in `use-map-thumbnail.test.ts` pass.
    - Existing `use-quicklook.test.ts` tests continue to pass (no shared-mock side effects).
    - Typecheck exits 0.
  </acceptance_criteria>
  <done>
    `use-map-thumbnail.ts` mirrors the `use-quicklook.ts` blob-lifecycle pattern; tests assert revoke on data change AND unmount; typecheck clean.
  </done>
</task>

</tasks>

<verification>
- Post-login redirect produces 0 `blob:` `net::ERR_FILE_NOT_FOUND` console errors (verified in Plan 06 CTRL-01 via Playwright MCP).
- Targeted vitest passes: `use-map-thumbnail.test.ts` (with new revoke-cleanup tests) + `use-quicklook.test.ts` (regression).
- Other `createObjectURL` call sites (datasets.ts, ExportSplitButton, SamlProvidersSection, StyleJsonDialog, use-builder-save.ts handleExportPNG, use-config-ops.ts) are NOT modified — preserved sync-revoke-after-click pattern.
</verification>

<success_criteria>
1. `use-map-thumbnail.ts` calls `URL.revokeObjectURL(data)` in a useEffect cleanup keyed on `[data]`.
2. The cleanup fires on mapId/query-key change AND on component unmount (verified by 2 new tests).
3. Typecheck clean.
4. e2e:smoke:builder unchanged (this hook is not on the builder's hot path, but a regression check is part of Plan 06).
</success_criteria>

<output>
Create `.planning/phases/1050-builder-smoke-carryover/1050-02-SUMMARY.md` when done — record:
- Before/after `use-map-thumbnail.ts` diff hash (line count delta).
- New test count in `use-map-thumbnail.test.ts`.
- Confirmation that other createObjectURL call sites were NOT touched.
</output>
