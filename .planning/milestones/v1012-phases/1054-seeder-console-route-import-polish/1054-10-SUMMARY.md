---
phase: 1054-seeder-console-route-import-polish
plan: "10"
subsystem: ui
tags: [stac, import, wizard, size-estimate, i18n, formatBytes]

requires:
  - phase: 1054-seeder-console-route-import-polish
    plan: "09"
    provides: i18n import.json infrastructure already expanded with register block

provides:
  - "EW-05: STAC import wizard confirmation step with size estimate from file:size"
  - "data_asset_size_bytes field on StacItemSummary (backend adapter + Pydantic schema + TS type)"
  - "formatBytes unit tests (5 assertions: null/zero/KB/MB/GB)"
  - "StacImportForm 'confirm' step: size aggregate panel, back-to-selection, confirm-and-import flow"
  - "stac.confirm.* i18n keys in en/de/es/fr (14 keys per locale)"

affects:
  - stac-import-wizard
  - EW-05

tech-stack:
  added: []
  patterns:
    - "'Advance to confirm' interception: 'Import N items' sets step to 'confirm' rather than calling API directly; API call stays in handleImport, triggered from confirmation panel"
    - "Partial-unavailable size note: shown only when some (not all) items lack size data; all-null case shows sizeUnavailable without a 0 B total"

key-files:
  created:
    - frontend/src/components/import/__tests__/StacImportForm.sizeEstimate.test.tsx
  modified:
    - backend/app/modules/catalog/sources/adapters/stac.py
    - backend/app/modules/catalog/sources/stac_router.py
    - frontend/src/types/api.ts
    - frontend/src/lib/__tests__/format.test.ts
    - frontend/src/components/import/StacImportForm.tsx
    - frontend/src/i18n/locales/en/import.json
    - frontend/src/i18n/locales/de/import.json
    - frontend/src/i18n/locales/es/import.json
    - frontend/src/i18n/locales/fr/import.json

key-decisions:
  - "formatBytes already existed in format.ts — added tests only, no new helper needed"
  - "Confirm step renders as a separate branch before the loading-states branch to keep the flow linear and selection state preserved on Back"
  - "data_asset_size_bytes extracted with isinstance(x, int) guard in backend so float/string/null values from malformed manifests all become None"

patterns-established: []

requirements-completed:
  - EW-05

duration: 10min
completed: 2026-05-19
---

# Phase 1054 Plan 10: STAC Import Size-Estimate Confirmation Step Summary

**STAC import wizard gains a 'confirm' step that aggregates file:size from the STAC manifest, showing estimated total download size before committing to a potentially multi-GB fetch (EW-05)**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-19T21:47:00Z
- **Completed:** 2026-05-19T21:57:31Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 9

## Accomplishments

- Backend STAC adapter extracts `data_asset.get("file:size")` per the STAC File Info Extension; non-int values defensively coerced to None; field propagated to Pydantic schema and TypeScript type
- StacImportForm gains a `'confirm'` step between `'items'` and `'importing'`: aggregates bytes across selected items, shows partial-unavailable note when some (not all) items lack size, falls back to "Size unavailable" when all are null
- "Import N items" now routes through confirmation panel; "Back to selection" preserves selection state; "Confirm and Import" calls the unchanged `handleImport`
- 5 `formatBytes` unit tests added (formatBytes already existed in format.ts)
- 3 wizard-flow regression tests in `StacImportForm.sizeEstimate.test.tsx`
- `stac.confirm.*` i18n keys added to all 4 locales (en/de/es/fr)

## STAC Spec Reference

`file:size` is defined by the [STAC File Info Extension](https://github.com/stac-extensions/file). It carries the byte size of the asset as an integer. Not all STAC catalogs include it — the backend's `isinstance(data_asset_size_bytes, int)` guard and the frontend's `typeof i.data_asset_size_bytes === 'number'` filter both handle the absent case cleanly.

## Size-Unavailable Fallback Behavior

| Scenario | Confirmation panel shows |
|----------|--------------------------|
| All items have `file:size` | Total (e.g. `2.9 MB`) |
| Some items have `file:size` | Total of available bytes + partial note: "N items missing size info — total is a lower bound" |
| No items have `file:size` | "Size unavailable" (never "0 B") |

## Task Commits

1. **Task 1: Backend adapter + types + formatBytes tests** — `4e484cae` (feat)
2. **Task 2: Confirm wizard step + i18n** — `6960e652` (feat, bundled with prior docs commit by concurrent executor)

## Files Created/Modified

- `backend/app/modules/catalog/sources/adapters/stac.py` — extract `file:size` from primary data asset; isinstance guard; add to items dict
- `backend/app/modules/catalog/sources/stac_router.py` — add `data_asset_size_bytes: int | None` to `StacItemSummary` Pydantic model
- `frontend/src/types/api.ts` — add `data_asset_size_bytes: number | null` to `StacItemSummary` interface
- `frontend/src/lib/__tests__/format.test.ts` — add 5 `formatBytes` unit tests
- `frontend/src/components/import/StacImportForm.tsx` — `'confirm'` step added to Step union; intercept button click; render confirmation panel with size aggregate
- `frontend/src/components/import/__tests__/StacImportForm.sizeEstimate.test.tsx` — 3 tests: mixed sizes, all-null fallback, confirm/back/import flow
- `frontend/src/i18n/locales/en/import.json` — `stac.confirm.*` keys (14)
- `frontend/src/i18n/locales/de/import.json` — `stac.confirm.*` keys (14)
- `frontend/src/i18n/locales/es/import.json` — `stac.confirm.*` keys (14)
- `frontend/src/i18n/locales/fr/import.json` — `stac.confirm.*` keys (14)

## Decisions Made

- `formatBytes` already existed in `frontend/src/lib/format.ts` — only tests were needed, no new helper written
- Confirm step inserted as a new render branch before the loading-states branch to keep the Step state machine linear
- `data_asset_size_bytes` placed adjacent to `data_asset_href` in both the adapter dict and the Pydantic schema for logical grouping

## Deviations from Plan

None — plan executed exactly as written. The only discovery was that `formatBytes` pre-existed; tests were still written as specified (Task 1 behavior block). The Pydantic schema grep found `stac_router.py` as the one schema file requiring the new field.

## Requirements Closed

- **EW-05**: STAC import wizard now shows estimated download size before commit; partial-unavailable fallback implemented; user can cancel from confirmation panel

## Self-Check: PASSED

All artifact files present. Commits `4e484cae` (Task 1) and `6960e652` (Task 2) exist. `vitest run` 14/14 pass. `tsc --noEmit` exit 0. `check:i18n:changed` exit 0.

---
*Phase: 1054-seeder-console-route-import-polish*
*Completed: 2026-05-19*
