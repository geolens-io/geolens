# Quick Task 260322-gzi: Review ArcGIS Online/Portal authenticated layer ingestion - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Review the full ArcGIS Online/Portal authenticated layer ingestion pipeline for correctness, completeness, and best practices. The goal is ensuring users migrating off ArcGIS Online can pull in their layers as simply and robustly as possible.

</domain>

<decisions>
## Implementation Decisions

### Token Handling & Authentication
- Current token approach may not work correctly with ArcGIS Online — verify what AGOL actually accepts
- Investigate whether username/password auth is feasible (ArcGIS generateToken endpoint)
- Persisting credentials is acceptable IF securely stored (encrypted at rest)
- Audit both URL query param token placement and header-based approaches

### ArcGIS Auth Model
- Audit current gaps: document what auth types exist in AGOL ecosystem and which ones the current code handles vs doesn't
- Don't implement full OAuth — focus on identifying gaps and documenting them

### Pagination & Large Datasets
- Verify GDAL's FEATURE_SERVER_PAGING actually works correctly with ArcGIS server-imposed limits
- Confirm the ESRIJSON driver handles pagination properly during ogr2ogr ingestion

### Import UX
- Full UX audit of the import flow for an AGOL migration user persona
- Review error messages, token input discoverability, and guidance quality
- Ensure the flow is clear for users who may not be technically sophisticated

### Claude's Discretion
- Specific code fix recommendations vs. documentation-only findings
- Priority ordering of issues found

</decisions>

<specifics>
## Specific Ideas

- User reports the token approach "doesn't seem to work correctly" — this is the highest priority finding to investigate
- Username/password auth via ArcGIS REST API's generateToken endpoint should be evaluated
- Credential persistence is OK if securely stored

</specifics>

<canonical_refs>
## Canonical References

- ArcGIS REST API authentication documentation
- GDAL ESRIJSON driver documentation
- GDAL OGR ArcGIS FeatureServer driver documentation

</canonical_refs>
