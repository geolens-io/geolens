# Open-Core Separation Audit — v13.1 Close (2026-04-29)

> **v13.1 closing-audit run.** This run verifies the post-Phase-217 state against the v13.1 milestone-close grade contract: Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C. See §8 for the grade-delta vs the 2026-04-26 source baseline.

## Scorecard

| Dimension | Grade | Rationale |
|-----------|-------|-----------|
| **Boundary Integrity** | **B−** | Three 🔴 violations all collapse to one architectural P0: OAuth IdP→role mapping (`oauth/models.py:82-84` columns + `oauth/schemas.py:116-129, 237-248` write API + `oauth/service.py:169-179, 261-263` runtime) executes unconditionally in community, despite `repo-split.md` classing IdP role mapping as Enterprise. Phase 217 explicitly deferred this gate to Phase 218 (`217-CONTEXT.md` "Out of scope" → "gating OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()`"); no implementation followed in 218. Three 🟡 risks all trace to AWS Marketplace billing in core runtime (`docker-compose.yml:128-129` + `core/config.py:87-88, 108` + `core/marketplace.py:1-30` + `api/main.py:184-203`). Audit-export gate intact at `audit/router.py:96`. SAML carve-out is pristine — all four documented files (`oauth/{models,schemas,service}.py`, `settings/router.py`) contain only enum literals, deferred-column scaffolding, and audit-snapshot helpers. Standards (OGC/STAC/DCAT) HARD-FREE preserved. Multi-tenant, SCIM, federation, airgap, govcloud, AI policy, approval-workflow, white-label-toggle: zero hits. |
| **Seam Quality** | **B** | 3🟢 / 1🟡 / 4🔴 — significant movement vs the baseline distribution of 0🟢 / 3🟡 / 5🔴. Three seams advanced to 🟢 in v13.1: **Auth provider** (Phase 214 wired `IdentityExtension` into BOTH `auth/dependencies.py:85` and `:141`; Phase 217 SAML overlay proved the seam end-to-end), **Audit export** (`audit/router.py:107` consults `get_audit_extension().get_export_formats()`; `require_enterprise` 404 gate), and **Branding** (`settings/router.py:630` consults extension defaults). Policy/permissions stays 🟡 (Phase 213 cleaned the visibility chokepoint at `catalog/authorization.py:34` but no `PermissionExtension` Protocol). Workflow, AI providers, persistent connectors, and tenant scoping remain 🔴 — untouched in v13.1. `AuthExtension.get_auth_methods()` (`protocols.py:29`) is wired through the registry but has zero call sites. |
| **Inventory Accuracy** | **B+** | All 17 claimed community features verified in code with file:line evidence. CLI (`cli/geolens_cli/`) ships 7 commands (login, logout, whoami, scan, publish, export stac), exceeding the 4-command MVP target from Phase 216. Python + TypeScript SDKs present (`sdks/python/`, `sdks/typescript/`). SAML correctly carved out per Phase 217 — backend retains only enum-string scaffolding. **Three undocumented capabilities flagged:** AI streaming + tool-calling loop (`processing/ai/{streaming.py, llm_loop.py, tool_call_parser.py}`) contradicts GTM's "single-shot only" claim at `free-vs-enterprise.md:70`; pgvector semantic search shipped in v7.2 not in CE feature list; AWS Marketplace metering wired into core lifespan unconditionally. **One frontend gap:** `frontend/src/pages/admin/AdminSamlPage.tsx` ships in the CE bundle (gated at runtime via `useEdition()` redirect at `:28-33`, but the page lives in core code). |
| **Deployment Separation** | **B** | Unchanged from 2026-04-27 baseline. `docker-compose.enterprise.yml` is a clean 29-line additive overlay (volume mounts + env injection, no image rebuild, graceful degradation when `/enterprise/` absent). `_ENTERPRISE_ONLY_TABS` gate at `settings/router.py:62, 90-104` correctly returns **404** with no detail body — **the 2026-04-27 P1 finding (revealing 403 detail string) is RESOLVED**. AWS Marketplace billing P1 still present in base runtime (same loci as Boundary §1). No `deployment/` directory, no Helm chart, `GEOLENS_EDITION` and `GEOLENS_ENTERPRISE_PATH` undocumented in `.env.example`. |
| **Coupling Health** | **B−** | Major v13.1 wins verified: **`User` import sites cut from 51 → 20 (−61%)** via `IdentityProtocol` (41 files now type against the protocol); `core ↔ settings` layering inversion eliminated (Phase 212 — 0 hits in `backend/app/core/`); `auth/visibility.py` relocation to `catalog/authorization.py` complete (Phase 213 — 0 callers of old path, no deferred-import shims). Remaining debt: `catalog/datasets/domain/service.py` is 1407 LOC with 29 function-scoped imports — the de-facto orchestration god-module. Function-scoped imports across `modules/` unchanged at 106 (still cycle-workaround tape). `log_action` decentralized further (14 → 19 call sites; needs `AuditSink` Protocol). `embed_tokens` reaches into `catalog.maps` internals. catalog ↔ processing two-way coupling persists (16 files in `processing/`+`standards/` import `catalog.datasets.domain.models`; catalog imports 10+ symbols from `processing.*`). |
| **OSS Surface Readiness** | **A−** | All four LICENSE files Apache-2.0 (root, `cli/`, `sdks/python/`, `sdks/typescript/`); package metadata consistent in 5 manifests. Zero copyleft contamination (`grep -ln "GPL\|AGPL\|copyleft"` returns no matches across `backend/app/`, `frontend/src/`, `cli/`, `sdks/`). OpenAPI snapshot at `backend/openapi.json` (1,057,614 bytes) with **enforced CI drift gate** (`.github/workflows/ci.yml` `openapi-snapshot` + `sdks-check` jobs). CLI + 2 SDKs built locally as wheels. **Holding short of A on:** (a) `geolens.yaml` catalog manifest spec — zero hits — the largest unshipped open-core enabler; (b) live PyPI/npm publishes — workflows wired but never run; (c) standalone `geolens-schemas` package not extracted; (d) no per-file SPDX headers. |

**Overall Readiness: B (3.06 / 4.0)** — up from B− (2.61 / 4.0) at the 2026-04-26 baseline.

---

## ⚠ MILESTONE CLOSE BLOCKED

**Boundary Integrity grade B− does NOT meet the v13.1 close target of A−.**

The shortfall traces to a **single architectural P0** that Phase 217 documented as deferred to Phase 218 in its CONTEXT.md "Out of scope" section: gating OAuth `group_claim` / `group_role_mapping` behind `require_enterprise()`. Phase 218 was scoped as the closing-audit phase, not the gating phase, so the deferral was never closed.

This is exactly the contingency CONTEXT.md D-06/D-07 was written for. Per Phase 218's discuss-phase decisions:
- Do NOT auto-spawn a remediation phase.
- Do NOT silently advance milestone close.
- Surface the failure for user judgment (Fix-now / Demote / Slip).

The other two target dimensions (Seam Quality B, OSS Surface A−) **MEET or EXCEED** their thresholds. Boundary is the sole blocker.

See **§7 Prioritized Action Items** for the recommended remediation phase scope, and the **P1 Residual Triage** section (after §8) for the full per-finding verdict table.

---

## Executive Summary

The v13.1 milestone delivered five of six P1 commitments cleanly: the `core ↔ settings` layering inversion is gone, `auth/visibility.py` relocated to `catalog/authorization.py`, `IdentityProtocol` extracted and adopted by 41 files (`User` direct imports cut from 51 → 20), Python + TypeScript SDKs and the `geolens` CLI shipped Apache-2.0 with an enforced OpenAPI drift gate, and the SAML enterprise overlay shipped to a sibling private repo with a clean four-file carve-out in core. Three extension seams advanced from 🟡 to 🟢 (auth provider, audit export, branding) — the seam infrastructure is now exercised by a real overlay rather than a dormant Protocol declaration.

The sixth P1 commitment is unfulfilled. The 2026-04-27 audit's P0 — IdP group-to-role mapping shipping in community via `oauth/models.py` columns, `oauth/schemas.py` write fields, and `oauth/service.py` runtime resolution — was explicitly deferred to Phase 218 by Phase 217's "Out of scope" list. Phase 218 was scoped as a closing-audit phase, not a gating phase, and the deferral was never closed. Three boundary violations all collapse to this single P0; once gated, Boundary moves from B− to A− (or A) and the v13.1 close criterion is met.

The unresolved P1 items are AWS Marketplace billing plumbing in the core runtime (dormant when env unset, but the boto3 import and lifespan registration ship to every community deployment), and the missing `geolens.yaml` catalog manifest spec. Coupling debt is concentrated in `catalog/datasets/domain/service.py` (1407 LOC orchestration god-module) and the catalog ↔ processing two-way knot. The recommended next step is a small Phase 219 (oc-audit-remediate-idp-mapping) that gates the three OAuth files behind `is_enterprise()` checks (~1 day of work, two model_validators + one runtime branch), re-runs the audit, and re-attempts v13.1 close. Marketplace billing extraction and manifest spec land in v13.2 or a follow-on cleanup phase.

---

## 1. Feature Boundary Leakage

### Findings

| File:line | Pattern | Class | Recommendation |
|---|---|---|---|
| `backend/app/modules/auth/oauth/models.py:82-84` | `default_role` / `group_claim` / `group_role_mapping` columns on OAuthProvider (IdP→role mapping) | 🔴 **Violation (UNRESOLVED — deferred from 2026-04-27)** | Gate at write path: keep columns (forward-compat scaffolding for enterprise) but reject non-default writes in community via `model_validator` + `is_enterprise()` check |
| `backend/app/modules/auth/oauth/service.py:169-179, 261-263` | `_resolve_role()` applies `group_role_mapping` for ALL OAuth providers in `find_or_create_oauth_user()` | 🔴 **Violation (UNRESOLVED)** | Wrap in edition check at `:261-263`: if `is_enterprise()`, call `_resolve_role(...)`; else `role_name = provider.default_role` |
| `backend/app/modules/auth/oauth/schemas.py:116-129, 237-248` | `default_role` / `group_claim` / `group_role_mapping` accepted in Create/Update schemas without enterprise gate | 🔴 **Violation (UNRESOLVED)** | Add `model_validator(mode="after")` to `OAuthProviderCreate` and `OAuthProviderUpdate` that raises `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` when `group_claim` is set or `group_role_mapping` is non-empty AND `not is_enterprise()` |
| `frontend/src/components/admin/saml/SamlProvidersSection.tsx:90-92, 511-528` | UI fields for `group_claim` / `group_role_mapping` | 🟢 Clean | Lives under `admin/saml/`, gated by `AdminSamlPage` `useEdition()` redirect (`AdminSamlPage.tsx:28-33`); enterprise-only by route. No equivalent UI under non-SAML OAuth provider editor — correct posture |
| `backend/app/api/main.py:184-203` | AWS Marketplace `register_marketplace_usage` runtime call in core startup | 🟡 Risk | Move behind a `BillingExtension.on_startup()` hook registered only by the enterprise overlay; core should not import `app.core.marketplace` |
| `backend/app/core/marketplace.py:1-30` | AWS Marketplace billing module in core runtime (boto3 dep) | 🟡 Risk | Relocate to `geolens-enterprise/geolens_enterprise/billing/` and register via the extension seam |
| `backend/app/core/config.py:87-88, 108` | `aws_marketplace_product_code` / `aws_marketplace_public_key_version` settings on core `Settings` | 🟡 Risk | Move to enterprise overlay's settings, OR keep as opaque pass-through env vars; the runtime *behavior* is the leak, not the env var |
| `backend/app/modules/audit/router.py:34, 96` | `_ent: None = Depends(require_enterprise)` on audit-export route | 🟢 Clean | Phase 217 pre-state intact; defense-in-depth working |
| `backend/app/modules/auth/oauth/{models,schemas,service}.py` + `backend/app/modules/settings/router.py` | SAML enum/strings/`deferred=True` columns in 4 carve-out files | 🟢 Clean | No SAML `class`/`def`/instantiation found — only enum literals (`'saml'`), validation strings, deferred-column scaffolding (`models.py:52-77`), audit-snapshot helpers, comments referencing enterprise migration `e002_add_saml_columns` |
| `backend/app/modules/settings/router.py:62, 90-104, 617-630` | `_ENTERPRISE_ONLY_TABS = {"branding"}` + `BRANDING_SHOW_BADGE` config | 🟢 Clean | Branding tab gated correctly (404 on community); only `show_badge` default lives in community via `DefaultBrandingExtension` (per allowlist) |
| `backend/app/standards/{ogc,stac,dcat}/` | OGC/STAC/DCAT routers and services | 🟢 Clean | Zero `require_enterprise`/`require_edition` calls; HARD-FREE preserved |
| `backend/app/modules/catalog/` | Persistent connector / stored credentials | 🟢 Clean | No `Credential`/`StoredSecret`/`ConnectorConfig` model; `secrets` import is for token generation only (`maps/service.py:852`); source adapters are stateless probes |
| Repo-wide | Multi-tenant, federation, SCIM, airgap, govcloud, AI policy, approval workflow, white-label-toggle | 🟢 Clean | Greps return zero hits |

### Summary

- 🔴 **Violations: 3** (all collapse to one architectural issue: OAuth IdP→role mapping in core)
- 🟡 **Risks: 3** (Marketplace billing in core runtime — same defect, three loci)
- 🟢 **Clean: 9 categories**

### Carve-out note (Phase 217 SAML)

All four documented carve-out files contain only enum literals, validation strings, `deferred=True` column scaffolding, audit-snapshot helpers, and comments referencing `e002_add_saml_columns`. No SAML `class`/`def`/instantiation present. **Carve-out is honored.**

### IdP group-mapping note (2026-04-27 P0 — STILL UNRESOLVED)

Phase 217's `217-CONTEXT.md` "Out of scope" list explicitly defers gating to Phase 218: *"gating OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()` (audit P0 from `oc-separation-audit-20260427.md` — deferred to Phase 218)"*. Phase 218 was scoped as a closing-audit phase only — the deferral was never closed. The columns, schema fields, and `_resolve_role()` runtime path all execute unconditionally in community. A community admin with `manage_settings` can POST to `/settings/oauth-providers/` with `group_role_mapping` populated and have it applied at OAuth login.

**This is the sole reason Boundary Integrity misses the A− target.** A 1-day Phase 219 closes it.

### Marketplace billing note (2026-04-27 P1 — STILL UNRESOLVED)

All three loci unchanged: `docker-compose.yml:128-129`, `backend/app/core/config.py:87-88`, `backend/app/api/main.py:184-203`, plus the implementation at `backend/app/core/marketplace.py`. Inert when `AWS_MARKETPLACE_PRODUCT_CODE` is unset (the default), but monetization plumbing in the open-core codebase. Lower priority than the IdP P0 because no community deployment will trigger it accidentally.

---

## 2. Extension Seam Quality

### Infrastructure Overview

The seam infrastructure lives at `backend/app/platform/extensions/` and is composed of three small modules: `protocols.py` (3 `Protocol`s — `BrandingExtension`, `AuditExtension`, `AuthExtension`), `defaults.py` (4 community no-op implementations including `DefaultIdentityExtension`), and `__init__.py` (registry + 4 typed accessors). Discovery uses Python's stdlib `importlib.metadata.entry_points(group="geolens.extensions")` (`__init__.py:43`); enterprise overlays register protocol implementations and may push routers via the `_routers` key. `load_extensions()` runs once on FastAPI startup (`backend/app/api/main.py:125`); registered routers attach at `main.py:134-135`. `IdentityProtocol` / `IdentityExtension` lives separately in `backend/app/core/identity.py:32-96` (Phase 214) to keep `core/` free of `core → modules.auth` import edges. Edition gating uses `require_enterprise()` in `platform/extensions/guards.py:10` (returns **404** to avoid feature leakage).

The seam set is small but disciplined: every accessor returns either a registered overlay or a community default — call sites never see `None`. Counter-examples: `AuthExtension.get_auth_methods()` (`protocols.py:29`) is wired through `get_auth_extension()` but never read by any route; OAuth provider directory is closed via `CheckConstraint` (`oauth/models.py:34`) — novel IdP types (LDAP/Kerberos) require constraint relaxation.

### Seam-by-Seam Audit

| # | Seam | Rating | Current State | What's Missing | Effort |
|---|------|--------|---------------|----------------|--------|
| 1 | **Auth provider registry** | 🟢 | `IdentityExtension` Protocol at `core/identity.py:80-96`; consumed in BOTH `auth/dependencies.py:85` and `:141` before JWT fallback. SAML overlay shipped Phase 217 in `~/Code/geolens-enterprise/`. OAuth provider model has SAML deferred columns (`oauth/models.py:52-77`). | OAuth directory closed via `CheckConstraint` (`oauth/models.py:34`); `AuthExtension.get_auth_methods()` (`protocols.py:29`) has zero call sites | 0d |
| 2 | **Audit sink/export registry** | 🟢 | `AuditExtension.get_export_formats()` consulted at `audit/router.py:107`; route 404s if overlay advertises no formats (community returns `[]` via `defaults.py:16`); `require_enterprise` 404 gate at `:96` | No write-side hook — audit *sinks* (S3, SIEM, syslog) still write directly via `audit/service.py:log_action`. Adding `AuditSink.emit()` Protocol + consuming inside `log_action` enables external-system streaming | 1d |
| 3 | **Branding/theme provider** | 🟢 | `BrandingExtension.get_branding_defaults()` consulted at `settings/router.py:630`; "show_badge" toggle is the only contract; community returns `{"show_badge": True}` (`defaults.py:9`); persisted override takes precedence | Defaults dict is untyped (`dict[str, object]` at `protocols.py:15`); no schema for logo URL, primary color, custom CSS; frontend OKLCH theming has no API surface | 1d |
| 4 | **Policy/permission hooks** | 🟡 | Permission matrix data-driven via `DEFAULT_ROLE_PERMISSIONS` + DB override (`auth/permissions.py:43, 124`); validators block lockout/admin-cap escalation (`:81-116`). Visibility centralized at `catalog/authorization.py:34` (`apply_visibility_filter`) and per-record at `:134` (`check_dataset_access`) — Phase 213 relocation gives one chokepoint to wrap | No `PermissionExtension` Protocol; field-level RBAC, ABAC, row-level filters via attributes are not reachable. Capabilities are a fixed list (`ALL_CAPABILITIES` at `permissions.py:28`); enterprise can't inject new capabilities without core change | 1-2d |
| 5 | **Workflow/approval hooks** | 🔴 | `ALLOWED_TRANSITIONS` is hardcoded dict at `catalog/datasets/api/router_data.py:210-215`; `_STATUS_ORDER` at `:260`; both inlined in `update_publication_status` and `set_target_status` route bodies. No registry, no hook events, no approver concept | Entire state machine is a literal — multi-step approvals, reviewers, custom states all require core code changes | 2-3d |
| 6 | **AI provider registry** | 🔴 | Hardcoded if/elif on provider string at `ai/llm_loop.py:117,132`; same dispatch repeats at `ai/streaming.py:501,515`, `ai/metadata_service.py:253,289`, `ai/sql_generator.py:351,355`, `ai/service.py:387`. Only `"anthropic"` and `"openai_compatible"` recognized; no `AIExtension` Protocol | A registry-style dispatch (`provider_id → client builder`) so Bedrock, Vertex, Azure, on-prem vLLM can plug in. Today every new provider touches 5+ files | 2-3d |
| 7 | **Persistent connector registry** | 🔴 | Sources are stateless probes — `sources/adapters/{stac,wfs,ogcapi,arcgis}.py` are pure HTTP-call modules imported directly. No `Connector` ORM model, no scheduler table, no encrypted credential vault for source secrets (only OAuth client_secret encrypted via `oauth/encryption.py`); no `SourceAdapter` Protocol; no entry-point group for adapters | Connector entity (model + CRUD), scheduling table, credential encryption beyond OAuth, adapter Protocol + registry, polling/sync workers | 5-10d |
| 8 | **Tenant scoping hooks** | 🔴 | Zero `tenant_id`/`organization_id`/`workspace_id` columns anywhere. User model (`auth/models.py:18`) has only `id/username/email/status/auth_provider`. Visibility filter operates on `user.id` and roles; no tenant predicate; no request-scoped tenant-context middleware | Tenant column on every owned table, tenant-context middleware reading from JWT/subdomain, automatic predicate injection on every Select, tenant-scoped role overlay, tenant admin UI | 10-15d |

### Summary

- 🟢 **Ready: 3** (Auth provider registry, Audit export registry, Branding provider)
- 🟡 **Adaptable: 1** (Policy/permission hooks)
- 🔴 **Monolithic: 4** (Workflow/approval, AI provider registry, Connector registry, Tenant scoping)

### Movement vs 2026-04-26 Baseline (0🟢 / 3🟡 / 5🔴)

Three seams advanced from 🟡 to 🟢:

1. **Auth provider registry: 🟡 → 🟢.** Phase 214 extracted `IdentityProtocol`/`IdentityExtension` to `core/identity.py` and wired the hot path at `auth/dependencies.py:85, 141`. Phase 217 proved the seam by shipping the SAML enterprise overlay end-to-end (deferred SAML columns, docstring scrub, verification gate). The seam is now exercised by a real overlay, not just a Protocol declaration.

2. **Audit export registry: 🟡 → 🟢.** The route at `audit/router.py:107` consults `get_audit_extension().get_export_formats()` — community returns `[]` and `require_enterprise` 404s, while overlays advertise formats. (Probably under-credited at baseline; verifying it now confirms 🟢.)

3. **Branding provider: 🟡 → 🟢.** `settings/router.py:630` consults `get_branding_extension().get_branding_defaults()`. Functionally complete for the `show_badge` contract; future expansion (logo, theme tokens) is additive within the same seam.

Net delta: **3🟢 / 1🟡 / 4🔴** vs baseline **0🟢 / 3🟡 / 5🔴** — a meaningful improvement driven almost entirely by the Phase 214 + 217 identity work.

---

## 3. Feature Inventory Verification

### 3a. Community Edition

| Feature | Claimed | Actual Status | Evidence | Gaps |
|---|---|---|---|---|
| Catalog & dataset CRUD | Free | Present | `backend/app/modules/catalog/datasets/`, `frontend/src/components/dataset/*` (24 components) | None |
| Records discovery layer | Free | Present | `backend/app/modules/catalog/records/router.py`, `service.py`, `models.py` | None |
| Faceted filter / FTS search | Free | Present (Postgres FTS) | `backend/app/modules/catalog/search/service.py`, migration `0002_initial_tables.py` | Runtime `to_tsvector`; no GIN index — perf risk noted |
| Map viewer + builder | Free | Present | `frontend/src/pages/MapBuilderPage.tsx`, `PublicMapViewerPage.tsx`, `components/builder/` (40+ components) | None |
| Vector + raster ingestion | Free | Present | `backend/app/processing/ingest/`, `processing/raster/` | None |
| OGC API Features + Records | Free | Present | `backend/app/standards/ogc/router.py`, `schemas.py`, `filtering.py` | None |
| STAC | Free | Present | `backend/app/standards/stac/router.py`, `serializer.py`; STAC import at `catalog/sources/stac_router.py` | None |
| DCAT | Free | Present (service-level) | `backend/app/standards/dcat/service.py` | No DCAT HTTP router file; export likely via dataset endpoints |
| OAuth/OIDC providers | Free | Present | `backend/app/modules/auth/oauth/`, `frontend/src/components/admin/settings/SettingsAuthTab.tsx` | None |
| Audit log viewer | Free | Present | `backend/app/modules/audit/router.py`, `frontend/.../AuditLogViewer.tsx`, `pages/admin/AdminAuditPage.tsx` | None |
| Single-shot AI / NL chat | Free | Present (exceeds claim) | `backend/app/processing/ai/` — chat_service.py, llm_loop.py, sql_generator.py, tools.py, streaming.py | Has streaming + tool-calling; see §3c |
| Embed/share tokens | Free (basic) | Present | `backend/app/modules/embed_tokens/` — router.py, admin_router.py, service.py | None |
| Python SDK | Free / Apache-2.0 | Present | `sdks/python/geolens_sdk/`, `sdks/python/LICENSE` | Not on PyPI |
| TypeScript SDK | Free / Apache-2.0 | Present | `sdks/typescript/src/`, `sdks/typescript/LICENSE` | Not on npm |
| `geolens` CLI | Free / Apache-2.0 | Present | `cli/geolens_cli/` (main.py, scan.py, publish.py, export_stac.py, auth.py); `cli/LICENSE` | Not on PyPI |
| OpenAPI snapshot | Free | Present | `backend/openapi.json` (1,057,614 bytes) | None |
| Pgvector semantic search | Free (implicit, v7.2 shipped) | Present | `backend/app/processing/embeddings/` | Not in GTM CE list — see §3c |

### 3b. Enterprise Edition

| Feature | Claimed Tier | Current State | Partial Implementations | Distance to MVP |
|---|---|---|---|---|
| SAML SSO | Enterprise (overlay) | Correctly carved out per Phase 217 | `oauth/{schemas,service,models}.py` enum-string scaffolding; `settings/router.py:374-547` audit-leak protection; SAML logic in `~/Code/geolens-enterprise/` | **Frontend gap:** `frontend/src/pages/admin/AdminSamlPage.tsx` ships in CE bundle (gated at runtime). Decision: edition-gate sufficient or move to enterprise frontend overlay |
| Branding / "Powered by GeoLens" badge removal | Enterprise | Read-only in community, write-gated in enterprise | `BrandingExtension.get_branding_defaults()`, `settings/router.py:62, 630`, `frontend/.../AppLayout.tsx:14` | MVP-ready as tier check; no white-label OEM (custom domain, theme override) infrastructure beyond badge |
| Audit log export | Enterprise | Endpoint exists in core; format list empty by default | `audit/router.py:86-117`; `defaults.py:13-17` returns `[]` | Extension Protocol in place; enterprise overlay registers CSV/JSON formatters |
| Multi-tenant / cross-org | Enterprise | **Not implemented** | None | Far from MVP — new tenant model, row-level scoping, migration |
| SCIM provisioning | Enterprise | **Not implemented** | None | Far from MVP — full new module |
| White-label / custom domain / OEM | Enterprise | **Not implemented** beyond badge | Only `show_badge` (above) | Far from MVP — no theming overrides, no custom-domain routing |
| Air-gap / GovCloud | Enterprise | **Not implemented** | None | Likely deployment/packaging concern, not code |
| AWS Marketplace metering | Enterprise (implicit) | **Implemented in core** — runs at startup if configured | `core/marketplace.py`, `core/config.py:87-108`, `api/main.py:20, 190`, `tests/test_marketplace_metering.py` | MVP-ready functionally; misplaced architecturally — see §1 |
| Identity overlay (SSO IdP backend) | Enterprise | Protocol-only in core | `defaults.py:27-43` `DefaultIdentityExtension.resolve_identity_from_token` returns `None`; SAML overlay implements in enterprise repo | Hook ready |

### 3c. Undocumented Capabilities

Features present in code but not surfaced in `docs-internal/GTM/free-vs-enterprise.md`:

1. **Pgvector semantic search (v7.2)** — `backend/app/processing/embeddings/` is a full module. Not in CE feature list; should be a CE selling point or explicitly placed.
2. **AI streaming + tool-calling loop** — `backend/app/processing/ai/{streaming.py, llm_loop.py, tool_call_parser.py, tools.py}`. GTM doc claims "single-shot only" (`free-vs-enterprise.md:70`) but code has multi-turn `llm_loop` with tool execution. Either rename the tier description or restrict the loop in CE.
3. **Map records architecture (v12.0)** — `backend/app/modules/catalog/records/` with separate `records_router`. Distinct from datasets; unmentioned in GTM.
4. **VRT raster mosaics (v10.1)** — `catalog/datasets/api/router_vrt.py`, `processing/raster/vrt.py`. Unmentioned.
5. **STAC import (sources)** — `catalog/sources/stac_router.py` (federation-adjacent). GTM puts "Federation/connectors" in Enterprise; core already has STAC ingestion — clarify boundary.
6. **Embed-token admin router** — `embed_tokens/admin_router.py` is separate from public; admin controls aren't called out.
7. **Config Ops module** — `platform/config_ops/router.py` (env-only banners, runtime config diff). Not mentioned in either tier.
8. **AWS Marketplace metering** — Wired into core lifespan today, not behind any extension Protocol. Either gate or document explicitly.

### v13.1 Deltas (Phases 212-217)

- **Python SDK landed (Phase 215):** `sdks/python/geolens_sdk/` with full `api/` + `models/` packages, `LICENSE` Apache-2.0, `pyproject.toml` present.
- **TypeScript SDK landed (Phase 215):** `sdks/typescript/src/` with auto-generated `client/sdk.gen.ts` + `client/types.gen.ts` from `@hey-api/openapi-ts`, `LICENSE` Apache-2.0.
- **OpenAPI snapshot (Phase 215):** `backend/openapi.json` regenerated by `scripts/dump_openapi.py`; CI drift gate at `.github/workflows/ci.yml`.
- **CLI landed (Phase 216):** `cli/geolens_cli/` ships 7 commands (login, logout, whoami, scan, publish, export stac), exceeds 4-MVP target. `LICENSE` Apache-2.0.
- **SAML moved to enterprise overlay (Phase 217):** Backend retains only enum-string scaffolding (no SAML auth logic). No `/saml/acs` or `/saml/login` routes in core. **One frontend gap:** `frontend/src/pages/admin/AdminSamlPage.tsx` ships in CE — review whether `useEdition()` gating is sufficient or move to enterprise frontend overlay.
- **User-facing docs:** `docs/sdks.md` (13.6 KB), `docs/cli.md` (14.2 KB), `docs/saml.md`.

---

## 4. Deployment Separation

### Current packaging model

GeoLens ships a single set of Docker images plus a 29-line additive overlay (`docker-compose.enterprise.yml:1-28`) that bind-mounts a sibling `../geolens-enterprise` package and points entrypoints at it via `GEOLENS_ENTERPRISE_PATH`. There is no separate enterprise image, no Helm chart, no `deployment/` directory — the open-core boundary is enforced entirely at the Python entry-point layer (`backend/app/platform/extensions/__init__.py:43`).

### Overlay correctness audit

`docker-compose.enterprise.yml` is clean: three services patched (`api`, `worker`, `migrate`) with identical volume + env injection (lines 4-20); `migrate` wraps its command to conditionally `uv add --editable /enterprise` before `alembic upgrade head` (lines 21-28); no image overrides or `build:` blocks — pure additive layering. Base `docker-compose.yml` contains no enterprise-suggestive references (`branding`, `saml`, `audit`, `tenants` are absent).

### Environment variable strategy

Edition detection lives in `backend/app/core/edition.py:27-40`:
- `GEOLENS_EDITION` env var (`community`/`enterprise`) is the authoritative override.
- Auto-detection falls back to `enterprise if loaded_extensions else community` (line 37).
- `is_enterprise()` (line 50) is the single boolean gate consumed by `guards.py:16` and `modules/settings/router.py:100`.

Feature toggles outside the extension system are sparse: `_ENTERPRISE_ONLY_TABS` constant (`settings/router.py:62`) explicitly lists `branding` as paid; the gate at lines 98-104 now correctly returns **`HTTP_404_NOT_FOUND`** with no detail body, matching the `require_enterprise()` 404 contract in `guards.py:11-17`. **The 2026-04-27 P1 finding (revealing 403 detail string) is RESOLVED.**

### Conditional module loading

`api/main.py:125-135` performs runtime wiring inside the lifespan:
1. `load_extensions()` walks `geolens.extensions` entry-point group (`platform/extensions/__init__.py:43-57`).
2. `init_edition(list_extensions())` stamps the singleton.
3. `for ext_router in get_extension_routers(): app.include_router(ext_router)` mounts enterprise routes only when the package is present.

Typed accessors return `Default*` no-op implementations when the key is missing — open-core null-object pattern implemented cleanly. Shell entrypoints (`backend/scripts/{api,worker}-entrypoint.sh:42-49`) graceful-degrade if `/enterprise/pyproject.toml` is absent.

### Blockers

**None** for clean community + enterprise packaging. Tested end-to-end via `backend/tests/test_edition.py:34-110`.

### Specific gaps

- **No `deployment/` directory.** Confirmed — only `db/`, `frontend/`, `backend/`, `docs/` and root compose files exist. For a v1.0.0 release with enterprise GTM aspirations this is a documentation/artifact gap, not a code gap.
- **No Helm chart.** `find . -name Chart.yaml -o -name values.yaml` returns zero matches. K8s deploy stories are entirely DIY.
- **AWS Marketplace billing in base runtime** (P1 — same loci as §1): `docker-compose.yml:128-129`, `core/config.py:87-88`, `api/main.py:184-203`. Dormant when product-code env unset; recommend extracting to `docker-compose.marketplace-aws.yml` overlay so community has no AWS billing surface.
- **`.env.example` does not document edition vars.** Marketplace vars at `:347-356`, but `GEOLENS_EDITION` and `GEOLENS_ENTERPRISE_PATH` are not, despite being primary edition-control switches.

---

## 5. Codebase Coupling

### Dependency matrix

Counts as of 2026-04-29 (`grep -rn "^from app\..." backend/app/`, excluding `__pycache__`).

| Domain | Inbound files | Outbound (cross-module) | Outbound to `core`/`db`/`platform` |
|---|---|---|---|
| `auth` | 70 | 1 | 12 |
| `audit` | 20 | 1 | 5 |
| `admin` | 4 | 9 | 2 |
| `settings` | 3 | 4 | 7 |
| `catalog` | 141 | 12 | 68 |
| `processing` (incl. `processing/ai` = 32) | 107 | 110 unique cross lines | n/a (sibling pkg) |

Top-level `User` import sites: **20 files** (down from baseline 51 — `IdentityProtocol` consumers now total 41 files). `log_action(` call sites: **19** (was 14 in baseline; spread across `core/persistent_config.py`, `processing/ingest/tasks_common.py`, `processing/export/router.py`, `platform/config_ops/service.py`, plus 15 module routers).

### Coupling risk by domain

| Domain | Risk | Inbound | Outbound | Notes |
|---|---|---|---|---|
| auth | 🟡 | 70 | 1 module + 12 core | Highest fan-in; `User` direct imports cut 51→20 via `core/identity.IdentityProtocol`. SAML overlay shipped, no SAML logic in core |
| audit | 🟢 | 20 | 1 | Effectively a leaf. `log_action` is the only widely-called surface (19 sites); easy overlay seam |
| admin | 🟢 | 4 | 9 | Thin coordinator |
| settings | 🟢 | 3 | 4 | Phase 212 broke `core ↔ settings` cycle (0 hits in `backend/app/core/`) |
| catalog | 🔴 | 141 | 12 module + 68 core | Highest fan-in and fan-out. `processing/` directly imports `catalog.datasets.domain.models` from 16 files. `domain/service.py` is 1407 LOC with 32 `app.*` imports (29 function-scoped) |
| processing/ai | 🔴 | 107 (32 ai) | 110 unique import lines | Two-way coupling with catalog: catalog → processing (10+ unique import lines) and processing → catalog (16+ unique). `processing/ingest/service.py` has 18 `app.*` imports; `processing/ai/service.py` has 16 |

### Specific decoupling wins from v13.1

1. **Phase 212 layering inversion fixed** — `grep -n "from app\.modules\.settings" backend/app/core/` returns 0. `core/persistent_config.py:30` and `core/public_urls.py:14` no longer pull `AppSetting`. Cycle eliminated.
2. **Phase 213 visibility relocation complete** — `backend/app/modules/auth/visibility.py` is gone; `from app.modules.auth.visibility` has 0 callers. Authorization lives at `backend/app/modules/catalog/authorization.py` where it depends on `DatasetGrant` (no deferred import needed).
3. **Phase 214 IdentityProtocol seam working** — `backend/app/core/identity.py:47` defines `IdentityProtocol`; `IdentityExtension` is wired via `platform/extensions/__init__.py:19`. `User` model imports dropped 51→20; 41 files now type against the protocol.

### Remaining coupling debt

- **Function-scoped imports**: 106 inside `backend/app/modules/` (was 106 in baseline — unchanged) + 127 inside `backend/app/processing/`. Catalog alone owns 71 of the modules count. These are the primary cycle workaround signal.
- **`catalog/datasets/domain/service.py` density**: 1407 LOC, 32 `app.*` imports (29 function-scoped). Reaches into `app.processing.embeddings.tasks`, `app.processing.raster.models`, `app.processing.ingest.metadata`, `app.modules.catalog.{records,maps,validation,collections}.service`, `app.platform.storage.provider`, `app.core.persistent_config` — the de-facto orchestration god-module.
- **catalog ↔ processing two-way coupling**: 16 files in `backend/app/processing/` and `backend/app/standards/` import `app.modules.catalog.datasets.domain.models`. Inverse: catalog imports 10+ symbols from `processing.embeddings`, `processing.export`, `processing.ingest`, `processing.raster`. Extracting either side requires breaking this knot.
- **`log_action` not centralized**: 19 call sites scattered across `core/persistent_config.py`, `platform/config_ops/service.py`, processing routers, most catalog routers. No injectable audit sink Protocol yet.
- **`embed_tokens` reaches into catalog internals**: `embed_tokens/service.py` imports `MapLayer`, `check_map_ownership`, `get_map` from `catalog.maps` (cross-domain knowledge of map ownership semantics).

### Specific recommendations (top 3)

1. **Decompose `catalog/datasets/domain/service.py`** — split into `service_lifecycle.py`, `service_relationships.py`, `service_search_facets.py`. Cuts catalog's intra-package fan-out and exposes clean seams for enterprise extension of publish-gate logic.
2. **Invert `catalog → processing` via `ProcessingProtocol` in `app.core/`** — mirror IdentityProtocol pattern. Define `IngestionProvider`, `EmbeddingProvider`, `RasterProvider` so `catalog/datasets/domain/service.py` stops reaching into `app.processing.*` directly. Lets enterprise overlay swap raster/embedding backends without forking catalog.
3. **Centralize `log_action` behind `AuditSink` Protocol** registered like `IdentityExtension`. The 19 call sites currently each `from app.modules.audit.service import log_action`; a single `core/audit.py` Protocol with default community implementation (and an enterprise sink for tamper-evident logging) removes inbound pressure on the audit module and unblocks compliance overlays. Highest-leverage win since `audit` is already a near-leaf.

---

## 6. OSS Surface & Licensing

### Readiness table

| Dimension | Y/N | Path | Rating | Gaps |
|---|---|---|---|---|
| CLI exists | Y | `cli/geolens_cli/main.py` — Apache-2.0, 7 commands (`login`, `logout`, `whoami`, `scan`, `publish`, `export stac`, `--version`) | **A** | Distribution is built wheel only (`cli/dist/geolens-1.0.0-py3-none-any.whl`); no `publish-cli` GitHub Action |
| Python SDK exists | Y | `sdks/python/geolens_sdk/` — Apache-2.0, name `geolens-sdk` v1.0.0, generated by `openapi-python-client@0.28.3` | **A** | Not yet on PyPI (token wired but workflow not run — `.github/workflows/publish-sdks.yml`) |
| TypeScript SDK exists | Y | `sdks/typescript/src/` — Apache-2.0, `@geolens/sdk` v1.0.0, generated by `@hey-api/openapi-ts@0.96.1` | **A** | npm org `@geolens` not yet claimed; built dist exists but unpublished |
| OpenAPI snapshot | Y | `backend/openapi.json` (1,057,614 bytes); CI drift gate at `.github/workflows/ci.yml:79-107` (`openapi-snapshot` job) and `sdks-check` job at lines 109-146 | **A** | None — drift gating enforced |
| Schema/validator package | Partial | Pydantic models in `backend/app/modules/**/schemas.py`; reachable indirectly via SDK regeneration | **C** | No standalone `geolens-schemas`/`geolens-validator` package |
| Catalog manifest spec (`geolens.yaml`) | **N** | Searched repo root + `backend/app/`; zero matches | **F** | Declarative catalog manifest absent — largest remaining open-core enabler not delivered by Phases 215/216 |

### License findings

All four LICENSE files Apache-2.0 v2.0:
- `/Users/ishiland/Code/geolens/LICENSE` — repo root
- `/Users/ishiland/Code/geolens/cli/LICENSE`
- `/Users/ishiland/Code/geolens/sdks/python/LICENSE`
- `/Users/ishiland/Code/geolens/sdks/typescript/LICENSE`

Package metadata Apache-2.0 across the board:
- `backend/pyproject.toml:6` — `license = "Apache-2.0"` + `license-files = ["LICENSE"]`
- `frontend/package.json:6` — `"license": "Apache-2.0"`
- `cli/pyproject.toml:9` — `license = { text = "Apache-2.0" }` + OSI classifier
- `sdks/python/pyproject.toml:9` — `license = { text = "Apache-2.0" }`
- `sdks/typescript/package.json:4` — `"license": "Apache-2.0"`

Source files do not carry per-file SPDX headers; acceptable for Apache-2.0 with NOTICE-style top-level LICENSE, but adding `# SPDX-License-Identifier: Apache-2.0` would harden provenance.

### Copyleft contamination

**Zero hits.** `grep "GPL\|AGPL\|copyleft"` across `backend/app/`, `frontend/src/`, `cli/`, `sdks/` returned no matches.

### Distribution status

- **Python SDK**: Not on PyPI. Wheel + sdist built locally. Manual workflow exists (`publish-sdks.yml:32-60`); requires `PYPI_TOKEN`.
- **CLI**: Not on PyPI. Wheel + sdist built locally. No publish workflow.
- **TypeScript SDK**: Not on npm. Build artifacts present. Manual workflow `publish-typescript` job exists; requires `NPM_TOKEN` and one-time `@geolens` org claim.

### v13.1 delivery vs gaps

**Shipped (Phases 215+216):** Three Apache-2.0 packages, enforced OpenAPI drift gate, generator pipeline documented in `Makefile:46-86`, version-pinning helper at `scripts/sync_sdk_versions.py`, user-facing docs at `docs/cli.md` and `docs/sdks.md`. CLI command set exceeds the §216 four-command MVP target.

**Still missing:** (1) `geolens.yaml` catalog manifest spec — the most impactful unshipped open-core surface; (2) live PyPI/npm publishes — workflows wired but never run; (3) standalone schema/validator package; (4) per-file SPDX headers.

**Grade: A−** — matches the 2026-04-27 audit. Holding short of A solely because manifest spec + live registry distribution remain unshipped.

---

## 7. Prioritized Action Items

| Priority | Action | Domain | Effort | Rationale | Blocks |
|----------|--------|--------|--------|-----------|--------|
| **P0** | Gate OAuth `group_claim` / `group_role_mapping` behind `is_enterprise()` checks (schema validators + service runtime branch) | `auth/oauth/{schemas,service}.py` | 1d | Phase 217's deferred P0; the SOLE reason Boundary Integrity misses A−. Without this, v13.1 close criterion is not met | v13.1 milestone close (AUDIT-V1) |
| **P1** | Extract AWS Marketplace billing to enterprise overlay via `BillingExtension.on_startup()` hook | `core/marketplace.py`, `api/main.py:184-203`, `docker-compose.yml:128-129` | 1-2d | Carry-over from 2026-04-27 P1; monetization plumbing should not ship in open-core base runtime | First paid customer |
| **P1** | Define `geolens.yaml` catalog manifest spec + reference validator | `cli/`, new `geolens-schemas/` | 1-2 weeks | Largest unshipped open-core enabler; declarative-config workflows | Ecosystem adoption |
| **P1** | Publish CLI + Python SDK to PyPI; TypeScript SDK to npm (one-time org claim + token wire-up) | `.github/workflows/publish-sdks.yml`, new `publish-cli.yml` | 0.5-1d | Built artifacts exist but installable distribution does not | Practitioner adoption |
| **P1** | Resolve AI streaming vs GTM "single-shot only" claim — either restrict CE loop OR rewrite GTM line | `processing/ai/{streaming.py,llm_loop.py}` OR `docs-internal/GTM/free-vs-enterprise.md:70` | 0.5d | Tier line in GTM doc contradicts shipped capability | GTM accuracy |
| **P1** | Verify `frontend/src/pages/admin/AdminSamlPage.tsx` edition gating is sufficient OR move to enterprise frontend overlay | `frontend/src/pages/admin/AdminSamlPage.tsx` | 0.5d | Page lives in CE bundle; runtime `useEdition()` redirect at `:28-33` is the only gate | Boundary defense-in-depth |
| **P2** | Decompose `catalog/datasets/domain/service.py` (1407 LOC, 29 function-scoped imports) | `modules/catalog/datasets/domain/` | 1 week | Catalog god-module is the primary cycle source | Future enterprise extensions of publish logic |
| **P2** | Define `ProcessingProtocol` in `core/` to invert catalog → processing dependency | new `core/processing.py` | 3-5d | Mirror IdentityProtocol pattern | Enterprise raster/embedding backend swaps |
| **P2** | Centralize `log_action` behind `AuditSink` Protocol | new `core/audit.py`, refactor 19 call sites | 1-2d | `audit` is near-leaf; centralizing unblocks compliance overlays | Compliance-tier audit sinks (S3, SIEM, syslog) |
| **P2** | Add `PermissionExtension` Protocol for field-level RBAC and row-level filter injection | `auth/permissions.py`, `catalog/authorization.py` | 2-3d | Capabilities are a fixed list; field-level RBAC is enterprise-tier feature | Business-tier RBAC admin UI |
| **P2** | Workflow / approval state machine via `WorkflowExtension` Protocol; replace `ALLOWED_TRANSITIONS` literal | `catalog/datasets/api/router_data.py:210` | 3-5d | State machine is hardcoded dict; reviewer/approver model needs hooks | Business-tier approval workflows |
| **P2** | AI provider registry (`AIExtension` Protocol) — convert 5+ if/elif dispatch to lookup | `processing/ai/llm_loop.py:117,132`, et al. | 2-3d | Every new provider touches 5+ files | Business-tier AI policy + provider routing |
| **P2** | Persistent connector registry (`SourceAdapter` Protocol + `Connector` model + scheduler + encrypted credential vault) | `modules/catalog/sources/` | 5-10d | No connector entity, scheduler, credential store today | Business-tier scheduled mirroring |
| **P2** | Helm chart + `deployment/` directory | new `deployment/k8s/` | 1 week | K8s deploy stories entirely DIY; benefits Marketplace listings | Cloud-platform / K8s buyers |
| **P2** | `.env.example` documents `GEOLENS_EDITION` + `GEOLENS_ENTERPRISE_PATH` | `.env.example` | 0.25d | Primary edition-control switches undocumented | Operator onboarding |
| **P2** | Standalone `geolens-schemas` package (extract pydantic models for third-party validation) | new package | 3-5d | Consumers must depend on full SDK to validate | Ecosystem tooling |
| **P3** | Per-file SPDX headers across first-party source | `backend/app/`, `frontend/src/`, `cli/`, `sdks/` | 0.5d | Provenance hardening; cosmetic | License-scanning tools |
| **P3** | Tenant scoping infrastructure (model, middleware, predicate injection) | repo-wide | 2-4 weeks | Multi-tenant isolation is Enterprise tier; no scaffolding today | Enterprise multi-tenant tier |

---

## 8. Comparison to Prior Audit

**Source baseline:** `docs-internal/audits/oc-separation-audit-20260426-b.md` (the same-day re-run that motivated the v13.1 milestone). Mid-milestone reference: `oc-separation-audit-20260427.md` (after 212-216 inline remediation, before 217 SAML).

### Grade-delta table

| Dimension | Source (2026-04-26) | v13.1 Close (this run) | Δ | Target | Met? |
|-----------|---------------------|------------------------|---|--------|------|
| Boundary Integrity | B | B− | ↓ (vs source); ↑ (vs 2026-04-27 — same) | A− | **❌ NO** |
| Seam Quality | C | B | ↑ | B | ✅ YES |
| Inventory Accuracy | A− | B+ | ↓ (more undocumented capabilities surfaced) | — | n/a |
| Deployment Separation | A | B | ↓ (one new finding: Marketplace + missing deployment/) | — | n/a |
| Coupling Health | C | B− | ↑ | — | n/a |
| OSS Surface Readiness | D | A− | ↑↑ (CLI + 2 SDKs + OpenAPI snapshot landed) | C | ✅ YES |

### What Improved

- **Coupling Health: C → B−.** `User` import sites cut from 51 → 20 (−61%) via `IdentityProtocol`. `core ↔ settings` cycle eliminated (0 hits in `backend/app/core/`). `auth/visibility.py` cleanly relocated to `catalog/authorization.py` with no deferred-import shims. Phase 212/213/214 fixes all verified.
- **OSS Surface Readiness: D → A−.** From "CLI/SDKs/manifest absent" to three Apache-2.0 packages (CLI 7 commands; Python + TypeScript SDKs) plus enforced OpenAPI drift gate. Phase 215/216 delivery.
- **Seam Quality: C → B.** Three seams advanced from 🟡 to 🟢 (auth provider, audit export, branding). Phase 214 + 217 identity work proved the seam end-to-end with a real overlay.
- **2026-04-27 P1 fix verified (Deployment §4):** Settings router gate now correctly returns 404 with no detail body, matching `require_enterprise()` 404 contract. `_ENTERPRISE_ONLY_TABS` consistency restored.

### What Regressed (vs source baseline)

- **Boundary Integrity: B → B−.** Source baseline had 1 🔴 (audit-export ungated). This run has 3 🔴 collapsing to 1 architectural P0 (OAuth IdP role mapping) — the audit-export gate is fixed, but a new P0 surfaced in the 2026-04-27 audit was not closed in v13.1. Matches the 2026-04-27 grade exactly; Phase 217 deferred the fix to Phase 218.
- **Deployment Separation: A → B.** Source baseline graded A on "zero blockers". This run keeps that "zero blockers" assessment but adds two negatives the source did not surface: (a) AWS Marketplace billing in core runtime (P1); (b) missing `deployment/` directory and Helm chart. Both are pre-existing conditions not measured in the source baseline.
- **Inventory Accuracy: A− → B+.** Closer scan in this run surfaced 7 undocumented capabilities (AI streaming/tool-calling, pgvector semantic search, VRT mosaics, records architecture, STAC import, embed-token admin router, config_ops module). The source baseline noted 9 at A−; this run notes 8 (slightly fewer undocumented but the GTM-vs-code single-shot AI contradiction is more severe).

### What's Unchanged

- **SAML carve-out** (Phase 217) is honored. Four documented files contain only enum-string scaffolding; no SAML logic in core.
- **Standards (OGC/STAC/DCAT)** remain HARD-FREE. Zero `require_enterprise`/`require_edition` calls.
- **Multi-tenant, federation, SCIM, airgap, govcloud, AI policy, approval workflow, white-label-toggle** all return zero greps. Boundary intact for the enterprise-tier-only feature set.
- **`docker-compose.enterprise.yml`** remains a clean 29-line additive overlay.
- **All licensing** Apache-2.0 across root, CLI, both SDKs; zero copyleft contamination.

### Net trajectory

Overall readiness moved from **B− (2.61 / 4.0)** at the source baseline to **B (3.06 / 4.0)** in this run — a meaningful improvement driven by Phase 212-217 work. The single remaining miss (Boundary B− vs target A−) is a deferred P0 from Phase 217 with a well-scoped 1-day fix path (Phase 219). Once gated, the boundary moves to A− or A and the v13.1 milestone-close contract is satisfied.

---

## P1 Residual Triage

> Per Phase 218 CONTEXT.md D-04 / D-05: every P1+ residual finding gets an explicit verdict — Fix-now (→ follow-up phase), Demote to P2 (→ deferred-items.md row), or Accept as OOS (→ phase-scope rationale).
>
> Only findings at the threshold of milestone close (P0/P1) appear in this table. P2 items below the close threshold flow through normal §7 backlog.

| # | Finding (audit ref) | File:line | Verdict | Rationale | Follow-up |
|---|---------------------|-----------|---------|-----------|-----------|
| 1 | OAuth IdP→role mapping in core (3 🔴 sites — schema + service + model) | `oauth/{schemas,service,models}.py` (§1) | **Fix-now** | Sole cause of Boundary B− vs A− target. Phase 217's documented deferral (`217-CONTEXT.md` "Out of scope"). Without this fix v13.1 milestone-close criterion AUDIT-V1 fails. ~1d effort: 2 model_validators + 1 runtime branch | **Phase 219: oc-audit-remediate-idp-mapping** (proposed). Re-run audit on completion; if Boundary ≥ A−, retire this audit doc and produce v13.1-close.md with passing grades, OR amend this v13.1-close.md in place with the remediated grade. |
| 2 | AWS Marketplace billing in core runtime (3 🟡 loci) | `core/marketplace.py`, `core/config.py:87-88, 108`, `api/main.py:184-203`, `docker-compose.yml:128-129` (§1, §4) | **Demote to P2** | Inert when `AWS_MARKETPLACE_PRODUCT_CODE` unset (the default). No community deployment triggers it accidentally. Architectural cleanup (extract to `BillingExtension`), not a v13.1 close blocker. Carry-over from 2026-04-27 audit. | Add row to `oc-separation-deferred-items-20260426.md` under "P2 — Address as enterprise tier ships": *"Move AWS Marketplace billing to enterprise overlay via BillingExtension.on_startup() hook (1-2d)"*. |
| 3 | `frontend/src/pages/admin/AdminSamlPage.tsx` ships in CE bundle | `frontend/src/pages/admin/AdminSamlPage.tsx:28-33` (§3b, §3 v13.1 deltas) | **Accept as OOS** | The page is gated at runtime via `useEdition()` → redirect. SAML data fetches go to backend endpoints that 404 in community via `require_enterprise()`. Bundle-size impact is minimal (one route). Frontend bundle code-split for enterprise components is already a P2 row in `oc-separation-deferred-items-20260426.md`, where this finding belongs. | None for v13.1 close. Reference: existing P2 deferred-items row "Frontend code-splitting for enterprise components". |
| 4 | AI streaming + tool-calling in CE contradicts GTM "single-shot only" claim | `processing/ai/{streaming.py, llm_loop.py, tool_call_parser.py}` vs `docs-internal/GTM/free-vs-enterprise.md:70` (§3c) | **Accept as OOS** | This is a GTM-doc accuracy issue, not a code/boundary issue. The shipped behavior is correct CE behavior (interactive chat). The fix is rewriting the GTM line to match reality, which is a docs writing pass outside Phase 218's "verification + triage only" scope. | None for v13.1 close. Recommend a small docs phase post-v13.1 to align GTM language with shipped capabilities. |
| 5 | `geolens.yaml` catalog manifest spec absent | repo-wide (§6) | **Accept as OOS** | OSS Surface graded A− (exceeds target C). Manifest spec is a post-v13.1 ecosystem enabler, not a v13.1 commitment. Already a P2 row in `oc-separation-deferred-items-20260426.md` under "P2 — Address as enterprise tier ships" header (*"Define `geolens.yaml` catalog manifest spec"*). | None for v13.1 close. Existing P2 row stays. |
| 6 | CLI / SDK distribution targets (PyPI, npm) not yet activated | `.github/workflows/publish-sdks.yml` and absent `publish-cli.yml` (§6) | **Demote to P2** | Built wheels and `npm` artifacts exist; the gap is the one-time PyPI/npm credential setup + first publish run. Not a code/boundary issue. v13.1 close criterion is "CLI + SDKs exist Apache-2.0" (✓ via §6), not "are installable from public registries". | Add row to `oc-separation-deferred-items-20260426.md` under "P2": *"Activate CLI + SDK distribution to PyPI/npm (one-time org claim + token wire-up; 0.5-1d)"*. |

### Triage summary

- **Fix-now: 1** (the IdP mapping P0 — drives v13.1 close)
- **Demote to P2: 2** (Marketplace billing, distribution activation)
- **Accept as OOS: 3** (frontend SAML page, AI single-shot wording, manifest spec)

### Milestone close decision

**v13.1 milestone close BLOCKED** until finding #1 is resolved.

Two paths forward (user decision):

1. **Plan and execute Phase 219 (oc-audit-remediate-idp-mapping).** Estimated 1 day. Scope: gate `oauth/schemas.py:116-129, 237-248` write fields, gate `oauth/service.py:261-263` runtime branch, optional comment on `oauth/models.py:82-84` columns. Re-run audit on completion. If Boundary ≥ A−, finalize v13.1 close.
2. **Slip v13.1 milestone to v13.2.** Reframe v13.1 as "Open-Core Separation P1 — partial close" with the IdP P0 documented as v13.2 scope. Lower-friction but loses the milestone-grade contract.

Recommended: Path 1. The fix is small, well-scoped, and closes a specific architectural debt that is otherwise visible to every audit run.

---

*Audit run: 2026-04-29 by /oc-audit at HEAD `0f656a43` (post-Phase-217 close). 6 parallel subagents. v13.1 closing-audit run.*
