---
phase: quick-260422
plan: 01
subsystem: dataset-detail
tags: [ux-review, table, access-tab]
key_files:
  reviewed:
    - frontend/src/components/dataset/tabs/AccessTab.tsx
    - frontend/src/components/dataset/DistributionsList.tsx
    - frontend/src/components/dataset/ExportButton.tsx
    - frontend/src/components/dataset/ConnectDropdown.tsx
    - backend/app/modules/catalog/records/service.py
    - backend/app/processing/export/router.py
    - backend/tests/test_ingest.py
    - frontend/src/components/dataset/__tests__/ExportButton.test.tsx
    - e2e/non-spatial.spec.ts
  created:
    - docs-internal/audits/ux-review-desktop-20260423.md
evidence:
  route: /datasets/5bdda186-fdcb-4694-91dc-097b3e058026#access
  screenshots:
    - docs-internal/audits/evidence/ux-review-20260423/table-access-desktop.png
    - docs-internal/audits/evidence/ux-review-20260423/table-access-tablet.png
    - docs-internal/audits/evidence/ux-review-20260423/table-access-mobile.png
decisions:
  - Reviewed the current working tree, not only HEAD, because DatasetPage.tsx has local unstaged changes.
  - Did not update .planning/STATE.md or create a commit because ROADMAP.md is absent and .planning/STATE.md already contains staged user work.
metrics:
  completed: 2026-04-23
  live_dataset: "Ucdp Ged V25 1 (10m)"
---

# Quick Task 260422: Review table dataset Access tab items

The table-data Access tab is partially sound.

- Valid and functional:
  - The backend-driven Access Points card is correct for non-spatial tables: it surfaces only a CSV download and an OGC API Features endpoint.
  - The Visibility card is accurate and harmless for table data.
- Broken or misleading:
  - The hardcoded "Access via API" snippet points to the wrong endpoint shape for tables.
  - The Export picker still offers unsupported non-spatial formats.

## Findings

### 1. Hardcoded API snippet is stale and non-functional for table datasets
- `frontend/src/components/dataset/tabs/AccessTab.tsx` builds the example URLs from `window.location.origin` plus `dataset.table_name`, using `/api/v1/collections/${collectionId}/items`.
- The live Access Points card for the audited table dataset resolves the real OGC endpoint to `/api/collections/<dataset-id>/items`.
- Runtime check:
  - `GET /api/collections/5bdda186-fdcb-4694-91dc-097b3e058026/items?limit=2` returned `200` and a GeoJSON `FeatureCollection` with `geometry: null`.
  - `GET /api/v1/collections/ucdp_ged_v25_1_10m/items?limit=1` returned `404`.
- Impact: users copying the curl/python/QGIS example get a broken URL, even though the real distribution above it works.

### 2. Export picker advertises formats the backend rejects for non-spatial tables
- `frontend/src/components/dataset/ExportButton.tsx` removes only `shp` for `recordType === 'table'`, leaving `gpkg`, `geojson`, and `csv`.
- The backend rejects non-spatial `gpkg`, `geojson`, and `shp`, explicitly allowing `csv` only.
- Runtime checks:
  - In the live UI, choosing `gpkg` showed `Cannot export non-spatial dataset as gpkg. Use csv format.`
  - Choosing `geojson` showed `Cannot export non-spatial dataset as geojson. Use csv format.`
  - Authenticated `GET /api/datasets/5bdda186-fdcb-4694-91dc-097b3e058026/export?format=csv` returned `200` with `text/csv`.
- Impact: the default/first export choices fail on a table dataset, which makes the tab feel unreliable.

### 3. Tests currently lock in the wrong table-export behavior and miss the Access-tab drift
- `frontend/src/components/dataset/__tests__/ExportButton.test.tsx` currently expects table datasets to keep `gpkg`, `geojson`, and `csv`.
- `e2e/non-spatial.spec.ts` verifies import, page load, and row rendering, but never opens the Access tab or exercises table export/API affordances.
- Impact: the current test suite allows both the stale snippet and the broken export picker to ship unnoticed.

### 4. Table workflow copy points users to a different access model than the Access tab
- The table hero says "use Connect for downstream access."
- `frontend/src/components/dataset/ConnectDropdown.tsx` gives tables only `Copy API URL`, which points to `/api/datasets/{dataset.id}` rather than the table's OGC items or CSV export endpoint.
- Impact: the primary callout above the tabs nudges users toward dataset metadata, while the Access tab itself exposes the actual data-access endpoints.

## Easy Wins

1. Generate the code snippet from the same resolved distribution URL used by `DistributionsList`.
   - Reuse the resolved OGC endpoint instead of rebuilding it from `window.location.origin` and `dataset.table_name`.
   - This fixes both the wrong path prefix and the wrong identifier.

2. Restrict table exports to the server-supported set and default to `csv`.
   - For current behavior, that means table datasets should only expose `csv`.
   - Update the unit test so it stops codifying unsupported formats.

3. Align `Connect` with the Access tab for tables.
   - Either expose "Copy OGC items URL" and "Copy CSV export URL" there as well, or rename the current action to make it clear it is a dataset metadata URL.

4. Add table-specific Access-tab coverage.
   - Unit test `AccessTab`/`ExportButton` for non-spatial datasets.
   - Add one E2E assertion in `e2e/non-spatial.spec.ts` that opens the Access tab, verifies the real OGC endpoint text, and ensures unsupported export options are absent.

## Workflow Notes

- GSD quick bookkeeping could not be completed normally because `node ... gsd-tools.cjs init quick ...` reported `roadmap_exists: false`.
- `.planning/STATE.md` also already has staged changes, so updating it or committing artifacts would risk capturing unrelated user work.
- Result: artifacts written only; no `STATE.md` mutation and no commit created.
