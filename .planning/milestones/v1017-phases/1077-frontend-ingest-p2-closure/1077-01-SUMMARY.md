---
phase: 1077-frontend-ingest-p2-closure
plan: 01
subsystem: frontend
tags: [frontend, refactor, ingest, presigned-upload, drift-risk]

# Dependency graph
requires:
  - phase: 1076-backend-ingest-p2-closure
    provides: stable JobStatusResponse contract referenced by JobProgress
provides:
  - "`getCogDownloadUrl(id: string): string` helper in frontend/src/api/datasets.ts"
  - "`uploadChunks(urls, file, partSize): Promise<string[]>` helper in frontend/src/api/_presignedUpload.ts"
  - "Single canonical chunked-PUT loop for both upload and reupload flows"
affects: [v1077-close-gate, future-upload-retry-work, future-abort-signal-work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Underscore-prefixed module name (`_presignedUpload.ts`) to signal an internal API helper not intended as a public surface from `@/api/*`"
    - "Helper returns minimal shape (`string[]` ETags) and lets call sites compose the API payload positionally — keeps the helper agnostic of the backend's `{etag, part_number}` contract"

key-files:
  created:
    - "frontend/src/api/_presignedUpload.ts"
    - "frontend/src/api/_presignedUpload.test.ts"
  modified:
    - "frontend/src/api/datasets.ts"
    - "frontend/src/api/ingest.ts"
    - "frontend/src/components/import/JobProgress.tsx"

key-decisions:
  - "`getCogDownloadUrl` returns a path (`${API_BASE}/datasets/${id}/download/cog`) — same contract as the existing `getExportUrl()` helper next to it. The clipboard call site in JobProgress.tsx prepends `${window.location.origin}` for the fully-qualified URL — same composition pattern the existing `downloadCog()` helper uses at datasets.ts:129."
  - "`uploadChunks` returns `string[]` (ETags in order) per the plan signature — both call sites build the `{etag, part_number: i + 1}` object via `.map`. The `part_number` is purely positional (1-indexed), so the helper has no business owning that wire-format detail."
  - "Empty-string ETag fallback preserved (`resp.headers.get('ETag') ?? ''`). Both pre-refactor loops had this fallback; it survives in the new helper. The matching call-site `.map` keeps the same shape passed to `completePresignedUpload`."
  - "Plain `fetch` (not `apiFetch`) — presigned URLs are V4-signed by the backend and must not carry the session JWT. S3 rejects requests that arrive with extra Authorization headers on V4-signed URLs. Documented as a JSDoc one-liner in `_presignedUpload.ts`."
  - "Single new test file `frontend/src/api/_presignedUpload.test.ts` (next to the helper, per the plan's literal path) — NOT under `src/api/__tests__/`. Both locations are picked up by vitest's default discovery; following the plan path lets the acceptance grep check find it without ambiguity."

patterns-established:
  - "Underscore-prefixed `_presignedUpload.ts` to signal internal-helper status."
  - "Helper returns positional `string[]`; call site composes API payload via `.map((v, i) => ({...}))`."

requirements-completed: [ING-01, ING-05]

# Metrics
duration: 6min
completed: 2026-05-21
---

# Phase 1077 Plan 01: ING-01 + ING-05 Helper Extraction Summary

**Two frontend ingest drift-risk findings closed: `/download/cog` URL now lives in `getCogDownloadUrl()` (one place instead of two), and the previously-duplicated chunked-PUT loop in `ingest.ts` + `datasets.ts` now lives in a single `uploadChunks()` helper with vitest behavior pins.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-21 16:11 EDT (phase plan commit `98284549`)
- **Completed:** 2026-05-21 16:17 EDT (test commit `0d24d39f`)
- **Tasks:** 3
- **Files modified:** 5 (3 modified + 2 created)

## Accomplishments

- **ING-01 (P2-01 in INGEST-AUDIT):** `getCogDownloadUrl(id: string): string` exported from `frontend/src/api/datasets.ts` next to `getExportUrl()`. `JobProgress.tsx:42` no longer constructs the URL by inline concatenation; it calls the helper and prepends `window.location.origin` for the clipboard write.
- **ING-05 (P2-05 in INGEST-AUDIT):** `uploadChunks(urls, file, partSize)` extracted to a new `frontend/src/api/_presignedUpload.ts`. Both `ingest.ts:147-159` (the `uploadPresigned()` flow) and `datasets.ts:370-383` (the `reuploadPresigned()` flow) now import and call it; the inline `for (let i = 0; ...)` loops are gone.
- **Test pin:** 5 vitest tests at `frontend/src/api/_presignedUpload.test.ts` pinning ETag order, exact-slice body verification, error path (4xx throws with 1-indexed part number), missing-ETag fallback, and short-circuit-on-first-failure.
- **Zero behavior change observable from the UI** — both items were pure refactors. The 112 existing tests across `src/api/` + `src/components/import/` continue to pass alongside the 5 new ones (117 / 117).
- **No divergence between the two pre-refactor loops** — they were byte-identical (modulo whitespace) once the audit's "identical chunked PUT loops" claim was verified side-by-side. The "prefer the more defensive shape" escape hatch in the plan was not exercised.

## Task Commits

Each task was committed atomically:

1. **Task 1: add `getCogDownloadUrl` helper, wire JobProgress (ING-01)** — `8c69f1e4` (refactor)
2. **Task 2: extract `uploadChunks` helper, rewire ingest + datasets (ING-05)** — `8fa5ba1d` (refactor)
3. **Task 3: pin `uploadChunks` helper behavior** — `0d24d39f` (test)

## Files Created / Modified

- `frontend/src/api/datasets.ts` — added `getCogDownloadUrl(id)` immediately after `getExportUrl()` (lines 63-66); added `import { uploadChunks } from './_presignedUpload'`; replaced the 11-line chunked-PUT loop at the bottom of `reuploadPresigned()` with two lines (`const etags = await uploadChunks(...)`; `const completedParts = etags.map(...)`)
- `frontend/src/api/ingest.ts` — added `import { uploadChunks } from './_presignedUpload'`; replaced the 11-line chunked-PUT loop at the bottom of `uploadPresigned()` with the same two-line shape.
- `frontend/src/components/import/JobProgress.tsx` — added `getCogDownloadUrl` to the existing `from '@/api/datasets'` named import; line 42 clipboard handler now reads ``${window.location.origin}${getCogDownloadUrl(datasetId)}`` instead of the literal ``${window.location.origin}/api/datasets/${datasetId}/download/cog``.
- `frontend/src/api/_presignedUpload.ts` (new, 47 lines including JSDoc) — `uploadChunks(urls, file, partSize): Promise<string[]>`.
- `frontend/src/api/_presignedUpload.test.ts` (new, 90 lines) — 5 vitest tests using the `globalThis.fetch = vi.fn()` pattern from `src/api/__tests__/client.test.ts`.

## Decisions Made

- **Helper returns a path, not a fully-qualified URL.** `getCogDownloadUrl(id)` returns `${API_BASE}/datasets/${id}/download/cog`, matching the contract of the existing `getExportUrl()` helper next to it. The JobProgress clipboard call composes the full URL via `${window.location.origin}${getCogDownloadUrl(datasetId)}` — same pattern as the existing `downloadCog()` helper at `datasets.ts:129`. Centralising the path-portion is the drift-risk closure; the protocol+host concatenation is call-site responsibility (it differs between clipboard, `window.open`, and back-end usage).
- **`uploadChunks` returns `string[]`, not `{etag, part_number}[]`.** Per the plan signature. `part_number` is purely positional (1-indexed) and is part of the *wire contract to the completion endpoint*, not part of the chunked-PUT behavior. Keeping it at the call site (`etags.map((etag, i) => ({ etag, part_number: i + 1 }))`) means the helper has zero coupling to the backend's `CompletePresignedRequest` shape.
- **Plain `fetch` inside the helper, not `apiFetch`.** Presigned URLs are V4-signed by the backend and reject extra Authorization headers. The pre-refactor loops both used plain `fetch` for this reason; the helper preserves that. Documented inline.
- **Empty-string fallback for missing ETag header preserved.** Both pre-refactor loops had `resp.headers.get('ETag') ?? ''`. Some S3-compatible backends (notably MinIO under specific config) omit the ETag header on small chunks; the empty string lets `completePresignedUpload` decide whether to accept the part. Behavior pin in `_presignedUpload.test.ts` `"falls back to empty string when ETag header is missing"`.
- **Test file lives next to the helper, not under `__tests__/`.** Vitest discovers both, but the plan's acceptance criterion grep targets `frontend/src/api/_presignedUpload.test.ts` literally — following the literal path makes the grep deterministic. Sibling-file shape is also conventional for small "helper.ts + helper.test.ts" pairs.

## Deviations from Plan

None — plan executed exactly as written. No deviation rules triggered:

- The two loops were byte-identical (verified by `grep -nE "for \(.* (of urls|i < urls.length"` returning 0 hits in both files post-refactor and visual side-by-side diff pre-refactor). No "prefer the more defensive shape" branch was needed.
- No pre-existing typecheck errors were introduced; all errors that surface in a full `npx tsc -b` run are pre-existing failures in unrelated test files (`DatasetDetailHeader.test.tsx`, `RegisterPage.alreadySignedIn.test.tsx`, etc.) reproduced on `main` at the plan-start commit `98284549` — out of scope per the scope-boundary rule.
- The `npm run typecheck` script does not exist in `frontend/package.json` (the typecheck step is wrapped inside the `build` script as `tsc -b && vite build`). Substituted `npx tsc -b` as the canonical typecheck and verified zero errors in the five touched files via a filtered grep.

## Verification

All plan acceptance gates green:

| Task | Gate | Expected | Actual | Status |
|---|---|---|---|---|
| 1 | `grep -nE "export (const\|function) getCogDownloadUrl" frontend/src/api/datasets.ts` | one line | `64:export function getCogDownloadUrl(id: string): string {` | PASS |
| 1 | `grep -n "getCogDownloadUrl" frontend/src/components/import/JobProgress.tsx` | >= 1 line | 2 lines (import + call site) | PASS |
| 1 | `grep -nE "/download/cog['\"]" frontend/src/components/import/JobProgress.tsx` | zero lines | (no match) | PASS |
| 2 | `frontend/src/api/_presignedUpload.ts` exists | true | true | PASS |
| 2 | `grep -nE "export (async function\|const) uploadChunks" frontend/src/api/_presignedUpload.ts` | one line | `26:export async function uploadChunks(` | PASS |
| 2 | `grep -n "from './_presignedUpload'" frontend/src/api/ingest.ts` | one line | `2:import { uploadChunks } from './_presignedUpload';` | PASS |
| 2 | `grep -n "from './_presignedUpload'" frontend/src/api/datasets.ts` | one line | `3:import { uploadChunks } from './_presignedUpload';` | PASS |
| 2 | `grep -cE "for \(.* (of urls\|i < urls.length\|presignedUrl)" frontend/src/api/ingest.ts` | 0 | 0 | PASS |
| 2 | `grep -cE "for \(.* (of urls\|i < urls.length\|presignedUrl)" frontend/src/api/datasets.ts` | 0 | 0 | PASS |
| 3 | `frontend/src/api/_presignedUpload.test.ts` exists | true | true | PASS |
| 3 | `grep -cE "describe\|test\(\|it\(" frontend/src/api/_presignedUpload.test.ts` | >= 3 | 6 | PASS |
| 3 | `cd frontend && npx vitest run src/api/_presignedUpload.test.ts` | exit 0 | 5/5 tests pass, exit 0 | PASS |
| all | `cd frontend && npx tsc -b` for touched files only | 0 errors in touched files | 0 errors | PASS |
| all | Regression: `npx vitest run src/api src/components/import` | All pass | 117/117 tests across 15 files | PASS |

Regression-test command:

```
cd frontend && npx vitest run src/api/_presignedUpload.test.ts src/api src/components/import
```

Output: `Test Files  15 passed (15) | Tests  117 passed (117)`.

## Issues Encountered

None. The two loops were genuinely identical, the plan signature mapped cleanly to a minimal helper, and the existing vitest fetch-mocking pattern at `src/api/__tests__/client.test.ts` ported directly to the new test file.

## Backward Compatibility Note

Both changes are pure internal refactors with zero observable behavior change from the UI:

- **`getCogDownloadUrl`:** the URL produced is bit-identical to the pre-refactor literal (`/api/datasets/${id}/download/cog`).
- **`uploadChunks`:** the network sequence is unchanged — same PUTs to the same URLs in the same order with the same body slices. The error message format (`"S3 part N upload failed: STATUS"`) is preserved verbatim.

No frontend API contract changes. No new dependencies. No environment variables.

## User Setup Required

None.

## Next Phase Readiness

- ING-01 / P2-01 and ING-05 / P2-05 closed; both deferred items from the Phase 1072 audit are now landed.
- Plan 1077-02 is the close-gate plan — verifying the two requirements are marked complete and the phase ships clean.
- Future work that can now land in one place:
  - Retry-on-ETag-mismatch / exponential backoff / abort signal on the chunked upload — single edit site in `_presignedUpload.ts`.
  - Centralised dataset-route URL builder — broader refactor, separate scope.

## Self-Check

PASSED — see verification table above.

- `frontend/src/api/datasets.ts` — present, contains `getCogDownloadUrl` (line 64) and `import { uploadChunks } from './_presignedUpload'` (line 3).
- `frontend/src/api/ingest.ts` — present, contains `import { uploadChunks } from './_presignedUpload'` (line 2), no inline loop.
- `frontend/src/api/_presignedUpload.ts` — present, exports `uploadChunks` (line 26).
- `frontend/src/api/_presignedUpload.test.ts` — present, 90 lines, 5 tests pass.
- `frontend/src/components/import/JobProgress.tsx` — present, calls `getCogDownloadUrl(datasetId)` at line 42; no `/download/cog` string literal remains.
- Task commits `8c69f1e4`, `8fa5ba1d`, `0d24d39f` — all present in `git log --oneline -5`.

## Threat Flags

None — no new security-relevant surface. The refactor produces bit-identical network behavior. Presigned URLs continue to be PUT'd via plain `fetch` (no Authorization header leak to S3) and the COG download URL helper composes the same `/download/cog` path that the audit (P0-01 / KNOWN-01) already certified end-to-end through the download-token flow.

---
*Phase: 1077-frontend-ingest-p2-closure*
*Plan: 01*
*Completed: 2026-05-21*
