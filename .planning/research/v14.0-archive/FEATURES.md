# Feature Research

**Domain:** Marketing site for open-source developer/infrastructure tool (GIS data catalog, open-core, enterprise/government buyers)
**Researched:** 2026-04-03
**Confidence:** HIGH (based on established patterns from PostHog, Meilisearch, Directus, Supabase, Metabase, MapTiler, CARTO, GeoServer, GeoNode)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that visitors assume exist. Missing these = the site feels unfinished or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Hero section with clear value prop | Every dev-tool site has one; absence signals amateur project | LOW | One sentence: what it is + who it's for. Not a tagline — a claim. |
| Dual CTA (self-host vs enterprise) | Open-core standard. Missing enterprise path loses qualified leads. | LOW | "Get Started Free" (OSS) + "Contact Sales" / "Request Demo" (enterprise) |
| Feature highlights section | Buyers need to scan capabilities without reading docs | LOW | 4-6 icon+headline+copy cards; don't hide behind "read the docs" |
| Product screenshots or UI preview | Dev tools without visuals feel vaporware; GIS buyers need to see the map UI | MEDIUM | Stylized screenshots in browser mockups; map + search + detail views |
| Quick-start / time-to-running section | Docker-native tools must show the 3-command path prominently | LOW | `docker compose up` + time estimate. PostHog/Supabase pattern. |
| GitHub star / repo link | OSS credibility signal; absence raises "is this actually open?" questions | LOW | Link to Apache 2.0 repo; badge optional but trust-building |
| License clarity | Enterprise/gov procurement requires knowing the license upfront | LOW | Apache 2.0 badge in hero or nav footer. Explicit, not buried. |
| Editions page or comparison table | Open-core buyers need to know what community vs enterprise includes | MEDIUM | Community free forever + Enterprise feature gating + contact path |
| Mobile-responsive layout | Non-negotiable web standard; GIS agency reviewers often on laptops/tablets | LOW | Tailwind + responsive grid; nothing exotic |
| Footer with nav, license, contact | Institutional buyers check footers for legitimacy signals | LOW | Links: docs, GitHub, license, contact, privacy |
| SEO fundamentals | Organic search is primary discovery for GIS software evaluators | LOW | Title/meta/OG per page, sitemap.xml, robots.txt, canonical URLs |
| Page load speed / static delivery | Slow marketing sites hurt conversions; gov IT proxies amplify this | LOW | Static site (Astro) gives this nearly for free |

### Differentiators (Competitive Advantage)

Features that set the site apart from generic dev-tool landing pages and speak to GIS/enterprise/gov buyers specifically.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| OGC API compliance callout | Government/FGDC procurement often requires OGC-compliant services; this is a hard filter | LOW | Explicit badge or section: "OGC API - Features compliant, STAC 1.1" |
| "On-premises / air-gapped friendly" positioning | Gov/defense buyers can't use SaaS; this is a disqualifier they check first | LOW | Single line in hero or trust-bar: "Deploy on your infrastructure. No cloud required." |
| PostGIS-native architecture story | GIS shops already running PostGIS see instant fit; competitors often have custom stores | LOW | Short architecture diagram or bullet: "Your data stays in PostGIS" |
| Enterprise buyer trust signals section | Procurement gatekeepers look for: RBAC, audit logs, SSO, CVE posture | MEDIUM | Row of badges/icons: RBAC, OAuth/OIDC/SAML, Prometheus metrics, Trivy-scanned |
| AI-assisted search / map builder callout | Differentiates from legacy GeoServer/GeoNode; enterprise buyers see "modern" signal | LOW | One feature card; show the natural-language query UX |
| STAC 1.1 + raster/VRT callout | Raster catalog is a GIS buyer filter; STAC is the interop standard they look for | LOW | Featured in capabilities section |
| Quickstart with realistic time estimate | "Running in 5 minutes" is a conversion claim competitors rarely make this specific | LOW | Use actual benchmark; if Docker pull+up takes ~3 min, say 3 min |
| Case-study-ready testimonial slot | Gov/enterprise buyers want social proof from peers; even a placeholder with "early user" quote | MEDIUM | Slot for 1-2 quotes with org type (e.g., "Municipal GIS Team") even without named attribution early on |
| Docs link prominent in nav | Technical evaluators bounce to docs immediately; burying the link signals bad docs | LOW | Top nav: Home, Features, Editions, Docs, GitHub |
| Changelog / "What's new" teaser | Active maintenance signal critical for gov procurement (abandoned software risk) | LOW | Link to GitHub releases or a minimal changelog page; just showing v14.0 is recent is enough |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Full interactive demo / live sandbox on marketing site | "Let them try before buying" sounds compelling | Requires a live backend, auth, seed data, keepalive monitoring — a product in itself. Scope explosion for launch. | Link to Docker quickstart; add a Loom/screen-recorded walkthrough video instead |
| Blog / content marketing section at launch | SEO content strategy long-term value | Premature: zero posts at launch looks emptier than no blog section; ongoing content requires editorial commitment | Add a blog route stub post-launch when there are 3+ posts ready |
| Pricing calculator | Complex tier pricing can use one | GeoLens is free (community) + "contact us" (enterprise); no tiers to calculate | Simple two-column edition comparison is sufficient |
| Newsletter signup | Standard growth tactic | Requires CRM integration, legal compliance (GDPR), and ongoing sends; zero ROI at launch traffic levels | Collect leads via the enterprise contact form only |
| Chat widget (Intercom, Crisp, etc.) | Enterprise buyers sometimes want async access | Adds JS bundle, requires monitoring/staffing, creates expectations you can't meet solo | Enterprise contact form + GitHub Discussions covers this |
| Social proof counters (GitHub stars live-fetched) | Shows activity | API-fetched counters add JS complexity and break on rate limits; vanity at low counts | Static badge image from shields.io updated at build time, or omit until meaningful count |
| "Roadmap" page | Transparency signal | Becomes a promise you're held to; roadmap items that slip create trust damage | Link to GitHub Issues/Milestones for community transparency without the commitment burden |
| Cookie consent banner (full CMP) | GDPR compliance | If the site has no analytics or only self-hosted analytics (Plausible), no consent banner needed | Use Plausible (cookieless); skip the CMP entirely |

---

## Feature Dependencies

```
Hero CTA (Get Started)
    └──requires──> Quickstart Page / Section
                       └──requires──> Docker Compose instructions tested + accurate

Hero CTA (Contact for Enterprise)
    └──requires──> Enterprise Contact Form
                       └──requires──> Form submission endpoint (Netlify Forms / Formspree / email)

Editions Comparison Page
    └──requires──> Clear definition of Community vs Enterprise feature split
                       └──requires──> enterprise repo feature list confirmed

Trust Signals Section
    └──enhances──> Editions Page conversion (enterprise buyers)

OGC / STAC callouts
    └──enhances──> SEO (government procurement keyword targeting)

Product Screenshots
    └──enhances──> Hero section credibility
    └──requires──> Stylized/annotated assets prepared (not raw dev screenshots)

Changelog teaser
    └──enhances──> Trust signals (active maintenance)
    └──requires──> GitHub releases exist and are tagged (they do — v12.3, v13.0)
```

### Dependency Notes

- **Quickstart requires tested instructions:** The Docker Compose path must be verified against the public repo before the page ships. A broken quickstart is worse than no quickstart.
- **Editions page requires feature split finalization:** Don't launch the comparison table until the community/enterprise boundary is locked (it is, per v13.0 open-core work).
- **Enterprise form requires a working submission target:** Even a simple Netlify Forms or Formspree endpoint must be tested before launch. Dead forms destroy enterprise trust.

---

## MVP Definition

### Launch With (v1)

Minimum viable site to support the v14.0 goal: convert GIS/IT evaluators toward self-hosted deployment, with a secondary enterprise contact path.

- [ ] Homepage — hero, value prop, dual CTA, feature highlights, trust signals, quickstart teaser, product screenshots
- [ ] Features page — full capability breakdown (search, map builder, raster/VRT, AI, RBAC, OGC)
- [ ] Editions page — Community vs Enterprise comparison table
- [ ] Quickstart section or page — `docker compose up`, 3-command path, time estimate
- [ ] Enterprise contact form — name, org, email, message; working submission
- [ ] Nav + footer — logo, page links, GitHub, license, docs, contact
- [ ] SEO fundamentals — title/meta/OG per page, sitemap.xml, robots.txt
- [ ] Responsive design — works on laptop/tablet (primary evaluator device)

### Add After Validation (v1.x)

- [ ] Testimonials / case study quotes — add when first external deployments exist
- [ ] Changelog / "What's new" page — add when there are 3+ meaningful entries post-launch
- [ ] Blog — add when 3+ posts are written and ready
- [ ] Demo video (Loom or embedded) — add after recording a polished walkthrough

### Future Consideration (v2+)

- [ ] Full interactive demo / sandbox — only if engineering capacity exists to maintain it
- [ ] Localization (French, German) — only if gov procurement in EU becomes a real pipeline
- [ ] Docs site integration — merge or cross-link if docs grow substantially

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Homepage hero + dual CTA | HIGH | LOW | P1 |
| Product screenshots/visuals | HIGH | MEDIUM | P1 |
| Quickstart section | HIGH | LOW | P1 |
| Features page | HIGH | LOW | P1 |
| Editions comparison table | HIGH | MEDIUM | P1 |
| Enterprise contact form | HIGH | LOW | P1 |
| OGC / on-prem trust callouts | HIGH (gov/enterprise) | LOW | P1 |
| SEO fundamentals | HIGH | LOW | P1 |
| Mobile responsive layout | HIGH | LOW | P1 |
| Nav + footer | MEDIUM | LOW | P1 |
| GitHub / license signals | MEDIUM | LOW | P1 |
| Changelog teaser | MEDIUM | LOW | P2 |
| Testimonial slots | MEDIUM | LOW | P2 |
| Demo video | MEDIUM | MEDIUM | P2 |
| Blog | LOW (at launch) | HIGH (ongoing) | P3 |
| Live interactive demo | LOW (risk outweighs) | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

Reference sites analyzed: PostHog, Meilisearch, Directus, Supabase, Metabase, MapTiler, CARTO, GeoServer (download page), GeoNode demo site.

| Feature | PostHog / Meilisearch / Directus (modern OSS SaaS-like) | GeoServer / GeoNode (legacy GIS OSS) | GeoLens Approach |
|---------|--------------------------------------------------------|--------------------------------------|-----------------|
| Hero clarity | Single sentence value prop, instant CTA | Dense technical descriptions, no clear CTA | Adopt modern OSS pattern: one-sentence claim + dual CTA |
| Visual evidence | Animated screenshots, short demo videos | None or dated screenshots | Stylized static screenshots in browser frames; skip animation at launch |
| Quickstart prominence | Top of homepage, 3-command snippet | Buried in docs or wiki | Prominent homepage section: `docker compose up`, time to running |
| Editions / pricing | Clear free vs paid tier table | No commercial model explained | Two-column Community / Enterprise table with feature matrix |
| OSS credibility | GitHub stars, contributors, license badge | License mentioned but not badged | Apache 2.0 badge + GitHub link in nav; stars badge optional |
| Trust for enterprise | SOC 2, audit logs, SSO callouts | No enterprise story | RBAC, OAuth/OIDC/SAML, audit logs, Trivy scanning in trust section |
| GIS-specific signals | N/A | OGC referenced but not marketed | Explicit OGC API, STAC 1.1, PostGIS-native callouts |
| Docs link | Prominent top nav | Hidden or links to external wiki | Top nav: "Docs" linking to GitHub Pages or docs site |
| On-prem / air-gap story | Cloud-first, self-host as option | Self-hosted by default but no marketing | Lead with on-prem/air-gap as primary value for gov/enterprise |

---

## Page Structure Reference

The following page structure is recommended based on patterns above.

```
/                   Homepage
/features           Full feature breakdown
/editions           Community vs Enterprise comparison + enterprise contact CTA
/quickstart         Step-by-step Docker Compose path
/contact            Enterprise contact form (can also be section on /editions)
```

### Homepage Section Order

1. Nav (logo, Features, Editions, Docs, GitHub, "Contact Sales" button)
2. Hero (headline, sub-headline, dual CTA, product screenshot)
3. Trust bar (Apache 2.0, OGC API, PostGIS-native, On-premises, STAC 1.1 — icon row)
4. Feature highlights (6 cards: Search, Map Builder, Raster/VRT, AI Chat, RBAC, OGC APIs)
5. Quickstart teaser (3-command snippet + "Running in ~3 minutes" + link to full quickstart)
6. Enterprise/trust section (RBAC, OAuth/SAML, audit, CVE scanning — for procurement gatekeepers)
7. Editions comparison teaser (Community free / Enterprise — link to /editions for full matrix)
8. CTA banner (repeat dual CTA before footer)
9. Footer (nav links, license, GitHub, docs, contact)

### Conversion Flows

**Self-hosted community path:**
Hero CTA "Get Started" → /quickstart → GitHub repo → docker compose up

**Enterprise evaluation path:**
Hero CTA "Contact for Enterprise" OR Editions page → Contact form → email follow-up

**Technical evaluator path:**
Hero → Features page → Docs (external) → GitHub → quickstart

**Procurement / compliance path:**
Trust bar OGC/Apache badge → Editions page enterprise column → Contact form

---

## Sources

- PostHog marketing site patterns (posthog.com) — hero, feature cards, dual OSS/cloud CTA
- Meilisearch (meilisearch.com) — quickstart prominence, open-source badge treatment
- Directus (directus.io) — open-core editions table, enterprise trust section
- Supabase (supabase.com) — Docker quickstart, GitHub star integration, trust signals
- Metabase (metabase.com) — on-prem vs cloud framing, government use case messaging
- MapTiler (maptiler.com) — GIS-specific trust signals, OGC/standards callouts
- CARTO (carto.com) — enterprise/government GIS buyer language, spatial data platform positioning
- GeoServer (geoserver.org) — negative example: no clear CTA, no editions story, dense text
- GeoNode (geonode.org) — negative example: outdated screenshots, buried quickstart
- General open-core marketing analysis: knowledge of buyer journey for self-hosted tools

---
*Feature research for: getgeolens.com marketing site*
*Researched: 2026-04-03*
