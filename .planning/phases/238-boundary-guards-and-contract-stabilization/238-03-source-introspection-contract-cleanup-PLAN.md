---
phase: 238-boundary-guards-and-contract-stabilization
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/tests/test_vrt_catalog_175.py
autonomous: true
requirements:
  - BOUND-03
  - BOUND-04
must_haves:
  truths:
    - "VRT search enrichment regression coverage no longer depends on concatenated source blocks from `_handle_search` and `_bulk_fetch_dataset_metadata`."
    - "The replacement tests assert behavior through the public search facade and the focused router metadata helper instead of brittle inline implementation text."
    - "Existing catalog<->processing guards remain green after the source-introspection cleanup."
  artifacts:
    - path: backend/tests/test_vrt_catalog_175.py
      provides: "Behavior-oriented VRT search enrichment regression tests"
      contains: "TestSearchEnrichmentVrt"
  key_links:
    - from: "backend/tests/test_vrt_catalog_175.py"
      to: "backend/app/modules/catalog/search/service.py"
      via: "dataset_to_ogc_record facade import for output contract"
      pattern: "from app.modules.catalog.search.service import dataset_to_ogc_record"
    - from: "backend/tests/test_vrt_catalog_175.py"
      to: "backend/app/modules/catalog/search/router.py"
      via: "_bulk_fetch_dataset_metadata helper behavior test"
      pattern: "_bulk_fetch_dataset_metadata"
---

<objective>
Replace brittle VRT search source-inspection tests with contract tests that survive the maps/search service split.

Purpose: keep the regression signal for `vrt_dataset` raster enrichment while avoiding tests that assert against concatenated inline source blocks.
Output: behavior-oriented tests in `backend/tests/test_vrt_catalog_175.py`.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@backend/tests/test_vrt_catalog_175.py
@backend/app/modules/catalog/search/router.py
@backend/app/modules/catalog/search/service.py
@backend/app/modules/catalog/search/service_records.py
@backend/tests/test_layering.py

<discovery_notes>
`backend/tests/test_vrt_catalog_175.py::TestSearchEnrichmentVrt` currently uses `inspect.getsource(search_module._bulk_fetch_dataset_metadata) + inspect.getsource(search_module._handle_search)` in three tests and asserts string counts for `vrt_dataset`. That is brittle because it couples the regression to implementation block placement.

The code under test has two better contracts:
- `app.modules.catalog.search.router._bulk_fetch_dataset_metadata(db, datasets)` should request raster metadata for both `raster_dataset` and `vrt_dataset` records and attach VRT `source_count` when metadata identifies a VRT.
- `app.modules.catalog.search.service.dataset_to_ogc_record(...)` should expose raster metadata fields such as `band_count` for records rendered through the public search facade.
</discovery_notes>

<interfaces>
Replace the three source-inspection tests in `TestSearchEnrichmentVrt` with behavior-focused tests. Keep the class name.

Expected replacement shape:
```python
async def test_bulk_fetch_dataset_metadata_includes_raster_and_vrt_records(monkeypatch): ...

def test_dataset_to_ogc_record_exposes_vrt_band_count_from_raster_meta(): ...
```

Use lightweight fake objects or existing ORM model constructors as appropriate. The `_bulk_fetch_dataset_metadata` test may use a fake async session and monkeypatch `app.processing.raster.queries.fetch_raster_meta_bulk` so it can assert the exact dataset IDs passed to raster metadata lookup without requiring a live database.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Replace VRT search source inspection with helper behavior coverage</name>
  <files>backend/tests/test_vrt_catalog_175.py</files>
  <action>In `TestSearchEnrichmentVrt`, delete the three tests that concatenate `inspect.getsource(search_module._bulk_fetch_dataset_metadata)` and `inspect.getsource(search_module._handle_search)`. Add an async test for `app.modules.catalog.search.router._bulk_fetch_dataset_metadata` that builds three lightweight datasets: one `vector_dataset`, one `raster_dataset`, and one `vrt_dataset`. Monkeypatch `app.processing.raster.queries.fetch_raster_meta_bulk` to record the IDs passed and return metadata for the raster and VRT datasets, with the VRT row including `vrt_type`. Use a fake async session whose `execute()` calls return empty STAC/extent rows and a VRT source-count row for the VRT query. Assert the helper requests exactly the raster and VRT IDs, excludes the vector ID, and returns `source_count` on the VRT metadata.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_vrt_catalog_175.py::TestSearchEnrichmentVrt -q</automated>
  </verify>
  <done>`TestSearchEnrichmentVrt` verifies VRT metadata behavior without inspecting `_handle_search` source.</done>
</task>

<task type="auto">
  <name>Add facade-level VRT record output contract and guard against old source checks</name>
  <files>backend/tests/test_vrt_catalog_175.py</files>
  <action>Add a second replacement test that imports `dataset_to_ogc_record` from `app.modules.catalog.search.service`, not `service_records.py`, and builds a minimal VRT dataset/record object using the existing ORM models or a lightweight object compatible with the function. Pass `raster_meta={"band_count": 3, "vrt_type": "mosaic", "source_count": 2}` and assert the returned feature properties include `record_type == "vrt_dataset"`, `band_count == 3`, and VRT metadata fields expected by the current renderer. Add an actual pytest test, for example `test_search_enrichment_vrt_no_longer_uses_source_introspection`, that reads `tests/test_vrt_catalog_175.py` and asserts the two forbidden strings are absent: `inspect.getsource(search_module._handle_search)` and `inspect.getsource(search_module._bulk_fetch_dataset_metadata)`. Do not rely on an inline shell here-doc for this assertion because a later command can mask the failed assertion status. Keep the tile-token source-inspection tests in the same file unchanged; they target `processing.tiles.router._resolve_raster_access`, not the maps/search service boundary.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_vrt_catalog_175.py::TestSearchEnrichmentVrt tests/test_vrt_catalog_175.py::test_search_enrichment_vrt_no_longer_uses_source_introspection tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q</automated>
  </verify>
  <done>The VRT search regression is asserted through the facade/helper contract, and existing catalog/processing guards still pass.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_vrt_catalog_175.py::TestSearchEnrichmentVrt -q
- cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q
- cd backend && uv run ruff check tests/test_vrt_catalog_175.py
- cd backend && uv run ruff format --check tests/test_vrt_catalog_175.py
</verification>

<success_criteria>
- BOUND-04 is satisfied: source-introspection regression coverage no longer couples VRT search enrichment to inline `_handle_search` source blocks.
- BOUND-03 remains true: existing catalog/processing boundary guards still pass.
</success_criteria>

<output>
After completion, create `.planning/phases/238-boundary-guards-and-contract-stabilization/238-03-SUMMARY.md`.
</output>
