# Requirements: GeoLens v13.6 Catalog Maps/Search Service Decomposition

**Defined:** 2026-05-03
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v13.6 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Maps Service Decomposition

- [ ] **MAPS-01**: Maintainer can continue importing the existing public map service API from `app.modules.catalog.maps.service` after decomposition without updating router, AI, or test call sites outside the planned migration.
- [ ] **MAPS-02**: Maintainer can work on map CRUD, ownership, listing, and layer replacement logic in focused modules instead of one 1,300-line service file.
- [ ] **MAPS-03**: Authenticated user can create, list, read, update, duplicate, and delete maps with the same response schema, ownership checks, visibility rules, and layer sort order as before the split.
- [ ] **MAPS-04**: Authenticated user can add and remove map layers with the same dataset access checks, default style generation, layer type inference, and permission behavior as before the split.
- [ ] **MAPS-05**: Public or anonymous user can use visibility checks, share tokens, shared map rendering, thumbnails, token revocation, and dataset-in-use checks with the same behavior as before the split.
- [ ] **MAPS-06**: Maintainer can verify map service behavior with focused regression tests that cover map CRUD, layer round-trips, sharing, thumbnails, and public viewer access.

### Search Service Decomposition

- [ ] **SRCH-01**: Maintainer can continue importing the existing public search service API from `app.modules.catalog.search.service` after decomposition, including `SearchFilters`, `search_datasets`, `get_facet_counts`, `search_collections`, and OGC record helpers.
- [ ] **SRCH-02**: Maintainer can work on common filters, facet counts, collection search, dataset search, semantic/RRF merge, and OGC record conversion in focused modules instead of one 1,300-line service file.
- [ ] **SRCH-03**: User can run dataset search with the same text, spatial, temporal, tag, organization, CRS, record type, CQL2, sort, pagination, RBAC, and publication filtering behavior as before the split.
- [ ] **SRCH-04**: User can retrieve facet counts, collection search results, collection metadata, collection items, queryables, sortables, and record schema responses with the same response shapes and cache semantics as before the split.
- [ ] **SRCH-05**: OGC, STAC, and AI callers can consume search results, OGC record conversion, assets, themes, and time metadata through the existing public contracts after the split.
- [ ] **SRCH-06**: User can use semantic and hybrid search with the same embedding-provider dispatch, RRF behavior, fallback behavior, and actor identity enrichment as before the split.

### Boundary Guards

- [ ] **BOUND-01**: Maintainer can rely on `catalog.maps.service` and `catalog.search.service` as stable public façades; external modules cannot import private split modules directly.
- [ ] **BOUND-02**: Maintainer can run an architecture guard that fails when the map or search façade grows back into a god module or when private decomposition modules exceed the agreed size budget without an explicit allowlist.
- [ ] **BOUND-03**: Maintainer can run the existing catalog/processing boundary guards after the split with no module-level `catalog ↔ processing` cycle regressions.
- [ ] **BOUND-04**: Maintainer can update any source-introspection regression tests to assert behavior across the façade plus helper modules, avoiding brittle checks tied to inline implementation blocks.

### Verification and Close Gate

- [ ] **QUAL-01**: Maintainer can run focused backend verification for maps and search, including `test_maps`, `test_search`, hybrid search, search facets, search cache, and VRT search enrichment tests.
- [ ] **QUAL-02**: Maintainer can run backend lint/format checks for the touched catalog modules with no ruff or formatting violations.
- [ ] **QUAL-03**: Maintainer can review a close-gate audit that records decomposition results, requirement coverage, residual risks, and confirms no unresolved P0/P1 findings for v13.6.

## Future Requirements

Deferred to future releases. Tracked but not in the current roadmap.

### Catalog Refactors

- **ROUTER-01**: Maintainer can split `catalog/search/router.py` into smaller endpoint modules while preserving OpenAPI route tags and cache behavior.
- **ROUTER-02**: Maintainer can split `catalog/maps/router.py` into smaller endpoint modules while preserving map-builder and public-viewer API behavior.
- **STAC-01**: Maintainer can profile and refactor STAC route session usage after collecting query and connection-pool evidence.

### Platform Roadmap

- **MANF-01**: User can define a `geolens.yaml` catalog manifest for reproducible catalog publishing.
- **CONN-01**: Admin can persist connector definitions and credentials for scheduled imports.
- **TENANT-01**: Operator can scope catalog, identity, and audit data by tenant for future Cloud deployment.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New map authoring features | This milestone preserves behavior while restructuring service code. |
| Search relevance or ranking changes | The split must keep existing result behavior stable. |
| New search filters or connector sources | Connector and manifest work remains backlog. |
| Frontend UI redesign | Only test or type updates required by response-contract preservation are in scope. |
| Search or maps router decomposition | Valuable follow-up, but this milestone targets the service layer first. |
| STAC route performance refactor | Requires profiling and does not share the primary maps/search service write set. |
| Tenant scoping, Helm/AMI/SBOM, `geolens-schemas` | Separate platform/distribution milestones. |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MAPS-01 | 236 | Pending |
| MAPS-02 | 236 | Pending |
| MAPS-03 | 236 | Pending |
| MAPS-04 | 236 | Pending |
| MAPS-05 | 236 | Pending |
| MAPS-06 | 236 | Pending |
| SRCH-01 | 237 | Pending |
| SRCH-02 | 237 | Pending |
| SRCH-03 | 237 | Pending |
| SRCH-04 | 237 | Pending |
| SRCH-05 | 237 | Pending |
| SRCH-06 | 237 | Pending |
| BOUND-01 | 238 | Pending |
| BOUND-02 | 238 | Pending |
| BOUND-03 | 238 | Pending |
| BOUND-04 | 238 | Pending |
| QUAL-01 | 239 | Pending |
| QUAL-02 | 239 | Pending |
| QUAL-03 | 239 | Pending |

**Coverage:**
- v13.6 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-05-03*
*Last updated: 2026-05-03 after roadmap creation*
