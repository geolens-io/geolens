# DCAT-US 3.0 Feature Research

**Milestone:** v1029 DCAT 3.0

## Table Stakes

- Catalog feed validates as DCAT-US Schema v3.0 JSON Schema 2020-12 when visible datasets have required metadata.
- Dataset entries use unprefixed DCAT-US 3.0 field names such as `title`, `description`, `identifier`, `publisher`, `contactPoint`, `keyword`, `theme`, `temporal`, `spatial`, and `distribution`.
- Distribution entries expose `accessURL`, `downloadURL` where appropriate, `format`, `mediaType`, `license`, and optional access service metadata for API/service distributions.
- Structured supporting classes are emitted where GeoLens has data: `Organization`, `Kind`, `PeriodOfTime`, `Location`, `Concept`, `Distribution`, and simple `DataService`.
- Existing visibility behavior remains unchanged: public/anonymous feeds exclude private datasets, authenticated feeds honor user roles and grants, and per-dataset export checks access before serialization.
- Validation output reports path, schema path, validator, and message so operators can see which metadata fields are missing or malformed.

## Differentiators

- Keep existing W3C DCAT 3 routes stable while adding explicit DCAT-US 3.0 profile routes.
- Include validation report endpoints so operators can preflight their own catalog before publishing a `data.json` feed.
- Document mapping gaps and non-goals instead of silently inventing federal metadata GeoLens does not store.
- Use Playwright MCP against the running API surface for final route/console/network verification.

## Deferred Or Out Of Scope

- Full DCAT-US v1.1 import/migration UI is deferred; this milestone should provide migration notes and output compatibility, not a bulk importer.
- DatasetSeries modeling is deferred unless existing collection/relationship data maps cleanly without schema changes.
- CUI/access/use restriction structured authoring is deferred unless current `access_constraints` / `usage_constraints` can be mapped without inventing policy fields.
