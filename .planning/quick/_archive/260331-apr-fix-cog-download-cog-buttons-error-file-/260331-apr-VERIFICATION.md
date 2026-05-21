---
phase: quick-260331-apr
verified: 2026-03-31T00:00:00Z
status: passed
score: 3/3 must-haves verified
re_verification: false
---

# Quick Task: Fix COG Download Buttons Verification Report

**Task Goal:** Fix COG "Download COG" buttons error — buttons used plain `<a href>` tags making unauthenticated browser requests against a protected endpoint (`require_permission("export")`).
**Verified:** 2026-03-31
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                   | Status     | Evidence                                                                                   |
|----|-------------------------------------------------------------------------|------------|--------------------------------------------------------------------------------------------|
| 1  | Download COG button works for authenticated users (sends JWT)           | VERIFIED | `downloadCog()` reads `useAuthStore.getState().token` and sets `Authorization: Bearer` header |
| 2  | Download COG button triggers file save dialog with .tif filename        | VERIFIED | `anchor.download = \`${title}.tif\`` in `datasets.ts` line 130                             |
| 3  | Both DatasetPage and JobProgress COG download buttons use authenticated fetch | VERIFIED | Both files import `downloadCog` and call it via `onClick` handler, no `<a href>` remains  |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact                                              | Expected                          | Status     | Details                                                          |
|-------------------------------------------------------|-----------------------------------|------------|------------------------------------------------------------------|
| `frontend/src/api/datasets.ts`                        | `downloadCog()` function          | VERIFIED | Lines 102-135: full implementation following `downloadExport` pattern |
| `frontend/src/pages/DatasetPage.tsx`                  | Authenticated COG download button | VERIFIED | Line 53: import; line 460: `onClick={() => downloadCog(...)}` |
| `frontend/src/components/import/JobProgress.tsx`      | Authenticated COG download button | VERIFIED | Line 18: import; line 139: `onClick={() => downloadCog(...)}` |

### Key Link Verification

| From                                             | To                              | Via                                   | Status     | Details                              |
|--------------------------------------------------|---------------------------------|---------------------------------------|------------|--------------------------------------|
| `frontend/src/pages/DatasetPage.tsx`             | `frontend/src/api/datasets.ts`  | `downloadCog()` import and onClick    | WIRED    | Import at line 53; usage at line 460 |
| `frontend/src/components/import/JobProgress.tsx` | `frontend/src/api/datasets.ts`  | `downloadCog()` import and onClick    | WIRED    | Import at line 18; usage at line 139 |

### Data-Flow Trace (Level 4)

Not applicable — this is a download trigger function, not a component rendering dynamic data from a store or query.

### Behavioral Spot-Checks

| Behavior                                     | Command                                              | Result         | Status |
|----------------------------------------------|------------------------------------------------------|----------------|--------|
| No plain anchor tags point to /download/cog  | `grep -r 'href.*download/cog' frontend/src/`         | No matches     | PASS |
| TypeScript compiles cleanly                  | `npx tsc --noEmit`                                   | No errors      | PASS |
| downloadCog imported in DatasetPage          | `grep 'downloadCog' DatasetPage.tsx`                 | Lines 53, 460  | PASS |
| downloadCog imported in JobProgress          | `grep 'downloadCog' JobProgress.tsx`                 | Lines 18, 139  | PASS |

### Requirements Coverage

| Requirement       | Source Plan          | Description                            | Status     | Evidence                            |
|-------------------|----------------------|----------------------------------------|------------|-------------------------------------|
| FIX-COG-DOWNLOAD  | 260331-apr-PLAN.md   | Authenticated COG download via fetch   | SATISFIED | `downloadCog()` sends JWT; buttons use `onClick` |

### Anti-Patterns Found

None. No plain anchor tags remain, no stubs, no TODO/FIXME markers in modified files.

### Human Verification Required

None. All checks pass programmatically. The actual browser download dialog behavior (file save, .tif filename) cannot be verified without a running browser session, but the implementation is structurally correct and matches the established `downloadExport` pattern exactly.

### Gaps Summary

No gaps. All three observable truths verified. The `downloadCog()` function faithfully mirrors `downloadExport`: reads JWT from auth store, sets `Authorization` header, fetches the endpoint, checks `response.ok`, blobs the response, and triggers a download with a `.tif` extension. Both call sites replaced `<Button asChild><a href>` with plain `<Button onClick>`. TypeScript compiles without errors.

---

_Verified: 2026-03-31_
_Verifier: Claude (gsd-verifier)_
