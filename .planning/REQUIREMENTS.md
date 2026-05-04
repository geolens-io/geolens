# Requirements: v13.7 Manifest-Driven Catalog Automation

## Goal

Let a new organization describe datasets, sources, metadata, and publication intent in `geolens.yaml`, validate it locally, and apply it through the CLI/backend path into a browsable GeoLens catalog.

## In Scope

### Manifest Schema

- [ ] **MAN-01**: User can define manifest version, catalog metadata, and stable dataset identity fields in `geolens.yaml`.
- [ ] **MAN-02**: User can define vector, raster COG, and VRT source entries using relative paths, URLs, or storage URIs.
- [ ] **MAN-03**: User can declare per-dataset metadata including title, description, tags, organization, CRS, license, attribution, and bbox hints.
- [ ] **MAN-04**: User can declare Community-safe publication intent such as draft, ready, internal, or published without depending on Enterprise-only controls.
- [ ] **MAN-05**: Maintainer can verify manifest schema compatibility with committed good/bad fixtures and versioned validation errors.

### CLI Workflow

- [ ] **CLI-01**: User can run `geolens init` to create a minimal `geolens.yaml` without overwriting an existing manifest unless explicitly forced.
- [ ] **CLI-02**: User can run `geolens validate` and receive deterministic exit codes plus path-specific validation errors without needing a running API.
- [ ] **CLI-03**: User can run `geolens apply` against a configured GeoLens API to create or update datasets from a manifest.
- [ ] **CLI-04**: User can run `geolens apply --dry-run` to preview create, update, skip, and error outcomes without writing data.

### Backend Apply And Ingest

- [ ] **INGEST-01**: Backend can accept a validated manifest through a typed service/API boundary and enqueue existing ingest jobs per dataset entry.
- [ ] **INGEST-02**: Manifest apply is idempotent by stable dataset key and reports create, update, skip, and error outcomes per entry.
- [ ] **INGEST-03**: Manifest ingestion preserves existing auth, RBAC, storage validation, file-safety, and edition-boundary checks.
- [ ] **INGEST-04**: Vector, raster COG, and VRT manifest entries round-trip through existing catalog metadata, search, and map-preview contracts.

### Docs And Examples

- [ ] **DOCS-01**: New user can follow docs/examples from `docker compose up` to a browsable catalog using sample `geolens.yaml` within 10 minutes.
- [ ] **DOCS-02**: Operator can adapt sample manifests for local paths, HTTP/S3 sources, and publication states without reading GeoLens source code.

### Quality And Contracts

- [ ] **QUAL-01**: OpenAPI snapshot, Python/TypeScript SDKs, and CLI docs reflect any new manifest/apply API surface.
- [ ] **QUAL-02**: CI runs focused backend, CLI, and schema-fixture tests for manifest validation and apply behavior.
- [ ] **QUAL-03**: Architecture guards prevent manifest support from coupling CLI directly to backend internals or introducing Enterprise-only dependencies into Community.
- [ ] **QUAL-04**: Formal close audit verifies all v13.7 requirements, examples, CI evidence, and adoption-path evidence.

## Future Requirements

- Persistent connector registry, stored credentials, scheduled mirroring, and connector UI (Phase 999.13).
- Tenant scoping for future Cloud multi-tenant isolation (Phase 999.6).
- Helm chart, AMI Packer pipeline, SBOM generation, signed images, and `geolens-schemas` extraction (Phases 999.14-999.16).
- Enterprise-only manifest extensions for approval workflows, custom governance, and scheduled connector sync.

## Out Of Scope

- New map-builder, layer editing, visual styling, search ranking, or sharing semantics.
- Full catalog federation or harvesting from remote catalogs.
- Enterprise credential vault or scheduled connector orchestration.
- Cloud multi-tenant org isolation.
- Distribution packaging work outside the existing CLI/backend/API surface.

## Traceability

| Requirement | Phase |
|-------------|-------|
| MAN-01 | 241 manifest-spec-and-schema |
| MAN-02 | 241 manifest-spec-and-schema |
| MAN-03 | 241 manifest-spec-and-schema |
| MAN-04 | 241 manifest-spec-and-schema |
| MAN-05 | 241 manifest-spec-and-schema |
| CLI-01 | 242 cli-init-validate |
| CLI-02 | 242 cli-init-validate |
| INGEST-01 | 243 backend-manifest-apply-ingest |
| INGEST-02 | 243 backend-manifest-apply-ingest |
| INGEST-03 | 243 backend-manifest-apply-ingest |
| INGEST-04 | 243 backend-manifest-apply-ingest |
| CLI-03 | 244 cli-apply-and-adoption-docs |
| CLI-04 | 244 cli-apply-and-adoption-docs |
| DOCS-01 | 244 cli-apply-and-adoption-docs |
| DOCS-02 | 244 cli-apply-and-adoption-docs |
| QUAL-01 | 245 contract-gates-and-close-audit |
| QUAL-02 | 245 contract-gates-and-close-audit |
| QUAL-03 | 245 contract-gates-and-close-audit |
| QUAL-04 | 245 contract-gates-and-close-audit |
