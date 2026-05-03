# 🧩 GeoLens Packaging Matrix

**Guiding principle:** *Open the ecosystem surface. Give small teams a complete Community Edition. Charge for operational trust, tenant isolation, deployment control, compliance, and automation.*

**Positioning:** *Enterprise-priced, practitioner-adopted.* GeoLens is geospatial data infrastructure — priced per-deployment, sold top-down to procurement-driven buyers, but adopted bottom-up by practitioners. The free Community Edition has to be excellent on its own terms, because the practitioner creates the internal demand even when the enterprise buyer signs the contract.

---

## 🟢 Community Edition (Free / Open)

**Goal:**
Max adoption. Zero friction. Fully usable for individuals and small teams.

### Core Data Platform

* Catalog + search (full-text + semantic)
* Faceted filtering
* Dataset preview (vector, raster, tabular)
* Collections (basic grouping)
* Versioning (basic)

### Data Ingestion

* File uploads (Shapefile, GeoJSON, GPKG, CSV, etc.)
* WFS / ArcGIS import
* Raster → COG conversion
* VRT creation
* Schema preview + diff

> 📝 **Future consideration:** *Scheduled mirroring* with stored credentials (auto-resync from S3 / WFS / ArcGIS / PostGIS on a recurring basis) is a candidate enterprise feature when it's built — that's an operational concern (compliance scope, key rotation, attack surface) rather than an ingestion concern. Import itself stays free regardless.

### Map + Visualization

* Map viewer
* Map builder (layers, styling, filters, labels)
* Vector tiles + raster rendering
* Basic basemap config

### Editing

* Geometry editing
* Attribute editing
* Schema editing (basic)

### Standards (HARD-FREE — VERY IMPORTANT to keep free)

* OGC API Features
* OGC API Records
* STAC export
* DCAT metadata

👉 This MUST stay free or you kill adoption.

### Sharing (Basic)

* Share links (non-expiring)
* Public/internal visibility toggle
* Basic embed

### Admin & Identity

* User accounts with role labels (viewer/editor/admin)
* Multi-user collaboration in a single deployment (shared collections, shared maps, role-based access)
* Basic per-user API keys (no quotas, no usage tracking)
* Basic audit log **viewing and searching** (no export, no compliance reports)
* Basic OIDC / OAuth login

> 📝 **Note on the multi-user vs multi-tenant boundary:** Multiple users collaborating in one deployment (one team, one org's data) is FREE. *Multi-tenant isolation* — multiple separate organizations sharing one deployment with isolated data, users, and billing — is **not an Enterprise self-hosted feature**. It belongs to a future hosted Cloud tier where the vendor operates one shared deployment for many customer orgs (see §3 Cloud Edition). Self-hosted Enterprise is single-tenant by design — that's what regulated, procurement-driven buyers actually want.

### AI (Limited — interactive, single-shot only)

* Chat-style map generation (one prompt → one map)
* Single styling-suggestion edits
* One-off metadata field assistance during manual editing

> ⚠️ **Note:** *Batch / automated / policy-controlled* AI is paid (auto-metadata for new uploads, scheduled summarization, model routing, AI policies). The line is: "I press a button and get one result now" → free; "GeoLens runs AI on my behalf in the background" → paid.

---

## 🛠 Open-Source Developer Surface (Free / Apache-2.0)

A permissively-licensed developer surface is the adoption wedge. Open these (when implemented):

* **GeoLens CLI** (`geolens scan`, `geolens publish`, `geolens export stac`, etc.) — Apache-2.0
* **SDKs / API clients** — Apache-2.0
* **Metadata schema definitions + validators** — Apache-2.0
* **STAC / GeoParquet / COG import-export utilities** — Apache-2.0
* **Sample connectors and recipes** — Apache-2.0
* **Catalog manifest format** (declarative `geolens.yaml` for describing datasets, sources, publishing rules) — Apache-2.0

👉 The CLI and SDK are how developers integrate GeoLens before they ever buy the platform. Permissive licensing here is non-negotiable — copyleft (GPL/AGPL) on the developer surface scares enterprise and government adopters.

### 🎯 Concrete adoption target

> **A new user should be able to publish a working geospatial catalog in 10 minutes — from `docker compose up` to a browsable, shareable catalog of their own data.**

This is the falsifiable goal that drives the Community Edition's quality bar. If a practitioner cannot get there in one sitting, the bottom-up adoption motion fails — and "Enterprise-priced, practitioner-adopted" collapses to "enterprise-priced, never adopted." The CLI / Docker Compose / sample data / first-run docs all serve this single target.

---

## 🧾 Undocumented capabilities (for GTM placement decisions)

These ship in Community today but were not classified in either §1 (Community) or §2 (Enterprise). All 10 tier placements were locked in on **2026-04-30** per the post-v13.2 audit (`docs-internal/audits/oc-separation-audit-20260430.md` §3c). Two rows ("Config import/export" and "Embed-token bulk-revoke") were resolved to Community on the principle: *don't paywall already-shipped admin utilities; layer richer governance features on top in the Enterprise overlay.* Audit reference: `docs-internal/audits/oc-separation-audit-20260426-b.md` §3.

| Capability | Surface | Tier | Status (as of 2026-04-30) |
|---|---|---|---|
| AI metadata assist suite | `processing/ai/router.py` `/ai/metadata/{summary,keywords,lineage,quality}/` | **Community** | ✅ Locked — matches "one-off metadata field assistance" |
| AI chat for map editing (streaming) | `/ai/chat/`, `/ai/chat/stream/` | **Community** | ✅ Locked — matches "press a button → get one result"; internal `MAX_TOOL_ROUNDS=5` is implementation, not background AI |
| Sandbox SQL executor | `platform/sandbox/{executor,validator}.py` | **Community** | ✅ Locked — internal infrastructure, powers AI tools |
| STAC catalog import client | `modules/catalog/sources/stac_router.py` | **Community** | ✅ Locked — already covered by "WFS/ArcGIS/STAC import" |
| Pending-account approval flow | `modules/auth/router.py:81,147,169` | **Community** | ✅ Locked — multi-user collab; distinct from enterprise *approval workflows* (draft→review→publish) |
| Jobs admin router | `platform/jobs/router.py` (`/jobs/cleanup/stale/`, `/jobs/by-dataset/{id}`) | **Community admin** | ✅ Locked — operations utility |
| AWS Marketplace metering | `geolens-enterprise/billing/` (hourly billing hook via `BillingExtension`) | **Cloud / Enterprise** | ✅ Locked — foundation for usage-based pricing. ✅ Extracted to enterprise overlay (Phase 223, 2026-04-30): `core/marketplace.py` deleted, `Settings.aws_marketplace_*` removed, `api/main.py:184-209` runs generic `for ext in get_billing_extensions(): await ext.on_startup(app)` dispatch. AWS Marketplace overlay subscribes via `BillingExtension` Protocol (`platform/extensions/protocols.py:62-83`). |
| AI token usage ledger | DB table populated by AI dispatch | **Implicit Enterprise** | ✅ Locked — foundation for AI governance/quotas; surface when AI governance ships |
| Config import/export | `platform/config_ops/router.py` (`/config-ops/{export,import,validate,dry-run}/`) | **Community** | ✅ Locked — single-deployment config backup/restore is individual-deployment ergonomics. The Business "configuration-as-code" angle is multi-deployment governance (drift detection, GitOps, central policy) — that lands as a *separate Enterprise overlay on top* of this endpoint, not a paywall on the endpoint itself. |
| Embed-token bulk-revoke | `modules/embed_tokens/admin_router.py` (`BulkRevokeRequest`) | **Community admin** | ✅ Locked — multi-delete operation is admin convenience for incident response. The Enterprise upsell is the *richer* embed-token surface (domain-restricted embeds, expiring links with revocation reasons, tokenized API + quotas, full management UI with audit trail) — not the bulk-DELETE primitive. |

---

# 🔒 Enterprise Edition (Paid, Self-Hosted, **Single-Tenant**)

**Goal:**
Charge for organization-level pain: control, risk, scale, and external-facing use — for one customer org operating their own isolated deployment.

**Tenancy model:** Enterprise is single-tenant by design — one deployment per customer org, with their own database, keys, and infrastructure. Procurement-driven buyers (federal, defense, regulated industries, utilities) actively want isolation, not shared infrastructure. Multi-tenancy is a Cloud-tier concern (see §3), not an Enterprise paywall.

---

## 💰 1. White-labeling (PRIMARY LEVER)

* Remove "GeoLens" branding
* Custom logo / theme
* Custom domain embedding
* OEM / client-facing deployments

👉 This alone can justify $$$ if positioned correctly.

---

## 🔐 2. Enterprise Security & Identity

* SSO (SAML / OIDC advanced config)
* SCIM provisioning
* Role mapping from IdP
* Customer-managed encryption keys (CMK) / encryption-at-rest controls
* Air-gapped / FIPS / FedRAMP-ready packaging

👉 This is table stakes for enterprise buyers.

> ⚠️ **Implementation status (2026-04-30):** SAML shipped in v13.1 (Phase 217) as the `auth_saml_enterprise` overlay. Basic OIDC works in core. SCIM provisioning has zero implementation. CMK/encryption-at-rest controls are unimplemented. Audit baseline: `docs-internal/audits/oc-separation-audit-v13.1-close.md`.

---

## 🏢 3. Governance & Workflow (BIG MONEY AREA)

* Dataset approval workflows (draft → review → publish)
* Granular permissions (dataset/field-level)
* Data ownership + stewardship assignment
* Collection-level access control
* Soft delete + retention policies

👉 This is what turns GeoLens from a tool into a system of record.

---

## 📜 4. Audit & Compliance

* Full audit logs (exportable as CSV/JSON)
* Compliance reports (who accessed what, when)
* Data lineage tracking
* AI query audit trail

👉 Required for gov / regulated environments.

---

## 🌐 5. Advanced Sharing & Distribution

* Expiring + revocable secure links
* Domain-restricted embeds
* Tokenized / scoped API access (with quotas, usage tracking, admin revocation)
* Embed token management UI
* External user access (guest roles)

👉 This is critical for real-world distribution.

---

## 🔗 6. Federation, Integration & Persistent Connectors

* Cross-instance federation (multiple GeoLens nodes)
* Enterprise catalog integration (Purview, CKAN, etc.)
* **Persistent external connectors** (stored credentials, scheduled mirroring, recurring sync from S3 / WFS / ArcGIS / PostGIS)
* Webhooks / eventing
* Advanced API controls / quotas

👉 This is how you expand into larger orgs.

---

## 🤖 7. Advanced AI & Automation (HIGH UPSIDE)

* Org-wide AI policies (what can/can't be queried, what data is allowed)
* Model routing / provider control / bring-your-own-key
* Saved AI workflows
* Batch / scheduled AI jobs (auto-metadata, summarization, AI-driven data processing)
* Integration with SpatialFlow (future 🔥)

👉 This is your long-term differentiator.

---

## ⚙️ 8. Deployment & Ops

* Hardened production builds
* HA / scaling configs
* Backup/restore tooling
* Air-gapped deployment packages
* GovCloud-ready builds

👉 Massive value for your target market.

---

## 🧑‍🔧 9. Support & SLA

* Priority support
* SLA guarantees
* Upgrade assistance
* Security patching guidance

👉 This is often the **first thing people pay for**.

---

# ☁️ 3. Cloud Edition (Future, Vendor-Hosted, **Multi-Tenant**)

**Status:** Deferred — post-traction (Phase 4 per `repo-split.md`). Not on the current roadmap.

**Goal:**
Offer a fully-managed GeoLens for teams that don't want to deploy or operate it themselves. The vendor (us) runs one shared infrastructure that hosts many customer organizations with strict data and identity isolation.

**Tenancy model:** Multi-tenant by design — every customer org is a tenant with isolated data, users, audit trail, and quotas. This is the *vendor's* operational problem; customers don't see "multi-tenant" as a feature, they see "you handle it for me."

### Why this is the right home for multi-tenancy

* Self-hosted Enterprise buyers want **isolation** (single-tenant). They will pay *more* to not share infrastructure.
* Customers who want a hosted catalog without operating it want **convenience** (multi-tenant). They will pay for the vendor to absorb the operational complexity.
* Conflating these into "multi-tenant on-prem" muddies both pitches.

### Capabilities (when this tier ships)

* Tenant-scoped data, identity, and audit isolation across all catalog/maps/embed-token/AI surfaces
* Per-tenant quotas (storage, API calls, AI tokens, embed bandwidth)
* Per-tenant billing (Stripe / AWS Marketplace metering)
* Self-service signup / org provisioning
* Vendor-operated SLA (uptime, backup, DR, patching)
* Pricing: monthly subscription with usage components — distinct from per-deployment Enterprise

### Architectural prerequisite

Multi-tenancy requires a tenant-scoping seam in core: nullable `tenant_id` columns, request-context middleware, query-injection callbacks. This is captured as **Phase 999.6 (BACKLOG)** — `tenant-scoping-infrastructure-for-multi-tenant-isolation`. Reframed: this is **Cloud-tier infrastructure**, not an Enterprise feature. Build only when starting Cloud, not before next Enterprise sale.

---

# 🧠 Critical Design Principles (DO NOT MESS THESE UP)

## 1. Community version must feel "complete"

If a single user can:

* ingest data
* find data
* visualize it
* share it (basic)

👉 you've succeeded.

If it feels crippled → you lose adoption.

---

## 2. Enterprise must solve ORGANIZATIONAL problems

Not individual user problems.

Bad paywall:

* "more map styles"
* "better UI"
* "extra formats"

Good paywall:

* governance
* compliance
* identity (SSO, SCIM, IdP mapping)
* single-tenant deployment hardening (CMK, air-gap, FedRAMP/FIPS)
* control
* branding
* support

> Multi-tenant isolation is **not** an Enterprise paywall — see §3 Cloud Edition.

---

## 3. White-labeling is your cleanest monetization lever

This is the most transferable idea from Open WebUI.

It works because:

* individuals don't care
* organizations absolutely do

---

## 4. Do NOT put standards behind a paywall

OGC / STAC / DCAT must remain free.

If you paywall interoperability:
👉 you kill your entire FAIR positioning.

---

## 5. AI should NOT be fully free long-term

Keep:

* basic interactive single-shot AI → free (for adoption)

Charge for:

* governance / policies
* batch / automated AI
* model routing / bring-your-own-key
* scale usage

The line is single-shot interactive vs. background-automated.

---

## 6. Permissive licenses on the developer surface

Use Apache-2.0 (or MIT) for the CLI, SDKs, schemas, validators, and sample connectors.

Avoid GPL / AGPL on the developer surface — it scares enterprise and government adopters away from integrating GeoLens at all. AGPL anywhere visible to commercial users is a deal-killer for many procurement teams.

If you want copyleft-style protection against SaaS freeloading, do it via the *deployment* license (e.g., source-available license on the hosted/enterprise modules), not by AGPL'ing the CLI.

---

## 7. Don't go fully closed

Even a polished closed app loses to a credible open competitor when:

* developers can't extend it
* government / academic / civic buyers can't audit it
* your own customers can't migrate off it

The trust budget for closed geospatial tools is small. Open the developer surface.

---

## 8. Transient credentials only in Community

External-source credentials (S3, WFS, ArcGIS, PostGIS) in Community Edition must be **transient** — used for one import, then discarded.

If GeoLens *stores* credentials to re-sync on a schedule, that's an enterprise capability. Storing credentials creates:

* compliance scope
* a key-rotation surface
* an audit obligation
* an attack surface for multi-tenant deployments

All of which are organizational concerns, not individual ones.

---

# 🚨 Where this could still fail (even with this setup)

Even with a perfect matrix, you can fail if:

### ❌ No clear wedge

You still need a primary use case (e.g. internal geo catalog for regulated orgs).

### ❌ No design partners

You need real orgs validating:

* what they'd pay for
* what they actually need

### ❌ Too much consulting dependency

If every deployment is custom → margins die.

---

# 🎯 Final Take

This structure gives you:

### ✔ Adoption engine

* free, open, FAIR-compliant core
* permissively-licensed developer surface (CLI, SDK, schemas)

### ✔ Monetization engine

* enterprise controls (governance, compliance, RBAC) — single-tenant, self-hosted
* white-labeling
* single-tenant deployment hardening (air-gap, GovCloud, CMK)
* support

### ✔ Expansion path

* AI + automation (SpatialFlow synergy)
* Cloud Edition (vendor-hosted, multi-tenant) — post-traction

---
