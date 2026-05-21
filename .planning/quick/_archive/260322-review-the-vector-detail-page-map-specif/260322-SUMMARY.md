---
phase: 260322
plan: 01
subsystem: dataset-map
tags: [review, maplibre, terra-draw, vector-editing, qa]

provides:
  - live verification of point/line/polygon edit affordances
  - backend/frontend trace of the feature editing path
  - identified correctness gaps in vector detail page editing
affects: [DatasetMap, use-feature-editing, use-terra-draw, features API, tests]

key-files:
  created:
    - .planning/quick/260322-review-the-vector-detail-page-map-specif/260322-CONTEXT.md
    - .planning/quick/260322-review-the-vector-detail-page-map-specif/260322-RESEARCH.md
    - .planning/quick/260322-review-the-vector-detail-page-map-specif/260322-PLAN.md
    - .planning/quick/260322-review-the-vector-detail-page-map-specif/260322-SUMMARY.md
    - .planning/quick/260322-review-the-vector-detail-page-map-specif/260322-VERIFICATION.md

metrics:
  completed: 2026-03-20
---

# Quick Task 260322 Summary

## Outcome

The vector detail page map editing stack is **not safe to sign off as correct and complete**.

The live affordances are mostly working:

- Polygon datasets expose polygon, rectangle, circle, and freehand editing.
- Line datasets expose only line editing.
- Point datasets expose only point editing.
- Feature selection on the live polygon page enters edit mode and exposes save/cancel/attribute/delete actions.

But the core persistence path has a serious correctness flaw for multi-part geometries:

- `frontend/src/hooks/use-terra-draw.ts` converts all multi-part geometries to single-part geometry for editing.
- `frontend/src/hooks/use-feature-editing.ts` always uses that simplified geometry when a feature is selected from the map.
- `backend/app/features/service.py` explicitly accepts `Polygon` into `MULTIPOLYGON`, `LineString` into `MULTILINESTRING`, and `Point` into `MULTIPOINT`, then writes it directly to the database.

That means editing a multi-part feature can silently discard every part except the first one.

## Findings

1. **High severity:** multi-part feature edits are destructive.
   `MultiPolygon`, `MultiLineString`, and `MultiPoint` are downgraded before editing and can be saved back as single-part geometry.

2. **Medium severity:** the current automated coverage is not strong enough to justify high confidence in the real edit stack.
   The key tests mock `MapLibre`, `useTerraDraw`, or `DatasetMap`, so the actual map selection and persistence path is largely untested.

3. **Medium severity:** the existing dataset-detail Playwright suite is stale and fails before it reaches the detail page.
   This removes the only plausible end-to-end safety net for detail-page editing regressions.

## Verification Notes

- Targeted frontend tests passed: 46/46.
- Live browser verification passed for geometry-specific toolbar affordances on point/line/polygon datasets.
- Existing Playwright dataset-detail coverage failed due outdated selectors, not map logic.
- In-app route-to-route navigation requested fresh vector tiles, so dataset switching itself does not appear to be the current blocker.

## Recommendation

Do not claim the vector detail map editing flow is correct, complete, or best-practice compliant until:

1. Multi-part editing is either made safe or explicitly blocked.
2. Real end-to-end edit flows are covered with non-mocked browser tests.
3. The stale dataset-detail Playwright suite is repaired so it can catch regressions again.
