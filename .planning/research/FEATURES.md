# Feature Research

**Domain:** Open-source technical documentation site (docs.getgeolens.com)
**Researched:** 2026-04-25
**Confidence:** HIGH (Starlight verified via Context7 + official docs; patterns verified via multiple live OSS docs sites)

---

## Context

This is a documentation site for an on-premises, open-source GIS data catalog. The audience is:

- **GIS analysts** — power users who need to find features fast, reference map builder options, understand format support
- **Data engineers / API consumers** — need API reference, code examples in curl/Python, OGC endpoint docs, authentication patterns
- **System admins / IT / DevOps** — need install guides, Docker Compose config reference, RBAC setup, backup/restore, OAuth/OIDC wiring

The docs site is built on **Astro Starlight** in the existing `getgeolens-com` repo, deployed to `docs.getgeolens.com` via Cloudflare Pages. The marketing site at `getgeolens.com` already exists (Astro 6). Starlight is Astro-native, so brand token sharing is straightforward.

---

## Feature Landscape

### Category: Site Shell

Table stakes nav structure that users expect from any OSS technical docs site.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Persistent left sidebar with section grouping | Every major docs site (Stripe, Vercel, Cloudflare) uses this pattern; users rely on it for orientation | LOW | Starlight built-in; `autogenerate` from directory or manual `sidebar` config |
| Collapsible sidebar groups | Long sidebars on install/admin content need progressive disclosure | LOW | Starlight built-in via `collapsed: true` on groups |
| Top navigation bar with logo + GitHub link | Users expect branding and a path to the source repo in the header | LOW | Starlight `social` config + `logo` config |
| Breadcrumb trail | "Where am I in this site?" — important for deep-linked content (e.g., arriving from a search result or marketing cross-link) | LOW | Starlight built-in, enabled by default |
| Prev/next page navigation in footer | Users reading sequentially (Install → Quickstart → User Guide) rely on this | LOW | Starlight built-in, `pagination: true` default; controllable per page via frontmatter |
| "Edit this page" link | OSS convention — lowers contribution friction; every OSS project (Astro, Cloudflare Workers, Supabase) shows this | LOW | Starlight `editLink.baseUrl` config pointing to GitHub main branch |
| Right-side table of contents | Long pages need in-page jump navigation; expected on any page with multiple H2/H3 sections | LOW | Starlight built-in; configurable `minHeadingLevel`/`maxHeadingLevel` |
| Responsive mobile layout | GIS analysts and admins reference docs on tablets in the field and on their phones | LOW | Starlight built-in; `starlight-sidebar-swipe` community plugin improves mobile sidebar UX |
| Custom 404 page | Broken links from external resources (QGIS forums, blog posts) should land somewhere useful, not a blank error | LOW | Starlight supports custom 404; should include search widget and link to home |

### Category: Search

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Full-text static search | Every OSS docs site has search; absence is immediately felt | LOW | Pagefind built into Starlight — indexes all content at build time, zero external service |
| Keyboard shortcut to open search (`/` or `Ctrl+K`) | Power users (data engineers) expect keyboard-first access | LOW | Pagefind UI ships with keyboard shortcuts; Starlight wires this by default |
| Search modal with keyboard navigation | Arrow-key navigation of results is expected by technical audiences | LOW | Pagefind's `pagefind-modal` component provides this out of the box |
| Result snippets with matched term context | Users need to see why a result matched, not just the page title | LOW | Pagefind highlights matched terms in excerpts automatically |
| Exclude non-content pages from index | Index pollution (e.g., landing splash page) degrades result quality | LOW | Per-page `pagefind: false` frontmatter to exclude splash pages |
| Search on 404 page | Users who land on a broken URL should be offered search as recovery | MEDIUM | Requires overriding the Starlight 404 component to embed a Pagefind widget |

### Category: Code Examples

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Syntax highlighting on all code blocks | Readers scan code; unhighlighted blocks look unfinished | LOW | Starlight uses Expressive Code (built-in) — Shiki-based, 100+ language grammars |
| Copy-to-clipboard button on code blocks | Everyone copy-pastes from docs; missing this creates friction | LOW | Expressive Code ships copy button by default — zero config |
| Shell/terminal frame differentiation | Docker Compose commands and `curl` examples should look like terminal output, not source code | LOW | Expressive Code `frame="terminal"` or `bash` language tag triggers terminal styling |
| Code editor frame with file title | Config files (`.env`, `docker-compose.yml`) benefit from the filename shown at top | LOW | Expressive Code `title="docker-compose.yml"` in the code fence meta |
| Line highlighting for important parts | Install guides need to call out which lines to edit (e.g., env vars) | LOW | Expressive Code `{3,7-9}` line range notation |
| Multi-language / tabbed code examples | API consumers need curl, Python (httpx/requests), and JavaScript (fetch) variants — all three audiences are represented | MEDIUM | Starlight `<Tabs>` component (built-in via `@astrojs/starlight/components`); requires manual authoring of each variant |
| Diff-style before/after blocks | Config migration guides (e.g., upgrading auth settings) benefit from diff display | LOW | Expressive Code `diff` language identifier |

### Category: API Reference

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Auto-rendered endpoint listing from OpenAPI spec | Data engineers expect a browsable API reference — they won't read raw JSON | MEDIUM | `starlight-openapi` plugin (HiDeoo) supports Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1; local or remote spec; read-only static output |
| Schema browser (request/response bodies) | Users need to understand parameter shapes without running the API | MEDIUM | Included in `starlight-openapi` output; rendered as structured reference pages |
| Automatic code snippet generation | curl examples for each endpoint lower the barrier for API consumers | MEDIUM | `starlight-openapi` generates code snippets automatically |
| Authentication section with API key and bearer examples | GeoLens supports JWT, API key (`?api_key=`), and OAuth — all three must be documented with concrete curl examples | LOW | Hand-authored section; reference the existing `_resolve_api_key()` pattern |
| OGC API endpoints called out separately | GeoLens is OGC API Records/Features compliant — QGIS and GDAL users will look for OGC-specific guidance | LOW | Dedicated OGC section within API reference or separate guide page |
| "Try it out" interactive console | Valued by developers evaluating the API; reduces "show me it works" friction | HIGH | Not available in `starlight-openapi` static output; `starlight-openapi-navigator` plugin offers a "Try it" console but adds build complexity. Defer to v15.1 — read-only reference ships first |
| Stable `openapi.json` snapshot committed to docs repo | Build-time rendering requires a stable spec; live fetch at build time ties docs deploys to API uptime | MEDIUM | Commit a versioned snapshot to the docs repo; update manually on breaking changes. This is the blocker noted in STATE.md |
| Link from API reference endpoints to relevant guide pages | Reduces "I see the endpoint, but how do I use it in context?" friction | LOW | Manual `<LinkCard>` or inline prose links from API ref pages to user/admin guide sections |

### Category: Content Components

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Callout/aside blocks (note, tip, caution, danger) | Install and admin guides need prominent warnings (e.g., "back up before running migrations") | LOW | Starlight `<Aside>` component built-in |
| Step-numbered install sequences | Install guides read better as ordered steps than prose paragraphs | LOW | Starlight `<Steps>` component built-in |
| Card grid for feature overview pages | Quickstart landing and admin guide overview benefit from scannable cards | LOW | Starlight `<CardGrid>` + `<Card>` components built-in |
| File tree component | Docker Compose file layout, directory structure for config files | LOW | Starlight `<FileTree>` component built-in |
| Tabbed panels for OS-specific instructions | Install steps differ across Linux, macOS, Windows host environments | LOW | Starlight `<Tabs>` + `<TabItem>` built-in |
| Collapsible details/accordions | Advanced configuration options that most users skip | LOW | Standard HTML `<details>` element works in Starlight MDX |
| Badge component for version labels and status | "New in v15.0", "Enterprise only" markers | LOW | Starlight `<Badge>` component built-in |

### Category: Cross-Linking

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Marketing site → docs links | "getgeolens.com" CTA buttons like "Read the docs" and "Quickstart" must resolve to `docs.getgeolens.com` | LOW | Hard URL links; the Features page (deferred Phase 216, now in v15.0 scope) cross-links to specific guide pages |
| Docs → marketing site links in header or footer | Users who arrived at docs directly should be able to navigate back to the product homepage | LOW | Override Starlight header or footer component to include `getgeolens.com` link |
| API reference → guide cross-links | A data engineer reading the `/datasets` endpoint should be linked to the User Guide "Search Datasets" section | LOW | Manual inline linking via `<LinkCard>` components in API reference pages |
| Guide pages → product UI deep links | "Map Builder" guide should link to `demo.getgeolens.com` for live exploration | LOW | External links; the demo site is live at `demo.getgeolens.com` |
| Sidebar badge "New" markers | Surfaces recently added pages to returning users | LOW | Starlight sidebar `badge: { text: 'New', variant: 'tip' }` per item |

### Category: SEO and Discoverability

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| `<title>` and `<meta description>` per page | Required for search indexing; missing hurts OSS adoption | LOW | Starlight generates from frontmatter `title` + `description`; set description on every page |
| XML sitemap | Search engines need it; Cloudflare Pages won't auto-generate | LOW | Astro `@astrojs/sitemap` integration; one config line with `site` URL |
| `robots.txt` | Standard crawler control; point to sitemap | LOW | Static file in `public/robots.txt`; permit all, point to sitemap.xml |
| OG image per page (`og:image`, `twitter:image`) | Social sharing of docs links (Slack, LinkedIn, Twitter) looks professional with branded cards | MEDIUM | No native Starlight per-page OG; use `astro-og-canvas` + a Starlight head route-data middleware to inject per-page `og:image` meta. The marketing site already does this via Astro — pattern is established |
| `llms.txt` and `llms-full.txt` | Emerging standard (844k sites adopted as of Oct 2025); LLM tools increasingly check for it; GeoLens users are technical and likely to ask AI assistants about the product | LOW | Static file in `public/llms.txt` with one-line summaries + links; `llms-full.txt` contains full page text dumps. Low effort, meaningful signal for AI-assisted devs |
| Canonical URL meta tag | Prevents duplicate-content penalties when content is cross-posted | LOW | Astro handles canonical automatically when `site` is set |

### Category: Dark / Light Mode

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Dark mode matching marketing site | Marketing site ships dark/light; docs without dark mode feels inconsistent; GIS analysts often work in dark environments | LOW | Starlight ships dark mode natively; map the OKLCH design tokens from `frontend/src/index.css` into Starlight's `--color-accent-*` and `--color-gray-*` CSS variables via `customCss` |
| System preference detection | Users who set OS-level dark mode expect all GeoLens surfaces to respect it | LOW | Starlight handles `prefers-color-scheme` detection by default |
| Light/dark hero image variants | Logo and hero illustrations in the docs header should not look washed out in either mode | LOW | Starlight `logo.dark` and `logo.light` config options |

### Category: Content Maintenance

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| "Last updated" timestamp in page footer | Admins evaluating whether docs are current | LOW | Starlight `lastUpdated: true` reads from Git commit history automatically |
| Contributor attribution | Optional; visible on some OSS docs (e.g., MDN); creates a sense of living documentation | LOW | Not a Starlight built-in; requires custom footer override. Low-priority for v15.0 given single-author context |
| Broken link validation in CI | Docs with broken internal links erode trust faster than missing content | LOW | `starlight-links-validator` community plugin; run as part of Cloudflare Pages build |

### Category: Versioning

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Version selector UI | Multi-version OSS projects (e.g., FastAPI) provide version selectors; GeoLens users on older deployments need docs that match | HIGH | `starlight-versions` plugin exists; deferred for v15.0 per STATE.md locked decision. Implement when 1.x.y churn creates meaningful divergence between installed and latest |
| Stable URL structure that supports future `/v1/` prefix | If versioning is added later, paths should be predictable | LOW | Design content paths now as `/guides/install`, `/reference/api` — not `/latest/guides/install`. Adding a prefix later is straightforward in Astro |

---

## Feature Dependencies

```
Pagefind search
    └──requires──> Content indexed at build time (Cloudflare Pages build)
                       └──requires──> All MDX pages have `title` frontmatter

OG image per page
    └──requires──> astro-og-canvas endpoint
                       └──requires──> head route-data middleware in Starlight

API reference pages
    └──requires──> Committed openapi.json snapshot in docs repo
                       └──requires──> Decision: snapshot vs live fetch (see STATE.md blocker)

"Edit this page" links
    └──requires──> Docs content living in a public GitHub repo path (already satisfied)

Dark mode token parity
    └──requires──> CSS mapping layer in customCss
                       └──requires──> Reading Starlight's props.css variable list from GitHub

llms.txt
    └──enhances──> SEO and AI discoverability (independent of other features)

Marketing site cross-links
    └──requires──> Features page on getgeolens.com (deferred Phase 216, v15.0 scope)
```

### Dependency Notes

- **API reference requires openapi.json snapshot:** The STATE.md blocker is real. Live fetch at build time creates a deployment coupling (docs build fails if API is down). Commit a snapshot; update via a script or CI job that pulls `/api/openapi.json` from a running instance and diffs it.
- **OG images require extra build step:** The marketing site already has this pattern — reuse the same `astro-og-canvas` approach for brand consistency.
- **Dark mode parity requires token mapping work:** Starlight's CSS variables use a `--color-accent-*` scale (50–950). GeoLens uses OKLCH values. The mapping is low-complexity but must be done deliberately to avoid the emerald accent (v2.4 tokens) clashing with Starlight's defaults.

---

## MVP Definition

### Launch With (v15.0)

These are the minimum features for the docs site to serve its OSS adoption purpose.

- [ ] Site shell — sidebar, breadcrumbs, prev/next, edit-this-page, responsive mobile
- [ ] Pagefind search with keyboard shortcut
- [ ] Expressive Code — syntax highlighting, copy button, terminal frames, file titles
- [ ] Multi-language code tabs (curl / Python / JavaScript) on API examples
- [ ] Callouts, Steps, CardGrid, Tabs, FileTree components used consistently
- [ ] Dark/light mode with OKLCH token mapping to Starlight variables
- [ ] "Last updated" timestamps from Git
- [ ] Sitemap, robots.txt, `<meta description>` on every page
- [ ] OG image per page (reusing marketing site's astro-og-canvas approach)
- [ ] Custom 404 page with Pagefind search widget embedded
- [ ] `llms.txt` + `llms-full.txt` static files
- [ ] API reference from committed `openapi.json` snapshot via `starlight-openapi`
- [ ] Broken link validation in CI via `starlight-links-validator`
- [ ] Cross-links: marketing site → docs (Features page CTAs), docs header → marketing site

### Add After Validation (v15.1)

Features to add once core content is written and user feedback surfaces gaps.

- [ ] Interactive "Try it out" API console — `starlight-openapi-navigator` plugin; adds real value for developer onboarding but requires auth setup to be useful against a live instance
- [ ] Contributor attribution in page footer — meaningful when the project has external contributors
- [ ] Starlight Telescope fuzzy page navigation — useful when page count is high (50+)
- [ ] Per-page sidebar badges ("New", "Updated") — useful when content changes frequently

### Future Consideration (v16+)

- [ ] Versioned docs (`starlight-versions`) — trigger: when two major versions are in active use simultaneously and users complain about docs mismatch
- [ ] Algolia DocSearch — trigger: when Pagefind result quality is insufficient at large page count (Pagefind is good to ~500 pages)
- [ ] Localized docs (i18n) — Starlight has built-in i18n; trigger: when the GeoLens user base includes non-English-speaking organizations requesting it

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Site shell (sidebar, prev/next, breadcrumbs) | HIGH | LOW | P1 |
| Pagefind search | HIGH | LOW | P1 |
| Syntax highlighting + copy button | HIGH | LOW | P1 |
| Multi-language code tabs | HIGH | MEDIUM | P1 |
| API reference (starlight-openapi) | HIGH | MEDIUM | P1 |
| Dark/light mode + token mapping | HIGH | MEDIUM | P1 |
| Callouts / Steps / Cards / FileTree | HIGH | LOW | P1 |
| Sitemap + robots.txt | MEDIUM | LOW | P1 |
| OG image per page | MEDIUM | MEDIUM | P2 |
| "Edit this page" links | MEDIUM | LOW | P1 |
| "Last updated" timestamps | MEDIUM | LOW | P1 |
| llms.txt | LOW | LOW | P1 (low cost, future-proof signal) |
| Custom 404 with search | MEDIUM | LOW | P1 |
| Broken link CI validation | HIGH | LOW | P1 |
| Cross-links marketing ↔ docs | HIGH | LOW | P1 |
| Interactive "Try it out" | MEDIUM | HIGH | P3 |
| Versioning UI | LOW | HIGH | P3 |
| Contributor attribution | LOW | MEDIUM | P3 |

---

## Anti-Features

Features that seem good but are wrong for this context.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Comments / Disqus / GitHub Discussions embed | "Let users ask questions on the page" | Introduces moderation burden; most OSS docs handle Q&A via GitHub Issues or Discord, not inline comments | Link to GitHub Discussions or Issues in the page footer |
| Login-required docs pages | "Enterprise-only content could be gated" | Fundamentally breaks OSS adoption; friction at any content gate kills top-of-funnel | Separate enterprise docs link or clearly labeled "Enterprise" badge on applicable sections |
| Ads or sponsorship banners | "Fund hosting costs" | GeoLens is OSS hosted on Cloudflare Pages (free tier); ads signal an abandoned/underfunded project to technical audiences | GitHub Sponsors link in the header instead |
| Full Algolia DocSearch for v15.0 | "Better search quality" | Requires Algolia DocSearch application, API keys, crawler setup, and approval; Pagefind is fully static and sufficient for the initial page count | Pagefind for v15.0; revisit at 500+ pages |
| Full versioning machinery for v15.0 | "Users on older versions need old docs" | Version UI complexity before content is stable creates confusion; 1.0.0 was just released, there is no meaningful divergence yet | Single "latest" docs + a GitHub tag reference in the install guide footer |
| Real-time collaboration / live editing | "Let the community edit in place" | Docs should go through GitHub PR review; real-time editing bypasses quality control | "Edit this page" GitHub link routes all edits through PRs |
| Animated hero / marketing content in docs | "Make the docs feel exciting" | Docs audiences (admins, engineers) prioritize speed and scannability over animation; marketing site handles brand impressions | Keep docs utilitarian; use the `splash` template only for the landing page if at all |

---

## Competitor Feature Analysis

These are docs sites relevant to GeoLens's audience and positioning.

| Feature | Supabase Docs | FastAPI Docs | QGIS Docs | Cloudflare Docs | GeoLens Approach |
|---------|---------------|--------------|-----------|-----------------|-----------------|
| Framework | Custom (Next.js) | mkdocs-material | Sphinx | Gatsby (custom) | Astro Starlight |
| Search | Algolia | Algolia | lunr.js | Algolia | Pagefind (static, no service) |
| API reference | Hand-authored | Auto-generated (OpenAPI built-in) | N/A | Hand-authored | Auto-generated via `starlight-openapi` from `openapi.json` |
| Code tabs (multi-lang) | Yes (curl/JS/Python) | Yes (Python-first) | No | Yes | Yes (manual MDX tabs) |
| Dark mode | Yes | Yes | No | Yes | Yes (Starlight native) |
| "Edit this page" | Yes | Yes | Yes | Yes | Yes (GitHub link) |
| OG image per page | Yes | No | No | Yes | Yes (astro-og-canvas) |
| llms.txt | Yes (Supabase) | No | No | Yes | Yes |
| Versioning | Yes (multiple) | Yes (multiple) | Yes | No | Deferred |
| Mobile responsive | Yes | Yes | Partial | Yes | Yes (Starlight native) |
| Try it out | No (links to dashboard) | N/A | N/A | No | Deferred |

**GeoLens-specific differentiators to call out:**

1. **OGC API / STAC endpoints** — GIS-native docs site should prominently document QGIS/GDAL connection patterns, OGC Records conformance, and STAC catalog endpoints. No competing GIS catalog docs do this well for the on-prem audience.
2. **Docker Compose topology diagram** — The 5-service stack (API, Worker, Frontend, Titiler, DB+backup) is non-trivial. A `<FileTree>` of the Compose file plus a topology diagram (Mermaid or SVG) in the install guide is a strong differentiator for the sysadmin audience.
3. **API key auth pattern for machine clients** — QGIS and GDAL users connecting via `?api_key=` need a dedicated code example section. This is a common GIS integration pattern that no peer docs site (Supabase, Cloudflare) addresses because they don't have a GIS audience.
4. **On-prem deployment focus** — Unlike cloud-hosted SaaS docs, GeoLens docs must cover env-var configuration depth, Redis/S3/Postgres alternatives, and corporate proxy setups. This is the primary reason the admin guide section is as important as the user guide.

---

## Sources

- Astro Starlight official docs: https://starlight.astro.build/
- Starlight configuration reference: https://starlight.astro.build/reference/configuration/
- Starlight plugins showcase: https://starlight.astro.build/resources/plugins/
- Starlight CSS/Tailwind guide: https://starlight.astro.build/guides/css-and-tailwind/
- starlight-openapi plugin: https://github.com/HiDeoo/starlight-openapi
- starlight-openapi-navigator (try-it): https://github.com/bline/starlight-openapi-navigator
- Pagefind search UI: https://pagefind.app/docs/search-ui/
- OG images for Starlight: https://hideoo.dev/notes/starlight-og-images/
- astro-og-canvas approach: https://hideoo.dev/notes/starlight-og-images-cloudinary-astro-sdk (pattern reference)
- llms.txt standard: https://buildwithfern.com/post/optimizing-api-docs-ai-agents-llms-txt-guide
- FastAPI OpenAPI reference: https://fastapi.tiangolo.com/reference/openapi/docs/
- Context7 Starlight docs (HIGH confidence verification): /withastro/starlight

---
*Feature research for: docs.getgeolens.com — Astro Starlight documentation site*
*Researched: 2026-04-25*
