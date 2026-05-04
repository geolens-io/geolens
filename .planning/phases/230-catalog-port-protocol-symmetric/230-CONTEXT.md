# Phase 230: catalog-port-protocol-symmetric - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 230 inverts the remaining module-level `catalog -> processing` import direction. It introduces a symmetric `CatalogPort` Protocol in `backend/app/core/catalog_port.py`, a default implementation that delegates to `app.processing.*`, a `get_catalog_port()` accessor, and an architecture guard that prevents future top-of-file imports from `backend/app/modules/catalog/` into `backend/app/processing/`.

This phase is an architectural boundary cleanup only. It must preserve current API behavior, user-visible behavior, database schema, and test expectations.

</domain>

<decisions>
## Implementation Decisions

### Protocol Shape
- Mirror the Phase 225 `ProcessingPort` pattern in the opposite direction: Protocol in `backend/app/core/catalog_port.py`, default implementation in `backend/app/platform/extensions/defaults.py`, accessor in `backend/app/platform/extensions/__init__.py`.
- Use a single-slot extension accessor (`get_catalog_port()`), not a dict-keyed provider registry. This matches the one active default port for the processing boundary.
- Keep the Protocol surface practical and call-site driven. Expose processing-owned types/helpers needed by catalog modules rather than creating broad pass-through access to all processing internals.

### Migration Scope
- Remove top-of-file imports from `backend/app/modules/catalog/` into `app.processing.*`; function-local deferred imports inside catalog remain allowed by the roadmap, but new deferred imports should prefer living in `DefaultCatalogPort`.
- Prioritize the named high-leverage call sites from the roadmap: `catalog/maps/service.py`, `catalog/layers/service.py`, `catalog/search/service.py`, `catalog/features/service.py`, and the `catalog/datasets/api/router_*.py` modules.
- Keep large service decomposition out of scope. Do not split `catalog/maps/service.py` or `catalog/search/service.py`; those are already tracked as backlog phases 999.21 and 999.22.

### Behavior Preservation
- Preserve public API responses, auth/RBAC behavior, export semantics, ingest/reupload flows, search results, and raster/VRT behavior byte-for-byte where practical.
- Do not add new settings, migrations, provider choices, product gates, or enterprise-only behavior.
- If a processing import exists only for a constant, schema, or ORM class used in FastAPI response typing, prefer narrow Protocol methods or type aliases that keep runtime imports out of catalog module scope.

### Guard And Verification
- Add `test_no_catalog_imports_processing` to `backend/tests/test_layering.py`, mirroring Phase 225's `test_no_processing_imports_catalog` style.
- The guard should fail on top-of-file catalog imports from `app.processing` / `backend.app.processing` and should document that function-local imports are permitted only as transitional/deferred-import boundaries.
- Include a transient negative-control proof: inject a forbidden top-of-file processing import in a catalog module, confirm the guard fails with the offending line surfaced, then revert.
- Run focused tests around migrated call sites plus architecture tests. Full backend suite is desired, but local DB provisioning may block it unless PostGIS + pgvector are available.

### Claude's Discretion
- Exact batching of files into plans and the final Protocol method names are left to research/planning, as long as the public behavior and import-boundary invariant are preserved.
- Planner may decide whether to migrate some already-function-local catalog imports into `DefaultCatalogPort` when doing so reduces complexity without broadening scope.

</decisions>

<specifics>
## Specific Ideas

- Treat Phase 225 as the primary implementation template: small core Protocol, default adapter with deferred imports, platform accessor, seam tests, and an architecture guard.
- Keep the output audit-friendly: each plan should make it easy to prove which import cluster was removed and which tests cover the behavior.

</specifics>

<deferred>
## Deferred Ideas

- Splitting `backend/app/modules/catalog/maps/service.py` remains backlog Phase 999.21.
- Splitting `backend/app/modules/catalog/search/service.py` remains backlog Phase 999.22.
- Share/embed token expiration gating remains backlog Phase 999.23 and is not part of this phase.

</deferred>

---

*Phase: 230-catalog-port-protocol-symmetric*
*Context gathered: 2026-05-03*
