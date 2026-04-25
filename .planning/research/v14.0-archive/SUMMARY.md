# Project Research Summary

**Project:** getgeolens.com — static marketing site for GeoLens open-core GIS catalog
**Domain:** Static marketing site for open-source developer/infrastructure tool (enterprise/government audience)
**Researched:** 2026-04-03
**Confidence:** HIGH

## Executive Summary

GeoLens needs a dedicated static marketing site (separate repo, `getgeolens.com`) targeting two parallel buyer personas: GIS analysts who self-evaluate the community edition, and IT managers/procurement officers who must approve and budget enterprise deployments. The research consensus is clear: use Astro 6 with `output: 'static'` deployed to Cloudflare Pages. This combination delivers zero-JS-by-default HTML (critical for SEO and government network compatibility), unlimited CDN bandwidth at no cost, and complete independence from the GeoLens product infrastructure. The site lives or dies by organic search, and Astro's pre-rendered HTML is the only correct answer for that requirement — React SPA, SvelteKit, or extending the existing Vite app would all be wrong choices.

The recommended approach is a five-page MVP (Home, Features, Editions, Quickstart, Enterprise Contact) with hardcoded copy, Tailwind 4 design tokens copied from the GeoLens product, privacy-first analytics (Plausible), and transactional email via Resend for enterprise form submissions. No CMS, no live demo, no blog at launch. Content is stable enough that git-commit-to-deploy (under 60 seconds on Cloudflare Pages) is an acceptable editorial workflow. The two highest-leverage features are: (1) a hero that leads with the user outcome rather than the technology stack, and (2) an explicit trust bar that surfaces OGC API compliance, on-premise deployment, Apache 2.0 licensing, and RBAC in the first viewport — these are hard procurement filters for the government buyer segment.

The dominant risk cluster is messaging, not technology. Three pitfalls are high-probability: hero copy that describes PostGIS architecture instead of analyst outcomes (builders write for themselves), a community/enterprise comparison table with too many negative cells that undermines open-core adoption, and missing WCAG 2.1 AA compliance that disqualifies the site from government evaluation pipelines entirely. ADA Title II enforcement deadlines arrived April 2026 for large jurisdictions — accessibility is a hard launch-blocker for the government segment. SEO neglect is the fourth critical risk: Astro's fast Lighthouse score is not a proxy for search optimization; page-unique title/description tags, per-page OG images via Satori, and `sitemap.xml` must be in place from day one.

---

## Key Findings

### Recommended Stack

The stack is a tight, well-justified set of tools. Astro 6.1 is the correct SSG for SEO-critical marketing sites — zero JS by default with a shallow learning curve and clean separation from the React/Vite product repo. Tailwind 4 (Oxide/Rust engine, CSS-native `@theme`) is already used in GeoLens, so brand tokens (emerald OKLCH palette, Inter variable font, radius scale) can be copied once into the marketing site's `global.css` with a comment noting the sync obligation. Cloudflare Pages is the clear hosting choice: unlimited bandwidth on the free tier eliminates cost uncertainty as traffic grows, 300+ PoPs deliver sub-50ms load globally, and `output: 'static'` requires no adapter.

Supporting tools are minimal: `astro-seo` for typed meta/OG tag management on every page, `@astrojs/sitemap` for automatic sitemap generation, `satori` + `resvg-js` for build-time per-page OG social card images, and Plausible Analytics for cookieless GDPR/CCPA-compliant tracking (no consent banner required). Resend handles enterprise contact form email with a developer-friendly API and domain-verified sending that builds trust with enterprise recipients.

**Core technologies:**
- **Astro 6.1:** Static site generation — zero-JS HTML output, strongest SEO story of any modern framework, separate repo from GeoLens product
- **Tailwind CSS 4.2:** Styling — already in GeoLens; brand tokens copy-once to keep visual consistency without shared package overhead
- **Cloudflare Pages:** Hosting/CDN — unlimited bandwidth free tier, sub-50ms global, preview deploys per branch, no adapter needed for static output
- **Resend:** Contact form email — 3,000/month free, domain-verified sending, server-side via Astro Actions
- **Plausible Analytics:** Web analytics — cookieless, zero consent banner, critical for government buyers who scrutinize data collection

**Supporting:**
- `astro-seo` — typed meta/OG tags component, enforces completeness per page
- `@astrojs/sitemap` — automatic sitemap.xml at build time
- `satori` + `resvg-js` — build-time OG PNG generation, zero runtime cost
- `@fontsource-variable/inter` — self-hosted Inter, no Google Fonts CDN dependency

**Do not use:**
- Google Analytics (requires cookie consent, scrutinized by gov buyers)
- Google Fonts CDN (GDPR flag for EU government visitors)
- Gatsby, CRA, or Vite SPA (SEO-hostile for a marketing site)
- `@astrojs/image` (deprecated since Astro v3)

---

### Expected Features

The site is a five-page MVP. The features research benchmarked against PostHog, Meilisearch, Directus, Supabase, Metabase, MapTiler, CARTO, and used GeoServer/GeoNode as negative examples of what to avoid.

**Must have (table stakes — P1):**
- Hero with single-sentence outcome-first value prop + dual CTA (primary: community self-serve; secondary: enterprise contact)
- Product screenshots in browser mockups — GIS buyers need to see the map UI or the product feels like vaporware
- Quickstart section with `docker compose up` and a time-to-running estimate — PostHog/Supabase pattern, must come first
- Features page — 6 capability cards (Search, Map Builder, Raster/VRT, AI Chat, RBAC, OGC APIs)
- Editions comparison page — Community vs Enterprise; prose list of enterprise additions, not a checkbox table with red X marks
- Enterprise contact form with working submission target and a `mailto:` fallback
- Trust bar in first viewport: Apache 2.0 badge, OGC API, PostGIS-native, on-premise/air-gap, STAC 1.1
- SEO fundamentals: unique title/meta/OG per page, sitemap.xml, robots.txt, canonical URLs
- Mobile-responsive layout (laptop/tablet is primary evaluator device)
- Nav + footer with GitHub link, Apache 2.0 license, Docs, contact

**Should have (differentiators — P2):**
- OGC API compliance explicit callout (hard government procurement filter)
- "On-premises / air-gapped friendly" positioning in hero sub-headline
- Enterprise trust signals section: RBAC, OAuth/OIDC/SAML, audit logs, Trivy-scanned containers
- AI-assisted search / map builder callout — differentiates from GeoServer/GeoNode legacy
- STAC 1.1 + raster/VRT callout — raster catalog is a GIS buyer filter
- Changelog teaser linking to GitHub releases (active maintenance signal)
- Testimonial slot for 1-2 quotes (even "Municipal GIS Team" without named attribution)

**Defer (v1.x — add after validation):**
- Demo video / Loom walkthrough — add after recording a polished session
- Blog — add only when 3+ posts are ready; zero posts looks emptier than no blog section
- Live interactive demo/sandbox — scope explosion; requires live backend, seed data, monitoring

**Do not build (anti-features):**
- Live sandbox on marketing site
- Newsletter signup at launch (zero ROI, GDPR overhead)
- Chat widget (adds JS, creates staffing expectations)
- Roadmap page (becomes a commitment; use GitHub Issues instead)
- Cookie consent banner (unnecessary with Plausible)

**Conversion flows to design for:**
1. Community: Hero "Get Started" → /quickstart → GitHub → `docker compose up`
2. Enterprise: Hero "Contact for Enterprise" or Editions page → Contact form → email follow-up
3. Technical evaluator: Hero → Features page → Docs → GitHub → quickstart
4. Procurement: Trust bar OGC/Apache badge → Editions enterprise column → Contact form

---

### Architecture Approach

The marketing site lives in a completely independent repo (`github.com/geolens-io/getgeolens.com`) with no shared packages, no monorepo tooling, and no runtime connection to the GeoLens product infrastructure. All pages are pre-rendered at build time. The only client-side JavaScript is a theme-detection inline script in `<head>` (FOUC prevention, matching the pattern already in GeoLens `index.html`) and optional progressive enhancement on the contact form. Enterprise form submission hits a Formspree endpoint or an Astro Actions route calling Resend — neither involves the GeoLens backend.

**Major components:**
1. **Astro pages (`src/pages/`)** — Static HTML generation; one file per route: index, features, editions, quickstart, enterprise/contact
2. **Layout components (`src/components/layout/`)** — SiteLayout.astro shell with Nav, Footer, dark mode toggle; applies FOUC-safe theme script
3. **Section components (`src/components/sections/`)** — Hero, FeatureGrid, EditionsTable, QuickstartSteps, EnterpriseCTA; one file per page section, keeps pages thin
4. **OG image endpoint (`src/pages/og/[slug].png.ts`)** — Satori + sharp Astro API route; generates per-page 1200×630 social cards at `astro build` time; zero runtime cost
5. **Design token layer (`src/styles/global.css`)** — CSS custom properties copied from GeoLens `frontend/src/index.css`; Tailwind `@import` follows; single cross-repo shared artifact
6. **CI/CD pipeline (GitHub Actions → Cloudflare Pages)** — push to main triggers build; PRs get preview deploys at `pr-N.getgeolens-com.pages.dev`

**Key architectural decisions:**
- No CMS at launch — hardcoded copy in `.astro` components; migrate to content collections only if a non-technical editor joins
- No shared npm package for design tokens — copy-once strategy with a comment noting sync obligation; token block is small and changes rarely
- No React islands for product demos — static stylized screenshots in hero; add video walkthrough post-launch
- `output: 'static'` with no Cloudflare adapter unless/until the contact form endpoint requires SSR (hybrid mode with `@astrojs/cloudflare` for `/api/contact` only)

---

### Critical Pitfalls

The pitfalls research identified seven critical risks. The top five with direct mitigation strategies:

1. **Hero copy describes technology instead of user outcomes** — Lead with the GIS analyst's pain point ("Find any dataset in seconds") before any mention of PostGIS, Docker, or RBAC. The five-second test: a non-GIS stranger should understand what problem is solved. Fix in copywriting phase, before any design work.

2. **Dual CTA competition collapses both conversions** — Community self-serve path gets primary visual weight (filled button, prominent position). Enterprise contact gets ghost/outline button positioned after. Equal-weight dual CTAs dilute both; give users a default path. B2B SaaS research shows single-primary-CTA pages convert 13.5% vs 10.5% for equal-weight dual CTAs.

3. **Editions comparison table undermines community adoption** — Never show more than ~30% of community cells as absent/negative. Frame enterprise as "everything in Community, plus [specific additions]." Use prose list of enterprise additions rather than a checkbox grid with red X marks. Open Core Ventures guidance: comparison tables are for competing products, not for community vs. enterprise tiers.

4. **Missing government trust signals** — Apache 2.0 badge, OGC API conformance, on-premise/data-sovereignty language, WCAG 2.1 AA claim, RBAC/audit log callouts must be in the first viewport or an early homepage section. Procurement gatekeepers need to build a business case internally — make their job easy. A draft VPAT document linked from the site (or available on request) signals seriousness for federal buyers.

5. **WCAG / Section 508 treated as optional** — ADA Title II enforcement deadlines arrived April 2026 for large jurisdictions. Government buyers are legally required to procure accessible software. Accessibility failures discovered during an evaluation move the contract to a competitor. Fix: target WCAG 2.1 AA from the first design mockup, run Axe in CI, verify emerald-600 contrast ratio on white (use emerald-700 if needed), test keyboard navigation before launch.

**Additional critical risks:**
6. **SEO neglect (Lighthouse score ≠ search optimization)** — Implement `BaseHead.astro` component that enforces unique `title`, `description`, `og:image`, and `canonical` on every page. Use `astro-seo` rather than hand-rolling tags. Submit sitemap.xml to Google Search Console at launch.

7. **Two-persona messaging collapse** — Assign a primary persona to each page section before copywriting. Homepage hero: analyst-primary, then IT manager trust layer. Editions page: IT manager-primary. Features page: analyst-primary with technical specifics.

---

## Implications for Roadmap

Based on dependencies across all four research files, the build sequence should follow content → infrastructure → pages → polish. Copywriting must precede design, which must precede implementation — this is the dependency that most commonly breaks marketing site projects.

### Phase 1: Content Strategy and Copywriting
**Rationale:** Hero messaging and persona mapping must be locked before any design or development work begins. The PITFALLS research is unambiguous: building the wrong message into a designed page costs more to fix than starting with copy. All downstream pages depend on a clear value proposition, defined community/enterprise feature split, and persona-per-section assignments.
**Delivers:** Hero headline, sub-headline, dual CTA labels, page-by-page copy outline, persona-to-section map, community/enterprise feature boundary definition
**Addresses:** Hero outcome framing (FEATURES P1), editions feature split (FEATURES editions dependency), two-persona messaging structure (PITFALLS #7)
**Avoids:** Hero-copy-describes-technology pitfall, messaging collapse under dual-persona conflict, editions table that undermines community
**Research flag:** Standard content strategy patterns — skip `/gsd:research-phase`

---

### Phase 2: Project Bootstrap and Design System
**Rationale:** Repo initialization, Astro + Tailwind setup, design token extraction from GeoLens, and WCAG 2.1 AA color/contrast decisions must happen before any page components are built. Accessibility failures are cheapest to fix at design-system time — most expensive to fix post-launch.
**Delivers:** `getgeolens.com` repo initialized (`npm create astro@latest`), Tailwind 4 configured, Inter self-hosted via `@fontsource-variable/inter`, GeoLens OKLCH design tokens copied to `global.css`, emerald contrast ratio verified (emerald-700 vs white confirmed at 4.5:1), FOUC-safe inline theme script in `BaseHead.astro`, `BaseHead.astro` component enforcing unique SEO props on every page, `astro-seo` + `@astrojs/sitemap` integrated
**Uses:** Astro 6.1, Tailwind 4.2, `@fontsource-variable/inter`, `astro-seo`, `@astrojs/sitemap` (STACK.md)
**Implements:** Design token layer, CI/CD pipeline foundation (ARCHITECTURE.md)
**Avoids:** WCAG/Section 508 failures (PITFALLS #6), FOUC on dark mode, SEO meta tag neglect (PITFALLS #5)
**Research flag:** Standard Astro + Tailwind setup — skip `/gsd:research-phase`

---

### Phase 3: SEO and OG Infrastructure
**Rationale:** SEO infrastructure must exist before content pages are added, not retrofitted. The PITFALLS research flags duplicate `<title>` tags and missing per-page OG images as common Astro mistakes. Building the `BaseHead` component and Satori OG endpoint first means every page that follows automatically gets correct SEO.
**Delivers:** `BaseHead.astro` with typed `title`, `description`, `ogImage`, `canonical` props; `src/pages/og/[slug].png.ts` Satori endpoint generating 1200×630 PNGs at build time; `robots.txt` in `public/`; JSON-LD `SoftwareApplication` schema on homepage; sitemap.xml auto-generated by `@astrojs/sitemap`
**Uses:** `satori`, `resvg-js`, `astro-seo`, `@astrojs/sitemap` (STACK.md)
**Implements:** OG image generator component (ARCHITECTURE.md)
**Avoids:** SEO neglect pitfall — unique meta/OG enforced structurally, not by convention (PITFALLS #5)
**Research flag:** Satori OG image generation with Astro is well-documented — skip `/gsd:research-phase`

---

### Phase 4: Homepage
**Rationale:** Homepage is the primary conversion surface. It must be built with all infrastructure in place (design system, SEO, FOUC script). It contains the most pitfall-dense content: hero copy, dual CTA hierarchy, trust bar, feature highlights, quickstart teaser, editions teaser.
**Delivers:** Full homepage with: Nav, Hero (outcome-first headline, dual CTA, product screenshot), Trust bar (5 icons: Apache 2.0, OGC API, PostGIS-native, on-premise, STAC 1.1), Feature highlights (6 cards), Quickstart teaser (3-command snippet + time estimate), Enterprise trust section (RBAC/OAuth/audit/Trivy), Editions teaser, repeat CTA, Footer
**Addresses:** Hero + dual CTA (FEATURES P1 priority matrix), trust signals (FEATURES P1 OGC/on-prem callouts), all homepage table-stakes features (FEATURES.md)
**Implements:** Hero, FeatureGrid, EnterpriseCTA, SiteLayout, Nav, Footer section components (ARCHITECTURE.md)
**Avoids:** Hero technology-description pitfall (PITFALLS #1), dual CTA competition (PITFALLS #2), missing gov trust signals (PITFALLS #4)
**Research flag:** Standard component implementation — skip `/gsd:research-phase`

---

### Phase 5: Inner Pages (Features, Quickstart, Editions, Enterprise Contact)
**Rationale:** Inner pages share infrastructure from phases 2-3 and copy from phase 1. Editions page requires the community/enterprise feature boundary to be locked (addressed in phase 1 content strategy). Enterprise contact form needs working submission endpoint tested before launch — dead forms are a critical trust failure.
**Delivers:**
- `/features` — full capability breakdown with per-feature sections (Search, Map Builder, Raster/VRT, AI, RBAC, OGC APIs)
- `/quickstart` — Docker Compose walkthrough with verified 3-command path and realistic time estimate
- `/editions` — Community vs Enterprise table using prose format (not red-X checkbox grid); enterprise additions list; CTA to contact page
- `/enterprise` or `/contact` — enterprise contact form with name/org/email/message; Formspree or Astro Actions + Resend; `mailto:` fallback visible without JavaScript
**Addresses:** Features page (FEATURES P1), Editions page (FEATURES P1), Quickstart (FEATURES P1), Enterprise contact form (FEATURES P1), form submission endpoint dependency (FEATURES dependency notes)
**Avoids:** Editions table undermining community (PITFALLS #3), contact form without email fallback (PITFALLS technical debt table), quickstart starting with prerequisites instead of the compose command (PITFALLS UX pitfalls)
**Research flag:** Formspree vs Astro Actions + Resend routing decision may need a quick spike — clarify at planning time whether the form needs SSR (hybrid mode) or Formspree eliminates that requirement

---

### Phase 6: Accessibility Audit, Performance, and Pre-Launch Checklist
**Rationale:** Government buyer segment requires WCAG 2.1 AA compliance as a procurement prerequisite. Accessibility issues found during government evaluation are unrecoverable within that procurement cycle. This is not optional polish — it is a launch gate for the target market.
**Delivers:** Axe CI scan passing, Lighthouse accessibility score ≥ 95 on desktop and mobile, keyboard navigation verified on all CTAs and form fields, all product screenshots have descriptive alt text, enterprise contact form has accessible error messages, HTTPS enforced with HSTS, CSP header configured, `robots.txt` and sitemap verified, mobile layout verified at 375px, OG image sharing tested via opengraph.xyz, dark mode FOUC test passing, draft VPAT document linked or available on request
**Addresses:** WCAG 2.1 AA requirement (PITFALLS #6), government trust signals (PITFALLS #4), accessibility for Section 508 compliance, "looks done but isn't" checklist (PITFALLS.md)
**Avoids:** Accessibility failures discovered in government evaluation (recovery cost: HIGH per PITFALLS recovery table), VPAT missing from federal RFP response (recovery cost: HIGH)
**Research flag:** Skip `/gsd:research-phase` — standard accessibility audit procedures with well-documented tools (Axe, Lighthouse). VPAT drafting is domain-specific; flag as a manual task, not a research phase.

---

### Phase Ordering Rationale

- **Copy before design, design before implementation:** The most expensive pitfall (wrong hero messaging) is fixed for free in phase 1 and very expensive to fix after pages are built. This ordering reflects the PITFALLS phase-mapping table.
- **Infrastructure before content:** SEO, design tokens, and FOUC-safe theming must exist before any page is added. Retrofitting BaseHead across 5 pages is a predictable time sink.
- **Homepage before inner pages:** Homepage is the primary conversion surface and has the most complex section composition. Getting it right informs inner page patterns.
- **Accessibility at end, but not optional:** Phase 6 is a gate, not a nice-to-have. Any accessibility failures found here must be fixed before launch. It is last because it requires finished pages to audit.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 5 (inner pages — contact form):** Formspree vs Astro Actions + Resend choice depends on whether SSR is acceptable. If the team prefers staying fully static with `output: 'static'`, Formspree is the right call. If a hybrid mode endpoint is acceptable, Resend via Astro Actions is preferred. Clarify this decision before implementation, as it affects the Astro output mode config.

Phases with standard patterns (skip `/gsd:research-phase`):
- **Phase 2 (bootstrap):** Astro + Tailwind 4 + Cloudflare Pages setup is well-documented with official guides
- **Phase 3 (SEO/OG):** Satori + Astro OG image generation has multiple tutorials; `astro-seo` + `@astrojs/sitemap` are one-liners in the Astro config
- **Phase 4 (homepage):** Component composition with Astro is standard; no novel patterns required
- **Phase 6 (accessibility audit):** Standard tools and procedures (Axe, Lighthouse CI, keyboard navigation testing)

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Astro 6.1.3 confirmed current via GitHub releases April 2026; Tailwind 4.2.2 confirmed; Cloudflare Pages limits verified from official docs; Resend and Plausible pricing confirmed |
| Features | HIGH | Benchmarked against 9 reference sites (PostHog, Meilisearch, Directus, Supabase, Metabase, MapTiler, CARTO, GeoServer, GeoNode); patterns are consistent across sources |
| Architecture | HIGH | Separate repo / no shared packages strategy is well-established; Satori OG generation is documented; Cloudflare Pages deployment is first-party documented |
| Pitfalls | HIGH (messaging/conversion/SEO), MEDIUM (gov accessibility specifics) | Messaging and SEO pitfalls are based on established B2B SaaS conversion research; government accessibility specifics (VPAT, Section 508 enforcement) are based on 2025-2026 sources but compliance interpretation can vary |

**Overall confidence:** HIGH

### Gaps to Address

- **VPAT specifics:** The research identifies a draft VPAT as valuable for federal buyers but does not enumerate exactly which WCAG success criteria to prioritize in a VPAT for GIS data catalog software. Address during Phase 6 by consulting Section508.gov's VPAT template for Software directly.
- **Formspree vs Astro Actions form routing:** Decision needs to be made at Phase 5 planning time. Formspree keeps the site fully static and eliminates SSR complexity; Astro Actions + Resend provides more control over email branding and deliverability. Clarify team preference before Phase 5 begins.
- **Product screenshot asset production:** The research calls for stylized screenshots using realistic GIS data (park boundaries, census tracts, road networks). This is a manual production task not addressed by research tools. Plan a screenshot session against the running GeoLens dev instance before Phase 4 (homepage) is implemented.
- **GitHub star count:** Research recommends a static star count (fetched at build time via GitHub API, no auth token needed for public repos) rather than a live-fetched widget that breaks in air-gapped environments. Implement as a build-time environment variable injected by GitHub Actions or a simple `fetch` in `astro.config.mjs`.

---

## Sources

### Primary (HIGH confidence)
- Astro 6.1.3 GitHub releases — version confirmation, static output mode, Sharp build-time behavior: https://github.com/withastro/astro/releases
- Astro deploy to Cloudflare Pages (official docs) — build command, output dir, adapter requirements: https://docs.astro.build/en/guides/deploy/cloudflare/
- Cloudflare Pages limits — unlimited bandwidth on free tier confirmed: https://developers.cloudflare.com/pages/platform/limits/
- Tailwind CSS v4.2.2 releases — CSS-native `@theme`, Oxide engine: https://github.com/tailwindlabs/tailwindcss/releases
- Resend pricing — 3,000/month free tier: https://resend.com/pricing
- Plausible enterprise analytics — GDPR/CCPA compliance, EU servers, 16k customers: https://plausible.io/enterprise-web-analytics
- Section508.gov: Sell Accessible Products and Services — VPAT guidance: https://www.section508.gov/sell/
- ADA Title II compliance deadlines (April 2026, large jurisdictions): https://www.accessibility.works/blog/ada-title-ii-2-compliance-standards-requirements-states-cities-towns/
- Open Core Ventures: pricing page and open-core model guidance: https://www.opencoreventures.com/blog/

### Secondary (MEDIUM confidence)
- SaaS Hero: B2B SaaS Conversion Benchmarks 2026 — single CTA vs dual CTA conversion rates: https://www.saashero.net/content/2026-b2b-saas-conversion-benchmarks/
- Cloudflare vs Vercel vs Netlify 2026 — edge performance and pricing comparison: https://dev.to/dataformathub/cloudflare-vs-vercel-vs-netlify-the-truth-about-edge-performance-2026-50h0
- Astro SEO complete guide — astro-seo, JSON-LD, sitemap patterns: https://eastondev.com/blog/en/posts/dev/20251202-astro-seo-complete-guide/
- Satori OG image generation with Astro — build-time endpoint patterns: https://knaap.dev/posts/dynamic-og-images-with-any-static-site-generator/
- Next.js vs Astro for marketing sites 2025 — framework comparison for marketing use case: https://makersden.io/blog/nextjs-vs-astro-in-2025-which-framework-best-for-your-marketing-website
- Privacy analytics 2026 comparison (Plausible vs Fathom vs PostHog): https://www.legal-forge.com/en/blog/privacy-first-analytics-alternatives-2026/

### Tertiary (LOW confidence)
- General open-core marketing analysis: knowledge of buyer journey for self-hosted tools (synthesized from multiple sources, not a single citable document)
- VPAT enumeration for GIS software: extrapolated from general Section 508 guidance; specific WCAG success criteria for GIS interfaces not confirmed with a primary source

---
*Research completed: 2026-04-03*
*Ready for roadmap: yes*
