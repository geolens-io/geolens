# Quick Task 260418-d1g: Implement OGC API Import Support - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Task Boundary

Add OGC API — Features as a third supported service type in the GeoLens import pipeline, alongside WFS and ArcGIS FeatureServer. Users can paste an OGC API root URL into the Service tab, GeoLens detects it via landing page probe, lists collections as layers, and imports the selected collection using GDAL's OAPIF driver.

</domain>

<decisions>
## Implementation Decisions

### OGC API Scope
- **Features only** (OGC API — Features Part 1). No Records, Tiles, or Coverages.
- This aligns with GDAL's `OAPIF:` driver and covers the primary use case (importing vector features from an OGC API endpoint).

### Detection Strategy
- **Landing page probe**: Fetch the root URL, check for JSON response with OGC conformance links (`/conformance` or `conformsTo` array).
- No URL pattern fast path — rely on the JSON landing page structure for reliable detection.
- Detection order in `detect_service_type()`: try WFS fast path → ArcGIS fast path → OGC API landing page probe → WFS slow path → ArcGIS slow path.

### Collection Selection
- **One collection = one layer**: Map OGC API collections 1:1 to the existing layer picker UI.
- User selects a single collection to import, same flow as WFS/ArcGIS.
- No batch multi-collection import.

### Claude's Discretion
- Authentication: Support Bearer token (same as WFS) — OGC API commonly uses OAuth2/Bearer.
- GDAL source string: Use `OAPIF:{url}` prefix for ogrinfo and ogr2ogr operations.
- source_format value: `ogcapi_features` to match GDAL convention.
- Pagination during probe: Fetch `/collections` endpoint, no pagination needed for collection listing (typically small).

</decisions>

<specifics>
## Specific Ideas

- The backend already exposes its own OGC API Features output (`/api/collections/{id}/items`). The import adapter handles the *input* side — connecting to external OGC API services.
- GDAL's OAPIF driver handles pagination, CRS negotiation, and feature retrieval automatically during ogr2ogr ingestion.
- The landing page probe should check for `links` array with `rel: "data"` or `rel: "conformance"`, or a top-level `conformsTo` array containing OGC API Features conformance URIs.

</specifics>

<canonical_refs>
## Canonical References

- OGC API — Features Part 1 Core: https://docs.ogc.org/is/17-069r4/17-069r4.html
- GDAL OAPIF Driver: https://gdal.org/en/stable/drivers/vector/oapif.html

</canonical_refs>
