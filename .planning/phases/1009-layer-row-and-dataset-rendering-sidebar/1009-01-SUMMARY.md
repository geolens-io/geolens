# Phase 1009 Plan 01 Summary

**Completed:** 2026-05-12
**Requirements:** STACK-01, STACK-02, STACK-03, STACK-04, STACK-05

## What Changed

- Kept the existing system groups: `surface`, `relief`, `basemap`, `data`, `labels`, and `interactions`.
- Extended stack entry metadata with existing `dataset_feature_count` so data headers can render current API metadata without schema changes.
- Updated primary layer rows with the v1 row controls:
  - drag handle
  - visibility toggle
  - type swatch
  - display name
  - display-only `as <renderAs>` control
  - row opacity control
  - zoom-range control
  - existing inspector and overflow actions
- Added data-group dataset-rendering headers for datasets with two or more renderings, including dataset name, record type, geometry type, feature count, and `N renderings`.
- Wired row opacity and zoom controls to existing builder handlers. Zoom range preserves existing layout keys and writes `_minzoom` / `_maxzoom`.

## Boundaries Preserved

- No backend schema/API changes, migrations, or persisted group model.
- No renderAs mutation dispatch yet; that remains Phase 1010.
- No LIVE/status badge is rendered because the current layer/search response does not provide a supporting field.
- UI uses existing shadcn/Radix/Tailwind primitives and lucide icons.

## Verification

- `cd frontend && npm run test -- MapStackPanel map-stack renderAs --run` — passed, 3 files / 25 tests.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed.

## Handoff

Phase 1010 can wire the existing `renderAs` display control into mutation dispatch and add duplicate-rendering actions. The row contract and dataset-rendering header behavior are now covered by component tests.
