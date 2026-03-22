# ADR-001: v12.0 Record-First Discovery Architecture

**Status:** Accepted
**Date:** 2026-03-16

## Context

GeoLens has evolved from an MVP catalog into a full geospatial platform spanning vector datasets, raster COGs, VRT mosaics, collections, semantic search, spatial intelligence, and cloud distribution (v1.0 through v11.0). The catalog serves both human users browsing a UI and machine clients consuming OGC Records and tile endpoints.

v12.0 transforms GeoLens from a catalog-with-search into a record-first discovery platform. Users need faceted search that understands record types, normalized assets that reflect each modality correctly, STAC 1.1 export for raster interoperability with the broader geospatial ecosystem, predictable VRT lifecycle management, and a unified detail page that adapts to the record type being viewed. The 8 decisions below establish the architectural foundation for these capabilities across phases 185-189.

## Decision 1: Record Type Taxonomy

**Decision:** The system recognizes four record types: `collection`, `vector_dataset`, `raster_dataset`, and `vrt_dataset`. Source COGs, individual features, and processing artifacts are excluded as first-class record types.

**Rationale:** These four types map directly to the data modalities GeoLens manages. Collections are organizational containers; vector, raster, and VRT datasets each have distinct ingestion pipelines, asset structures, and rendering paths. COGs are implementation details of VRTs (they are sources, not standalone records in the catalog). Individual features and processing artifacts are transient or internal -- surfacing them as records would add noise without discovery value.

**Alternatives Considered:**
- Include COGs as a fifth record type. Rejected because COGs are always consumed through their parent VRT; promoting them creates duplicate search results and confuses the "one record = one discoverable thing" model.
- Collapse raster and VRT into a single "raster" type. Rejected because VRTs have fundamentally different lifecycle concerns (multi-source, regeneration, source health) that the UI and API must handle differently.

**Downstream Impact:**
- Phase 185 (Search & Discovery): SRCH-01 facets filter by `record_type`; SRCH-03 collection discovery treats collections as a distinct type
- Phase 186 (Asset Normalization): ASSET-01 uses record type to determine which asset links to emit
- Phase 187 (STAC Export): STAC-01 serializer maps record type to STAC item type; only raster/VRT types are STAC-eligible
- Phase 189 (UI Polish): POLISH-01 renders type-specific detail panels based on record type

## Decision 2: Collection Ranking

**Decision:** Collections are de-ranked relative to datasets in search results by default. Collections receive a ranking boost on high-relevance or exact name matches.

**Rationale:** Users searching the catalog typically want datasets -- the actual data they can view, download, or integrate. Collections are organizational containers that are less frequently the target of a search. However, when a user types an exact collection name, that collection should surface prominently rather than being buried under its member datasets.

**Alternatives Considered:**
- Equal ranking for collections and datasets. Rejected because collections would dominate results for broad queries (a collection named "Climate Data" would compete with dozens of individual climate datasets).
- Exclude collections from search entirely. Rejected because collections are legitimate discovery targets and excluding them would break drill-down workflows.

**Downstream Impact:**
- Phase 185 (Search & Discovery): SRCH-03 collection search ranking logic implements the de-rank/boost behavior
- Phase 189 (UI Polish): POLISH-05 ranking boosts apply the collection-specific scoring rules

## Decision 3: Publication Lifecycle

**Decision:** Datasets have a publication status enum with states: `draft` > `ready` > `internal` > `published`. Publication status is separate from visibility/access control.

**Rationale:** Visibility (who can see a record) and readiness (is the record complete and curated) are orthogonal concerns. A dataset might be visible to internal users but not yet ready for publication. Conflating these into a single field forces awkward states like "visible but draft" to be represented as special cases. Separating them gives administrators clear workflow stages: draft records are incomplete, ready records await review, internal records are approved for staff use, and published records are available to all consumers including STAC machine clients.

**Alternatives Considered:**
- Boolean `is_published` flag. Rejected because it collapses the workflow into two states, making it impossible to distinguish "work in progress" from "reviewed but internal-only."
- Combine visibility and publication into a single enum. Rejected because it creates a combinatorial explosion of states (draft-private, draft-internal, ready-private, etc.) that is harder to reason about and enforce.

**Downstream Impact:**
- Phase 186 (Asset Normalization): ASSET-05 enforces state transitions; ASSET-06 uses publication status to determine URL security policy
- Phase 187 (STAC Export): STAC-01 and STAC-02 filter to only published records for STAC output
- Phase 189 (UI Polish): POLISH-05 boosts published datasets in search ranking

## Decision 4: STAC Eligibility

**Decision:** All published raster and VRT records are STAC-eligible. Vector datasets and unpublished records are excluded from STAC endpoints.

**Rationale:** STAC (SpatioTemporal Asset Catalog) is designed for raster-centric workflows -- satellite imagery, aerial photography, elevation models. Vector datasets are better served through OGC Records and Features APIs, which are purpose-built for vector data discovery and access. The publication gate ensures only curated, reviewed data reaches STAC consumers, maintaining catalog quality for machine clients that may programmatically ingest everything they find.

**Alternatives Considered:**
- Make all record types STAC-eligible. Rejected because STAC's data model (assets as downloadable files, bands, resolution) maps poorly to vector datasets. Forcing vector data into STAC would produce confusing or misleading metadata.
- This was the natural choice given GeoLens's dual OGC Records + STAC architecture. OGC Records handles all types; STAC handles the raster subset.

**Downstream Impact:**
- Phase 187 (STAC Export): STAC-01 through STAC-06 all filter by published status and raster/VRT record type. This decision is the central gating rule for the entire STAC layer.

## Decision 5: Asset URLs

**Decision:** STAC output uses signed URLs for S3/cloud-stored assets. Local deployments use API proxy URLs for auth-gated access. Thumbnails for published records use public URLs for cacheability.

**Rationale:** STAC machine clients need direct access to asset files (signed URLs) because they download assets programmatically without browser session context. Local deployments behind the API proxy benefit from centralized auth enforcement. Thumbnails are low-risk, small files that benefit from CDN caching and browser preloading -- making them public for published records is safe and improves performance.

**Alternatives Considered:**
- All assets through proxy, even for STAC. Rejected because STAC clients expect direct URLs to assets; routing through a proxy adds latency, requires session management that machine clients lack, and breaks standard STAC client workflows.
- All assets signed, even local. Rejected because local deployments without S3 have no signing infrastructure. The proxy approach leverages the existing auth middleware.

**Downstream Impact:**
- Phase 186 (Asset Normalization): ASSET-06 implements the URL generation strategy per deployment mode and publication status
- Phase 187 (STAC Export): STAC-02 item serializer generates the correct URL type based on storage backend

## Decision 6: stac_assets Transition

**Decision:** Soft merge strategy -- emit both `assets` (new unified dict) and `stac_assets` (legacy key) during a transition period, then deprecate `stac_assets`.

**Rationale:** The existing `stac_assets` field on records is consumed by frontend components and potentially external integrations. A hard cutover would break existing consumers. The soft merge approach lets the frontend migrate to the unified `assets` dict at its own pace while `stac_assets` continues to work. Once all consumers are migrated, `stac_assets` can be removed in a future release.

**Alternatives Considered:**
- Hard cutover: remove `stac_assets` immediately. Rejected because it would require simultaneous backend and frontend changes with no rollback path.
- Keep `stac_assets` permanently alongside `assets`. Rejected because maintaining two representations of the same data indefinitely increases maintenance burden and confusion about which is canonical.

**Downstream Impact:**
- Phase 186 (Asset Normalization): ASSET-02 builds the unified `assets` dict and emits `stac_assets` for backward compatibility; ASSET-07 migrates frontend consumers to `assets`
- Phase 187 (STAC Export): STAC serializer reads from the unified `assets` dict, ignoring the legacy `stac_assets` key

## Decision 7: STAC Architecture

**Decision:** STAC endpoints live under a dedicated `/stac/` router, separate from the existing OGC Records endpoints.

**Rationale:** STAC has its own conformance classes, link structure (self/root/parent/collection), response format, and specification requirements that differ significantly from OGC Records. Mixing STAC-specific logic into the OGC Records router would create extensive conditional branches ("if STAC request, format links differently; if STAC, filter to raster only; if STAC, add STAC extensions"). A dedicated router keeps each concern cleanly separated and independently testable.

**Alternatives Considered:**
- Shared router with content negotiation. Rejected because the response structures are different enough (STAC Items vs OGC Records) that content negotiation alone cannot bridge the gap -- the underlying query logic and link generation also differ.
- This was the natural choice for separation of concerns. The OGC Records router serves the primary catalog API; the STAC router serves the interoperability layer.

**Downstream Impact:**
- Phase 187 (STAC Export): STAC-02 through STAC-05 all implement endpoints under the `/stac/` prefix with their own router, middleware, and conformance declaration

## Decision 8: VRT Regeneration

**Decision:** VRT regeneration is manual-only (triggered by user action). Each regeneration acquires a PostgreSQL advisory lock per VRT. Generation states are: `active`, `regenerating`, `failed`, `superseded`. Regeneration uses atomic swap with rollback on failure. The design accommodates future webhook-triggered regeneration.

**Rationale:** Manual-first regeneration is safer for data integrity -- automatic regeneration on source changes could trigger cascading rebuilds or produce VRTs from partially updated source sets. Advisory locks prevent concurrent regeneration of the same VRT, which would waste resources and risk file corruption. Atomic swap ensures the existing VRT file remains usable if regeneration fails (the old file is preserved until the new one is verified). Generation states give both the API and UI clear status to display.

**Alternatives Considered:**
- Automatic regeneration on source change. Deferred (not rejected) -- the design accommodates future webhook/event-driven regeneration, but launching with manual-only avoids unexpected behavior until usage patterns are understood.
- File-level locking instead of advisory locks. Rejected because PostgreSQL advisory locks integrate with the existing transaction model and are released automatically on connection close, avoiding stale lock files.
- In-place file replacement instead of atomic swap. Rejected because if regeneration fails mid-write, the VRT would be corrupted with no recovery path. Atomic swap preserves the previous version.

**Downstream Impact:**
- Phase 188 (VRT Lifecycle): VRT-01 creates the `vrt_generations` table with status enum; VRT-02 exposes status and history via API; VRT-03 renders generation info in the UI; VRT-04 implements the regeneration endpoint with advisory lock and atomic swap; VRT-05 adds the regenerate button with active-state disabling; VRT-06 adds source health checking

## Consequences

### What These Decisions Enable

- **Type-aware faceted search**: The record type taxonomy (Decision 1) powers facet counts and type-specific filtering, letting users narrow results to exactly the data modality they need.
- **Safe STAC interoperability**: STAC eligibility (Decision 4), asset URL strategy (Decision 5), and the dedicated router (Decision 7) create a clean, standards-compliant STAC layer that serves machine clients without compromising the primary catalog API.
- **Predictable VRT lifecycle**: Manual regeneration with advisory locks and atomic swap (Decision 8) ensures VRTs remain usable through the rebuild process, with clear status visibility for users.
- **Gradual migration path**: The stac_assets soft merge (Decision 6) and publication lifecycle (Decision 3) allow incremental adoption without breaking existing consumers.
- **Intelligent search ranking**: Collection de-ranking (Decision 2) and publication-aware ranking (Decision 3) ensure search results prioritize the most relevant, curated datasets.

### Constraints Accepted

- **No automatic VRT regeneration** in v12.0. Users must manually trigger rebuilds. Future versions may add webhook-driven regeneration once usage patterns are understood.
- **No STAC for vector datasets**. Vector data is served exclusively through OGC Records and Features APIs. STAC consumers will only discover raster and VRT records.
- **Publication status required for STAC visibility**. Unpublished records (draft, ready, internal) are invisible to STAC endpoints, even if they are technically complete. This is intentional -- STAC consumers should only see curated data.
- **Transition period for stac_assets**. Both `assets` and `stac_assets` will coexist temporarily, adding a small maintenance overhead until the deprecation is complete.
