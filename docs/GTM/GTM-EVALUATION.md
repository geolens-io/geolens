# GeoLens GTM Evaluation

**Date:** 2026-03-25
**Scope:** Audit of `docs/GTM/free-vs-enterprise.md`, `docs/GTM/pricing-to-tiers.md`, and `docs/GTM/repo-split.md` against the GeoLens codebase and independent market research.

---

## 1. Executive Summary

The three GTM advisory documents provide a sound open-core framework that aligns with how comparable geospatial OSS projects monetize. The feature split (free core vs. enterprise governance/white-label/SSO), per-deployment pricing model, and emphasis on keeping OGC standards free all match proven industry patterns. The strategic advice is directionally correct.

However, there is a significant execution gap. Of 21 community edition feature claims, 20 are fully implemented and 1 has minor gaps (column rename missing from schema editing). This is a strong position -- the community edition is substantially complete and could ship today. By contrast, of 13 enterprise feature categories, 0 are fully implemented, 2 have partial overlap with existing functionality (OIDC auth, dataset-level grants), and 11 are entirely missing. The enterprise edition exists mostly on paper, though key foundations (RBAC grants, OAuth) are already in place.

The Year 1 revenue projection of $50K-$200K is aggressive for a zero-awareness product with no sales pipeline, website, or design partners. A more realistic Year 1 projection is $0-$25K, primarily from professional services, with the first license revenue likely arriving in months 9-12 if community adoption gains traction in the first 6 months. The pricing tiers themselves are defensible but sit 1.5-3x above the nearest comparables (Terria, CKAN managed hosting), which means the product must clearly demonstrate differentiated value at each tier before those prices will close.

---

## 2. Feature Inventory: Community Edition

| # | Feature | GTM Claim | Status | Evidence |
|---|---------|-----------|--------|----------|
| 1 | Catalog + search (full-text + semantic) | Core data platform | **Exists** | `backend/app/search/` (full-text), `backend/app/embeddings/` (pgvector semantic search) |
| 2 | Faceted filtering | Core data platform | **Exists** | `backend/app/search/router.py` -- source_organization, geometry_type, format filters |
| 3 | Dataset preview (vector, raster, tabular) | Core data platform | **Exists** | `frontend/src/pages/DatasetPage.tsx`, DatasetMap component, non-spatial table view |
| 4 | Collections (basic grouping) | Core data platform | **Exists** | `backend/app/collections/` -- full CRUD, router, service, models |
| 5 | Versioning (basic) | Core data platform | **Exists** | `DatasetVersion` model, `/{dataset_id}/versions` API endpoint, `frontend/src/components/dataset/VersionHistory.tsx` UI. Re-upload creates new versions with schema diff. No rollback to prior versions. |
| 6 | File uploads (Shapefile, GeoJSON, GPKG, CSV, etc.) | Data ingestion | **Exists** | `backend/app/ingest/` -- ogr2ogr pipeline, validation, metadata extraction; XLSX support added |
| 7 | WFS / ArcGIS import | Data ingestion | **Exists** | `backend/app/services/wfs.py`, `backend/app/services/arcgis.py` -- both with auth support |
| 8 | Raster COG conversion | Data ingestion | **Exists** | `backend/app/raster/cog.py` -- COG compliance check and conversion |
| 9 | VRT creation | Data ingestion | **Exists** | `backend/app/raster/vrt.py` -- VRT mosaic creation |
| 10 | Schema preview + diff | Data ingestion | **Exists** | `backend/app/datasets/router.py` -- `compute_schema_diff()`, `SchemaDiff` model |
| 11 | Map viewer | Map + visualization | **Exists** | `frontend/src/pages/PublicViewerPage.tsx`, dataset detail maps |
| 12 | Map builder (layers, styling, filters, labels) | Map + visualization | **Exists** | `frontend/src/pages/MapBuilderPage.tsx`, layer configuration, style editor, filter controls, label support |
| 13 | Vector tiles + raster rendering | Map + visualization | **Exists** | `backend/app/tiles/`, Titiler integration for raster; MapLibre vector tile rendering |
| 14 | Basic basemap config | Map + visualization | **Exists** | `backend/app/settings/` -- basemap configuration, `frontend/src/lib/basemap-utils.ts` |
| 15 | Geometry editing | Editing | **Exists** | `frontend/src/hooks/use-terra-draw.ts`, `use-feature-editing.ts`; backend feature CRUD endpoints |
| 16 | Attribute editing | Editing | **Exists** | `backend/app/features/router.py` -- `FeatureUpdate` with PATCH semantics |
| 17 | Schema editing (basic) | Editing | **Exists** | `backend/app/layers/router.py` has `add_column_endpoint` and `drop_column_endpoint` with full service implementations. No rename column support. |
| 18 | OGC API Features / Records, STAC, DCAT | Standards | **Exists** | `backend/app/ogc/` (Features + Records), `backend/app/stac/`, `backend/app/dcat/` |
| 19 | Share links + embed | Sharing | **Exists** | `backend/app/embed_tokens/`, `backend/app/maps/` share functionality, `PublicViewerPage` |
| 20 | Users + roles, API keys, audit logs | Admin | **Exists** | `backend/app/auth/` (roles: viewer/editor/admin, RBAC), `backend/app/admin/` (API key management), `backend/app/audit/` |
| 21 | Basic AI (map generation, styling edits) | AI | **Exists** | `backend/app/ai/` -- chat service, map tools, metadata generation, SQL generation, streaming |

**Summary:** 20 of 21 features Exist, 0 Partial, 1 Missing (column rename in schema editing). The community edition is substantially complete and shippable as-is.

---

## 3. Feature Inventory: Enterprise Edition

| # | Feature Category | GTM Claim | Status | Evidence |
|---|-----------------|-----------|--------|----------|
| 1 | White-labeling (remove branding, custom logo/theme) | Primary monetization lever | **Missing** | No branding removal toggle, no white-label settings. Theme system exists (`theme-provider.tsx`) but is general-purpose, not enterprise-gated. |
| 2 | SSO (SAML/OIDC advanced config) | Enterprise security | **Partial** | OIDC exists in `backend/app/auth/oauth/` (Google, Microsoft, generic OIDC). SAML is not implemented. No advanced IdP group-to-role mapping. |
| 3 | SCIM provisioning | Enterprise security | **Missing** | No SCIM endpoints or user provisioning automation. |
| 4 | Multi-org / tenant isolation | Enterprise security | **Missing** | Single-tenant architecture. No organization model, no tenant isolation. |
| 5 | Approval workflows (draft > review > publish) | Governance | **Missing** | No workflow engine, no draft/review states on datasets. |
| 6 | Granular permissions (dataset/field-level) | Governance | **Partial** | `DatasetGrant` model exists (`backend/app/datasets/models.py`) with role-to-dataset mapping. `apply_visibility_filter` in `auth/visibility.py` enforces per-dataset access. Missing: field-level permissions, admin UI for grant management. |
| 7 | Full audit export + compliance reports | Audit & compliance | **Missing** | Audit logging exists (`backend/app/audit/`) with viewing and search, but no export functionality, no compliance report generation. |
| 8 | Data lineage tracking | Audit & compliance | **Missing** | AI-generated lineage summaries exist (`backend/app/ai/metadata_service.py`) as free-text metadata, but no structured lineage graph or provenance tracking system. |
| 9 | Cross-instance federation | Federation | **Missing** | No federation protocol, no multi-instance discovery or sync. |
| 10 | Webhooks / eventing | Federation | **Missing** | No webhook registration, no event bus or notification system. |
| 11 | AI governance (policies, model routing) | Advanced AI | **Missing** | AI provider selection exists in settings, but no org-wide policies, no allow/deny rules, no model routing per role or dataset. |
| 12 | Air-gapped deployment | Deployment & ops | **Missing** | Docker Compose deployment works, but no pre-built air-gapped packages, no offline container registry, no dependency bundling. |
| 13 | GovCloud configs | Deployment & ops | **Missing** | No GovCloud-specific Terraform, Helm values, or compliance configurations. Helm charts and Packer AMI configs exist but are not GovCloud-certified. |

**Summary:** 0 of 13 enterprise features are fully implemented. 2 have partial overlap (SSO/OIDC, dataset-level RBAC via DatasetGrant). 11 are entirely missing. The enterprise edition would need substantial building, though the RBAC foundation reduces the governance effort.

---

## 4. Competitor Comparison

| Dimension | CKAN | GeoServer | GeoNode | Terria | MapStore | GeoLens |
|-----------|------|-----------|---------|--------|----------|---------|
| **License** | AGPL-3.0 | GPL-2.0 | GPL-3.0 | Apache-2.0 | BSD | Apache-2.0 |
| **Revenue model** | Services ecosystem (Datopian, Link Digital) | Service companies (GeoSolutions, GeoCat) | Bundled with GeoServer services | SaaS tiers | Bundled with GeoServer ecosystem | Open-core (planned) |
| **Pricing range** | Managed hosting: $6K-$20K/yr | Custom quotes; crowdfunding for major versions | No standalone pricing | $3.8K-$13.2K/yr (SaaS) | No standalone pricing | Proposed: $8K-$200K/yr |
| **Open-core boundary** | None (pure services) | None (pure services) | None (pure services) | Free tier vs. hosted tiers (SSO, white-label in Custom) | None (pure services) | Governance, white-label, SSO, compliance |
| **Primary buyer** | Government data portals | Government, utilities, enterprises | Same as GeoServer | Government (Australia-heavy), enterprises | Same as GeoServer | Government GIS teams, utilities, consultancies |
| **Data catalog** | Strong | None | Basic | None | None | Strong |
| **Map builder** | No | No | No | Yes | Yes (limited) | Yes |
| **OGC API Features** | Plugin | Strong | Via GeoServer | No | No | Yes |
| **OGC API Records** | Limited | No | No | No | No | Yes |
| **AI features** | No | No | No | No | No | Yes |
| **Single Docker deploy** | No | Partial | Complex | No (SaaS) | Partial | Yes |
| **Modern UI** | No (jQuery) | No (GWT/Wicket) | No (Angular 1.x) | Yes (React) | Yes (React) | Yes (React 19) |

**Key insight:** CKAN and GeoServer/GeoNode dominate by ecosystem maturity and installed base, not by product quality. Terria is the closest product-model comparison. No competitor offers the combination of catalog + map builder + OGC standards + AI in a single self-hosted deployment.

---

## 5. Pricing Benchmark Analysis

| Tier | GeoLens Proposed | Terria Actual | CKAN Managed (Datopian) | Delta |
|------|-----------------|---------------|------------------------|-------|
| Free | $0, full core | $0, limited features | Self-hosted only | Aligned -- GeoLens free tier is more generous |
| Entry (Team) | $8K-$15K/yr | $3.8K-$5.4K/yr | $6K-$7.2K/yr (hosting only) | GeoLens is 1.5-2.5x higher than Terria entry |
| Mid (Business) | $25K-$60K/yr | $13K-$18K/yr | $12K-$20K/yr (hosting + support) | GeoLens is 2-3x higher than comparables |
| Enterprise | $75K-$200K+/yr | Custom (contact) | Custom (contact) | Plausible for gov/defense, unvalidated |

### Assessment

The Team tier at $8K-$15K is defensible only if it delivers tangible value that free cannot: SSO + priority support + branding removal. At this price point, SSO alone is often worth $5K-$10K/yr to a government team that would otherwise need to maintain a separate identity system. The risk is that $8K is a meaningful procurement threshold -- many small teams have $5K discretionary budgets but need approval for $10K+.

The Business tier at $25K-$60K requires features that do not yet exist: approval workflows, advanced RBAC, SCIM, audit export. Without these, the tier has no product backing. Even with them, $25K-$60K is aggressive compared to the $12K-$20K that CKAN managed hosting + support costs.

The Enterprise tier at $75K-$200K+ is speculative. It targets federal government and defense contractors, where these price points are normal, but no prospect validation has occurred. This pricing requires multi-org isolation, federation, air-gapped deployment, and compliance reporting -- all missing.

**Recommendation:** Consider lowering the Team entry point to $5K-$10K/yr to reduce procurement friction. Keep Business at $25K-$60K but ensure it ships with at least 3 differentiating features. Enterprise pricing should remain aspirational and validated with design partners before committing to a public price.

---

## 6. Year 1 Revenue Projection Reality Check

The GTM docs project $50K-$200K in Year 1, based on 2-5 paying customers at $10K-$40K each.

### Reality Factors

| Factor | Assessment |
|--------|-----------|
| Installed base | Zero. Product is not yet public. |
| Website / landing page | Does not exist. |
| Sales pipeline | Does not exist. |
| Market awareness | Zero. No conference talks, blog posts, or community presence. |
| Design partners | None identified. |
| Team size | Solo developer. |
| Enterprise features ready | None. Team tier partially ready (OIDC exists, no SAML). |
| Time to first customer | Optimistically 6-9 months after public launch. |

### Comparable Revenue Patterns

- **Terria** built its SaaS on top of 5+ years of government-funded development for Australian government. Revenue came after a large installed base existed.
- **CKAN** ecosystem companies (Datopian, Link Digital) took years to build pipelines. Their revenue comes from known government contracts, not inbound product sales.
- **GeoSolutions** (GeoServer/GeoNode) built a services business over 10+ years of community engagement.

### Realistic Year 1 Projection

| Scenario | Revenue | Source |
|----------|---------|--------|
| Conservative | $0-$5K | No paying customers. Some ad-hoc consulting inquiries. |
| Moderate | $5K-$15K | 1 small professional services engagement. Perhaps 1 Team license late in the year. |
| Optimistic | $15K-$25K | 1-2 small customers (services + Team license). Requires active outreach starting month 1. |

The $50K-$200K projection is a Year 2-3 target, not Year 1. Reaching it in Year 1 would require either (a) an existing professional network that converts to customers, or (b) a viral community adoption moment that generates inbound demand. Neither is planned.

---

## 7. Gap Analysis: What Must Be Built Before Paid Tiers

### Team Tier ($8K-$15K) -- Minimum Viable Paid Product

| Feature | Status | Effort | Notes |
|---------|--------|--------|-------|
| OIDC SSO (already exists) | Exists | None | Generic OIDC + Google + Microsoft already implemented |
| SAML SSO | Missing | Medium (2-3 weeks) | Required for government buyers who mandate SAML |
| Priority email support | Missing | Low (process, not code) | Define SLA, set up support channel |
| Branding removal toggle | Missing | Low (1 week) | "Powered by GeoLens" footer + settings flag |
| Audit log export (CSV) | Missing | Low (1 week) | Simple CSV/JSON export of existing audit data |

**Verdict:** The Team tier could be viable with 4-6 weeks of engineering. OIDC already exists. Adding SAML, a branding toggle, and audit export would create a credible $8K offering.

### Business Tier ($25K-$60K) -- Minimum Viable Enterprise

| Feature | Status | Effort | Notes |
|---------|--------|--------|-------|
| Everything in Team | See above | See above | |
| Dataset-level RBAC | Partial | Medium (2-3 weeks) | `DatasetGrant` model and `apply_visibility_filter` exist. Needs: admin UI for managing grants, collection-level grants, field-level permissions |
| Approval workflows | Missing | High (4-6 weeks) | Draft/review/publish state machine on datasets |
| SCIM provisioning | Missing | Medium (2-3 weeks) | User/group sync from IdP |
| Compliance audit reports | Missing | Medium (2-3 weeks) | Structured reports: who accessed what, when |

**Verdict:** The Business tier requires 10-15 weeks of focused engineering (reduced from original estimate since DatasetGrant foundation exists). This is a significant investment that should not begin until there is at least one design partner willing to pay for it.

### Enterprise Tier ($75K+) -- Full Enterprise

| Feature | Status | Effort | Notes |
|---------|--------|--------|-------|
| Everything in Business | See above | See above | |
| White-label (full rebrand) | Missing | Medium (3-4 weeks) | Custom logo, colors, domain, removal of all GeoLens references |
| Multi-org / tenant isolation | Missing | Very High (8-12 weeks) | Fundamental data model change; affects every query |
| Air-gapped deployment | Missing | Medium (3-4 weeks) | Offline container images, bundled dependencies |
| Cross-instance federation | Missing | Very High (8-12 weeks) | Discovery protocol, sync, conflict resolution |

**Verdict:** The Enterprise tier requires 6+ months of engineering. Multi-org and federation are architectural changes, not feature additions. Do not attempt until Business tier customers exist and are requesting it.

---

## 8. Repo Architecture Assessment

### Current State

The codebase is a monorepo with a well-organized domain-driven backend structure:

```
backend/app/
  auth/     audit/     admin/     search/    maps/
  ingest/   export/    stac/      dcat/      ogc/
  raster/   tiles/     storage/   cache/     ai/
  collections/  datasets/  features/  embed_tokens/
  settings/     embeddings/  services/
```

This is clean and suitable for open-core packaging.

### Extension Seams

The `repo-split.md` recommendation to add `backend/app/extensions/` with protocol interfaces is sound but **not yet implemented**. No `extensions/` directory exists. No formal plugin or extension registration mechanism is in place.

### Private Overlay Repo

No `geolens-enterprise` repo exists. No enterprise overlay structure has been created.

### Assessment

The repo-split advice is architecturally correct but premature. The current monorepo structure already supports a clean free/paid boundary through:

1. **Docker Compose overlay** -- `compose.enterprise.yml` can mount additional modules
2. **FastAPI router registration** -- Enterprise routers can be conditionally included via config flag
3. **Feature flags** -- `backend/app/settings/` already supports toggleable features

**Recommendation:** Do not invest in the extension seam pattern or private repo until the first paid feature (likely SAML or branding toggle) is ready to ship. At that point, create the extension registry as part of the first enterprise feature, not as a standalone architecture project.

---

## 9. Recommendations (Prioritized)

### Pre-Launch (Before Going Public)

| # | Recommendation | Effort | Impact | Rationale |
|---|---------------|--------|--------|-----------|
| 1 | Publish a public website with features page and installation guide | Low | High | Without a website, the product does not exist to potential users. This is the single highest-impact action. |
| 2 | Define and publish the free/paid boundary | Low | High | Set expectations before anyone adopts. Changing boundaries later erodes trust (see: HashiCorp, n8n controversies). |
| 3 | Set up a public demo instance | Low | High | Government buyers want to click before they deploy. A read-only demo removes the Docker barrier to evaluation. |
| 4 | Create a GitHub Discussions or Discord community | Low | Medium | Community feedback will drive feature priorities better than advisory docs. |
| 5 | Write a quickstart installation guide | Low | Medium | `docker compose up` is simple, but users need env config, initial admin setup, and data loading guidance. |

### Early Revenue (First 6 Months Post-Launch)

| # | Recommendation | Effort | Impact | Rationale |
|---|---------------|--------|--------|-----------|
| 6 | Build SAML SSO | Medium | High | Government buyers mandate SAML. This is the minimum feature to unlock the Team tier. |
| 7 | Add branding removal toggle | Low | Medium | "Powered by GeoLens" in footer, removable via Team license. Clean monetization with minimal engineering. |
| 8 | Add audit log export (CSV/JSON) | Low | Medium | Simple export of existing audit data. Unlocks compliance-adjacent buyers. |
| 9 | Offer professional services for deployment | Low | Medium | Early revenue will come from services, not licenses. Package deployment assistance at $5K-$15K. |
| 10 | Identify and engage 2-3 design partners | Low | Very High | Design partners validate what to build next. Without them, every engineering investment is a guess. |

### Growth (6-18 Months Post-Launch)

| # | Recommendation | Effort | Impact | Rationale |
|---|---------------|--------|--------|-----------|
| 11 | Build dataset-level RBAC admin UI | Medium | High | `DatasetGrant` model already exists. Needs admin UI for managing grants. Unlocks Business tier. |
| 12 | Build approval workflows | High | High | Draft/review/publish is table stakes for government data governance. |
| 13 | Build SCIM provisioning | Medium | Medium | Required for organizations with >50 users. Pairs with SAML for enterprise identity story. |
| 14 | Create compliance audit reports | Medium | Medium | Structured "who accessed what" reports. Required for regulated industries. |
| 15 | Evaluate white-label demand | Low | High | Only build full white-label if customers request it. The branding toggle (item 7) may be sufficient for years. |

---

## 10. Easy Wins

These items require less than one week of effort each and meaningfully strengthen the GTM position.

1. **Publish FEATURES.md as a web page.** A comprehensive features document already exists (`docs/FEATURES.md`, written in quick task 260324-qln). Convert it to a landing page or publish on GitHub Pages.

2. **Set up a public read-only demo instance.** Deploy to a $20/month VPS with sample data. Link from the repository README. Government evaluators will click a demo URL before they will run `docker compose up`.

3. **Create a pricing page (even if "contact us" for paid tiers).** Publish the Community/Team/Business/Enterprise tiers. Use "contact us" for Business and Enterprise. Making pricing visible signals product maturity.

4. **Write an installation quickstart.** Step-by-step: clone, configure `.env`, `docker compose up`, create admin user, upload first dataset. Target: working deployment in under 10 minutes.

5. **Add "Powered by GeoLens" branding.** Place a small footer attribution in the UI. This is the precursor to the branding removal monetization lever. Enterprise customers will pay to remove it.

6. **Create a GitHub Discussions community channel.** Enable GitHub Discussions on the repository. This is zero-effort community infrastructure that generates public social proof.

7. **Write a "Why GeoLens" comparison page.** A brief comparison against CKAN, GeoServer, ArcGIS highlighting the unique value: single deployment, modern UI, AI-assisted, OGC-compliant. Address the "why not just use X" question before it is asked.

8. **Tag a v1.0 release.** The community edition is feature-complete enough to warrant a 1.0. A tagged release with release notes signals production readiness. Remaining on pre-1.0 signals "not ready" to enterprise evaluators.

---

## 11. Risks and Concerns

### Risk 1: Overbuilding Enterprise Before Community Traction

The GTM docs list 9 enterprise feature categories totaling 6+ months of engineering. Building any of these before the community edition has active users is a high-risk investment. Enterprise features should be demand-driven, not spec-driven. The correct sequence is: public launch, community adoption (50-100 deployments), inbound enterprise inquiries, then targeted enterprise development.

### Risk 2: Pricing Above Market Without Differentiation Proof

The proposed Team tier ($8K-$15K) is 1.5-2.5x above Terria's comparable offering. The Business tier ($25K-$60K) is 2-3x above CKAN managed hosting. These premiums are defensible only if the product demonstrably delivers unique value (AI, map builder, single deployment). Without a public demo and customer testimonials, the pricing is unanchored.

### Risk 3: No Design Partners

Every recommendation in the GTM docs assumes features will meet market needs. Without 2-3 design partners providing feedback, there is a meaningful risk of building the wrong enterprise features. SAML seems safe (universally required), but the prioritization of approval workflows vs. RBAC vs. white-label vs. webhooks is a guess without customer input.

### Risk 4: Consulting Dependency Trap

The GTM docs correctly identify professional services as the early revenue driver ($5K-$25K per engagement). The risk is that services become the business: every deployment requires custom work, margins are low, and the product license revenue never materializes. Mitigate by ensuring `docker compose up` always works without assistance and by capping services at 30% of revenue by Year 2.

### Risk 5: Solo Developer Bandwidth

A single developer maintaining a production open-source project, responding to community issues, engaging design partners, building enterprise features, and running sales is not sustainable. The GTM docs do not address this constraint. Realistic planning should assume 50% of time goes to maintenance and community support, leaving 50% for new feature development. This halves all engineering effort estimates.

### Risk 6: License Choice

The GTM docs do not specify a license. This is a foundational decision that affects the entire GTM strategy and should be made before public launch. **Consensus recommendation: Apache 2.0** -- maximizes adoption at the zero-distribution stage. Can tighten to AGPL later if commercial exploitation becomes a problem. See Section 12 for full analysis.

---

## 12. Consensus Conclusions (Post-Review)

This evaluation was reviewed by the original GTM advisor. The following conclusions represent consensus across the initial assessment, QA audit, and advisor rebuttal.

### Unanimous Decisions

| Decision | Rationale |
|----------|-----------|
| **Ship publicly now** | The community edition is complete (20/21 features). Every hour spent building instead of distributing is negative ROI. GeoLens is in a distribution phase, not a build phase. |
| **Build only 3 enterprise features pre-revenue** | SAML SSO, branding removal toggle, audit log export. Nothing else until demand signals exist. |
| **Do not build governance, federation, or multi-org** | These are 6+ months of engineering. Building them without customers is the classic solo-founder over-engineering trap. |
| **Revenue Year 1: $0-25K realistic** | The original $50-200K projection assumed pipeline and awareness that don't exist. Anything higher requires either existing network leverage or viral adoption. |
| **Repo split: right idea, wrong time** | The extension seam architecture is correct long-term but premature. Build it alongside the first enterprise feature, not as a standalone project. |
| **Enterprise features must be demand-driven** | Let customers pull features out of you. Do not pre-build a speculative enterprise roadmap. |
| **Design partners needed in parallel with launch** | 2-3 targeted organizations providing feedback are more valuable than 50 passive free users for validating what to build next. |

### Licensing Decision

**Recommendation: Apache 2.0 + trademark protection + enterprise add-ons**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Apache 2.0 | Lowest friction, fastest adoption, aligns with zero-distribution stage | No license-driven monetization pressure, forks possible | **Recommended for launch** |
| AGPL | Creates monetization pressure, prevents free enterprise usage, understood in gov legal | Reduces adoption, scares some orgs early, complicates contributors | Better after traction exists |
| BSL/SSPL | Prevents cloud hosting competition, strong commercial protection | Controversial, alienates OSS community, complex legal standing | Not recommended |

Start permissive. You can tighten later if commercial exploitation becomes a problem (Grafana, MongoDB, and others have done this successfully). AGPL is the right tool when you're being exploited -- you are not there yet because no one is using the product.

### Pricing Strategy

**Publish $8-15K Team tier but close first deals at $5-10K with early-adopter discounting.**

This resolves the tension between the advisor's "anchor high" guidance and the evaluation's "reduce procurement friction" recommendation:

- Published list price signals product maturity ($8-15K)
- Early-adopter / design-partner discounting enables first deal velocity ($5-10K)
- Raise to list price once 3-5 paying customers and testimonials exist
- Business and Enterprise tiers: "contact us" only until features exist

Do not publish a pricing page until the Team tier features (SAML, branding toggle, audit export) are built. Premature pricing pages for vaporware erode trust.

### White-Label Clarification

White-labeling is two distinct features with different timing:

| Feature | Effort | Timing | Tier | Value |
|---------|--------|--------|------|-------|
| **Branding toggle** ("Powered by GeoLens" footer removal) | 1 week | Month 1-2 post-launch | Team ($5-10K) | High leverage, low effort. Can anchor early deals. |
| **Full white-label** (custom logo, colors, domain, OEM rights) | 3-4 weeks | Only when requested | Enterprise ($75K+) | Build on demand only. The toggle may be sufficient for years. |

The branding toggle is one of the cleanest early monetization levers. Full OEM rebrand is a year-two feature that should not be built speculatively.

### Product Differentiation: Necessary but Not Sufficient

GeoLens is genuinely differentiated -- no competitor combines data catalog + map builder + OGC standards + AI in a single Docker deployment. This is a real product moat.

However, differentiation does not convert to revenue without trust. The competitive advantage is real but latent until:

- A public demo exists where buyers can evaluate it
- Community adoption creates social proof
- Testimonials from early adopters validate the claims

The competitors (CKAN, GeoServer) win on ecosystem maturity and installed base, not product quality. GeoLens competes for net-new adopters who haven't committed to an incumbent, not for switching existing deployments.

### Minimum Viable Launch Checklist

Everything needed for public launch. Nothing else belongs in the critical path.

- [ ] Public GitHub repo (clean README, Apache 2.0 license file)
- [ ] Landing page (GitHub Pages is sufficient -- does not need to be fancy)
- [ ] Live demo instance (read-only, sample data, ~$20/mo VPS)
- [ ] Installation quickstart (clone, .env, docker compose up, < 10 min to working deployment)
- [ ] v1.0 tag with release notes
- [ ] GitHub Discussions enabled

**Not required for launch** (build in weeks 2-4 post-launch):
- Pricing page (wait until Team tier features exist)
- Comparison page (nice-to-have, not blocking)
- SAML / branding toggle / audit export (ship in month 2)

### Post-Launch Sequence

| Phase | Timeline | Focus | Build |
|-------|----------|-------|-------|
| **Launch** | Week 1 | Distribution | Public repo, landing page, demo, quickstart, v1.0 |
| **Traction** | Months 1-3 | Adoption + outreach | SAML, branding toggle, audit export. Engage 2-3 design partners. Target 10-50 users. |
| **First revenue** | Months 3-6 | Validate pricing | Close first Team tier deals ($5-10K). Professional services engagements. |
| **Scale** | Months 6-12 | Demand-driven enterprise | Build only what design partners request. Raise pricing after 3-5 customers. |
| **Expand** | Year 2+ | Product-led growth | Business tier features, full white-label, compliance. Only if demand exists. |

---

## References

- `docs/GTM/free-vs-enterprise.md` -- Feature packaging matrix
- `docs/GTM/pricing-to-tiers.md` -- Pricing model and revenue projections
- `docs/GTM/repo-split.md` -- Repository architecture recommendations
- `.planning/quick/260324-t98-evaluate-gtm-advisement-for-public-relea/260324-t98-RESEARCH.md` -- Independent market research
- `docs/FEATURES.md` -- Existing features one-pager
