# Requirements: GeoLens v1029 DCAT 3.0

**Defined:** 2026-05-27
**Core Value:** Users can find any dataset in the catalog in seconds - search, see it on a map, understand what it is, and get it out in the format they need.

## v1029 Requirements

### Profile Contract

- [x] **PROFILE-01**: GeoLens has an explicit DCAT-US Schema v3.0 profile separate from the existing W3C DCAT 3 JSON-LD serializer.
- [x] **PROFILE-02**: The DCAT-US 3.0 implementation is pinned to the official GSA/dcat-us JSON Schema source and records the source commit or version.
- [x] **PROFILE-03**: The milestone documents which existing GeoLens catalog fields map to DCAT-US Catalog, Dataset, Distribution, DataService, DatasetSeries, and supporting classes.
- [x] **PROFILE-04**: Metadata that GeoLens cannot populate from current catalog fields is documented as fallback, warning, future-field, or out-of-scope behavior.

### Serialization

- [x] **SER-01**: User can request a DCAT-US 3.0 catalog feed whose top-level Catalog includes schema-valid `dataset` entries for visible datasets with complete required metadata.
- [x] **SER-02**: User can request a single dataset as DCAT-US 3.0 with required Dataset fields: `title`, `description`, `identifier`, `publisher`, and `contactPoint`.
- [x] **SER-03**: DCAT-US 3.0 output emits structured `PeriodOfTime`, `Location`, `Concept`, `Organization`, `Kind`, and `Distribution` objects where GeoLens has source data.
- [x] **SER-04**: Distribution output distinguishes indirect access URLs from direct download URLs where current distribution metadata can support that distinction.
- [x] **SER-05**: Service-like distributions can emit simple `DataService` metadata without requiring a new connector registry or service table.

### Validation

- [x] **VAL-01**: The official DCAT-US 3.0 JSON Schema definitions are available locally so validation works without network access.
- [ ] **VAL-02**: Backend validation uses JSON Schema 2020-12 and resolves the official schema `$ref` graph.
- [ ] **VAL-03**: User or operator can get a validation report for the catalog feed and for an individual dataset, including path, schema path, validator, and message for each error.
- [ ] **VAL-04**: Validation failure for incomplete metadata is reported clearly without hiding visibility/access failures or inventing fake federal metadata.

### API and Access Control

- [x] **API-01**: Existing `/datasets/dcat/` and `/{dataset_id}/dcat/` routes keep their current W3C DCAT 3 behavior.
- [x] **API-02**: Explicit DCAT-US 3.0 catalog and per-dataset routes are available for federal-profile consumers.
- [x] **API-03**: Anonymous DCAT-US catalog export excludes private datasets using the same visibility filter as existing DCAT export.
- [x] **API-04**: Per-dataset DCAT-US export and validation enforce the same dataset access checks as existing per-dataset DCAT export.
- [ ] **API-05**: Public API snapshot and generated SDKs are refreshed if the DCAT-US routes are included in OpenAPI.

### Documentation and Quality

- [ ] **DOC-01**: Developer/operator documentation explains the DCAT-US 3.0 route strategy, validation behavior, schema source, and mapping gaps.
- [ ] **DOC-02**: Migration notes call out DCAT-US v1.1 to v3.0 breaking areas relevant to GeoLens: `modified`, `temporal`, `spatial`, `language`, restrictions, services, and dataset series.
- [ ] **DOC-03**: CHANGELOG records the DCAT-US 3.0 support surface and any accepted limitations.
- [ ] **QA-01**: Focused backend tests cover serializer mapping, schema-valid happy paths, validation errors, visibility filtering, and route-order conflicts.
- [ ] **QA-02**: Backend lint/format checks and focused pytest gates pass for touched standards/export code.
- [ ] **QA-03**: OpenAPI/SDK checks pass or any skipped generator surface is justified with no public API changes.
- [ ] **QA-04**: Playwright MCP verifies the running API surface for DCAT-US catalog export, validation, response status, network hygiene, and console hygiene.

## Future Requirements

### DCAT-US Follow-Ups

- **DCAT-FU-01**: Add first-class DatasetSeries authoring if GeoLens collections or dataset relationships need to publish federal series metadata.
- **DCAT-FU-02**: Add structured AccessRestriction, UseRestriction, and CUIRestriction authoring instead of mapping only existing free-text constraints.
- **DCAT-FU-03**: Add DCAT-US v1.1 import/migration tooling if operators need to bulk transform existing `data.json` files into GeoLens metadata.
- **DCAT-FU-04**: Promote the shared DCAT/STAC/OGC validators into the future `geolens-schemas` package when Phase 999.16 is prioritized.

### CI Infrastructure

- **CI-01-v1029**: Live-verify `pytest-parallel-isolation` on real GitHub Actions infrastructure after geolens-io billing is resolved. This rolling external blocker remains outside the DCAT-US 3.0 milestone invariant.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replacing existing W3C DCAT 3 routes | Compatibility routes should remain stable; DCAT-US is added as an explicit profile. |
| Bulk DCAT-US v1.1 import/migration UI | This milestone adds export/validation/mapping support; import tooling is a separate product surface. |
| New persistent connector registry | DataService can be emitted from current distribution metadata; stored connector credentials remain Phase 999.13. |
| Full DatasetSeries data model | Current catalog relationships may not be sufficient; document the gap and defer first-class authoring. |
| Structured CUI/access/use restriction authoring | Current catalog fields are free-text; structured restriction capture needs a separate metadata-editing pass. |
| Closing the GitHub Actions billing blocker | CI live-verify remains an external operator prerequisite carried forward from earlier milestones. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROFILE-01 | Phase 1129 | Complete |
| PROFILE-02 | Phase 1129 | Complete |
| PROFILE-03 | Phase 1129 | Complete |
| PROFILE-04 | Phase 1129 | Complete |
| VAL-01 | Phase 1129 | Complete |
| SER-01 | Phase 1130 | Complete |
| SER-02 | Phase 1130 | Complete |
| SER-03 | Phase 1130 | Complete |
| SER-04 | Phase 1130 | Complete |
| SER-05 | Phase 1130 | Complete |
| API-01 | Phase 1130 | Complete |
| API-02 | Phase 1130 | Complete |
| API-03 | Phase 1130 | Complete |
| API-04 | Phase 1130 | Complete |
| VAL-02 | Phase 1131 | Pending |
| VAL-03 | Phase 1131 | Pending |
| VAL-04 | Phase 1131 | Pending |
| API-05 | Phase 1131 | Pending |
| DOC-01 | Phase 1131 | Pending |
| DOC-02 | Phase 1131 | Pending |
| DOC-03 | Phase 1131 | Pending |
| QA-01 | Phase 1132 | Pending |
| QA-02 | Phase 1132 | Pending |
| QA-03 | Phase 1132 | Pending |
| QA-04 | Phase 1132 | Pending |

**Coverage:**
- v1029 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-05-27*
*Last updated: 2026-05-27 after v1029 roadmap creation*
