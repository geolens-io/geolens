# Quick Task 260324-t98: GTM Advisement Evaluation - Research

**Researched:** 2026-03-25
**Domain:** Geospatial open-core monetization, competitor analysis, GTM strategy
**Confidence:** MEDIUM

## Summary

The GTM advisory documents in `docs/GTM/` follow a sound open-core playbook that aligns with how comparable geospatial OSS projects monetize. The feature split (free core vs enterprise governance/white-label/SSO) matches industry patterns. Pricing ranges ($8K-$200K/yr) are plausible but on the ambitious side for a solo-developer product without established market presence. The biggest risk is not the strategy itself but the execution gap: most enterprise features listed as paid tiers do not yet exist in the codebase.

**Primary recommendation:** The GTM docs are a reasonable starting framework. Focus evaluation on (1) which claimed features actually exist, (2) whether Year 1 revenue projections are realistic given zero installed base, and (3) what minimum viable enterprise feature set would justify the Team tier price point.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Produce a full structured analysis doc with gap analysis, competitor comparison, concrete recommendations, and easy-win list
- Focus on geo-specific competitors: CKAN, GeoNode, MapStore, Terria, GeoServer
- Compare their monetization models, pricing, open-core boundaries
- Full feature inventory: check which GTM-listed features actually exist in the codebase vs aspirational
- Map each claimed feature to actual implementation status

### Claude's Discretion
- Document structure and organization
- Level of detail in competitor profiles

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Competitor Monetization Models

### How Geo OSS Projects Make Money

| Project | License | Core Revenue Model | Pricing | Who Pays |
|---------|---------|-------------------|---------|----------|
| **CKAN** | AGPL-3.0 | Services ecosystem (Datopian, Link Digital) | Managed hosting: ~$500-600/mo base + $500-2,330/mo support tiers | Government agencies, research orgs |
| **GeoServer** | GPL-2.0 | Service companies (GeoSolutions, GeoCat, Camptocamp) | Custom quotes; crowdfunding model (GS3: EUR 550K target) | Government, utilities, enterprises |
| **GeoNode** | GPL-3.0 | GeoSolutions services overlay | Bundled with GeoServer support; no standalone pricing | Same as GeoServer customers |
| **MapStore** | BSD | GeoSolutions enterprise support | Bundled with GeoServer/GeoNode ecosystem | Same ecosystem |
| **Terria** | Apache-2.0 | SaaS platform (terria.com) | Free / $499 AUD/mo / $1,699 AUD/mo / Custom | Government (Australia-heavy), enterprises |
| **GeoNetwork/GeoCat** | GPL-2.0 | Enterprise distribution + support | Custom quotes for "GeoNetwork Enterprise" | Government metadata teams |

**Confidence:** MEDIUM -- pricing is partially verified from UK Digital Marketplace (CKAN) and Terria's public pricing page. GeoServer/GeoNode/MapStore pricing is contact-sales only.

### Key Patterns Observed

1. **Pure services model dominates geo OSS.** CKAN, GeoServer, GeoNode, and MapStore do NOT sell software licenses. Revenue comes from professional services, managed hosting, and support contracts. There is no "enterprise edition" binary.

2. **Terria is the only clear SaaS/tiered model.** They charge $499-$1,699 AUD/mo (~$320-$1,100 USD/mo, or ~$3,800-$13,200 USD/yr) for their hosted platform. White-label/SSO are in the Custom tier (contact sales).

3. **White-label is consistently the highest-tier paywall.** Both Terria and the GTM docs agree: branding removal is what organizations pay premium for.

4. **Nobody charges per-seat in geo infrastructure.** Per-deployment or per-organization pricing is universal in this space. The GTM docs get this right.

5. **OGC standards are always free.** Every competitor keeps interoperability standards in the free tier. The GTM docs correctly flag this as non-negotiable.

## Pricing Benchmarks

| Tier | GTM Docs Propose | Terria Actual | CKAN Managed (Datopian) | Assessment |
|------|-----------------|---------------|------------------------|------------|
| Free | $0, full core | $0, limited | Self-hosted only | Aligned |
| Entry | $8K-$15K/yr | ~$3.8K-$5.4K/yr | ~$6K-$7.2K/yr (hosting only) | **GTM is 1.5-2x higher than Terria entry** |
| Mid | $25K-$60K/yr | ~$13K-$18K/yr | ~$6K + $6K-$14K support = $12K-$20K/yr | **GTM is 2-3x higher than comparables** |
| Enterprise | $75K-$200K+/yr | Custom/contact | Custom/contact | Plausible for gov/defense, unverified |

**Assessment:** The Team tier ($8K-$15K) is defensible if it includes real SSO + support, but only because no direct competitor offers a self-hosted catalog with AI + map builder at this quality. The Business tier ($25K-$60K) needs genuine governance features (approval workflows, RBAC, audit export) to justify the price -- these do not exist yet. Enterprise tier pricing is speculative without design partners to validate.

## Common Monetization Pitfalls for Geo OSS

### Pitfall 1: Building Enterprise Before Having Community Users
**What goes wrong:** Engineering months on SAML, SCIM, approval workflows before anyone uses the free version.
**Why it happens:** Enterprise features feel like "real product" work. Community building feels slow.
**How to avoid:** Get 50-100 active community deployments first. Let support requests drive which enterprise features to build.
**Relevance to GeoLens:** HIGH -- the GTM docs propose 9 enterprise feature categories. None are built. Community edition isn't public yet.

### Pitfall 2: Revenue Projection Fantasy
**What goes wrong:** Projecting $50K-$200K Year 1 without a sales pipeline, website, or any market presence.
**Why it happens:** Anchoring to "if we get just 2-5 customers..."
**How to avoid:** Realistic Year 1 for solo dev: $0-$20K from services, maybe 1 paying customer if lucky.
**Relevance to GeoLens:** HIGH -- the GTM docs project $50K-$200K Year 1. This requires landing 2-5 customers at $10K-$40K each as a zero-awareness product.

### Pitfall 3: Moving Free Features Behind Paywall Later
**What goes wrong:** Erodes trust, generates community backlash (see: n8n pricing controversy, HashiCorp BSL switch).
**How to avoid:** Define the free/paid boundary once and commit to it publicly. The Open Core Ventures "buyer-based" model recommends: individual contributor features = free, management/executive features = paid.
**Relevance to GeoLens:** MEDIUM -- not an issue yet since nothing is public, but the boundary should be set before launch.

### Pitfall 4: Consulting Dependency
**What goes wrong:** Every deployment requires custom work. "Product" revenue is actually disguised consulting.
**Why it happens:** Enterprise geo deployments are complex; customers need hand-holding.
**How to avoid:** The `docker compose up` story must work without assistance. Professional services should be optional, not required.
**Relevance to GeoLens:** LOW for now -- the deployment story is already clean. But the GTM docs budget $5K-$25K "deployment setup" as a services add-on, which could become a trap.

### Pitfall 5: Competing with Free Ecosystem Incumbents
**What goes wrong:** CKAN + GeoServer + GeoNode are free, mature, and have 10+ years of government adoption.
**Why it happens:** Switching costs are high in government procurement.
**How to avoid:** Don't compete head-to-head. Position on what incumbents lack: modern UI/UX, AI features, single-deployment simplicity, map builder.
**Relevance to GeoLens:** HIGH -- this is GeoLens's actual competitive advantage and the GTM docs should lean into it more.

## Market Positioning

### Where GeoLens Sits

GeoLens occupies a gap that no single competitor fills:

| Capability | CKAN | GeoServer | GeoNode | Terria | GeoLens |
|-----------|------|-----------|---------|--------|---------|
| Data catalog/search | Strong | None | Basic | None | Strong |
| Map visualization | Plugin | Strong | Strong | Strong | Strong |
| Map builder (create/save maps) | No | No | No | Yes | Yes |
| OGC API Features | Plugin | Strong | Via GeoServer | No | Yes |
| OGC API Records | Limited | No | No | No | Yes |
| AI-assisted mapping | No | No | No | No | Yes |
| Raster support | No | Strong | Via GeoServer | Yes | Yes |
| Single `docker compose up` | No | Partial | Complex | No (SaaS) | Yes |
| Modern React UI | No (jQuery) | No (GWT/Wicket) | No (Angular 1.x) | Yes (React) | Yes (React 19) |

**GeoLens's moat:** The only self-hosted platform that combines data catalog + map builder + OGC standards + AI in a single Docker deployment with a modern UI. This is genuinely differentiated.

**Realistic addressable market:** Government GIS teams (federal, state, local), utilities, environmental consultancies, and research institutions that need an internal data catalog but find CKAN too developer-heavy, GeoServer too map-server-focused, and ArcGIS too expensive. Estimated TAM for self-hosted geo data catalogs: a thin slice of the $189M government open data platform market (growing 12.5% CAGR). Realistic serviceable market for a solo product: $1M-$5M/yr if executed well over 3-5 years.

## GTM Doc Assessment Summary

| GTM Doc | Strengths | Gaps |
|---------|-----------|------|
| **repo-split.md** | Correct architecture (keep monorepo, add extension seams, private overlay repo). Pragmatic phasing. | No timeline or effort estimates. Extension seam pattern is described but not implemented. |
| **free-vs-enterprise.md** | Feature split follows industry best practices. OGC stays free. White-label as primary lever is correct. | Many "enterprise" features are aspirational (governance, federation, compliance, AI automation). No prioritization of which to build first. |
| **pricing-to-tiers.md** | Per-deployment pricing is correct. Professional services as early revenue is realistic. | Year 1 projections ($50K-$200K) are aggressive for zero-awareness product. No pricing validation with actual prospects. Team tier may be too expensive for entry. |

## Sources

### Primary (HIGH confidence)
- [Terria pricing page](https://terria.com/plans) -- verified tiers and pricing
- [UK Digital Marketplace CKAN Enterprise SaaS](https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud/services/843466017916891) -- verified CKAN managed pricing
- [Open Core Ventures pricing model](https://www.opencoreventures.com/blog/a-standard-pricing-model-for-open-core) -- buyer-based open-core framework

### Secondary (MEDIUM confidence)
- [GeoSolutions enterprise support](https://www.geosolutionsgroup.com/enterprise-support-services) -- confirmed services model, no public pricing
- [GeoServer commercial support](https://geoserver.org/support/) -- confirmed vendor ecosystem
- [CKAN commercial page](https://ckan.org/commercial) -- confirmed services ecosystem

### Tertiary (LOW confidence)
- GIS market size figures ($14-18B in 2025) from Mordor Intelligence / Allied Market Research -- varies by source
- Government open data platform market ($189M growing 12.5%) from Technavio -- single source

## Metadata

**Confidence breakdown:**
- Competitor models: MEDIUM -- pricing verified for Terria and CKAN; others are contact-sales
- Pricing benchmarks: MEDIUM -- limited public pricing data in geo OSS space
- Pitfalls: HIGH -- well-documented patterns across OSS ecosystem
- Market positioning: HIGH -- based on direct feature comparison with known products

**Research date:** 2026-03-25
**Valid until:** 2026-04-25
