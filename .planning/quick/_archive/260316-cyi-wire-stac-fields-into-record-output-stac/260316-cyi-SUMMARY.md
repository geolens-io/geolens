---
phase: quick-260316-cyi
plan: 01
subsystem: search, datasets
tags: [stac, ogc-records, api]
dependency_graph:
  requires: [260316-bgd]
  provides: [stac-version-in-records, stac-datetime, stac-assets-in-records, stac-assets-in-detail]
  affects: [search-router, datasets-router, datasets-schemas]
tech_stack:
  added: []
  patterns: [stac-1.1.0-datetime-rules, stac-assets-dict]
key_files:
  created:
    - backend/tests/test_stac_record_output.py
  modified:
    - backend/app/search/service.py
    - backend/app/search/router.py
    - backend/app/datasets/schemas.py
    - backend/app/datasets/router.py
decisions:
  - Separate stac_assets key from existing assets key to avoid breaking changes
  - STAC datetime follows 1.1.0 rules -- single date, range with start/end, or null
  - Only detail endpoint gets stac_assets (list endpoint omits for performance)
metrics:
  duration: 453s
  completed: "2026-03-16T13:31:39Z"
  tasks_completed: 2
  tasks_total: 2
  test_count: 10
---

# Quick Task 260316-cyi: Wire STAC Fields Into Record Output Summary

Wire STAC 1.1.0 stac_version, properties.datetime, and stac_assets dict into OGC record output and dataset detail responses using DatasetAsset rows.

## What Was Done

### Task 1: Add stac_version, properties.datetime, and stac_assets to OGC record output
- **Commit:** be0c3ffc (RED), 34ca86f0 (GREEN)
- Added `stac_version: "1.1.0"` at top level of all OGC record features
- Added `properties.datetime` following STAC 1.1.0 rules:
  - Single temporal_start only: datetime = RFC 3339 string
  - Both temporal_start and temporal_end: datetime = null, start_datetime/end_datetime set
  - Neither: datetime = null
- Added `_build_stac_assets()` helper to serialize DatasetAsset rows as STAC assets dict
- Updated `dataset_to_ogc_record()` to accept optional `stac_asset_rows` parameter
- Bulk-query DatasetAsset in `_handle_search` for all search results
- Single-item query in `get_collection_item` for individual record fetch

### Task 2: Add stac_assets to DatasetResponse schema and detail endpoint
- **Commit:** da716842
- Added `StacAsset` Pydantic schema (href, type, title, description, roles, size_bytes)
- Added `stac_assets: dict[str, StacAsset] | None` field to `DatasetResponse`
- Query DatasetAsset rows in `get_single_dataset` and serialize via StacAsset schema
- List endpoint unaffected (stac_assets=None by default, no extra query)

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- 10 new tests in `test_stac_record_output.py` all passing
- 7 existing tests in `test_stac_asset_model.py` still passing
- 227 tests passing in full suite (2 pre-existing failures unrelated: test_chat_streaming, test_embed_tokens)

## Self-Check: PASSED
