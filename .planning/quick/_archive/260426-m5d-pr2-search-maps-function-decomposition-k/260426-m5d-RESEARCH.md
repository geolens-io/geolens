---
name: PR2 search/maps function decomposition - Research
description: Pitfalls + concrete signatures grounded in file:line citations
type: quick-task-research
status: ready
researched: 2026-04-26
---

# Quick Task 260426-m5d — Research

**Confidence:** HIGH (every signature, ordering, and pitfall verified against current source).

## TL;DR

- **PR1 cache contract is preserved naturally.** Cache lookup/write happens in `_handle_search` at lines 331-345 (read) and 546-548 (write), entirely *upstream* of the four bulk-fetch blocks (lines 359-432). KISS-2 only refactors the post-`search_datasets()` body, so the cache key construction, TTL, and JSON round-trip stay byte-for-byte identical. **No PR1 invariant is at risk.**
- **KISS-1 must thread `(stmt, has_text_search, rank_col)` through all three helpers.** `total` is computed at line 712 from `stmt.whereclause`, so the count must remain inline in `search_datasets` (or accept that `_run_rrf_merge` only takes the already-computed `total`, which matches the locked CONTEXT signature). The non-trivial dependency is that `_run_rrf_merge` reads `stmt`, `rank_col`, and the unfetched results — sentinel-tuple discipline is critical.
- **PERF-6 has a hidden trap: `Map` has no `relationship()` to `MapLayer`** (verified `backend/app/modules/catalog/maps/models.py:21-120`). The "in-session ORM state" the handoff alludes to is the bare ORM objects added inside `_replace_layers` / `duplicate_map` — there is no eager-loadable `Map.layers` collection. The service must explicitly re-query `MapLayer` rows joined with `Record`/`Dataset` (the same SELECT that `get_map_with_layers` builds at lines 184-201) to produce the 4-tuple. The "savings" are: skip the second fetch of `Map`, `ForkedMap`, and `User`.

---

## 1. PR1 Cache Contract — What Must Be Preserved Verbatim

| Constant / Helper | File:Line | KISS-2 Risk |
|-------------------|-----------|-------------|
| `SEARCH_CACHE_TTL = 30` | `backend/app/modules/catalog/search/cache.py:18` | None — KISS-2 doesn't touch `cache.py` |
| `is_anon_cacheable(user) -> user is None` | `cache.py:23-29` | None — gate logic stays in `_handle_search` |
| Cache key construction (sha1 over `dataclasses.asdict(filters)` + endpoint + sorted roles + `public_api_url` + `semantic_enabled`) | `cache.py:32-71` | None — key built at `router.py:335-341` BEFORE `search_datasets` call (line 347) |
| Cache lookup short-circuit | `router.py:331-344` | **Must remain upstream of the bulk-fetch helper** |
| Cache write-through | `router.py:546-548` | **Must remain at the very end, AFTER `OGCFeatureCollectionResponse` is assembled** |
| `model_dump(mode='json')` round-trip | `router.py:547` | KISS-2 must not change response assembly — write-through path is unchanged |
| `delete_pattern("catalog:*")` autouse fixture | `tests/test_search_cache.py:36-57` | Already broader than `catalog:search:*` — KISS-2 helper rename doesn't affect tests |

**Key invariant from `260426-ihc-PLAN.md` line 89:** "DO NOT bypass `response_model` by returning a `JSONResponse`." KISS-2 must return the same `OGCFeatureCollectionResponse` — the cache write at line 547 stores `response.model_dump(mode='json')`, and the lookup at line 344 reconstructs via `OGCFeatureCollectionResponse(**cached)`. Any helper that mutates response assembly inline after the bulk-fetches (lines 434-545) breaks this.

**No KISS-2 helper signature changes are needed for cache compat.** The bulk-fetch helper receives `db, datasets` (which are produced by `search_datasets` at line 347, fully *after* the cache lookup) and returns `(stac_assets_by_dataset, raster_meta, extent_geojson_map)`. The cache layer never sees this output directly — it sees the final assembled `response` object. Confirmed.

---

## 2. KISS-1 Extraction Signatures (search_datasets — service.py:612)

`search_datasets` is at `backend/app/modules/catalog/search/service.py:612-837` (currently 226 lines including the docstring and trailing blank). All three extracted helpers should live as module-private functions immediately *above* `search_datasets` to match the existing convention (`_apply_common_filters` is at line 339, above the facet/search functions that consume it).

### Helper 1 — `_apply_search_only_filters` (~12 lines)

Body to extract: `service.py:683-699` (the `record_type / date_from / date_to / vintage_start / vintage_end / cql2_filter` block).

```python
def _apply_search_only_filters(stmt, filters: SearchFilters):
    """Apply filters that belong to /search but NOT to /facets.

    record_type, date_from, date_to, vintage_start, vintage_end, cql2_filter.
    Spatial / keyword / org / srid filters are already applied via
    _apply_common_filters (line 681) and stay shared.
    """
```

- **Return type:** the same `Select` SQLAlchemy construct that's passed in (mirrors `_apply_common_filters` at line 339 — note that helper has no annotated return type either, so following local convention is correct).
- **Imports:** `from app.standards.ogc.filtering import apply_cql2_filter` is currently scoped *inside* the `if filters.cql2_filter:` block at line 697 — keep it scoped inside the helper for the same reason (avoids a top-level import cycle through the OGC module).
- **No async needed** — the extracted block has no `await`.

### Helper 2 — `_resolve_sort_order` (~30 lines)

Body to extract: `service.py:777-822` (the `published_boost` / `freshness_boost` definitions plus the `if/elif/else` chain on `filters.sort_by`).

```python
def _resolve_sort_order(stmt, filters: SearchFilters, has_text_search: bool, rank_col):
    """Apply ORDER BY clauses for the standard (non-RRF) sort path.

    Handles the 5 sort modes: relevance, date_added, title/name,
    last_updated, and the default fallback. ``rank_col`` may be None when
    no text query is present.
    """
```

- **Why `rank_col` parameter:** at line 790, `boosted_rank = rank_col * published_boost * freshness_boost` only fires when `has_text_search` is True. When `has_text_search=False`, `rank_col=None` is fine (the `elif filters.sort_by == "relevance":` branch at line 792 doesn't reference it).
- **Imports `case`, `literal`, `text`, `collate`, `func`** — all already imported at module top (lines 17-25).
- **No async needed.**

### Helper 3 — `_run_rrf_merge` (~50 lines)

Body to extract: `service.py:718-775` (the entire `if use_rrf:` branch, including the inner `if vector_ranks:` and `if page_ids:` branches and the trailing `await _attach_updated_actor_identities(...)` + `return datasets, total`).

**Locked signature (from CONTEXT.md decisions):**

```python
async def _run_rrf_merge(
    session: AsyncSession,
    filters: SearchFilters,
    stmt,            # the FTS+filter Select with rank_col added
    rank_col,        # the labeled rank column reference
    total: int,      # already-computed count
) -> tuple[list[Dataset], int] | None:
    """Execute hybrid FTS+vector RRF merge and return paginated results.

    Returns ``None`` when RRF doesn't apply (semantic disabled, no text
    search, vector backend empty/failed). Caller falls through to the
    standard sort path on None.
    """
```

- The helper internally re-checks `semantic_enabled` and `has_text_search` semantics implicitly through the call site (see "Caller pattern" below). **Do not pass `has_text_search` and `semantic_enabled` separately** — the locked CONTEXT decision is that the caller does the check, and the helper returns `None` only on the "vector backend gave up" path (line 724 `if vector_ranks:` failing).

**Caller pattern at the existing line 718:**

```python
# Replaces lines 714-775
semantic_enabled = await SEMANTIC_SEARCH_ENABLED.get(session)
if (
    semantic_enabled
    and has_text_search
    and filters.q
    and filters.q.strip()
):
    if rrf_result := await _run_rrf_merge(
        session, filters, stmt, rank_col, total
    ):
        return rrf_result
```

- The walrus binding on `rrf_result` matches the CONTEXT snippet (line 64). The double check (`semantic_enabled and has_text_search and filters.q`) stays at the call site to keep the helper focused on the merge — this matches the locked decision.

### What `search_datasets` looks like after extraction

Steps 1-2 (FTS + RBAC at lines 626-678), step 3 (`_apply_common_filters` at line 681), step 4 (now `_apply_search_only_filters(stmt, filters)`), step 5 (count at lines 701-712), step 5b (`_run_rrf_merge` early-return at lines 714-718), step 6 (`stmt = _resolve_sort_order(stmt, filters, has_text_search, rank_col)`), step 7 (paginate at lines 824-825), step 8 (execute + attach + return at lines 827-837). Estimated size: **~75 lines** including blank/comment lines, hitting the <80 target.

---

## 3. KISS-2 Extraction Signature (_bulk_fetch_dataset_metadata)

**Location:** module-private helper at the bottom of `backend/app/modules/catalog/search/router.py` (per CONTEXT.md decision — keeps blast radius minimal, leaves `processing/raster/queries.py` raster-only as KISS-6 left it).

**Body to extract:** `router.py:359-432` (74 lines: 4 inline blocks for STAC assets, raster meta, VRT source_count, ST_AsGeoJSON extents).

**Locked signature (from CONTEXT.md):**

```python
async def _bulk_fetch_dataset_metadata(
    db: AsyncSession,
    datasets: list[Dataset],
) -> tuple[
    dict[str, list[dict]],   # stac_assets_by_dataset, keyed by str(dataset_id)
    dict[str, dict],          # raster_meta with VRT source_count merged in
    dict[str, str | None],    # extent_geojson_map: dataset_id -> ST_AsGeoJSON output
]:
    """Bulk-fetch the three pre-render maps used by dataset_to_ogc_record.

    Takes the materialized datasets list (not just IDs) because the raster
    branch needs ``record.record_type`` to filter the raster_ids set.
    """
```

### Why pass `datasets: list[Dataset]` not `dataset_ids: list[uuid.UUID]`

- Verified at `router.py:384-388`: `raster_ids = [d.id for d in datasets if getattr(d.record, "record_type", None) in ("raster_dataset", "vrt_dataset")]`. This needs `d.record.record_type`, which is already eagerly loaded by `search_datasets` via `selectinload(Dataset.record)` at `service.py:634-636`. Passing only IDs would force a re-query of `Record.record_type`.
- The handoff at `post-impl-20260426-HANDOFF.md:114` suggests `dataset_ids` but the locked CONTEXT (line 41-48) correctly chose `datasets`. **Use `datasets`.**

### Internal ordering inside the helper (data dependencies)

The four blocks have *no* execution-order dependencies:

| Block | Inputs | Lines |
|-------|--------|-------|
| 1. STAC assets bulk fetch | `all_dataset_ids` only | `router.py:359-380` |
| 2. Raster meta bulk fetch | `raster_ids` (derived from `datasets[*].record.record_type`) | `router.py:382-392` |
| 3. VRT source_count | `vrt_dataset_ids` (derived from `raster_meta` keys) | `router.py:394-417` |
| 4. ST_AsGeoJSON extents | `all_dataset_ids` only | `router.py:419-432` |

Block 3 reads `raster_meta` (block 2's output), so within the raster path **the existing block-2-then-block-3 ordering must be preserved**. Blocks 1, 2, and 4 are mutually independent — order doesn't matter. Concretely, do not flatten these into a single `gather()` because block 3 mutates `raster_meta` in place at line 416-417.

### Imports inside the helper

The current code imports `DatasetAsset` at line 360, `fetch_raster_meta_bulk` at line 390, and `RasterAsset, VrtGeneration` at line 395 — all *inside* the function body to keep the top-level import surface minimal and avoid the raster module being loaded for every search request. **Preserve these as function-local imports inside the helper.** No new top-level imports.

### Caller pattern (replaces router.py:359-432)

```python
stac_assets_by_dataset, raster_meta, extent_geojson_map = (
    await _bulk_fetch_dataset_metadata(db, datasets)
)
```

The downstream `features = [dataset_to_ogc_record(...) for d in datasets]` at line 434 stays unchanged — it consumes the three maps via `.get(str(d.id))`.

---

## 4. PERF-6 Service Shape

### Current return shapes

| Function | File:Line | Returns |
|----------|-----------|---------|
| `update_map` | `service.py:343-396` | `Map` (refreshed in-session, line 395) |
| `duplicate_map` | `service.py:574-647` | `tuple[Map, int]` (new_map, excluded_layer_count) |
| `get_map_with_layers` | `service.py:157-205` | `tuple[Map \| None, list[tuple], str \| None, str \| None]` |

### Target 4-tuple shape (from `get_map_with_layers`, line 160)

```python
tuple[
    Map | None,
    list[tuple],            # 10-element rows: (MapLayer, title, geometry_type, table_name, spatial_extent, column_info, feature_count, sample_values, record_type, is_3d)
    str | None,             # forked_from_name
    str | None,             # owner_username
]
```

For `duplicate_map`, also need to keep `excluded_layer_count: int` — proposal: return a 5-tuple `(new_map, layer_tuples, forked_name, owner_username, excluded_count)`, OR keep the 4-tuple shape and return the count separately. **Recommendation:** keep the 4-tuple consistent and return `(new_map_4tuple, excluded_count)` as `tuple[<4-tuple>, int]` to mirror the current `tuple[Map, int]` shape — minimal caller-side churn. Final shape:

```python
async def update_map(...) -> tuple[Map, list[tuple], str | None, str | None]: ...

async def duplicate_map(...) -> tuple[
    tuple[Map, list[tuple], str | None, str | None],  # the 4-tuple
    int,                                                 # excluded_layer_count
]: ...
```

Alternative for `duplicate_map`: flatten to a 5-tuple. Either is defensible; the 5-tuple is shorter at the call site but mixes two concerns. Pick whichever the planner prefers; 5-tuple is slightly more idiomatic with the rest of the file.

### CRITICAL: Map has no `MapLayer` relationship

Verified in `backend/app/modules/catalog/maps/models.py:21-120`: the `Map` class has zero `relationship()` declarations — no `Map.layers` exists. Likewise, `MapLayer` (lines 83-120) declares only `ForeignKey` columns, never `relationship(back_populates=...)`.

**Consequence:** the "in-session ORM state" that PERF-6 wants to leverage is just a bag of `MapLayer` instances `session.add()`-ed inside `_replace_layers` (line 469) or `duplicate_map` (line 644). There is no eager-loaded collection on `map_obj` to inspect. Reading them back requires *either* (a) tracking the added objects in a list and using them directly (no DB round-trip but no `Record.title` etc.), or (b) re-running the same SELECT that `get_map_with_layers` uses at lines 184-201 (one DB round-trip vs the current two — saves the redundant `Map` + `ForkedMap` + `User.username` query block at lines 167-178).

### Recommended implementation

Add a `MapLayer.sort_order`-ordered SELECT inside `update_map` and `duplicate_map` that reads everything `get_map_with_layers`'s second SELECT (lines 184-201) reads, **plus** computes `forked_from_name` and `owner_username` from the in-session `Map` object's `forked_from` and `created_by` fields. Two minimal helpers:

```python
async def _fetch_layer_rows_ordered(
    session: AsyncSession, map_id: uuid.UUID
) -> list[tuple]:
    """Same SELECT as get_map_with_layers lines 184-201."""
    stmt = (
        select(
            MapLayer, Record.title, Dataset.geometry_type, Dataset.table_name,
            Record.spatial_extent, Dataset.column_info, Dataset.feature_count,
            Dataset.sample_values, Record.record_type, Dataset.is_3d,
        )
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order)
    )
    return [tuple(row) for row in (await session.execute(stmt)).all()]


async def _resolve_forked_and_owner(
    session: AsyncSession, map_obj: Map
) -> tuple[str | None, str | None]:
    """One query for forked_from name + owner username. Both nullable."""
    forked_name: str | None = None
    if map_obj.forked_from is not None:
        forked_name = (
            await session.execute(
                select(Map.name).where(Map.id == map_obj.forked_from)
            )
        ).scalar_one_or_none()
    owner_username: str | None = None
    if map_obj.created_by is not None:
        owner_username = (
            await session.execute(
                select(User.username).where(User.id == map_obj.created_by)
            )
        ).scalar_one_or_none()
    return forked_name, owner_username
```

Then refactor `get_map_with_layers` to call both helpers internally — preserves the existing API, eliminates duplication, and `update_map` / `duplicate_map` use the same helpers to assemble their 4-tuples in-session. Net: still **two queries** post-mutation (layers SELECT + forked/owner combined or separate) instead of three (the current `get_map_with_layers` does one combined Map+forked+owner query at lines 167-178 and one layers query at 184-202). Modest improvement; the real PERF win comes from eliminating the redundant `await get_map(db, map_id)` already-done lookup in `update_map_endpoint` at `router.py:372`.

**Even cheaper alternative:** since `update_map` already has `map_obj` in-session and refreshed (`service.py:395`), and `_replace_layers` just inserted fresh `MapLayer` rows, the layers SELECT *must* run anyway to denormalize `Record.title`/`Dataset.geometry_type`/etc. — there's no shortcut for that data. The forked/owner query also stays. **Conclusion: PERF-6's saving is exactly the elimination of the second `Map` + `ForkedMap` + `User` join (lines 167-178 of `get_map_with_layers`), saving ~1 round-trip.**

### MapLayer.sort_order ordering

Verified that `get_map_with_layers` orders explicitly via `.order_by(MapLayer.sort_order)` at `service.py:200`. There is **no relationship-level `order_by`** to leverage (no relationship exists). The new helper `_fetch_layer_rows_ordered` MUST include the same `.order_by(MapLayer.sort_order)` clause. **Do not rely on insertion order from `_replace_layers` at lines 421-468** — `session.add()` ordering is not preserved across a flush and a subsequent SELECT.

The same ordering is also enforced explicitly by `duplicate_map` at line 613 (`.order_by(MapLayer.sort_order)`) when copying source layers. Preserve that.

---

## 5. Test Inventory — High-Signal Tests for Each Finding

### KISS-1 (search_datasets) — likely behavior-change catchers

All tests live in `backend/tests/`.

| File | Test | Why high-signal |
|------|------|------------------|
| `test_search.py:210` | `test_search_text_match` | Exercises `_build_text_filter` + ranking — KISS-1 helper 2 path |
| `test_search.py:270` | `test_search_bbox_intersects` | Exercises `_apply_common_filters` (untouched, but regression catch) |
| `test_search.py:337` | `test_search_filter_by_keywords` | Exercises shared filter stack |
| `test_search.py:396` | `test_search_filter_by_date_range` | Directly hits `_apply_search_only_filters` (date_from/date_to) |
| `test_search.py:445` | `test_search_filter_by_vintage` | Directly hits `_apply_search_only_filters` (vintage_start/vintage_end) |
| `test_search.py:662` | `test_search_sort_by_name` | Hits `_resolve_sort_order` title branch (collate paths) |
| `test_search.py:680` | `test_search_sort_by_frontend_name_alias` | Hits `_resolve_sort_order` `name` alias |
| `test_search.py:698` | `test_search_sort_by_date_added` | Hits `_resolve_sort_order` `date_added` branch |
| `test_search.py:721` | `test_search_pagination` | Verifies skip/limit applied AFTER sort |
| `test_search.py:763` | `test_search_rbac_private_hidden` | Verifies visibility filter survives extraction |
| `test_search.py:859` | `test_ranking_published_boost` | **CRITICAL** — verifies `published_boost * freshness_boost` math in `_resolve_sort_order` |
| `test_hybrid_search.py:234` | `test_semantic_search_returns_200` | Hits `_run_rrf_merge` happy path |
| `test_hybrid_search.py:264` | `test_semantic_fallback_no_embeddings` | Forces `_run_rrf_merge` to return None (no embeddings → empty `vector_ranks`) |
| `test_hybrid_search.py:301` | `test_semantic_fallback_toggle_off` | Forces `_run_rrf_merge` to never be called (semantic_enabled=False) |
| `test_hybrid_search.py:402` | `test_rrf_ranking_with_embeddings` | **CRITICAL** — verifies RRF merge produces the right ordering |
| `test_hybrid_search.py:451` | `test_compute_rrf_scores_basic` | Pure unit test on `_compute_rrf_scores` — should not be affected |

### KISS-2 (_handle_search bulk-fetch) — likely catchers

| File | Test | Why high-signal |
|------|------|------------------|
| `test_search.py:909` | `test_search_unauthenticated_returns_200` | Anon path — exercises STAC asset bulk fetch (block 1) |
| `test_search.py:816` | `test_ogc_items_search` | OGC `/collections/datasets/items` path — same `_handle_search` shared with `/search/datasets/` |
| `test_search.py:835` | `test_ogc_single_record` | Lookup-by-externalId branch — does NOT call `_handle_search`; safe canary for OGC routing |
| `test_search_cache.py:158` | `test_anon_search_caches_response` | **CRITICAL** — full-body equality check at line 208 catches *any* response shape drift |
| `test_search_cache.py:223` | `test_authed_search_bypasses_cache` | Authed path — confirms bulk-fetch helper produces fresh results |
| `test_search_facets.py:120-229` | All 5 facets tests | Use `get_facet_counts`, NOT `_handle_search` — safe canary that confirms facets path is untouched |

For raster meta and VRT source_count specifically, no dedicated unit tests exist for the bulk-fetch path that I located; behavior is exercised transitively through OGC-record serialization in `test_ogc_items_search` (line 816). **Recommendation:** if the planner wants belt-and-braces coverage, add one targeted test that seeds a raster + a VRT dataset and asserts `raster_meta` keys (`vrt_type`, `source_count`, `gsd`, `bands`) round-trip through `/search/datasets/`. CONTEXT.md "Claude's Discretion" allows skipping if existing coverage is judged sufficient — handoff line 107 only requires `test_search.py + test_hybrid_search.py + test_search_facets.py` to remain green.

### PERF-6 (update_map / duplicate_map) — likely catchers

| File | Test | Why high-signal |
|------|------|------------------|
| `test_maps.py:195` | `test_update_map_name` | Verifies PUT response body has `name`, `description` — minimal smoke |
| `test_maps.py:210` | `test_update_map_viewport` | Verifies viewport fields in PUT response |
| `test_maps.py:267` | `test_update_map_rejects_public_with_non_public_datasets` | Verifies 400 path is NOT broken by service refactor |
| `test_maps.py:307` | `test_update_map_allows_public_with_all_public_datasets` | Verifies layers are present after update |
| `test_maps.py:806` | `test_update_map_widgets` | Verifies a JSONB field round-trips through PUT response |
| `test_maps.py:410` | `test_duplicate_map_success` | Verifies duplicate response has `name` with `(copy)` suffix and a new `id` |
| `test_maps.py:457` | `test_duplicate_map_preserves_layers` | **CRITICAL** — `assert data["layer_count"] == 1` directly asserts that layers are populated in the response |
| `test_maps.py:485` | `test_duplicate_lineage` | **CRITICAL** — `forked_from_id` and `forked_from_name` must populate; verifies `_resolve_forked_and_owner` |
| `test_maps.py:559` | `test_duplicate_rbac_filtering` | Verifies `excluded_layer_count == 1` AND `layer_count == 1` — covers the response-shape branch |
| `test_maps.py:608` | `test_duplicate_all_layers_excluded` | Verifies `layer_count == 0` path (empty layer list) |
| `test_maps.py:712` | `test_excluded_layer_count_in_response` | Locks the `excluded_layer_count` field in the response |
| `test_maps.py:782` | `test_duplicate_preserves_widgets` | JSONB field round-trip on duplicate path |
| `test_maps.py:2127` | `test_layer_type_round_trip_get` | Verifies `layer_type` populates from the layer SELECT — shared infrastructure |
| `test_maps.py:2154` | `test_layer_type_auto_detect_via_put` | **CRITICAL** — verifies layer ordering (`raster_ds.id` at sort_order 0, `vector_ds.id` at sort_order 1) survives PUT response. The assertion uses `dict[str, str]` keyed by dataset_id (line 2181), so it would NOT catch an ordering bug. **Sort-order-specific testing is thin — see Pitfalls below.** |
| `test_maps.py:2232` | `test_show_in_legend_round_trip_via_put` | Boolean field round-trip on PUT |

---

## 6. Pitfalls — Cited

### KISS-1

- **`search_datasets.py:712` reads `stmt.whereclause` to build `count_base`.** This MUST stay inline (not pushed into a helper) because `stmt` is mutated by `_apply_search_only_filters` and the subsequent `cql2_filter` block — the count must reflect those filters. If `_run_rrf_merge` ran *before* the count, the count would include filters but the merge would too, so order is fine. Just don't reorder the count vs. the filter helpers.
- **`service.py:715` reads `SEMANTIC_SEARCH_ENABLED.get(session)` inline.** Per `260426-ihc-PLAN.md:27`, this is also read in `_handle_search` for the cache key; PersistentConfig is process-cached so the double read is cheap. KISS-1 should keep the read inline at line 715 (not move it into `_run_rrf_merge`) — matches the locked CONTEXT.md caller pattern.
- **`service.py:721` reads `filters.q.strip()` — guaranteed non-None by the surrounding `filters.q and filters.q.strip()` check at line 716.** Inside the helper, `filters.q` is `str` not `str | None` at runtime but the type checker won't know that. Either re-check inside the helper or annotate with `assert filters.q is not None`.
- **`service.py:734-735` returns `Dataset.record_id` only.** The PERF-8 trick (strip eager-loads via `.with_only_columns(Dataset.record_id)`) must be preserved verbatim in the helper — losing it re-introduces 4 wasted `selectinload` queries per request. Confirmed comment at lines 727-728.
- **`_attach_updated_actor_identities` is called twice** (line 774 inside RRF, line 835 standard path). After extraction, the RRF call lives inside `_run_rrf_merge` — preserve it. Don't move it into the caller, or you'll attach actors to non-RRF results twice.
- **No circular import risk.** `_run_rrf_merge` uses `_get_vector_ranks` (line 243) and `_compute_rrf_scores` (line 297) — both already in the same module. `apply_cql2_filter` (line 697) is imported lazily inside the function body — preserve that lazy import inside `_apply_search_only_filters`.

### KISS-2

- **`test_db_session` and request-handler sessions are SEPARATE sessions sharing the engine** (`conftest.py:316-325` yields a session distinct from the `override_get_db` factory at `conftest.py:166-170`). KISS-2 is a no-op session-wise (the helper takes the request session) — but if the planner adds a unit test that calls `_bulk_fetch_dataset_metadata` directly with `test_db_session`, ensure datasets created in that session have been **committed** before the helper runs (the existing factories at `test_search_cache.py:147` already do `await session.commit()`).
- **Function-local imports inside the helper are load-bearing** for keeping the raster-module import surface minimal on every search request. Specifically, `from app.processing.raster.models import DatasetAsset` (line 360), `from app.processing.raster.queries import fetch_raster_meta_bulk` (line 390), and `from app.processing.raster.models import RasterAsset, VrtGeneration` (line 395). Don't promote these to top-level imports.
- **`router.py:382-417` mutates `raster_meta` in place** (line 416-417 sets `raster_meta[str(row.dataset_id)]["source_count"] = ...`). This is correct only because the same dict is returned — preserve in-place mutation, do not refactor to a copy-and-return pattern.
- **`getattr(d.record, "record_type", None)` at line 387 is defensive** — `Dataset.record` is `selectinload`-ed in `search_datasets` (line 634) so `.record` is always populated, but the `getattr` with default protects against the `_lookup_by_external_id` path (line 1141) which uses `joinedload`. Since the helper is only called from `_handle_search` (single call site), the defensive `getattr` could be relaxed to `d.record.record_type`. **Recommendation: keep the `getattr` — it adds zero overhead and matches the existing style.**
- **No name-collision risk with `_build_raster_assets`** at `router.py:140-170` — that's the single-dataset helper for `get_collection_item`. Different helper, different signature, can coexist.

### PERF-6

- **`Map` has zero `relationship()` to `MapLayer`** (`maps/models.py:21-120`). No `Map.layers` collection exists. Any plan that says "add `order_by` to the relationship" (handoff line 128) cannot be implemented as written — there is no relationship to add `order_by` to. The fix is: ensure the explicit SELECT in `_fetch_layer_rows_ordered` includes `.order_by(MapLayer.sort_order)`.
- **`update_map` already calls `await session.refresh(map_obj)` at line 395.** The refresh re-reads `Map`'s columns (including `updated_at` which is `onupdate=func.now()` per model line 79). After refactor, retain this refresh — `MapResponse.updated_at` at `router.py:217` reads `map_obj.updated_at`, which the DB-side `onupdate` populates only after a flush + refresh.
- **`duplicate_map` at `service.py:608` calls `session.add(new_map)` followed by `await session.flush()` at line 609.** This populates `new_map.id` (server-default `gen_random_uuid()`). The 4-tuple build must come AFTER this flush. Then `_replace_layers` / the layer-copy loop at lines 624-644 adds `MapLayer` rows; another `flush()` at line 646 ensures they're queryable before the new helper SELECTs them.
- **`update_map_endpoint` calls `await db.commit()` at `router.py:419` BEFORE the re-fetch at line 422.** After PERF-6, the commit must still happen (it's the audit log + map mutation commit), and the new in-session SELECT should run AFTER the commit. SQLAlchemy AsyncSession after commit: the session is still usable, expired objects refresh on access. Order: `update_map` flush → `log_action` → `db.commit()` → new SELECT (within same session, post-commit).
- **`duplicate_map_endpoint` similarly calls `await db.commit()` at `router.py:503` BEFORE re-fetch at line 506.** Same constraint — keep the commit before the new SELECT, or move the commit AFTER the SELECT (cheaper but changes timing semantics; recommend keeping commit-before-SELECT to preserve current observable order).
- **No test asserts MapLayer round-trip order.** `test_layer_type_auto_detect_via_put` at `test_maps.py:2154` asserts `dict[str, str]` keyed by dataset_id (line 2181), losing list order. `test_duplicate_map_preserves_layers` at line 457 only checks `layer_count == 1`. **If the planner wants ordering proven, add a focused test that PUTs layers with `sort_order=[2,0,1]` and asserts the response `layers[*].sort_order` is `[0,1,2]`.** Otherwise, a manual response diff (CONTEXT.md "Specific Ideas" line 79) is the verification step.
- **No circular import risk for the two new helpers** — both stay in `maps/service.py`, use already-imported symbols (`User` at line 19, `Map`/`MapLayer` at line 22, `Dataset`/`Record`/`DatasetGrant` at line 21, `aliased`/`select` at lines 15-17).

---

## 7. Sources

- `backend/app/modules/catalog/search/service.py` — read lines 1-120, 200-360, 600-840 (full `search_datasets` + supporting helpers)
- `backend/app/modules/catalog/search/router.py` — read full file (1353 lines) with focus on `_handle_search` (lines 315-548) and the OGC `/collections/datasets/items` consumer (lines 1223-1284)
- `backend/app/modules/catalog/search/cache.py` — read full file
- `backend/app/modules/catalog/maps/service.py` — read full file
- `backend/app/modules/catalog/maps/router.py` — read lines 1-525 (covers update + duplicate endpoints and shared helpers)
- `backend/app/modules/catalog/maps/models.py` — read full file (confirmed no `relationship()` declarations)
- `backend/app/modules/catalog/maps/schemas.py` — grepped for response shapes
- `backend/tests/conftest.py` — read lines 125-340 for fixture model
- `backend/tests/test_search_cache.py` — read full file (PR1 test pattern reference)
- `backend/tests/test_search.py`, `tests/test_hybrid_search.py`, `tests/test_search_facets.py`, `tests/test_maps.py` — grepped for test names
- `.planning/quick/260426-ihc-pr1-search-hot-path-caching-perf-2-perf-/260426-ihc-PLAN.md` — read header + first 150 lines for cache contract
- `.planning/quick/260426-m5d-pr2-search-maps-function-decomposition-k/260426-m5d-CONTEXT.md` — locked decisions
- `docs-internal/audits/post-impl-20260426-HANDOFF.md:92-130` — PR 2 handoff context
- Commits `217eafcf`, `7ed5ca15`, `7aebc4d8`, `dd81ec57` (PR1) — referenced via PLAN.md, no new behavior beyond what `cache.py` exposes

## RESEARCH COMPLETE

**File:** `/Users/ishiland/Code/geolens/.planning/quick/260426-m5d-pr2-search-maps-function-decomposition-k/260426-m5d-RESEARCH.md`

**TL;DR:**
1. PR1 cache contract is preserved without effort — KISS-2 only refactors the post-`search_datasets()` body, while cache lookup/write live entirely upstream/downstream of the bulk-fetch blocks. No cache-key field, TTL, or `model_dump(mode='json')` round-trip needs touching.
2. PERF-6's "in-session ORM state" idea hits a wall: `Map` has zero `relationship()` to `MapLayer`. The actual saving is eliminating the second `Map`+`ForkedMap`+`User` join (~1 round-trip) — the layer-row SELECT and the forked/owner lookups must still run.
3. Test coverage for the 3 findings is good for behavior but thin for ordering — `test_ranking_published_boost` and `test_rrf_ranking_with_embeddings` lock the search math, but no test asserts `MapLayer.sort_order` round-trips through PUT/duplicate. Recommend a focused ordering test for PERF-6 as the single belt-and-braces addition (CONTEXT allows discretion).
