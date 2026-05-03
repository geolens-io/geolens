# Requirements: v13.5 Enterprise Governance Seams

**Defined:** 2026-05-03
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Turn the remaining governance-adjacent permission and workflow chokepoints into first-class extension seams so Enterprise overlays can implement advanced RBAC and approval workflows without forking core.

**Audit-grade targets:** Seam Quality A− → **A**; Boundary Integrity ≥ **A**; Inventory Accuracy ≥ **A−**.

## v13.5 Requirements

### Permission Extension

- [x] **PERM-01**: A `PermissionExtension` Protocol exists in `backend/app/platform/extensions/protocols.py` for action-level checks and catalog visibility filtering.
- [x] **PERM-02**: The default permission implementation preserves the current role/capability matrix, admin overrides, lockout prevention, and API behavior for Community users.
- [x] **PERM-03**: `require_permission()` and catalog visibility filtering consult the permission extension instead of relying only on hardcoded matrix/query logic.
- [x] **PERM-04**: A test overlay can allow, deny, or filter access through `PermissionExtension` without modifying core files.
- [x] **PERM-05**: Architecture or regression tests prevent future bypasses of the permission extension at known permission and visibility chokepoints.

### Workflow Extension

- [x] **WORK-01**: A `WorkflowExtension` Protocol exists in `backend/app/platform/extensions/protocols.py` for allowed publication transitions and transition hooks.
- [x] **WORK-02**: The default workflow implementation preserves the current `draft -> ready -> internal -> published` lifecycle, status ordering, audit behavior, and API responses.
- [x] **WORK-03**: Dataset publication endpoints consult the workflow extension for every status transition instead of directly relying on hardcoded transition dictionaries.
- [x] **WORK-04**: A test overlay can block, add, or observe a workflow transition without modifying core files.
- [ ] **WORK-05**: Architecture or regression tests prevent future bypasses of the workflow extension at dataset publication transition call sites.

### Governance Contract Verification

- [ ] **SHARE-01**: Advanced sharing controls remain gated consistently across schema validators, service guards, and UI affordances in Community versus Enterprise.
- [ ] **SHARE-02**: GTM docs, API schema descriptions, route docstrings, and UI copy match the advanced-sharing implementation without false paid/free claims.
- [ ] **SHARE-03**: Basic community sharing remains intact: users can still create and revoke non-advanced share/embed tokens after governance gates are verified.

### Close Audit

- [ ] **GOVAUD-01**: A dated v13.5 close audit covers `PermissionExtension`, `WorkflowExtension`, advanced-sharing contract verification, and open-core seam grades.
- [ ] **GOVAUD-02**: All P1 findings from the close audit are fixed inline or explicitly deferred with rationale and tracked backlog entries.
- [ ] **GOVAUD-03**: The close audit records Seam Quality ≥ **A**, Boundary Integrity ≥ **A**, and Inventory Accuracy ≥ **A−**.

## Future Requirements

Deferred to later milestones.

### Open-Core Adoption

- **MANIFEST-01**: `geolens.yaml` catalog manifest spec and CLI apply/validate workflow.
- **SCHEMA-01**: Standalone `geolens-schemas` package for reusable STAC/OGC/DCAT validation.

### Enterprise Deployment

- **DEPLOY-01**: Helm chart and AMI/Packer pipeline for production Enterprise distribution.
- **DEPLOY-02**: SBOM generation and signed image distribution in release/publish workflows.

### Enterprise Product Surface

- **CONN-01**: Persistent connector registry with stored credentials, schedule, adapter protocol, and sync workers.
- **CATDEBT-01**: Split `catalog/maps/service.py` behind a thin facade.
- **CATDEBT-02**: Split `catalog/search/service.py` behind a thin facade.

### Cloud

- **TENANT-01**: Tenant scoping infrastructure for future hosted Cloud deployments.

## Out of Scope

Explicitly excluded from v13.5.

| Feature | Reason |
|---------|--------|
| Field-level RBAC admin UI | v13.5 ships the seam; product UI and policy authoring belong in a later Business-tier milestone. |
| Full approval workflow product UI | v13.5 ships the extension seam; reviewer assignment, notifications, and custom states belong after the protocol is proven. |
| Persistent connector registry | Larger Enterprise feature; cleaner after permission and workflow seams are in place. |
| Tenant scoping | Cloud-only prerequisite; not needed for self-hosted Enterprise governance seams. |
| `geolens.yaml` manifest and schema package | High OSS-adoption value, but separate from Enterprise governance seam work. |
| Helm/AMI/SBOM distribution work | Enterprise procurement work, but not required to close permission/workflow extensibility. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PERM-01 | Phase 232 | Complete |
| PERM-02 | Phase 232 | Complete |
| PERM-03 | Phase 232 | Complete |
| PERM-04 | Phase 232 | Complete |
| PERM-05 | Phase 232 | Complete |
| WORK-01 | Phase 233 | Complete |
| WORK-02 | Phase 233 | Complete |
| WORK-03 | Phase 233 | Complete |
| WORK-04 | Phase 233 | Complete |
| WORK-05 | Phase 233 | Pending |
| SHARE-01 | Phase 234 | Pending |
| SHARE-02 | Phase 234 | Pending |
| SHARE-03 | Phase 234 | Pending |
| GOVAUD-01 | Phase 235 | Pending |
| GOVAUD-02 | Phase 235 | Pending |
| GOVAUD-03 | Phase 235 | Pending |

**Coverage:**
- v13.5 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-05-03*
*Last updated: 2026-05-03 after initial v13.5 definition*
