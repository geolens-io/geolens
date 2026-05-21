---
phase: quick-260316-cyi
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/search/service.py
  - backend/app/datasets/router.py
  - backend/app/datasets/schemas.py
  - backend/tests/test_stac_record_output.py
autonomous: true
requirements: [STAC-WIRE-01, STAC-WIRE-02]

must_haves:
  truths:
    - "OGC record output includes stac_version='1.1.0' at top level"
    - "OGC record output includes properties.datetime (RFC 3339 from temporal_start, or null)"
    - "Dataset detail response includes stac_assets dict keyed by DatasetAsset.key"
    - "OGC record output includes stac_assets dict from DatasetAsset rows"
  artifacts:
    - path: "backend/app/search/service.py"
      provides: "stac_version, properties.datetime, and stac_assets in dataset_to_ogc_record()"
      contains: "stac_version"
    - path: "backend/app/datasets/schemas.py"
      provides: "StacAsset schema and stac_assets field on DatasetResponse"
      contains: "stac_assets"
    - path: "backend/app/datasets/router.py"
      provides: "DatasetAsset query and serialization in detail endpoint"
      contains: "DatasetAsset"
    - path: "backend/tests/test_stac_record_output.py"
      provides: "Tests for STAC fields in record output"
  key_links:
    - from: "backend/app/search/service.py"
      to: "backend/app/raster/models.py"
      via: "DatasetAsset query for stac_assets"
      pattern: "DatasetAsset"
    - from: "backend/app/datasets/router.py"
      to: "backend/app/raster/models.py"
      via: "DatasetAsset query for detail response"
      pattern: "DatasetAsset"
---

<objective>
Wire STAC 1.1.0 fields into existing API output: add stac_version literal and properties.datetime to OGC record features, and serialize DatasetAsset rows as a STAC assets dictionary in both OGC record output and dataset detail responses.

Purpose: Close the three remaining HIGH/MEDIUM gaps identified in the STAC gap analysis, making OGC record output a valid STAC Item structure without breaking changes.
Output: Updated search service, dataset schemas/router, and integration tests.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260316-c8k-address-stac-readiness-and-raster-vrt-di/STAC-GAP-ANALYSIS.md

<interfaces>
<!-- Key types and contracts the executor needs -->

From backend/app/raster/models.py (DatasetAsset):
```python
class DatasetAsset(Base):
    __tablename__ = "dataset_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key", name="uq_dataset_assets_key"),
        {"schema": "catalog"},
    )
    id: Mapped[uuid.UUID]
    dataset_id: Mapped[uuid.UUID]  # FK to catalog.datasets.id
    key: Mapped[str]               # "data", "vrt", "thumbnail", "overview"
    href: Mapped[str]
    media_type: Mapped[str | None]
    title: Mapped[str | None]
    description: Mapped[str | None]
    roles: Mapped[list | None]     # ARRAY(Text)
    size_bytes: Mapped[int | None]
    created_at: Mapped[datetime]
```

From backend/app/search/service.py (dataset_to_ogc_record, lines 464-579):
- Returns a dict with keys: type, id, geometry, properties, links, assets, bbox
- `bbox` is ALREADY computed via `extract_bbox(dataset)` and added (lines 575-577)
- `properties.time` already has temporal interval from `_build_time(dataset)`
- `assets` already has download/tile/feature assets from `_build_assets(dataset, public_api_url)`

From backend/app/datasets/schemas.py (DatasetResponse, line 83-127):
- Pydantic model with `raster: RasterMetadata | None` field
- No `stac_assets` field yet

From backend/app/datasets/router.py (get_single_dataset, lines 511-578):
- Already queries RasterAsset for raster/VRT datasets
- Does NOT query DatasetAsset yet
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add stac_version, properties.datetime, and stac_assets to OGC record output</name>
  <files>backend/app/search/service.py, backend/tests/test_stac_record_output.py</files>
  <behavior>
    - Test 1: OGC record dict has top-level "stac_version" = "1.1.0"
    - Test 2: OGC record with temporal_start set has properties.datetime = temporal_start.isoformat() + "T00:00:00Z"
    - Test 3: OGC record with no temporal_start has properties.datetime = null
    - Test 4: OGC record with temporal_start AND temporal_end has properties.start_datetime and properties.end_datetime
    - Test 5: OGC record includes stac_assets dict keyed by DatasetAsset.key with href, type, roles, title fields
    - Test 6: OGC record with no DatasetAsset rows has empty stac_assets dict
  </behavior>
  <action>
    In `backend/app/search/service.py`, modify `dataset_to_ogc_record()`:

    1. Add `"stac_version": "1.1.0"` to the top-level `ogc_record` dict (after "type": "Feature").

    2. Add `properties.datetime` following STAC 1.1.0 rules:
       - If `record.temporal_start` exists and `record.temporal_end` is None: set `datetime` to `record.temporal_start.isoformat()` (it's a `date` object, so format as `YYYY-MM-DDT00:00:00Z`)
       - If both `temporal_start` and `temporal_end` exist: set `datetime` to None, and add `start_datetime` and `end_datetime` (both as ISO 8601 with T00:00:00Z suffix)
       - If neither exists: set `datetime` to None

    3. Add a new helper `_build_stac_assets(dataset_id, session)` -- BUT since `dataset_to_ogc_record` is synchronous and doesn't have a session, instead accept an optional `stac_assets` parameter (list of DatasetAsset dicts pre-fetched). Build the STAC assets dict:
       ```python
       def _build_stac_assets(asset_rows: list[dict] | None) -> dict:
           if not asset_rows:
               return {}
           result = {}
           for row in asset_rows:
               entry = {"href": row["href"]}
               if row.get("media_type"):
                   entry["type"] = row["media_type"]
               if row.get("roles"):
                   entry["roles"] = row["roles"]
               if row.get("title"):
                   entry["title"] = row["title"]
               if row.get("description"):
                   entry["description"] = row["description"]
               result[row["key"]] = entry
           return result
       ```

    4. Update `dataset_to_ogc_record` signature to accept `stac_asset_rows: list[dict] | None = None`. Add `"stac_assets": _build_stac_assets(stac_asset_rows)` to the record dict.

    5. In `_handle_search` in `backend/app/search/router.py`, after raster enrichment, add a bulk query for DatasetAsset rows for all feature IDs and pass them to `dataset_to_ogc_record`. Update the call at line 136 to pass stac_asset_rows. Also update the single-item endpoint `get_collection_item` to query and pass DatasetAsset rows.

    NOTE: The existing `assets` key in the record output contains download/tile/feature service URLs. The new STAC physical assets go in a SEPARATE key `stac_assets` to avoid breaking existing consumers. This follows the additive-only principle from the gap analysis.

    Create test file `backend/tests/test_stac_record_output.py` with unit tests for `dataset_to_ogc_record` and `_build_stac_assets`. Use the existing test patterns from `test_stac_asset_model.py` (create Record + Dataset fixtures, call the function, assert on output structure). Tests need the database running (integration tests using `client` and `test_db_session` fixtures).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -m pytest tests/test_stac_record_output.py -x -v</automated>
  </verify>
  <done>
    - dataset_to_ogc_record() output includes stac_version="1.1.0" at top level
    - properties.datetime is RFC 3339 string from temporal_start (or null)
    - properties.start_datetime/end_datetime present when both temporal bounds exist
    - stac_assets dict serializes DatasetAsset rows keyed by asset key
    - All search and collection item endpoints pass stac_asset_rows
  </done>
</task>

<task type="auto">
  <name>Task 2: Add stac_assets to DatasetResponse schema and detail endpoint</name>
  <files>backend/app/datasets/schemas.py, backend/app/datasets/router.py</files>
  <action>
    1. In `backend/app/datasets/schemas.py`, add a new schema and field:
       ```python
       class StacAsset(BaseModel):
           href: str
           type: str | None = None
           title: str | None = None
           description: str | None = None
           roles: list[str] | None = None
           size_bytes: int | None = None
       ```
       Add `stac_assets: dict[str, StacAsset] | None = None` to `DatasetResponse` (after the `raster` field).

    2. In `backend/app/datasets/router.py`:
       - In `get_single_dataset()` (around line 554, after the RasterAsset query), add a query for DatasetAsset rows:
         ```python
         from app.raster.models import DatasetAsset
         da_result = await db.execute(
             select(DatasetAsset).where(DatasetAsset.dataset_id == dataset.id)
         )
         dataset_asset_rows = da_result.scalars().all()
         ```
       - Build the stac_assets dict from the rows:
         ```python
         stac_assets_dict = {}
         for da in dataset_asset_rows:
             stac_assets_dict[da.key] = StacAsset(
                 href=da.href,
                 type=da.media_type,
                 title=da.title,
                 description=da.description,
                 roles=da.roles,
                 size_bytes=da.size_bytes,
             )
         ```
       - Pass `stac_assets=stac_assets_dict or None` to `_dataset_to_response()`.

    3. In `_dataset_to_response()`, accept `stac_assets=None` parameter and pass it to `DatasetResponse(... stac_assets=stac_assets)`.

    Note: Only add stac_assets to the DETAIL endpoint (`get_single_dataset`), NOT the list endpoint. The list endpoint returns many datasets and the extra query would be expensive. The stac_assets field is nullable so list responses simply omit it.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -m pytest tests/test_stac_asset_model.py tests/test_stac_record_output.py -x -v</automated>
  </verify>
  <done>
    - DatasetResponse schema has stac_assets field (dict[str, StacAsset] | None)
    - GET /datasets/{id} returns stac_assets dict with DatasetAsset rows serialized
    - List endpoint is unaffected (stac_assets=None in list responses)
    - No breaking changes to existing API consumers
  </done>
</task>

</tasks>

<verification>
1. All existing tests pass: `cd backend && python -m pytest -x --timeout=60`
2. New STAC record output tests pass: `cd backend && python -m pytest tests/test_stac_record_output.py -x -v`
3. Manual spot check: `curl -s http://localhost:8080/api/collections/datasets/items?limit=1 | python -m json.tool | grep stac_version` should show "1.1.0"
</verification>

<success_criteria>
- OGC record features include stac_version="1.1.0" at top level
- OGC record features include properties.datetime (RFC 3339 or null)
- OGC record features include stac_assets dict from DatasetAsset table
- Dataset detail API response includes stac_assets dict
- All existing tests continue to pass
- No breaking changes to existing API structure
</success_criteria>

<output>
After completion, create `.planning/quick/260316-cyi-wire-stac-fields-into-record-output-stac/260316-cyi-SUMMARY.md`
</output>
