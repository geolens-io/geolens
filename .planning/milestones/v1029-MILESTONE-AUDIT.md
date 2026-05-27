---
milestone: v1029
status: complete
verdict: clear
completed: 2026-05-27
requirements_total: 25
requirements_complete: 25
---

# v1029 Milestone Audit: DCAT 3.0

## Verdict

CLEAR. v1029 satisfies 25/25 requirements. GeoLens now supports explicit DCAT-US Schema v3.0 export and validation routes while preserving the existing W3C DCAT 3 compatibility routes and catalog visibility/access-control behavior.

## Delivered

- Vendored the official GSA/dcat-us DCAT-US 3.0 JSON Schema definitions from commit `98408dc000f0b71131a03920e2dec6247a84abff`.
- Added a separate `app.standards.dcat_us` profile layer for schema loading, serialization, and validation.
- Added DCAT-US catalog and per-dataset export routes:
  - `GET /datasets/dcat-us/3.0/`
  - `GET /datasets/{dataset_id}/dcat-us/3.0/`
- Added DCAT-US catalog and per-dataset validation report routes:
  - `GET /datasets/dcat-us/3.0/validation/`
  - `GET /datasets/{dataset_id}/dcat-us/3.0/validation/`
- Preserved existing W3C DCAT routes:
  - `GET /datasets/dcat/`
  - `GET /datasets/{dataset_id}/dcat/`
- Added mapping docs, migration notes, CHANGELOG coverage, OpenAPI output, and generated Python/TypeScript SDK endpoints.

## Verification Summary

- Focused backend tests: 22 passed.
- Backend Ruff check: passed.
- Backend Ruff format-check: passed.
- Clean worktree `make openapi-check`: passed.
- Clean worktree `make sdks-check`: passed.
- Playwright MCP runtime verification:
  - `GET /datasets/dcat-us/3.0/validation/` -> 200 OK, `schema=Catalog`.
  - `GET /datasets/dcat-us/3.0/` -> 200 OK, `@type=Catalog`, DCAT-US context, 123 visible datasets in the local database.
  - `GET /datasets/{dataset_id}/dcat-us/3.0/` -> 200 OK, `@type=Dataset`.
  - `GET /datasets/{dataset_id}/dcat-us/3.0/validation/` -> 200 OK, `schema=Dataset`.

## Data and Access Safety

Catalog export and validation use the same visibility-filtered query path as existing DCAT catalog export. Per-dataset export and validation use the same dataset access helper as existing per-dataset DCAT export.

The local runtime catalog contains records with incomplete federal metadata, so validation correctly reported schema errors instead of fabricating required `description` or `contactPoint` fields.

## Operational Notes

The Compose API image was stale after `jsonschema` moved from dev-only to runtime dependencies, so it reported `ModuleNotFoundError: No module named 'jsonschema'` until rebuilt. Runtime Playwright MCP verification used a local backend launched from the committed Python environment with a writable `/tmp` staging path.

The main working tree contains unrelated pre-existing map-builder/map-access changes. OpenAPI and SDK drift checks were run from a detached clean worktree at the DCAT-US commit to keep those unrelated edits out of the v1029 generated artifacts.

## Follow-Ups

- **DCAT-FU-01:** Add first-class DatasetSeries authoring if GeoLens collections or dataset relationships need to publish federal series metadata.
- **DCAT-FU-02:** Add structured AccessRestriction, UseRestriction, and CUIRestriction authoring instead of mapping only existing free-text constraints.
- **DCAT-FU-03:** Add DCAT-US v1.1 import/migration tooling if operators need to bulk transform existing `data.json` files into GeoLens metadata.
- **DCAT-FU-04:** Promote shared DCAT/STAC/OGC validators into the future `geolens-schemas` package when Phase 999.16 is prioritized.
- **CI-01-v1029:** Live-verify `pytest-parallel-isolation` on GitHub Actions after the existing org billing blocker is resolved.
