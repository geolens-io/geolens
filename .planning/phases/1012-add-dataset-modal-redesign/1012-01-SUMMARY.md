# Phase 1012 Plan 01 Summary

**Completed:** 2026-05-12
**Requirements:** ADD-01, ADD-02, ADD-03, ADD-04, ADD-05, ADD-06, ADD-07, ADD-08

## What Changed

- Reworked the existing `DatasetSearchPanel` into the v1 Add Dataset modal body:
  - search-first input;
  - `All`, `Vector`, `Raster`, and `Basemap` tabs;
  - API-backed filter chips for existing `source_organization` and `keywords` params;
  - expandable rows with preview/metadata and primary actions;
  - `/import` footer link as **Import data...**.
- Added data row states:
  - not on map → `Add to map`;
  - already on map → `Added` plus `another rendering`;
  - `another rendering` routes to the Phase 1010 duplicate-rendering handler.
- Added basemap row states from the existing enabled `BasemapEntry` registry:
  - active → `in use`;
  - inactive → `swap`, writing existing map-level basemap handlers with normalized config.
- Expanded `BuilderDialogs` / `MapBuilderPage` wiring so the modal can call existing layer, duplicate-rendering, and basemap handlers.
- Added focused `DatasetSearchPanel` component tests for tabs, filters, add/added/another-rendering, basemap swap/in-use, expansion, and import routing.

## Boundaries Preserved

- No new dataset search endpoint, migration, table, persisted field, or import flow.
- No Curated / Your imports / Public scope chips.
- No cross-surface drag from modal into the stack.
- Basemap writes stay on `basemap_style`, `show_basemap_labels`, and `basemap_config`.

## Verification

- `cd frontend && npm run test -- DatasetSearchPanel MapStackPanel map-stack renderAs use-builder-layers --run` — passed, 5 files / 61 tests.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed, with the existing large-chunk warning only.

## Handoff

Phase 1013 can focus on milestone QA closeout, including Playwright-oriented browser validation for the sidebar and modal.
