# Stack Research

**Domain:** Static marketing site (open-source GIS software product, enterprise/government audience)
**Researched:** 2026-04-03
**Confidence:** HIGH

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Astro | 6.1.x | Static site generator | Zero-JS-by-default output produces pure HTML for crawlers — the strongest SEO story of any modern framework. Ships ~0kB JS for content pages. v6 is current stable as of April 2026 with Server Islands, Zod 4, and stabilized experimental features. Separate repo from the GeoLens app means zero risk of coupling. |
| Tailwind CSS | 4.2.x | Styling | v4 (Rust/Oxide engine, `@import "tailwindcss"`, CSS-native `@theme`) is the current stable release. GeoLens already uses Tailwind; brand tokens (emerald palette, Inter) can be extracted to a shared `tokens.css` and `@import`-ed in both repos without any build tooling changes. |
| Cloudflare Pages | — | Hosting / CDN | Unlimited bandwidth on free tier (no 100 GB cap unlike Vercel/Netlify). 300+ PoPs, sub-50ms globally for static assets. Zero egress fees. Free SSL, preview deployments per branch, 500 builds/month on free plan. `output: 'static'` in Astro deploys with no adapter needed — avoids the Cloudflare Workers / Sharp incompatibility entirely. |
| Resend | — | Transactional email for contact/demo forms | 3,000 emails/month free (100/day), developer-friendly API, official Astro integration. Used in Cloudflare's own developer spotlight for Astro form handling. Keeps API key server-side via Astro Actions with `@astrojs/cloudflare` SSR endpoint, or via a minimal Cloudflare Worker function alongside the static site. |
| Plausible Analytics | — | Web analytics | Cookie-free, GDPR/CCPA compliant with no consent banner required — critical for government buyers who scrutinize data practices. 1 KB script via CDN. 16k+ paying customers including 600+ enterprise. Cloud plan processes data on EU servers only. Simple `<script>` tag drop-in for any static site. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@astrojs/sitemap` | latest | Auto-generate sitemap.xml | Always — add to `astro.config.mjs` integrations array. Submit resulting `/sitemap.xml` to Google Search Console. |
| `astro-seo` | latest | Declarative meta/OG tags component | Wrap every page layout. Handles `<title>`, `description`, `og:*`, `twitter:*`, canonical URL in one component with typed props. |
| `satori` + `resvg-js` | latest | Build-time OG image generation | Generate per-page 1200×630 social preview images at build time. No runtime cost. Use an Astro endpoint `[...route].png.ts` with `prerender = true`. |
| `sharp` | bundled via Astro | Build-time image optimization | Astro 6 bundles Sharp as default image service. In `output: 'static'` mode, all `<Image />` and `<Picture />` transformations run at build time — produces WebP/AVIF with CLS-safe `width`/`height` attributes. No adapter needed. |
| `@astrojs/mdx` | latest | MDX for blog/changelog pages | Use if adding a changelog or case-study blog. Gives access to React components inside Markdown. Optional for v14.0 launch. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| TypeScript | Type safety across Astro components and content collections | Astro 6 ships full TS support; use `strict: true`. Content Collections define typed frontmatter schemas via Zod 4 (now bundled). |
| `@astrojs/check` | Astro-aware TypeScript checking in CI | Run as `astro check` in the build pipeline — catches prop mismatches and missing frontmatter fields before deploy. |
| GitHub Actions | CI/CD pipeline | Trigger Cloudflare Pages deploy via `wrangler pages deploy` or Cloudflare's native GitHub integration. Run `astro check` + link checker on every PR. |
| Lighthouse CI | Performance/accessibility regression guard | Run in CI against Cloudflare preview URL. Enforce LCP < 2.5s, CLS < 0.1, accessibility score ≥ 90. |

---

## Installation

```bash
# Bootstrap new repo (separate from geolens core)
npm create astro@latest getgeolens-site -- --template minimal --typescript strict

# Core integrations
npx astro add tailwind sitemap

# Supporting
npm install astro-seo satori @resvg/resvg-js

# Dev tooling
npm install -D @astrojs/check

# For contact form (Astro Actions route calling Resend)
npm install resend
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Astro 6 | Next.js (static export) | If the marketing team needs a React dev who already knows Next. Drawback: larger JS bundle by default, requires discipline to avoid unnecessary client components. Astro's zero-JS default is safer for a site where content changes infrequently. |
| Astro 6 | Remix / SvelteKit | Never for this use case — server-rendered by default, overkill for a brochure site, adds deployment complexity. |
| Cloudflare Pages | Vercel | If the team is already deep in Vercel's ecosystem and uses Next.js. Vercel's free tier caps bandwidth at 100 GB/month, which becomes a concern if product demo videos or large screenshots are served. For a pure static site, Cloudflare's unlimited bandwidth wins. |
| Cloudflare Pages | Netlify | Netlify has built-in form handling that eliminates Resend, but Netlify has lost ground on performance and pricing vs Cloudflare in 2025–2026. Netlify forms also have a 100-submission/month free limit — not enough if the site gets traction. |
| Resend | Formspree | Formspree is simpler (no code, hosted form backend), but adds a third-party dependency with less control over email deliverability and branding. Resend sends from your own verified domain, which improves trust with enterprise buyers. |
| Resend | HubSpot Forms | HubSpot makes sense only if a full CRM pipeline is needed immediately. At launch, a simple Resend notification to a shared inbox is sufficient. HubSpot can be layered in later by forwarding form data from the same Astro Action. |
| Plausible | Google Analytics 4 | Never — GA4 requires cookie consent banners, which add friction and visual noise. Government buyers specifically scrutinize GA usage. Plausible requires zero consent UI. |
| Plausible | PostHog | PostHog if behavioral analytics (session replays, funnels, feature flags) are needed. For a static marketing site tracking page views, referrers, and CTA clicks, Plausible's simpler model is sufficient and faster to set up. |
| Plausible | Fathom | Fathom is equivalent to Plausible for privacy. Fathom has SOC 2 / ISO 27001 certs (stronger for regulated-industry enterprise). Choose Fathom if the sales team is actively targeting FedRAMP-adjacent customers. Otherwise Plausible is cheaper at scale. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `@astrojs/cloudflare` adapter for static pages | If `output: 'static'` is set, no adapter is needed. Adding the adapter will default Astro to Workers mode, causing confusion about which Cloudflare product is being used, and invalidates Sharp at build time for dynamic routes. Only add the adapter if you need SSR endpoints (e.g., the contact form Action). In that case, add it and keep the Sharp workaround documented. | `output: 'static'` with no adapter, or hybrid mode with `@astrojs/cloudflare` only for the `/api/contact` endpoint. |
| `@astrojs/image` (old integration) | Deprecated in Astro v3+. Replaced by the built-in `astro:assets` module with the Sharp service. | Built-in `<Image />` from `astro:assets`. |
| Gatsby | Stagnant ecosystem, long build times, GraphQL layer is complexity with no benefit for a small marketing site. | Astro |
| Jekyll / Hugo | Fine for blogs but no component model, harder to share brand tokens with a React-based design system. | Astro |
| Create React App / Vite SPA for marketing | SPA = no pre-rendered HTML = crawlers see blank page without JS = bad SEO. | Astro with `output: 'static'`. |
| Google Fonts CDN | Causes render-blocking from an external origin, GDPR flag for EU government visitors (font CDN request leaks user IPs to Google). | Self-host Inter via `fontsource` npm package: `@fontsource-variable/inter`. Add to global CSS. Zero external requests. |
| Google Analytics / gtag.js | Requires GDPR cookie consent banner, adds 45+ KB of JS, sends data to US servers — problems for government procurement. | Plausible |

---

## Stack Patterns by Variant

**For contact/demo-request form (recommended at launch):**
- Use Astro Actions with `output: 'hybrid'` so the single `/api/contact` endpoint renders on-demand via `@astrojs/cloudflare`, all other pages stay static.
- Action calls Resend SDK server-side, sends notification email to a shared inbox.
- Client form uses standard HTML `<form>` with progressive enhancement (JS fetch for UX, native submit as fallback).

**If a CRM is added later:**
- Add a Resend webhook or forward the contact form Action payload to HubSpot via their REST API.
- No change to the front-end form — it still hits the same Astro Action.

**If a blog/changelog is added:**
- Add `@astrojs/mdx` and define a `blog` Content Collection with Zod schema for `title`, `pubDate`, `description`, `tags`.
- OG images auto-generated per post via the Satori endpoint.
- Feeds a `/blog/[slug]` route with zero additional hosting cost.

**If Fathom is chosen over Plausible (FedRAMP-adjacent customers):**
- Drop-in replacement: swap the script `src` and `data-site` attribute. No other changes.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| astro@6.1.x | tailwindcss@4.2.x | Use `@astrojs/tailwind` integration or the new CSS-native `@import "tailwindcss"` directly. Tailwind v4 drops `tailwind.config.js` — configure via CSS `@theme`. |
| tailwindcss@4.2.x | `@fontsource-variable/inter` | Fontsource is framework-agnostic, imported in global CSS before Tailwind. No conflict. |
| astro@6.1.x | sharp (bundled) | Sharp runs at build time only for `output: 'static'` pages. No server runtime dependency. |
| satori + resvg-js | astro@6.x | Both are Node.js build-time only. Use inside `getStaticPaths` or a `.png.ts` prerendered endpoint. |
| `@astrojs/cloudflare` | sharp | Incompatible for SSR image transformation. Use no-op passthrough service for any SSR routes and pre-optimize images in `output: 'static'` pages at build time. See Astro docs: `image.service = passthroughImageService()`. |

---

## Integration Points with GeoLens Core

The marketing site lives in a **separate repository**. Integration is content-only, not code:

| GeoLens Asset | How It Crosses into Marketing Site |
|---------------|-----------------------------------|
| Brand tokens (emerald palette, Inter font, spacing scale) | Export as a standalone `brand-tokens.css` file from the GeoLens design system. Import in `src/styles/global.css` via `@import`. Keep in sync via a shared `tokens/` package or copy-on-update. |
| Product screenshots / demo GIFs | Generated from local GeoLens dev instance, optimized at build time via Astro `<Image />`, committed to `src/assets/`. |
| Quickstart Docker Compose command | Copy static text from GeoLens `README.md`. No live API call. |
| Changelog / release notes | Either manual MDX posts or a GitHub Actions job that pulls `CHANGELOG.md` content and writes MDX files on release tag. |
| Enterprise feature list | Maintained as a static JSON/YAML file in the marketing site repo. Updated when enterprise features ship. |

---

## Sources

- GitHub releases (astro@6.1.3, confirmed April 2026): https://github.com/withastro/astro/releases
- Astro images docs (Sharp at build time for static mode): https://docs.astro.build/en/guides/images/
- Astro deploy to Cloudflare docs: https://docs.astro.build/en/guides/deploy/cloudflare/
- Cloudflare Pages limits (unlimited bandwidth free): https://developers.cloudflare.com/pages/platform/limits/
- Tailwind CSS v4.2.2 (confirmed March 2025): https://github.com/tailwindlabs/tailwindcss/releases — MEDIUM confidence (latest confirmed patch)
- Resend pricing (3k/month free): https://resend.com/pricing
- Resend + Astro Actions + Cloudflare tutorial: https://developers.cloudflare.com/developer-spotlight/tutorials/handle-form-submission-with-astro-resend/
- Plausible enterprise (16k customers, EU servers, GDPR): https://plausible.io/enterprise-web-analytics
- Privacy analytics 2026 comparison (Plausible vs Fathom vs PostHog): https://www.legal-forge.com/en/blog/privacy-first-analytics-alternatives-2026/
- Astro SEO complete guide (astro-seo, JSON-LD, sitemap): https://eastondev.com/blog/en/posts/dev/20251202-astro-seo-complete-guide/
- Satori OG image generation with Astro: https://knaap.dev/posts/dynamic-og-images-with-any-static-site-generator/
- Cloudflare vs Vercel vs Netlify 2026 (edge performance, pricing): https://dev.to/dataformathub/cloudflare-vs-vercel-vs-netlify-the-truth-about-edge-performance-2026-50h0

---

*Stack research for: getgeolens.com — static marketing site for enterprise/government GIS buyers*
*Researched: 2026-04-03*
