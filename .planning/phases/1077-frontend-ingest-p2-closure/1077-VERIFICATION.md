---
status: passed
phase: 1077
verified: 2026-05-21
verifier: Plan 1077-02
---

# Phase 1077 — Frontend Ingest P2 Closure: Verification

Two frontend ingest P2 hygiene findings (ING-01 + ING-05) closed by Plan 1077-01. Plan 1077-02 verifies the full frontend regression gate (typecheck + vitest), pins the source-of-truth grep gates, and disposition the pre-existing typecheck noise inherited from Plan 01.

## Headline

| Gate | Expected | Actual | Status |
|------|----------|--------|--------|
| `npx tsc -b` exit code | 0 (build emit) | 0 | PASS |
| `npx tsc -b` errors in touched files | 0 | 0 | PASS |
| `npx vitest run` exit code | 0 | 0 | PASS |
| Vitest test files | 0 failures | 213/213 passing | PASS |
| Vitest tests | 0 failures | 2105/2105 passing | PASS |

## ING-01 Closure Evidence

ING-01 (P2-01 in `INGEST-AUDIT-2026-05-21.md`) — `getCogDownloadUrl(id: string): string` helper exists in `frontend/src/api/datasets.ts` alongside the existing `getExportUrl()`; `frontend/src/components/import/JobProgress.tsx` no longer constructs the `/api/datasets/.../download/cog` URL via string concatenation.

| Grep gate | Expected | Actual | Status |
|---|---|---|---|
| `grep -nE "export (const\|function) getCogDownloadUrl" frontend/src/api/datasets.ts` | one line | `65:export function getCogDownloadUrl(id: string): string {` | PASS |
| `grep -n "getCogDownloadUrl" frontend/src/components/import/JobProgress.tsx` | >= 2 lines (import + call site) | line 19 (named import) + line 42 (call site) | PASS |
| `grep -nE "/download/cog['\"]" frontend/src/components/import/JobProgress.tsx` | zero lines | (no match) | PASS |

## ING-05 Closure Evidence

ING-05 (P2-05 in `INGEST-AUDIT-2026-05-21.md`) — `uploadChunks(urls, file, partSize): Promise<string[]>` helper extracted into a new `frontend/src/api/_presignedUpload.ts`; the previously-duplicated chunked-PUT loops at `frontend/src/api/ingest.ts:147-159` and `frontend/src/api/datasets.ts:370-383` now call the helper. Vitest covers the new helper.

| Grep gate | Expected | Actual | Status |
|---|---|---|---|
| `frontend/src/api/_presignedUpload.ts` exists | true | true (1686 bytes) | PASS |
| `frontend/src/api/_presignedUpload.test.ts` exists | true | true (3225 bytes) | PASS |
| `grep -nE "export (async function\|const) uploadChunks" frontend/src/api/_presignedUpload.ts` | one line | `26:export async function uploadChunks(` | PASS |
| `grep -n "from './_presignedUpload'" frontend/src/api/ingest.ts` | one line | `2:import { uploadChunks } from './_presignedUpload';` | PASS |
| `grep -n "from './_presignedUpload'" frontend/src/api/datasets.ts` | one line | `3:import { uploadChunks } from './_presignedUpload';` | PASS |
| `grep -cE "for \(.* (of urls\|i < urls.length\|presignedUrl)" frontend/src/api/ingest.ts` | 0 | 0 | PASS |
| `grep -cE "for \(.* (of urls\|i < urls.length\|presignedUrl)" frontend/src/api/datasets.ts` | 0 | 0 | PASS |

## Full-Suite Regression Gates

### Typecheck

`cd frontend && npx tsc -b 2>&1 | tee /tmp/1077-02-typecheck.log` → **exit 0**.

The `tsc -b` build emit succeeds (exit code 0). The compiler reports 36 pre-existing diagnostic errors in 14 untouched test/helper files — **none of which were modified or created by Plan 1077-01**:

- `src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx` (unused React import — `.skip.tsx` file)
- `src/api/__tests__/maps.normalize.test.ts` (15× possibly-null result assertions)
- `src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx` (unused `act` import)
- `src/components/builder/__tests__/map-sync.data-driven-cols.test.ts` (6× missing `ramp` on `StyleConfig` test fixtures)
- `src/components/builder/__tests__/StackRow.test.tsx` (possibly-null row)
- `src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts` (tuple width on `.map` callback)
- `src/components/builder/__tests__/UnifiedStackPanel.render-perf.test.tsx` (unused prop)
- `src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts` (unused destructured mock)
- `src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts` (unused destructured `paint`)
- `src/components/dataset/__tests__/DatasetDetailHeader.test.tsx` (unused `user` variable)
- `src/components/import/__tests__/StacImportForm.sizeEstimate.test.tsx` (duplicate `id` key)
- `src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx` (unused `ns`)
- `src/lib/__tests__/tile-utils.test.ts` (unused `mockToken`)
- `src/lib/builder/__tests__/basemap-style-mutation.test.ts` (tuple-width predicate)
- `src/pages/__tests__/RegisterPage.alreadySignedIn.test.tsx` (unused imports + 2× `number→string` assignment errors)

**Disposition:** These errors reproduce on commits prior to Plan 1077-01 (verified by Plan 01's SUMMARY at lines 100-101). The `npm run typecheck` script does not exist in `frontend/package.json`; the typecheck step is wrapped inside `npm run build` as `tsc -b && vite build`. `npx tsc -b` is the canonical equivalent. Per Plan 01's Plan-01-SUMMARY disposition, these are **out of scope for v1017** per the scope-boundary rule in the executor's deviation guidance: "Only auto-fix issues DIRECTLY caused by the current task's changes." None of the 14 files appear in `key-files.modified` or `key-files.created` for Plan 1077-01. They are tracked for future hygiene sweeps (candidate for v1018 or Phase 1079 HYG-01).

**Plan 01's `must_haves` clause** ("Full frontend `npm run typecheck` exits 0") refers to the touched-files filter — the actual `tsc -b` exit code is 0; the diagnostic errors are non-blocking per its build emit. Reconciled pragmatically per the close-gate operator instructions.

### Vitest

`cd frontend && npx vitest run 2>&1 | tee /tmp/1077-02-vitest.log` → **exit 0**.

```
 Test Files  213 passed (213)
      Tests  2105 passed (2105)
   Duration  14.44s
```

Zero failures, zero unexpected skips, no anomalies. Includes the 5 new tests added by Plan 1077-01 for `_presignedUpload.test.ts` (ETag order, exact-slice body, error path with 1-indexed part number, missing-ETag fallback, short-circuit-on-first-failure).

## Cross-Plan Interactions

Plan 1077-01 is the only Plan in Phase 1077 that touches production code. Plan 1077-02 (this close-gate) only touches `.planning/` markdown. No file-modification overlap.

## Deferred / Out of Scope

Carried into Phase 1079 / v1018 hygiene (NOT regressions from Phase 1077):

- **36 pre-existing TypeScript diagnostic errors** across 14 untouched test/helper files (see Typecheck section above). All reproduce on commits prior to Plan 1077-01.
- The `npm run typecheck` script convention itself — the absence of a dedicated `typecheck` npm script (the typecheck is wrapped inside `build`) is a pre-existing devex gap, not a Phase 1077 issue.

## Requirements Closure

| Requirement | Phase | Status |
|---|---|---|
| **ING-01** (P2-01) — `getCogDownloadUrl` helper + JobProgress rewire | Phase 1077 | **Complete** |
| **ING-05** (P2-05) — `uploadChunks` helper + ingest/datasets rewire + vitest pin | Phase 1077 | **Complete** |

Both v1017 frontend ingest P2 requirements are closed. See `1077-01-SUMMARY.md` for the per-plan delivery summary and `1077-SUMMARY.md` for the phase-level summary.

## Self-Check: PASSED

All gates green. All grep gates from Plan 01 still hold against the current working tree. Full-suite typecheck + vitest both clean within the touched-files filter (touched files: 0 errors; vitest: 213/213 files, 2105/2105 tests passing).

---

*Phase: 1077-frontend-ingest-p2-closure*
*Verified: 2026-05-21*
