# Requirements: GeoLens v13.1 Open-Core Separation P1

**Defined:** 2026-04-26
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Source spec:** `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 bucket
**Milestone goal:** Close the six P1 boundary/seam debts so the open-core architecture is demonstrably ship-ready before the first paid customer. Target audit grade improvements: Boundary B → A−, Seam Quality C → B, OSS Surface D → C.

## v13.1 Requirements

Requirements for v13.1. Each maps to exactly one phase in `.planning/ROADMAP.md`. REQ-IDs continue from existing prefixes (LAYER, IDENT, OCSDK, OCCLI new for this milestone; SAML continues from SAML-07 in v13.0).

### Layering & Boundaries

Two mechanical refactors that fix illegal dependencies between modules.

- [x] **LAYER-01**: `core/persistent_config.py` and `core/public_urls.py` no longer import `AppSetting` from `modules/settings` — the layering inversion is broken (either by relocating `AppSetting` to `core/db/models.py` or by registering a config provider into core at startup).
- [x] **LAYER-02**: `auth/visibility.py` is removed; all 23 inbound callers (15 visibility imports + 8 deferred-import callers) migrated to `catalog/authorization.py` with no behavior change to dataset-visibility semantics.

### Identity Protocol

Prerequisite for any clean enterprise auth overlay (SAML, SCIM, multi-org).

- [x] **IDENT-01**: `IdentityProtocol` is defined in `core/identity.py` capturing the surface 51 `User` import sites across 11 domains depend on (id, email, role, tenant context, etc.).
- [x] **IDENT-02**: Concrete `User` SQLAlchemy model satisfies `IdentityProtocol`; all 51 cross-domain import sites depend on the Protocol rather than the concrete model. Existing test suite passes (1965/1965 baseline).
- [x] **IDENT-03**: Enterprise auth overlays can register custom identity backends through the extension system without modifying core code.

### Public Surface — SDKs

Auto-generated client libraries unblock external integrators and the CLI. The OpenAPI snapshot at `backend/openapi.json` (committed during the 2026-04-26 inline remediation pass) is the source of truth.

- [x] **OCSDK-01**: Python SDK auto-generated from `backend/openapi.json`, packaged with proper auth helpers (Bearer token + API key), published to PyPI under an Apache-2.0 license.
- [x] **OCSDK-02**: TypeScript SDK auto-generated from `backend/openapi.json` with typed request/response models, published to npm under an Apache-2.0 license.
- [x] **OCSDK-03**: SDK regeneration is one-shot (`make sdks` or equivalent); CI gates drift via `make sdks-check` analogous to the existing `make openapi-check`.
- [x] **OCSDK-04**: SDK version pins to the OpenAPI snapshot version; release process documented in `docs/sdks.md` (or chosen path) including which generator was selected and why.

### Public Surface — CLI

The strategy's adoption wedge. Apache-2.0 standalone tool that exercises the SDK.

- [x] **OCCLI-01**: `geolens` CLI distributed as an Apache-2.0 Python package via PyPI; works against any GeoLens instance (community or enterprise) with the same code path.
- [ ] **OCCLI-02**: `geolens login <instance-url>` authenticates against the instance and stores the resulting token in the OS keyring (or equivalent secure store), with a fallback for headless/CI environments.
- [ ] **OCCLI-03**: `geolens scan <dir>` walks a local directory, identifies spatial files (vector + raster), and reports what would be ingested without uploading.
- [ ] **OCCLI-04**: `geolens publish <file>` uploads a vector or raster file to a configured GeoLens instance via the generated Python SDK and reports the resulting dataset URL.
- [ ] **OCCLI-05**: `geolens export stac <dataset-id>` exports STAC 1.1 metadata for a raster dataset to stdout or a chosen file.
- [x] **OCCLI-06**: CLI consumes the generated Python SDK (depends on OCSDK-01) — there is no hand-rolled HTTP client inside the CLI.

### Enterprise Auth — SAML Overlay

Reintroduce SAML cleanly as an enterprise extension. Government-buyer mandate. The dead scaffold removed by migration `2026_04_08_0001` does **not** return — this is a fresh implementation that lives in the `geolens-enterprise` repo, not core.

- [ ] **SAML-08**: SAML implementation lives entirely in the `geolens-enterprise` repo; `git grep -i saml` against the core repo returns zero matches outside test fixtures and documentation.
- [ ] **SAML-09**: Core exposes an auth-extension hook that the enterprise SAML overlay registers into via the existing `importlib.metadata` entry_points seam (no SAML-specific code paths in core).
- [ ] **SAML-10**: Admin UI shows a SAML configuration tab only when the enterprise edition is detected at startup; community edition shows no SAML controls (404 on direct route access).
- [ ] **SAML-11**: SAML SP supports SP-initiated SSO with metadata XML endpoint, signed assertion validation (signature, expiry, audience, replay protection), and just-in-time user provisioning that re-uses the existing `find_or_create_oauth_user()` pathway.
- [ ] **SAML-12**: Configurable SAML attribute → role mapping (e.g., `groups` → admin/editor/viewer) administered through the same admin UI tab; audited via the existing audit log.

### Audit-Grade Verification

Milestone-level success criterion that ties the work back to the source audit.

- [ ] **AUDIT-V1**: After the milestone closes, re-running `/oc-audit` produces grades meeting or exceeding: Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C. Audit output committed under `docs-internal/audits/oc-separation-audit-v13.1-close.md`.

## Future Requirements (Deferred)

P2 items from the audit that are explicitly **not** in v13.1. Each will be planned individually as the enterprise tier matures or as customer signal demands.

### Extension Surface (P2)

- **EXT-06**: `AIExtension` Protocol — convert `processing/ai/llm_loop.py` provider dispatch from `if/elif` to a registry. _(Audit §2 / §7 P2; 1–2d)_
- **EXT-07**: `BrandingExtension` extended with logo, colors, favicon, footer fields beyond `show_badge`. _(Audit §2 / §7 P2; 1d)_
- **EXT-08**: `WorkflowExtension` Protocol — replace `ALLOWED_TRANSITIONS` literal with extensible state machine plus reviewer/approver model. _(Audit §2 / §7 P2; 3–5d)_
- **EXT-09**: `PermissionExtension` Protocol with `should_allow()` hook — enables field-level RBAC overlays. _(Audit §2 / §7 P2; 2–3d)_
- **EXT-10**: `SourceAdapter` Protocol + `Connector` model + encrypted credential store + scheduling — foundation for Business-tier "stored-cred connectors." _(Audit §2 / §7 P2; 4–5d)_

### Architecture Refactors (P2)

- **LAYER-03**: Move `audit.service.log_action` behind `core/audit_port.py` — 14 call sites migrate. _(Audit §5 / §7 P2; 1d)_
- **LAYER-04**: `CatalogReadModel` façade for standards & processing — eliminates 15+ direct imports of `catalog.datasets.domain.models`. _(Audit §5 / §7 P2; 3–5d)_
- **LAYER-05**: Split `catalog/datasets/domain/service.py` — densest cycle hub with 29 function-scoped `from app.` imports. _(Audit §5 / §7 P2; 1w)_

### Public Surface (P2)

- **OCSDK-05**: `geolens.yaml` catalog manifest spec — declarative ingestion contract. _(Audit §6 / §7 P2; 1w design + 2–3w impl. Defer until CLI usage signals shape.)_
- **OCCLI-07**: Schema editor UI rename + alter type — backend exists at `PATCH /layers/{id}/columns/{name}/{name,type}` (delivered 2026-04-26); the SchemaEditor component needs the affordances. _(Audit §3 / §7 P2; 1–2d. UI work, not CLI.)_
- **DEPLOY-04**: Publish enterprise overlay via wheel/private index — current overlay only works with sibling source clone. _(Audit §4 / §7 P2; 2–3d)_
- **DEPLOY-05**: Frontend code-splitting for enterprise components in `vite.config.ts` `manualChunks`. _(Audit §4 / §7 P2; 1d)_
- **DEPLOY-06**: Migration overlay duplicate `uv add` cleanup — drop one of `docker-compose.enterprise.yml` `migrate` or `api-entrypoint.sh` invocations. _(Audit §4 carried; 1h)_

### Enterprise Features (P2)

- **ENT-04**: Dataset-level RBAC admin UI on existing `DatasetGrant` model — backend ready, UI heavy. _(Audit §3 / §7 P2; 2–3w)_

### P3 Backlog (Already Tracked Separately)

- **DEPLOY-99-5** = `.planning/phases/999.5-helm-chart-for-kubernetes-deployment/` — Helm chart for K8s deployment.
- **TENANT-99-6** = `.planning/phases/999.6-tenant-scoping-infrastructure-for-multi-tenant-isolation/` — multi-org/tenant scoping foundation.

## Out of Scope

Explicitly excluded from v13.1.

| Feature | Reason |
|---------|--------|
| Cloud SaaS hosting | Strategy is per-deployment pricing, not per-seat SaaS — see `docs-internal/GTM/`. Cloud is deferred indefinitely. |
| Per-seat license-key validation / metering | Pricing model is per-deployment, not per-seat. License-key infrastructure (`ENT-02`/`ENT-03` from v13.0 deferred) stays deferred. |
| IdP-initiated SAML, SAML SLO | Already excluded in v13.0 v2 deferred; SP-initiated covers 95% of buyer demand. v13.1 scope is "ship a working SAML overlay," not "complete every SAML feature." |
| SCIM user provisioning | v13.0 deferred; v13.1 stays focused on the SP-initiated SAML happy path. |
| Multi-organization tenancy | P3 architectural prerequisite (tenant scoping is `.planning/phases/999.6/`). v13.1 IDENT-* lays groundwork but does NOT implement tenant scoping. |
| Field-level RBAC / `PermissionExtension` | P2 (`EXT-09`). v13.1 only ships the Identity protocol, not all extension protocols. |
| Workflow approval state machine | P2 (`EXT-08`). |
| Persistent connector registry | P2 (`EXT-10`). Big architectural item; needs design before build. |
| `geolens.yaml` manifest spec | P2 (`OCSDK-05`). Defer until real CLI usage signals what the spec should contain. |
| New AI provider integrations | Provider dispatch refactor (`EXT-06`) is P2. v13.1 does not touch `processing/ai/llm_loop.py`. |
| Marketing-site copy / docs-site work | Lives in the `getgeolens.com` repo, not this one. Cross-repo style alignment shipped as 999.5 there. |

## Traceability

Populated by the roadmapper on 2026-04-27. All 21 v13.1 requirements map to exactly one phase in `.planning/ROADMAP.md`.

| Requirement | Phase | Status |
|-------------|-------|--------|
| LAYER-01 | 212 (core-settings-decouple) | Complete |
| LAYER-02 | 213 (catalog-authz-relocate) | Complete |
| IDENT-01 | 214 (identity-protocol-extract) | Complete |
| IDENT-02 | 214 (identity-protocol-extract) | Complete |
| IDENT-03 | 214 (identity-protocol-extract) | Complete |
| OCSDK-01 | 215 (sdks-from-openapi) | Complete |
| OCSDK-02 | 215 (sdks-from-openapi) | Complete |
| OCSDK-03 | 215 (sdks-from-openapi) | Complete |
| OCSDK-04 | 215 (sdks-from-openapi) | Complete |
| OCCLI-01 | 216 (geolens-cli-mvp) | Complete |
| OCCLI-02 | 216 (geolens-cli-mvp) | Pending |
| OCCLI-03 | 216 (geolens-cli-mvp) | Pending |
| OCCLI-04 | 216 (geolens-cli-mvp) | Pending |
| OCCLI-05 | 216 (geolens-cli-mvp) | Pending |
| OCCLI-06 | 216 (geolens-cli-mvp) | Complete |
| SAML-08 | 217 (auth-saml-enterprise) | Pending |
| SAML-09 | 217 (auth-saml-enterprise) | Pending |
| SAML-10 | 217 (auth-saml-enterprise) | Pending |
| SAML-11 | 217 (auth-saml-enterprise) | Pending |
| SAML-12 | 217 (auth-saml-enterprise) | Pending |
| AUDIT-V1 | 218 (oc-audit-close-v13.1) | Pending |

**Coverage:**
- v13.1 requirements: 21 total
- Mapped to phases: 21 ✓
- Unmapped: 0

---
*Requirements defined: 2026-04-26*
*Last updated: 2026-04-27 — traceability populated; 21/21 requirements mapped to phases 212–218*
