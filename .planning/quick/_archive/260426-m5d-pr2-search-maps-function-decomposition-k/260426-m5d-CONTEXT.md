---
name: PR2 search/maps function decomposition - Context
description: Locked decisions for KISS-1, KISS-2, PERF-6 before planning
type: quick-task-context
status: locked
gathered: 2026-04-26
---

# Quick Task 260426-m5d: PR2 search/maps function decomposition (KISS-1, KISS-2, PERF-6) - Context

**Gathered:** 2026-04-26
**Status:** Ready for planning
**Parent audit:** `docs-internal/audits/post-impl-20260426-HANDOFF.md` (PR 2 section)

<domain>
## Task Boundary

Continue PR2 from the post-impl 2026-04-26 handoff: three findings bundled as one quick task, each shipped as an atomic commit.

- **KISS-1** — Split `search_datasets` (`backend/app/modules/catalog/search/service.py:619`, 222-line function). Extract `_apply_search_only_filters`, `_resolve_sort_order`, `_run_rrf_merge`. Target: `search_datasets` < 80 lines after refactor.
- **KISS-2** — Split `_handle_search` (`backend/app/modules/catalog/search/router.py:340-481`, 254-line handler). Extract `_bulk_fetch_dataset_metadata` collapsing the four inline bulk-fetch blocks (assets, raster meta, VRT source_count, ST_AsGeoJSON) into one helper that returns `(stac_assets, raster_meta, geojson_extents)`.
- **PERF-6** — Eliminate post-save re-fetch in `update_map_endpoint` / `duplicate_map_endpoint` (`backend/app/modules/catalog/maps/router.py:421-436`). Refactor `update_map` / `duplicate_map` in `service.py` to return the response shape directly.

**Out of scope:** KISS-7, KISS-8 (signature refactors deferred per handoff). Audit-router enterprise gating WIP is on `wip/audit-enterprise-gate` branch and is not part of this PR.

**Baseline:** `main` is clean — 1970 passed / 17 skipped before starting (verified 2026-04-26).
</domain>

<decisions>
## Implementation Decisions

### KISS-2 helper module location
**Decision:** `_bulk_fetch_dataset_metadata` lives as a module-private helper at the bottom of `backend/app/modules/catalog/search/router.py`.
**Rationale:** Lowest blast radius; only `_handle_search` uses it. Two of three fetches (STAC assets, GeoJSON extents) aren't raster-specific, so promoting them into `app/processing/raster/queries.py` would expand that module's scope inappropriately. KISS-6 (commit `fa210582`) already moved the raster-only queries (`fetch_raster_meta_bulk`) into `processing/raster/queries.py` — keep that boundary clean.
**Signature:**
```python
async def _bulk_fetch_dataset_metadata(
    db: AsyncSession,
    datasets: list[Dataset],
) -> tuple[
    dict[str, list[dict]],          # stac_assets_by_dataset
    dict[str, dict],                 # raster_meta (with VRT source_count merged in)
    dict[str, str | None],           # extent_geojson_map
]
```
The helper takes the materialized `datasets` list (not just IDs) because the raster-meta path needs to read `record.record_type` to build the `raster_ids` filter.

### PERF-6 approach
**Decision:** Service-level fix. `update_map` and `duplicate_map` in `backend/app/modules/catalog/maps/service.py` return the same 4-tuple shape as `get_map_with_layers`: `(Map, layer_tuples, forked_from_name, owner_username)`.
**Rationale:** Eliminates the re-fetch entirely. The router stops calling `get_map_with_layers` after save, just builds the response from what the service returned. Cheaper-but-uglier alternative (joinedload + inline tuple-build) was rejected because it duplicates response-build logic between save and get paths.
**Watch-out (from handoff):** `MapLayer` ordering must respect `sort_order`. Add `order_by(MapLayer.sort_order)` to the relationship or to the in-session collection sort before returning.

### KISS-1 RRF helper signature
**Decision:** `_run_rrf_merge(...)` returns `tuple[list[Dataset], int] | None`. Caller does `if result := await _run_rrf_merge(...): return result`. None means RRF didn't apply (semantic disabled, no text search, or vector backend returned empty) — fall through to standard sort path.
**Rationale:** Mirrors the existing early-return shape inside `search_datasets` (line 775). Optional return is cheap to read and easy to unit-test. Sentinel-tuple alternative (`(applied, datasets, total)`) was rejected as more verbose with no readability gain.
**Signature:**
```python
async def _run_rrf_merge(
    session: AsyncSession,
    filters: SearchFilters,
    stmt: Select,
    rank_col,
    total: int,
) -> tuple[list[Dataset], int] | None
```

### Claude's Discretion
- Helper visibility: single underscore (`_apply_search_only_filters`, `_resolve_sort_order`, `_run_rrf_merge`, `_bulk_fetch_dataset_metadata`). Module-private — not exported.
- Test additions: rely on existing 28 search tests + maps tests for regression coverage. Add minimum-viable unit tests only if a new helper has logic that isn't already exercised end-to-end (RRF helper does — keep that test).
- Commit boundaries: one commit per finding (3 atomic commits). KISS-1 → KISS-2 → PERF-6 (in that order, since KISS-2 doesn't depend on KISS-1's helpers and PERF-6 is in a different module).
- Commit message style: match the recent convention from PR1 commits (`perf(search): ...`, `refactor(search): ...`).
</decisions>

<specifics>
## Specific Ideas

- KISS-1 target line counts (per handoff): `_apply_search_only_filters` ≈ 12 lines, `_resolve_sort_order` ≈ 30 lines, `_run_rrf_merge` ≈ 50 lines. After extraction, `search_datasets` should be under 80 lines.
- KISS-2 expectation: the four inline bulk-fetch blocks (lines 359-432 in current router.py) collapse into one call: `stac_assets, raster_meta, extent_geojson = await _bulk_fetch_dataset_metadata(db, datasets)`.
- PERF-6 verification: confirm `MapLayer.sort_order` ordering still matches by diffing a `GET /maps/{id}` response before and after a save (should be identical to pre-refactor `get_map_with_layers` output).
- Don't change the `/search/datasets` or `/collections/datasets/items` response contracts. Phase 225 API reference site renders against these OpenAPI specs.
</specifics>

<canonical_refs>
## Canonical References

- `docs-internal/audits/post-impl-20260426-HANDOFF.md` — PR 2 section (lines 92-130) for full per-finding context.
- `docs-internal/audits/post-impl-20260426.md` — Section 6 (Prioritized Action Items), Section 9 (Explicitly NOT Flagged).
- PR 1 precedent commits: `217eafcf`, `7ed5ca15`, `7aebc4d8`, `dd81ec57` — same handoff, same review-loop discipline applied.
- KISS-6 boundary: commit `fa210582` (RasterAsset bulk-fetch consolidation) — keep `processing/raster/queries.py` raster-only.
- Test suites that must remain green: `tests/test_search.py` (28 tests), `tests/test_hybrid_search.py`, `tests/test_search_facets.py`, `tests/test_maps.py`.
</canonical_refs>
