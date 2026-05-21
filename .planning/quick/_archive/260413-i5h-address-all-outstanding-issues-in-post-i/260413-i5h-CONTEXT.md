# Quick Task 260413-i5h: Address all outstanding issues in post-impl-20260413-b audit - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Task Boundary

Address all remaining (unfixed) findings from docs-internal/audits/post-impl-20260413-b.md across all priority levels (P0-P3). Five recent commits already addressed ~20 findings — skip confirmed duplicates.

</domain>

<decisions>
## Implementation Decisions

### Scope
- All priority levels (P0-P3) — comprehensive cleanup
- Skip items already addressed by the 5 recent audit remediation commits (040c0920..2831a00d)

### Commit Strategy
- One commit per audit dimension (KISS, Performance, Cleanup, Type Safety, Resilience)

### Already Fixed (skip these)
- P0: MapErrorBoundary on DatasetHeroMap (040c0920)
- P0: CreateLayerRequest max_length (040c0920)
- P1: Redundant ST_Intersects (ee20ba28)
- P1: api_key plaintext logging (ee20ba28)
- P1: Tile proxy retry concurrency cap (ee20ba28)
- P1: pgvector statement_timeout (ee20ba28)
- P1: structlog redaction (ee20ba28)
- P1: SSE chat tool error propagation (ee20ba28)
- P1: init_tile_pool crash (ee20ba28)
- P1: get_tile_config double DB query (ee20ba28)
- P1: layerDatasetIds unstable reference (d090b557)
- P1: scoped_dataset_ids optional (d090b557)
- P1: record_status str|None (d090b557/ee20ba28)
- P1: S3 CRS validation warning (ee20ba28)
- P2: quicklook frontend (hook, key, test, schema field) (d090b557)
- P2: stac_assets typed as unknown (d090b557)
- P2: DatasetDeleteRequest max_length (ee20ba28)
- P2: OAuthCallbackPage silent failure (2831a00d)
- P3: sort_by → sortBy (ee498834)
- P3: BuilderSidebar React.memo (2831a00d)

</decisions>

<specifics>
## Remaining Findings

### P1 (2 remaining)
1. get_user_roles() uncached — auth/visibility.py:96-106
2. Facet queries sequential — search/service.py:354-567

### P2 (10 remaining)
3. Job-failure boilerplate 14 sites — ingest/tasks.py
4. _build_layer_response 10 params — maps/router.py:73-121
5. config_ops/service raises HTTPException — config_ops/service.py:226,243,330
6. toViewerSyncInput/toAdapterInput dup — ViewerMap.tsx:98-139
7. VrtCreatorForm silent query errors — VrtCreatorForm.tsx:176-196
8. SavedSearches silent fetch error — SavedSearches.tsx:121
9. duplicate_feature_count fields — maps/schemas.py:92,109
10. quicklook backend computation — datasets/schemas.py:132, datasets/helpers.py:70,103
11. SpatialFilterPanel type cast comment — SpatialFilterPanel.tsx:42
12. LayerFilterEditor redundant cast — LayerFilterEditor.tsx:181

### P3 (12 remaining)
13. handleMoveUp/Down duplication — use-builder-layers.ts:118-138
14. prefixed*Id 4 helpers — map-sync.ts:87-101
15. handlePublishToggle/Unpublish dup — DatasetPage.tsx:299-339
16. pendingNavigationAnchor 53-line effect — DatasetPage.tsx:194-247
17. HNSW index default params — embeddings/service.py:155-156
18. Admin jobs poll 30s — use-admin.ts:296
19. DEV console.debug duplicates — use-layer-map-sync.ts
20. API_BASE inconsistency — api/tiles.ts
21. Raw status codes — services/router.py:387, ogc/router.py:439
22. OAuth routes missing response_class — oauth/router.py:69,84
23. _post_reupload_success one-liner — ingest/tasks.py:1341
24. enrich_source_url single-callsite — ingest/tasks.py:996-1000
25. .lower().endswith() x5 — ingest/tasks.py:833-839

</specifics>
