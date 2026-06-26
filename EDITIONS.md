<!--
DRAFT — pending maintainer sign-off before this goes public. Confirm before publishing:
  1. The commitments below are ones you are willing to make publicly and keep permanently.
  2. Each Enterprise capability listed is actually available, OR is clearly marked as roadmap —
     trim/label anything not yet shipped so this never reads as "advertising vapor."
  3. The Enterprise contact channel is real (placeholder used below).
This file is public-repo-safe; infra/ and .planning/ stay private.
-->

# GeoLens Editions

GeoLens is **open core**. The platform in this repository is **free, Apache-2.0 licensed, and fully self-hostable** for a single organization with many users — no commercial license, no feature keys, no trial clock. A separately-licensed, commercial **Enterprise** overlay adds organization-scale identity, governance, compliance, and branding for large and regulated deployments. You never need it to run GeoLens.

## Our commitments

These are the rules we hold ourselves to, so you can adopt, build on, and contribute to GeoLens without worrying the ground will shift:

1. **The open standards stay free, forever.** OGC API (Features, Records), STAC, and DCAT are never gated — interoperability is the entire point of GeoLens.
2. **We never move a feature *out* of Community.** Anything that ships in the Apache-2.0 edition stays in the Apache-2.0 edition. Paid capabilities are *added* in the Enterprise overlay; existing free ones are never taken behind a paywall.
3. **Community is complete, not crippled.** A single team can ingest, catalog, search, map, edit, and share their spatial data end-to-end on the free edition.
4. **DCO, not a CLA.** Contributions are made under the [Developer Certificate of Origin](.github/CONTRIBUTING.md#developer-certificate-of-origin) — copyright stays with you, and your work cannot be unilaterally relicensed.
5. **Security fixes ship to the open edition too** — never withheld to force an upgrade.

## What's in each edition

**Enterprise includes everything in Community, plus the commercial capabilities below.** In the Enterprise column, **✅ = available today**; ***(planned)*** = on the roadmap (timing varies — ask). A `—` means the area is already fully covered by Community.

| Area | Community — Apache-2.0, free | Enterprise — commercial overlay |
|---|---|---|
| **Catalog & search** | Full-text + semantic (pgvector) search, faceted filtering, datasets, collections, versioning | — |
| **Ingestion** | File uploads (Shapefile, GeoJSON, GeoPackage, CSV, GeoTIFF, …), one-shot WFS / ArcGIS / STAC import, COG conversion, VRT mosaics, schema diff, `geolens.yaml` manifest apply | Persistent stored-credential connectors, scheduled sync, webhook re-ingest *(planned)* |
| **Maps & visualization** | Map viewer + builder (layers, styling, filters, labels), vector tiles, raster rendering, basemaps | — |
| **Editing** | Geometry, attribute, and schema editing | — |
| **Standards** | OGC API Features & Records, STAC, DCAT / DCAT-US / GeoDCAT-AP — *always free* | — |
| **Sharing** | Share links, public/internal visibility, basic embeds | Expiring & revocable links, domain-restricted embeds, scoped API + quotas, embed-token management UI *(planned)* |
| **Identity & access** | Local auth, OAuth/OIDC (Google, Microsoft, GitHub), roles (viewer/editor/admin), multi-user single-org collaboration, API keys | **SAML SSO** ✅ · SCIM provisioning *(planned)* · IdP group→role mapping *(planned)* · customer-managed keys / CMK *(planned)* |
| **Governance** | — | **Publication approval workflows** (draft → review → publish) ✅ · **advanced dataset access control** (ABAC / role-based) ✅ · stewardship & retention policies *(planned)* |
| **Audit & compliance** | Audit log viewing + search | **Audit log export** (CSV / JSON) ✅ · **SIEM streaming** ✅ · compliance reports & AI-query audit trail *(planned)* |
| **AI** | Interactive single-shot assist (map generation, styling suggestions, metadata help) | Org AI policies, model routing / bring-your-own-key, batch & scheduled AI jobs *(planned)* |
| **Branding** | — | **Remove "Powered by GeoLens"** ✅ · full white-label — custom logo, theme, domain, OEM *(planned)* |
| **Deployment & ops** | Docker Compose, prebuilt images, upgrade & backup tooling | Hardened / HA builds, air-gapped & GovCloud / FIPS / FedRAMP-ready packaging, cross-instance federation *(planned)* |
| **Support** | Community (GitHub Discussions & Issues) | **Priority support, SLA, upgrade assistance** ✅ |
| **Developer surface** | CLI, Python & TypeScript SDKs, manifest schema — all Apache-2.0 | — |

> Enterprise is a commercial overlay distributed as a separate package — it is **not** in this repository. The ✅ capabilities are available today; *(planned)* items are on the roadmap. <!-- TODO: real contact --> Reach out via [getgeolens.com](https://getgeolens.com) to discuss availability and timing.

## Tenancy

Both Community and Enterprise are **single-tenant**: one organization per deployment, on infrastructure you control — which is what regulated and procurement-driven teams actually want. Multi-tenant isolation (many separate organizations sharing one vendor-operated deployment) is a future, vendor-hosted **Cloud** offering and is **not** part of the self-hosted editions.

---

*This document describes the open/commercial boundary as a matter of policy. If you spot a discrepancy between this and the code, please [open an issue](https://github.com/geolens-io/geolens/issues) — keeping this honest is part of the commitment.*
