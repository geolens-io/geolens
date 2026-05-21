---
phase: 260515-ilt
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/processing/raster/queries.py
  - backend/app/modules/catalog/search/service_records.py
  - backend/tests/test_quicklook_predicate.py
autonomous: true
requirements:
  - HAS-QUICKLOOK-RASTER-01
must_haves:
  truths:
    - "For a `raster_dataset` record whose `RasterAsset.quicklook_256_uri` is set, the OGC search response reports `has_quicklook=True`."
    - "For a `raster_dataset` record whose `RasterAsset.quicklook_256_uri` is None, the OGC search response reports `has_quicklook=False`."
    - "For a `vrt_dataset` record whose `RasterAsset.quicklook_256_uri` is set, the OGC search response reports `has_quicklook=True`."
    - "For a `vrt_dataset` record whose `RasterAsset.quicklook_256_uri` is None, the OGC search response reports `has_quicklook=False`."
    - "For vector_dataset / table records, `has_quicklook` continues to read from `Dataset.quicklook_256_uri` exactly as before (no regression on the 4 cases already covered by `test_quicklook_predicate.py`)."
    - "The OGC response properties do NOT include `quicklook_256_uri` as a field — it is a storage key, internal-only."
  artifacts:
    - path: "backend/app/processing/raster/queries.py"
      provides: "Centralized `RasterAsset` projection: both `fetch_raster_meta_one` and `fetch_raster_meta_bulk` SELECT `RasterAsset.quicklook_256_uri` and `_row_to_meta()` forwards it into the returned dict."
      contains: "quicklook_256_uri"
    - path: "backend/app/modules/catalog/search/service_records.py"
      provides: "`dataset_to_ogc_record` dispatches `has_quicklook` on `record_type` — Dataset column for vector/table, `raster_meta['quicklook_256_uri']` for raster/vrt."
      contains: "raster_meta"
    - path: "backend/tests/test_quicklook_predicate.py"
      provides: "Extended test coverage with raster_dataset + vrt_dataset cases (both URI-set and URI-null), plus the existing 4 vector tests still passing."
      min_lines: 250
  key_links:
    - from: "backend/app/processing/raster/queries.py:_row_to_meta"
      to: "RasterAsset.quicklook_256_uri"
      via: "SELECT column + dict key"
      pattern: "quicklook_256_uri"
    - from: "backend/app/modules/catalog/search/service_records.py:312"
      to: "raster_meta.get('quicklook_256_uri')"
      via: "predicate dispatch on record_type"
      pattern: "has_quicklook.*record_type.*raster"
---

<objective>
Make `has_quicklook` truthful for `raster_dataset` and `vrt_dataset` records in the OGC search response.

Today, `service_records.py:312` is hardcoded:

    "has_quicklook": dataset.quicklook_256_uri is not None,

For vector records this is correct — the URI lives on `Dataset.quicklook_256_uri`. For raster and VRT records, the URI lives on `RasterAsset.quicklook_256_uri` (see `RasterAsset` model `backend/app/processing/raster/models.py:69`). The Dataset column is always None for those rows, so `has_quicklook` always reports False — and the frontend `SearchResultCard.tsx:164` / `DatasetSearchPanel.tsx:124` never fire the quicklook GET, so raster thumbnails never render in search or Builder panels, even though `/api/datasets/{id}/quicklook` (`router.py:200-260`) serves them correctly.

This is the natural follow-on to SP-07 (quick task `260515-i45`, just shipped) which fixed the predicate's truthfulness for vector records via a backfill sweeper. Vector noise gone → raster thumbnail-gap becomes the next visible defect.

**Approach: dispatch on `record_type`, route raster/vrt reads through the already-threaded `raster_meta` dict.**

`raster_meta` is already passed into `dataset_to_ogc_record` as a keyword argument (`service_records.py:196-203`) and consumed at `service_records.py:411-452` for STAC properties (epsg, gsd, bands, vrt_type, source_count). Both call sites — `_build_search_assets_bulk` at `search/router.py:1461-1515` and `_build_raster_assets` at `search/router.py:176-202` — populate `raster_meta` from `queries.py:_row_to_meta()`. So the change is:

1. **`queries.py`** — add `RasterAsset.quicklook_256_uri` to BOTH `columns` lists (lines 46-60 and 82-95) AND `"quicklook_256_uri": row.quicklook_256_uri` to `_row_to_meta()` (lines 17-35). KISS-6 cascade: one centralized projection feeds both single and bulk paths.
2. **`service_records.py:312`** — dispatch on `record_type` (already computed at line 410 for the STAC block):
   - `vector_dataset` / `table` / unset → `dataset.quicklook_256_uri is not None` (unchanged behavior)
   - `raster_dataset` / `vrt_dataset` → `raster_meta is not None and raster_meta.get("quicklook_256_uri") is not None`
3. **Do NOT forward `quicklook_256_uri` into the public OGC response properties.** Read service_records.py:411-452 carefully — the raster_meta forwarding block selects specific keys (epsg, width, height, res_x, res_y, band_count, band_info, vrt_type, source_count). Adding `quicklook_256_uri` there would leak a storage path. The predicate is internal-only.
4. **`test_quicklook_predicate.py`** — extend with raster + vrt cases (URI-set + URI-null for each = 4 new tests), plus one explicit assertion that the OGC response properties dict does NOT contain a `quicklook_256_uri` key (no leak). The existing 4 vector tests must still pass unchanged.

**Out of scope (explicitly):**
- Frontend. The frontend gate is already `has_quicklook`; once the backend tells the truth, raster thumbnails will start rendering automatically.
- Backfill of existing `RasterAsset.quicklook_256_uri` rows. Per `tasks_raster.py:374-380` and `tasks_vrt.py:312-321`, raster URIs are only written after a successful `storage.put()`, so URI-presence already implies file-on-disk. A separate raster-side reconcile sweeper is a future follow-up if ops want one — not part of this fix.
- Any schema change. `RasterAsset.quicklook_256_uri` already exists (line 69 of `models.py`).

Purpose: Close the raster/vrt thumbnail gap in search and Builder dataset panels by making `has_quicklook` mean what it says regardless of `record_type`.
Output: Minimal, surgical edit at the centralized projection (`queries.py`) + the predicate site (`service_records.py:312`) + extended test coverage.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

# Prior plan + summary (this is the follow-on)
@.planning/quick/260515-i45-sp-07-backend-has-quicklook-predicate/260515-i45-PLAN.md
@.planning/quick/260515-i45-sp-07-backend-has-quicklook-predicate/260515-i45-SUMMARY.md

# Edit sites (read fully before editing)
@backend/app/processing/raster/queries.py
@backend/app/modules/catalog/search/service_records.py

# Read-only references
@backend/app/processing/raster/models.py
@backend/app/modules/catalog/datasets/api/router.py
@backend/app/modules/catalog/search/router.py
@backend/tests/test_quicklook_predicate.py
@backend/tests/test_ogc_record_properties.py
@backend/tests/test_raster_tiles.py

<interfaces>
<!-- Key contracts. Extracted from codebase. -->

From `backend/app/processing/raster/queries.py:17-35` — `_row_to_meta` (centralized projection):
The function builds a flat `dict` from a SELECTed RasterAsset row. Currently includes: band_count, epsg, res_x, res_y, width, height, dtype, nodata, band_info, (optionally) vrt_type, resolution_strategy, current_generation_id. We ADD one entry: `"quicklook_256_uri": row.quicklook_256_uri`. We do NOT add it to an `include_*` toggle — it's always present (None when the raster has no quicklook).

From `backend/app/processing/raster/queries.py:46-60` and `82-95` — the two SELECT column lists. Both must additionally include `RasterAsset.quicklook_256_uri`.

From `backend/app/modules/catalog/search/service_records.py:196-203` — `dataset_to_ogc_record` signature:
    def dataset_to_ogc_record(
        dataset: Dataset,
        public_api_url: str,
        *,
        stac_asset_rows: list[dict] | None = None,
        raster_meta: dict | None = None,
        spatial_extent_geojson: str | None = None,
    ) -> dict:
`raster_meta` is already a keyword arg. NO signature change.

From `backend/app/modules/catalog/search/service_records.py:410` — `record_type` is already computed inside the function:
    record_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
BUT that local is defined AFTER line 312 (the predicate site). The dispatch at line 312 must compute its own local — duplicate the same `getattr` fallback — OR (cleaner) move the `record_type` local definition up to immediately before the `ogc_record` dict literal at line 278 and reuse it. Either is acceptable; pick the smaller diff.

From `backend/app/modules/catalog/search/service_records.py:411-452` — the raster_meta forwarding block: explicitly enumerates which raster_meta keys land in `ogc_record["properties"]`. DO NOT add `quicklook_256_uri` to this block.

From `backend/app/processing/raster/models.py:69`:
    quicklook_256_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
Already exists. No schema change.

From `backend/tests/test_quicklook_predicate.py:27-64` — `_create_quicklook_dataset` helper (existing).
Creates a vector_dataset with optional `quicklook_256_uri` on the Dataset. We MIRROR this pattern with a new helper `_create_raster_quicklook_dataset` (in the same test file) that creates a Record with `record_type="raster_dataset"` or `"vrt_dataset"`, a Dataset (without quicklook_256_uri — that column is meaningless for raster), AND a `RasterAsset` row with the optional `quicklook_256_uri`. See `backend/tests/test_raster_tiles.py:30-80` for the RasterAsset fixture pattern.

From `backend/tests/test_raster_tiles.py:66-74` — RasterAsset construction pattern. Minimum fields used in that fixture: `dataset_id`, `asset_uri`, `storage_backend`. Other columns (band_count, epsg, etc.) are optional / nullable. For the predicate test, set `quicklook_256_uri` to either None or a stub path like `f"rasters/{dataset.id}/quicklook_256.png"`.

From `backend/app/modules/catalog/search/router.py:176-202` (`_build_raster_assets`) and `1461-1515` (`_build_search_assets_bulk` raster_meta block) — both call sites consume `_row_to_meta()` output and pass it as `raster_meta=` into `dataset_to_ogc_record`. NO changes needed at these call sites — the new dict key flows through.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1 — Thread `quicklook_256_uri` through `_row_to_meta` and dispatch the predicate on `record_type`</name>
  <files>backend/app/processing/raster/queries.py, backend/app/modules/catalog/search/service_records.py, backend/tests/test_quicklook_predicate.py</files>
  <behavior>
    Extend `backend/tests/test_quicklook_predicate.py` with five new tests (all `@pytest.mark.anyio`, using the existing `client: AsyncClient, test_db_session` fixtures and `get_user_id` helper). Add a new helper `_create_raster_quicklook_dataset(session, *, created_by, record_type, raster_quicklook_uri)` that inserts a `Record(record_type=record_type)`, a `Dataset` (without `quicklook_256_uri`), and a `RasterAsset(dataset_id=..., asset_uri="rasters/<id>/source.cog.tif", storage_backend="local", quicklook_256_uri=raster_quicklook_uri)`. Mirror the loading discipline of `_create_quicklook_dataset`: `await session.flush()`, `await session.commit()`, `await session.refresh(dataset)`, then `await session.refresh(record, attribute_names=["keywords", "contacts", "distributions"])` and `dataset.record = record`.

    The five new tests cover:

    1. **`test_has_quicklook_true_for_raster_dataset_when_raster_asset_uri_set`** — Build a raster_dataset with `RasterAsset.quicklook_256_uri = f"rasters/{dataset.id}/quicklook_256.png"`. Build `raster_meta` by calling `fetch_raster_meta_one(test_db_session, dataset.id)` directly (this exercises the centralized projection — DO NOT hand-construct the dict, since the whole point is that `_row_to_meta` now ships the new key). Call `dataset_to_ogc_record(dataset, "http://test", raster_meta=raster_meta)`. Assert `result["properties"]["has_quicklook"] is True`.

    2. **`test_has_quicklook_false_for_raster_dataset_when_raster_asset_uri_null`** — Same setup but `quicklook_256_uri=None` on the RasterAsset. Assert `result["properties"]["has_quicklook"] is False`.

    3. **`test_has_quicklook_true_for_vrt_dataset_when_raster_asset_uri_set`** — Same as #1 but `record_type="vrt_dataset"`.

    4. **`test_has_quicklook_false_for_vrt_dataset_when_raster_asset_uri_null`** — Same as #2 but `record_type="vrt_dataset"`.

    5. **`test_raster_response_does_not_leak_quicklook_uri_property`** — For any raster_dataset case (re-use the #1 fixture), assert `"quicklook_256_uri" not in result["properties"]`. Guards against accidentally forwarding the storage key into the public response.

    The four existing vector tests (`test_has_quicklook_false_when_uri_null`, `test_has_quicklook_true_when_uri_set`, `test_reconcile_clears_stale_uri`, `test_reconcile_preserves_present_uri`) MUST continue to pass unchanged — they exercise the vector branch of the new dispatch.
  </behavior>
  <action>
    Edit `backend/app/processing/raster/queries.py`:

    - In `_row_to_meta` (lines 17-35): add `"quicklook_256_uri": row.quicklook_256_uri,` to the `meta` dict. Place it adjacent to `band_info` (the last unconditional key) — order matches the SELECT column order below. Always present (no `include_*` toggle); it is None when the raster asset has no quicklook.
    - In `fetch_raster_meta_one`'s `columns` list (lines 46-56): append `RasterAsset.quicklook_256_uri` after `RasterAsset.band_info`.
    - In `fetch_raster_meta_bulk`'s `columns` list (lines 82-93): append `RasterAsset.quicklook_256_uri` after `RasterAsset.band_info`.
    - Do not change any function signatures or kwargs. The new key is unconditional.

    Edit `backend/app/modules/catalog/search/service_records.py`:

    - At line 312, replace the hardcoded predicate with a dispatch on `record_type`. The cleanest diff: compute the `record_type` local once near the top of the function (before the `ogc_record` dict literal at line 278) — note that line 410 currently re-computes the same `getattr(record, "record_type", "vector_dataset") or "vector_dataset"` later in the function, so introducing the local earlier and reusing it at line 410 is a tiny secondary cleanup (replace the line-410 re-computation with the existing local). If that secondary cleanup feels too coupled, leave line 410 alone and just duplicate the `getattr` at line 312 — the test suite will still pass either way; KISS wins.
    - New predicate logic (substituting for the single-line literal at 312):

          # has_quicklook source depends on record_type:
          # - vector_dataset / table: Dataset.quicklook_256_uri (Dataset column is set by vector ingest)
          # - raster_dataset / vrt_dataset: RasterAsset.quicklook_256_uri, surfaced via raster_meta
          # The RasterAsset URI is internal-only (storage key) — never forwarded to response properties.
          "has_quicklook": (
              raster_meta is not None
              and raster_meta.get("quicklook_256_uri") is not None
          )
          if record_type in ("raster_dataset", "vrt_dataset")
          else (dataset.quicklook_256_uri is not None),

    - DO NOT touch the raster_meta forwarding block at lines 411-452. The new key flows through `_row_to_meta` but is consumed exclusively by the predicate at line 312.
    - DO NOT change the function signature. `raster_meta` is already a keyword arg.

    Edit `backend/tests/test_quicklook_predicate.py`:

    - Add imports at top: `from app.processing.raster.models import RasterAsset` and `from app.processing.raster.queries import fetch_raster_meta_one`.
    - Add the `_create_raster_quicklook_dataset` helper (see <behavior>). Use `record_type` to switch between raster_dataset and vrt_dataset; do NOT branch on `include_vrt` for the queries call — `fetch_raster_meta_one`'s default `include_vrt=True` is fine for both record types.
    - Add the five new tests described in <behavior>, placed AFTER the existing 4 tests, each with the standard double-rule comment separator the file already uses.
    - Test 5 (no-leak) MUST call `dataset_to_ogc_record(..., raster_meta=raster_meta)` and then `assert "quicklook_256_uri" not in result["properties"]`.
    - For raster fixtures: when calling `dataset_to_ogc_record`, pass `raster_meta=` (fetched via `fetch_raster_meta_one`). The vector tests do NOT pass `raster_meta` — they exercise the default `raster_meta=None` path through the new dispatch, which must continue to return `dataset.quicklook_256_uri is not None`.

    Constraints (reinforced):
    - No other files touched. Run `git status` after edits and verify the modified set is exactly `backend/app/processing/raster/queries.py`, `backend/app/modules/catalog/search/service_records.py`, `backend/tests/test_quicklook_predicate.py`, and (newly created) `.planning/quick/260515-ilt-fix-has-quicklook-raster-vrt-dispatch/260515-ilt-PLAN.md` + (when done) the SUMMARY.
    - No new test file. No script. No migration. No frontend.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/raster/queries.py app/modules/catalog/search/service_records.py tests/test_quicklook_predicate.py && uv run ruff format --check app/processing/raster/queries.py app/modules/catalog/search/service_records.py tests/test_quicklook_predicate.py && uv run pytest tests/test_quicklook_predicate.py -x -v</automated>
  </verify>
  <done>
    - `_row_to_meta` in `queries.py` returns a dict containing `"quicklook_256_uri"` (verified via `grep -n quicklook_256_uri backend/app/processing/raster/queries.py` showing at least three matches: one in `_row_to_meta`, two in `columns` lists).
    - `service_records.py:312` no longer reads `dataset.quicklook_256_uri` unconditionally — it dispatches on `record_type`.
    - `pytest backend/tests/test_quicklook_predicate.py -x -v` runs 9 tests (4 existing + 5 new), all PASS.
    - `ruff check` + `ruff format --check` clean on all three modified files.
    - `git status` shows exactly the three source files + the plan + (later) SUMMARY in `.planning/quick/260515-ilt-fix-has-quicklook-raster-vrt-dispatch/` modified. No frontend, no migrations, no other test files.
  </done>
</task>

<task type="auto" tdd="false">
  <name>Task 2 — Regression sweep: full search-related test set + smoke against live raster record</name>
  <files></files>
  <action>
    Run the broader regression set affected by the predicate change. No code edits in this task — purely verification.

    1. Run the OGC record properties suite (covers raster STAC field forwarding — the adjacent block to our edit):

           cd backend && uv run pytest tests/test_ogc_record_properties.py -x -v

    2. Run the search-router suite (covers `_build_search_assets_bulk` and `_build_raster_assets`):

           cd backend && uv run pytest tests/test_search_router.py -x -v 2>&1 | tail -40

       If `test_search_router.py` does not exist, substitute with: `cd backend && uv run pytest -k "search" -x -v 2>&1 | tail -60`.

    3. Run the raster tiles suite (sanity check that RasterAsset fixtures still resolve):

           cd backend && uv run pytest tests/test_raster_tiles.py -x -v 2>&1 | tail -30

    4. **Live smoke (best-effort — if the local stack is up, OTHERWISE record "stack down — skipped" in SUMMARY):**

       - Find a raster record id from the local DB:

             docker compose exec db psql -U geolens -d geolens -c "SELECT d.id FROM catalog.datasets d JOIN catalog.records r ON d.record_id = r.id JOIN raster.raster_assets ra ON ra.dataset_id = d.id WHERE r.record_type = 'raster_dataset' AND ra.quicklook_256_uri IS NOT NULL LIMIT 1;"

       - Hit the OGC items endpoint for that record:

             curl -s "http://localhost:8080/api/collections/datasets/items/<ID>" | jq '.properties.has_quicklook, .properties.quicklook_256_uri // "absent"'

         Expected output: `true` then `"absent"` (predicate true; no leak).

       - For contrast, hit a `raster_dataset` record where `quicklook_256_uri IS NULL` (replace WHERE clause) and confirm `false` / `"absent"`.

       - Capture the curl outputs in SUMMARY.

    5. **Visual confirmation (optional, only if stack up):** Reload the Search page in the browser at http://localhost:8080. Confirm a raster dataset card now shows a thumbnail (the GET to `/api/datasets/<id>/quicklook?size=256` should fire and return 200). If using Playwright MCP, drive it yourself per the `feedback_playwright_mcp_self_verify` memory; otherwise leave the browser-check as a note for the user.

    Record the outcome of each step in the SUMMARY (PASS counts for each pytest run, curl response bodies, visual confirmation status).
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_ogc_record_properties.py tests/test_quicklook_predicate.py tests/test_raster_tiles.py -x -v 2>&1 | tail -20</automated>
  </verify>
  <done>
    - All three pytest suites (test_ogc_record_properties, test_quicklook_predicate, test_raster_tiles) pass with no regressions.
    - `-k "search"` sweep clean (or test_search_router.py if it exists).
    - SUMMARY records either (a) live curl outputs proving predicate is True with no `quicklook_256_uri` leak in properties, or (b) "stack down — live verification skipped" with rationale.
  </done>
</task>

</tasks>

<verification>
- `uv run pytest backend/tests/test_quicklook_predicate.py -x -v` — 9/9 PASS.
- `uv run pytest backend/tests/test_ogc_record_properties.py backend/tests/test_raster_tiles.py -x -v` — clean.
- `uv run ruff check backend/app/processing/raster/queries.py backend/app/modules/catalog/search/service_records.py backend/tests/test_quicklook_predicate.py` — clean.
- `uv run ruff format --check ...` — clean on all three files.
- `git diff --stat` shows exactly: `queries.py` (~3 line additions), `service_records.py` (~6 line additions, 1 deletion), `test_quicklook_predicate.py` (~150 line additions for helper + 5 tests). No other files in the diff.
- Optional live check: `curl /api/collections/datasets/items/<raster-id>` returns `has_quicklook: true` for a raster_dataset with a non-null `RasterAsset.quicklook_256_uri`, and the response properties do not contain a `quicklook_256_uri` field.
</verification>

<success_criteria>
- For raster_dataset and vrt_dataset records, the OGC search response now reports `has_quicklook=True` when (and only when) the underlying `RasterAsset.quicklook_256_uri` is non-null.
- No regression on vector_dataset / table — the existing 4 tests in `test_quicklook_predicate.py` still pass.
- The OGC response properties do not leak `quicklook_256_uri` as a public field — confirmed by `test_raster_response_does_not_leak_quicklook_uri_property`.
- Files touched: exactly `backend/app/processing/raster/queries.py`, `backend/app/modules/catalog/search/service_records.py`, `backend/tests/test_quicklook_predicate.py`. No frontend, no migrations, no new scripts, no other test files.
- Once the backend is in place, the frontend (which already gates on `properties.has_quicklook`) will start showing raster thumbnails in search and Builder dataset panels with zero frontend changes.
</success_criteria>

<output>
Create `.planning/quick/260515-ilt-fix-has-quicklook-raster-vrt-dispatch/260515-ilt-SUMMARY.md` when done — record:
- Diff stat for the three modified files (line counts).
- `pytest test_quicklook_predicate.py` result (e.g., "9/9 PASS in 0.x s").
- `pytest test_ogc_record_properties.py` + `test_raster_tiles.py` regression results.
- Live verification disposition: applied curl outputs (raster_dataset with URI → has_quicklook=true; raster_dataset without URI → has_quicklook=false; no `quicklook_256_uri` leak in either) OR "stack down — skipped" with rationale.
- Visual / Playwright confirmation status if applicable.
- Confirmation that the change is purely backend (`git status` shows no frontend files).
</output>
