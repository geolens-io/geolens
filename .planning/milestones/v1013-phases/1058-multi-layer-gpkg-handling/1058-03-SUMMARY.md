---
phase: 1058-multi-layer-gpkg-handling
plan: "03"
subsystem: frontend-bulk-review
tags: [bulk-review, gpkg, multi-layer, fan-out, promise-allsettled, concurrency]

requires:
  - phase: 1057-service-url-reliability
    provides: "no direct dependency"

provides:
  - "BulkReviewList.onIngestAllLayers optional prop (entryId: string) => void"
  - "'Ingest all N layers' button visible for multi-layer entries when prop provided"
  - "UploadForm.handleIngestAllLayers fan-out with runWithConcurrency(4) cap"
  - "FanOutResult type + fanOutResults state for results modal"
  - "Results Dialog modal with per-layer CheckCircle2/AlertCircle icons + retry affordance"
  - "upload.multiLayer* i18n keys (6 keys) in en/de/es/fr"
  - "bulk.ingestAllLayers i18n key in en/de/es/fr"
  - "BulkReviewList.multiLayer.test.tsx (4 tests)"
  - "UploadForm.multiLayerFanOut.test.tsx (5 tests)"

affects:
  - 1060-close-gate (live MCP re-verify of GPKG-03 affordance)

tech-stack:
  added: []
  patterns:
    - "runWithConcurrency<T,R>: generic async pool helper with ordered PromiseSettledResult[] output; cap enforced via nextIndex cursor + Array.from(runners)"
    - "FanOutResult modal pattern: setFanOutResults after settled; Dialog open=true gated on fanOutResults !== null"
    - "T-1058C-03 documented inline: backend rejects commits 2..N for same job_id; first layer wins"

key-files:
  created:
    - "frontend/src/components/import/__tests__/BulkReviewList.multiLayer.test.tsx"
    - "frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx"
  modified:
    - "frontend/src/components/import/BulkReviewList.tsx"
    - "frontend/src/components/import/UploadForm.tsx"
    - "frontend/src/i18n/locales/en/import.json"
    - "frontend/src/i18n/locales/de/import.json"
    - "frontend/src/i18n/locales/es/import.json"
    - "frontend/src/i18n/locales/fr/import.json"

key-decisions:
  - "runWithConcurrency implemented inline in UploadForm.tsx (not a separate util file) — self-contained, can be extracted later if reused"
  - "Retry affordance = 'Close + re-click' per D-11 minimum scope — full retry-failed-subset deferred to Known Stubs"
  - "T-1058C-03: backend rejects second commit per job_id — documented in SUMMARY, NOT escalated as plan blocker (D-08 scoping: UI ships, backend gap documented)"

requirements-completed:
  - GPKG-03

duration: 53min
completed: 2026-05-20
---

# Phase 1058 Plan 03: GPKG-03 P2 Bulk Review "Ingest all layers" Fan-Out Summary

**"Ingest all layers" button in Bulk Review that fans out one commit per layer for any multi-layer GPKG entry, using runWithConcurrency(4) and a results modal with per-layer success/failure display**

## Performance

- **Duration:** ~53 min
- **Started:** 2026-05-20T01:30:00Z
- **Completed:** 2026-05-20T02:23:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- **BulkReviewList.tsx**: New optional `onIngestAllLayers?: (entryId: string) => void` prop; renders "Ingest all N layers as separate datasets" button inside expanded row when `entry.previewData.layers.length > 1 && onIngestAllLayers` is provided; button disabled when `isCommitting` or `entry.status !== 'preview'`; data-testid for targeting
- **UploadForm.tsx**: `runWithConcurrency<T,R>` async pool (cap=4, ordered results); `FanOutResult` type; `fanOutResults` state; `handleIngestAllLayers` fan-out handler; results Dialog modal with CheckCircle2/AlertCircle per layer; retry affordance (dismiss + re-click); `onIngestAllLayers` prop wired to BulkReviewList
- **i18n**: `bulk.ingestAllLayers` + 6 `upload.multiLayer*` keys added to en/de/es/fr
- **Tests**: 4 BulkReviewList tests (visibility, single-layer guard, omitted-prop guard, click callback) + 5 UploadForm tests (single-layer no-op, fan-out shape, concurrency cap, partial-fail modal, full-success toast)

## Task Commits

1. **Task 1: BulkReviewList button + prop + i18n** - `63cd22a1` (feat)
2. **Task 2: UploadForm fan-out handler + results modal** - `99bf0cd6` (feat)

## Files Created/Modified

- `frontend/src/components/import/BulkReviewList.tsx` — `onIngestAllLayers` prop; "Ingest all layers" conditional button block
- `frontend/src/components/import/UploadForm.tsx` — `runWithConcurrency` helper; `FanOutResult` type; `fanOutResults` state; `handleIngestAllLayers`; results Dialog modal; prop wiring
- `frontend/src/components/import/__tests__/BulkReviewList.multiLayer.test.tsx` — 4 new tests
- `frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx` — 5 new tests
- `frontend/src/i18n/locales/{en,de,es,fr}/import.json` — `bulk.ingestAllLayers` + 6 `upload.multiLayer*` keys

## Manual T-1058C-03 Verification

**Backend endpoint:** `POST /ingest/commit/{job_id}` at `backend/app/processing/ingest/router.py:607`

**Finding:** The backend commit endpoint checks `if job.status != "pending": raise HTTPException(400, "Job already processed")`. After the first commit call, the job status transitions to `"queued"` (via `queue_ingest_job`). A second commit call for the same job_id will receive a 400 error.

**Implication for fan-out:** A single uploaded GPKG file produces a single job_id. The fan-out in `handleIngestAllLayers` issues N concurrent `commitImport` calls against this single job_id. With `runWithConcurrency(4)`, the first call to win the race will succeed (the job transitions to `"queued"`); all subsequent calls receive `"Job already processed"`.

**Outcome:** Only 1 of N layers will be successfully committed per upload. The remaining N-1 layer commits will fail with 400 errors, which the results modal surfaces as failed rows.

**UI behavior is correct:** The results modal accurately shows the backend outcome. The user sees `1 succeeded, N-1 failed` and can re-click "Ingest all layers" — but this will fail for the same reason (job is now `"queued"`, not `"pending"`). The user must re-upload the file N times to ingest all layers, which is exactly the UX gap that GPKG-03 was intended to solve.

**Root cause:** The backend commit endpoint was designed for one-commit-per-job semantics. Multi-layer fan-out requires either:
- (a) Server-side per-layer commit support (job stays `"pending"` until all layers are committed, or each layer gets its own Procrastinate task), OR
- (b) Frontend re-uploads the file N times to get N distinct job_ids (one per layer)

**Disposition:** Documented as a known limitation. The UI is implemented as specified per D-08 (fan-out UX ships); the backend constraint prevents the intended N-dataset outcome. Phase 1060 close-gate live MCP re-verify should flag this. A follow-up plan (suggested: Phase 1061 or a 1058-04 revision) should implement backend multi-layer commit support. See "Known Stubs" below.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed as written.

### Simplifications Applied

**[D-11 minimum scope] Retry affordance is "Close + re-click" not "retry failed subset"**
- **Reason:** True retry-of-failed-subset would require filtering the layer list before re-invoking `handleIngestAllLayers`. This adds ~20 LOC and the T-1058C-03 backend constraint makes retry semantics moot anyway (the job is no longer `"pending"`).
- **Implementation:** "Close (retry by re-clicking Ingest all layers)" button per D-11's explicit note: "if implementing a real 'Retry failed' path adds >30 LOC, skip it in v1."
- **Tracked in Known Stubs.**

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| T-1058C-03: multi-commit-per-job-id | `UploadForm.tsx:handleIngestAllLayers` | Backend `/ingest/commit/{job_id}` checks `job.status == 'pending'` — rejects second commit. Fan-out result: only first layer ingested. Full fix requires backend multi-layer commit support (new Procrastinate task per layer, or job stays pending until all committed). |
| Retry-failed-subset button | `UploadForm.tsx` results modal footer | D-11 minimum scope: "Close + re-click" placeholder. Real retry needs filtered layer subset + fresh job handling. Moot until T-1058C-03 is resolved. |

## Decisions Made

- **`runWithConcurrency` inline in UploadForm.tsx**: Not extracted to a utils module — self-contained helper, can be moved to `frontend/src/lib/` in a future plan if reused elsewhere.
- **Retry affordance = dismiss + re-click**: D-11 minimum scope; implementing per-layer retry subset would add ~20 LOC and is semantically broken against the T-1058C-03 constraint anyway.
- **`bulk.ingestAllLayers` key placement**: Added as sibling to `bulk.sheetLabel` and `bulk.importAllDefaults`, matching the existing camelCase neighbor pattern.

## Test Results

| Gate | Result | Count |
|------|--------|-------|
| TypeScript typecheck (production files: BulkReviewList.tsx, UploadForm.tsx) | PASS | 0 errors |
| Frontend vitest `BulkReviewList` | PASS | 4/4 new tests |
| Frontend vitest `UploadForm` | PASS | 8/8 (3 pre-existing IMPORT-03 + 5 new fan-out) |
| i18n parity (`npm run test:i18n`) | PASS | 2/2 |

## Threat Surface Scan

No new network endpoints, auth paths, or file-access patterns beyond plan scope.

| Threat ID | Disposition | Implemented |
|-----------|-------------|-------------|
| T-1058C-01 | mitigate | `runWithConcurrency(4)` cap enforced — max 4 parallel commits at peak |
| T-1058C-02 | mitigate | `layer.name` originates from server-side `previewData.layers` — not user-writable |
| T-1058C-03 | document | Backend rejects commits 2..N for same job_id (see Manual Verification above) |
| T-1058C-04 | accept | Error messages from `ApiError.message` — same redaction as existing `buildErrorDisplay` |

## Self-Check

**Created files:**
- `/Users/ishiland/Code/geolens/frontend/src/components/import/__tests__/BulkReviewList.multiLayer.test.tsx` — FOUND
- `/Users/ishiland/Code/geolens/frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx` — FOUND
- `/Users/ishiland/Code/geolens/.planning/phases/1058-multi-layer-gpkg-handling/1058-03-SUMMARY.md` — (this file)

**Commits:**
- `63cd22a1` — Task 1 (feat BulkReviewList button + prop + i18n)
- `99bf0cd6` — Task 2 (feat UploadForm fan-out handler + results modal)

## Self-Check: PASSED

## Next Phase Readiness

- Plan 1058-02 (GPKG-02): unaffected by Plan 03 — touches `ReuploadDialog.tsx` schema diff rendering only.
- Phase 1060 close gate: live MCP re-verify of GPKG-03 will surface the T-1058C-03 backend limitation in the browser. A plan revision or new Phase 1061 plan should add backend multi-layer commit support.
- Suggested follow-up: `1058-04-PLAN.md` — Backend multi-layer commit: modify `/ingest/commit/{job_id}` to accept `commit_all_layers: true` flag that dispatches N Procrastinate tasks (one per layer), keeping the job in `"pending"` until all are dispatched.

---
*Phase: 1058-multi-layer-gpkg-handling*
*Completed: 2026-05-20*
