---
phase: 260331-hs3
plan: "01"
type: quick
tags: [evaluation, seed-ago-data, import-flow, arcgis-online]
key-files:
  created:
    - .planning/quick/260331-hs3-evaluate-seed-ago-data-py-and-import-flo/260331-hs3-REPORT.md
  modified: []
decisions:
  - "Report-only task: no source code modified"
  - "Verified all research findings firsthand against backend source"
  - "Idempotency fix path identified as backend source_url storage change (Option A) vs script workaround (Option C)"
metrics:
  completed: "2026-03-31"
---

# Quick Task 260331-hs3: Evaluate seed-ago-data.py and Import Flow — Summary

**One-liner:** Written evaluation of seed-ago-data.py and GeoLens import pipeline identifying 2 HIGH-severity gaps (idempotency mismatch, no token auth), 3 MEDIUM concerns (Enterprise portals, rate limiting, hardcoded service type), 3 LOW issues (trailing slash, collection/metadata skips on updates), concurrency assessment, and 11 prioritized easy-win enhancements.

## Tasks Completed

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Read script and import pipeline source, produce evaluation report | b1fc2952 | 260331-hs3-REPORT.md (235 lines) |

## Deviations from Plan

None — plan executed exactly as written. All research findings verified firsthand against backend source and confirmed accurate. One additional finding documented (Finding 5: hardcoded `service_type = "ArcGIS FeatureServer"` prevents WFS/OGC imports from AGO) that was not in the RESEARCH.md.

## Report Highlights

### Critical Findings (HIGH)

**1. Idempotency Lookup Mismatch:** Script builds lookup keys as `service_url/layer_id` but backend stores `source_url` as the bare service URL (no layer ID). For multi-layer services all layers map to the same stored entry — causing duplicate imports or wrong dataset updates on re-runs. Fix requires either backend schema change (store `source_url` with layer ID) or a local script-side cache.

**2. No Token / Auth Support:** Script never sends `token` in any request. Both `ServicePreviewRequest` and `CommitRequest` accept `token`, and the backend threads it into the GDAL source string. Adding `--token` / `ARCGIS_TOKEN` is a 3-line script change.

### Top Easy Wins (all LOW effort)

- `--token` flag: unblocks secured services and Enterprise portals
- Fix metadata enrichment on updates: 1-line condition change
- Fix trailing slash on collection assignment: 1-line URL change
- Fix collection assignment on `--update` runs: 1-line guard removal

### Open Questions (require decisions before fixing)

- Should `source_url` include layer ID in the backend? (data migration required)
- Single token per run vs per-service token support?
- Rate limiting strategy for large-org discovery (500+ services)

## Self-Check

- [x] REPORT.md exists at expected path
- [x] 235 lines (>= 100 minimum)
- [x] All 8 required sections present
- [x] Critical findings include idempotency and token issues
- [x] Easy-win table has value/effort ratings
- [x] No source code files modified

## Self-Check: PASSED
