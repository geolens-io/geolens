---
phase: 1077-frontend-ingest-p2-closure
completed_at: 2026-05-21
requirements: [ING-01, ING-05]
plans_completed: 2
verdict: PASS
tests_run: 2105
tests_passed: 2105
tests_failed: 0
tests_skipped: 0
duration_minutes: ~10 (cumulative across 2 plans)
---

# Phase 1077 — Frontend Ingest P2 Closure

**Closed 2 frontend ingest P2 drift-risk findings from `INGEST-AUDIT-2026-05-21.md` (deferred from v1015 / v1016 per Phase 1073 remediation plan); 2105/2105 full vitest suite passing; zero behavior change observable from the UI.**

## Summary

Phase 1077 closes the frontend ingest P2 tail of v1017 — two surgical helper extractions that centralize drift-prone URL construction and the previously-duplicated chunked-PUT loop so future retry / abort / backoff work lands in a single edit site:

- **ING-01 (P2-01)** — Added `getCogDownloadUrl(id: string): string` helper to `frontend/src/api/datasets.ts` (line 65) next to the existing `getExportUrl()`. `frontend/src/components/import/JobProgress.tsx:42` no longer constructs the `/api/datasets/.../download/cog` URL by inline string concatenation; it calls the helper and prepends `window.location.origin` for the clipboard write. The path returned by the helper is bit-identical to the pre-refactor literal (`/api/datasets/${id}/download/cog`).

- **ING-05 (P2-05)** — Extracted `uploadChunks(urls, file, partSize): Promise<string[]>` helper into a new `frontend/src/api/_presignedUpload.ts`. Both `frontend/src/api/ingest.ts:147-159` (the `uploadPresigned()` flow) and `frontend/src/api/datasets.ts:370-383` (the `reuploadPresigned()` flow) now import and call it; the inline `for (let i = 0; ...)` loops are gone. 5 new vitest tests at `frontend/src/api/_presignedUpload.test.ts` pin ETag order, exact-slice body verification, error path with 1-indexed part number, missing-ETag fallback, and short-circuit-on-first-failure behavior.

Both items were pure internal refactors with zero observable behavior change from the UI: the URL produced by `getCogDownloadUrl` is bit-identical to the pre-refactor literal, and the network sequence emitted by `uploadChunks` (same PUTs to the same URLs in the same order with the same body slices) is preserved. No frontend API contract changes, no new dependencies, no environment variables.

## Plan References

- [Plan 01 — ING-01 + ING-05 helper extraction](1077-01-SUMMARY.md) (~6 min, 3 commits)
- Plan 02 — Phase verification + close-gate (this file; commits to follow)

## Production-Code Files Touched

- `frontend/src/api/datasets.ts` — added `getCogDownloadUrl(id)` immediately after `getExportUrl()` (lines 63-66); added `import { uploadChunks } from './_presignedUpload'`; replaced the 11-line chunked-PUT loop at the bottom of `reuploadPresigned()` with two lines (`const etags = await uploadChunks(...)`; `const completedParts = etags.map(...)`) (ING-01 + ING-05).
- `frontend/src/api/ingest.ts` — added `import { uploadChunks } from './_presignedUpload'`; replaced the 11-line chunked-PUT loop at the bottom of `uploadPresigned()` with the same two-line shape (ING-05).
- `frontend/src/components/import/JobProgress.tsx` — added `getCogDownloadUrl` to the existing `from '@/api/datasets'` named import; line 42 clipboard handler now reads ``${window.location.origin}${getCogDownloadUrl(datasetId)}`` instead of the literal ``${window.location.origin}/api/datasets/${datasetId}/download/cog`` (ING-01).
- `frontend/src/api/_presignedUpload.ts` (new, 47 lines including JSDoc) — `uploadChunks(urls, file, partSize): Promise<string[]>`; plain `fetch` (not `apiFetch`) per presigned-URL V4 signing requirement; empty-string ETag fallback preserved (ING-05).

## Tests Added

- `frontend/src/api/_presignedUpload.test.ts` — **90 LOC**, 5 vitest tests using the `globalThis.fetch = vi.fn()` pattern from `src/api/__tests__/client.test.ts`. Pins:
  - ETag order via two-PUT roundtrip
  - Exact-slice body verification at chunk boundaries
  - Error path: 4xx response throws with 1-indexed part number in the message
  - Missing-ETag header fallback to empty string (MinIO compatibility)
  - Short-circuit on first failure (no PUT to subsequent URLs after error)

**Test artifact totals:** 1 new file (90 LOC), 5 new test methods. No existing test files were modified.

## Cross-Plan Interactions

Phase 1077 has only one production-code plan (Plan 01); Plan 02 is the close-gate and touches only `.planning/` markdown. No cross-plan file overlap. The full frontend vitest suite (213 test files, 2105 tests) passes cleanly under `npx vitest run` — the 5 new `_presignedUpload` tests sit alongside the 2100 pre-existing tests with zero regression.

## Verification

See [1077-VERIFICATION.md](1077-VERIFICATION.md) for the full test evidence trail.

**Headline:** 2105/2105 vitest tests passing across 213 test files; `tsc -b` exits 0; zero errors in any of Plan 01's 5 touched/created files. All grep gates green:

- ING-01: `getCogDownloadUrl` exported (`datasets.ts:65`), imported (`JobProgress.tsx:19`), called (`JobProgress.tsx:42`); zero `/download/cog` string literals remain in `JobProgress.tsx`.
- ING-05: `_presignedUpload.ts` + `_presignedUpload.test.ts` exist; `uploadChunks` exported (`_presignedUpload.ts:26`); imported by both `ingest.ts:2` and `datasets.ts:3`; zero remaining `for (... of urls)` / `for (... i < urls.length)` / `for (... presignedUrl)` loop patterns in either consumer.

## Deferred / Out of Scope

Per Plan 1077-02 VERIFICATION:

- **36 pre-existing TypeScript diagnostic errors** across 14 untouched test/helper files (`maps.normalize.test.ts`, `DatasetDetailHeader.test.tsx`, `RegisterPage.alreadySignedIn.test.tsx`, etc.) — reproduce on commits prior to Plan 1077-01 per the scope-boundary rule. Candidate for v1018 hygiene or Phase 1079 HYG-01 triage.
- **`npm run typecheck` script convention** — `frontend/package.json` does not expose a dedicated `typecheck` npm script; the typecheck is wrapped inside `build` as `tsc -b && vite build`. `npx tsc -b` was used as the canonical equivalent. Adding a top-level `typecheck` script is a pre-existing devex gap, not a Phase 1077 issue.
- **Retry / backoff / abort logic on `uploadChunks`** — out of scope per Phase 1077 context (the helper was extracted *first*; future v1018 / marketplace work adds the resilience). The future single-edit-site advantage is exactly what ING-05's drift-risk closure secures.

## Patterns Established

Documented at the per-plan level (`1077-01-SUMMARY.md`), summarized:

1. **Underscore-prefixed module name** (`_presignedUpload.ts`) — signals an internal API helper not intended as a public surface from `@/api/*`. Matches the convention used inside `src/api/` for cross-file helpers that shouldn't be re-exported from the main API surface.
2. **Helper returns minimal shape** — `uploadChunks` returns `string[]` (ETags in order); both call sites build the `{etag, part_number: i + 1}` object via `.map`. `part_number` is purely positional (1-indexed) and is part of the wire contract to the completion endpoint, not part of the chunked-PUT behavior. Helper has zero coupling to the backend's `CompletePresignedRequest` shape.
3. **Plain `fetch` (not `apiFetch`) inside the helper** — presigned URLs are V4-signed by the backend and reject extra Authorization headers. The pre-refactor loops both used plain `fetch` for this reason; the helper preserves that. Documented inline.
4. **Empty-string ETag fallback** — both pre-refactor loops had `resp.headers.get('ETag') ?? ''`. Some S3-compatible backends (notably MinIO under specific config) omit the ETag header on small chunks; the empty string lets `completePresignedUpload` decide whether to accept the part.
5. **Test file lives next to the helper** (`_presignedUpload.test.ts` sibling, not under `__tests__/`) — vitest discovers both; following the plan path makes the acceptance grep deterministic. Sibling-file shape is conventional for small "helper.ts + helper.test.ts" pairs.
6. **Helper returns a path, not a fully-qualified URL** — `getCogDownloadUrl(id)` returns `${API_BASE}/datasets/${id}/download/cog` matching the contract of the existing `getExportUrl()` helper. JobProgress clipboard call composes the full URL via `${window.location.origin}${getCogDownloadUrl(datasetId)}` — same pattern as the existing `downloadCog()` helper at `datasets.ts:129`. Centralising the path-portion is the drift-risk closure; the protocol+host concatenation is call-site responsibility.

## Next Phases

Phase 1077 → ✅ Complete. Two downstream conditions advance:

- **Phase 1078 — CI Alembic Clean-DB Upgrade Workflow** (CI-01): unchanged eligibility — independent of test infra and ingest work; can execute now or in parallel with downstream cleanup.
- **Phase 1079 — Close Gate + Hygiene** (TI-03, VG-01, HYG-01): gated on Phase 1075 + 1076 + 1077 + 1078. With Phase 1077 complete, three of four predecessors are now closed. The remaining gate is Phase 1078.

## Self-Check: PASSED

Verified post-write:

- `.planning/phases/1077-frontend-ingest-p2-closure/1077-VERIFICATION.md` — FOUND
- `.planning/phases/1077-frontend-ingest-p2-closure/1077-SUMMARY.md` — FOUND (this file)
- `.planning/phases/1077-frontend-ingest-p2-closure/1077-01-SUMMARY.md` — FOUND
- `.planning/STATE.md` — updated (Phase 1077 complete; completed_phases 3; percent 60)
- `.planning/ROADMAP.md` — updated (`- [x] **Phase 1077`; progress table `2/2 Complete 2026-05-21`)
- `.planning/REQUIREMENTS.md` — updated (ING-01 + ING-05 → Complete in traceability table; checkboxes flipped to `[x]`)
- 2105/2105 vitest tests pass (213 files)
- `npx tsc -b` exits 0 with zero errors in Plan 01's 5 touched/created files
- All ING-01 + ING-05 grep gates green

---

*Phase: 1077-frontend-ingest-p2-closure*
*Completed: 2026-05-21*
