# DCAT-US 3.0 Research Summary

**Milestone:** v1029 DCAT 3.0
**Source of truth:** resources.data.gov DCAT-US 3.0 reference and GSA/dcat-us JSON Schema at `98408dc000f0b71131a03920e2dec6247a84abff`.

## Key Findings

- DCAT-US Schema v3.0 is JSON Schema 2020-12 and is organized around Catalog, Dataset, Distribution, DataService, DatasetSeries, and supporting classes.
- Existing GeoLens DCAT output is W3C DCAT 3 JSON-LD with prefixed keys; DCAT-US v3.0 should be a separate profile, not an in-place mutation of current compatibility routes.
- Dataset mandatory fields are `description`, `publisher`, `title`, `contactPoint`, and `identifier`.
- Catalog mandatory field is `dataset`; Distribution has no required fields but has recommended access, format, license, and modified fields.
- DataService support is useful for API/service distributions but must include mandatory `contactPoint`, `endpointURL`, `publisher`, and `title` if emitted.
- The official implementation guidance was marked draft on 2026-05-07, so tests should pin behavior to the official JSON Schema files rather than prose alone.

## Recommended Milestone Shape

1. Serializer and validator foundation.
2. Public API routes and compatibility-preserving endpoint strategy.
3. Tests, docs/mapping notes, OpenAPI/SDK refresh.
4. Runtime verification including Playwright MCP against the API surface.
