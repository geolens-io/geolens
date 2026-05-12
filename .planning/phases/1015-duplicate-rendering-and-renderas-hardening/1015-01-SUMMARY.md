---
phase: 1015-duplicate-rendering-and-renderas-hardening
plan: 01
status: complete
completed: 2026-05-12
requirements: [DUP-01, DUP-02, DUP-03, DUP-04, DUP-05]
commits:
  - d1e2055e test(1015): cover duplicate rendering browser flows
---

# Phase 1015 Summary: Duplicate Rendering And RenderAs Hardening

## Completed

- Added a browser-level builder smoke flow for duplicate renderings:
  - Duplicates the current map layer from the layer-row overflow menu.
  - Confirms the backend creates a sibling `MapLayer` with the same `dataset_id`, a distinct layer id, and copied style fields.
  - Confirms the dataset-rendering header updates to `2 renderings`.
  - Opens Add Dataset, uses `another rendering`, and confirms the backend count/header update to `3 renderings`.
  - Confirms no error toasts appear.
- Kept renderAs and unsupported-renderer coverage in focused unit/component tests rather than expanding browser scope for every render mode.

## Requirement Coverage

- **DUP-01:** Covered by `e2e/builder.spec.ts` row overflow `Duplicate rendering` flow.
- **DUP-02:** Covered by `e2e/builder.spec.ts` Add Dataset modal `another rendering` flow.
- **DUP-03:** Covered by the same browser flow plus `MapStackPanel.test.tsx`; dataset-rendering header counts update to 2 and 3.
- **DUP-04:** Covered by `renderAs.test.ts` and `use-builder-layers.test.ts`; renderAs patches use existing writable fields and do not write `is_3d`.
- **DUP-05:** Covered by `renderAs.test.ts` supported/punted option checks.

## Verification

- `npx playwright test e2e/builder.spec.ts --project=chromium -g "duplicates dataset renderings"`
  - Result: passed — setup + focused duplicate-rendering test, 2 total.
- `cd frontend && npm run test -- DatasetSearchPanel MapStackPanel map-stack renderAs use-builder-layers --run`
  - Result: passed — 5 files, 61 tests.
- `npm run e2e:smoke:builder`
  - Result: passed — 23 tests.

## Notes

- No schema, renderer, catalog API, or import workflow changes were made.
- No new renderAs options were introduced.
