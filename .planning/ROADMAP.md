# Roadmap: v15.0 Documentation Site (docs.getgeolens.com)

**Milestone:** v15.0
**Created:** 2026-04-25
**Granularity:** Standard
**Phase range:** 223–228

## Phases

- [ ] **Phase 223: Bootstrap & Infrastructure Lock** — Starlight scaffold, CF Pages multi-project, deploy pipeline, URL structure, token bridge, redirects stub, version pin, CI scaffolding
- [ ] **Phase 224: Brand, Shell & Search** — Full OKLCH token bridge, Inter font, dark/light parity, sidebar groups, shell components (prev/next, edit-this-page, 404, last-updated), Pagefind config, cross-site nav links, OG image pipeline, llms.txt
- [ ] **Phase 225: API Reference** — openapi.json snapshot script, starlight-openapi plugin, API auth and OGC hand-authored sections, snapshot freshness README
- [ ] **Phase 226: Quickstart & Install Guide** — Migrate and expand backend/docs/install.md, topology diagram, screenshots, expected outcomes, legacy stub replacement
- [ ] **Phase 227: User Guide & Admin Guide** — All USER-* and ADMIN-* pages, migrate backend/docs/admin.md, legacy stub replacement, repo README/CONTRIBUTING update
- [ ] **Phase 228: SEO, A11Y, Marketing Features Page & Launch** — Per-page OG images, sitemap submission, llms.txt completion, A11Y audit, Lighthouse CI, marketing /features page, GA4 install on both sites, post-launch GSC submission

## Phase Details

### Phase 223: Bootstrap & Infrastructure Lock
**Goal**: A deployable Starlight skeleton is live at a `*.pages.dev` URL with locked URL structure, CF Pages isolation, token bridge foundation, and all infrastructure decisions hard-set — so no content phase can inherit a wrong canonical URL, a flat URL, or a cross-contaminating build.
**Depends on**: Nothing (first phase of milestone)
**Requirements**: BOOT-01, BOOT-02, BOOT-03, BOOT-04, DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, MIG-02, SEO-05, CI-02
**Success Criteria** (what must be TRUE):
  1. Navigating to the Cloudflare Pages preview URL returns a Starlight homepage — the docs site is deployed and accessible
  2. Pushing a marketing-only change to `main` does not trigger a docs rebuild, and pushing a docs-only change does not trigger a marketing rebuild
  3. Every page URL served by the docs site uses the `/guides/` prefix — no flat `/install` or `/admin` paths exist
  4. `npx astro check` passes in CI with zero type errors on the skeleton scaffold
  5. `site: 'https://docs.getgeolens.com'` is set in `astro.config.mjs` and canonical `<link rel="canonical">` resolves to `docs.getgeolens.com` in the built output
**Plans:** 2 plans
- [x] 223-01-PLAN.md — Docs subtree scaffold: package.json, astro.config.mjs (site, sidebar /guides/ groups, noindex meta), stub homepage, custom.css placeholder, robots.txt (Disallow: /), _redirects (3 rules per legacy path), tsconfig, wrangler.toml, .nvmrc, verify-build.sh ✓ shipped 2026-04-25 (getgeolens.com@77b7c63)
- [~] 223-02-PLAN.md — Deploy & production cutover: docs-ci.yml + marketing ci.yml paths-ignore patch shipped 2026-04-25 (getgeolens.com@8726935 + 836076d). **CF Pages dashboard / custom domain / TLS / probe PRs DEFERRED** — operator developing docs locally; resume steps preserved in 223-02-SUMMARY.md "Deferred Verification" section. Phase 228 must close this loop before launch.

### Phase 224: Brand, Shell & Search
**Goal**: The docs site looks and feels like a GeoLens property — primary blue accent (not Starlight default purple), Inter font, dark/light parity with the marketing site — and all shell navigation (sidebar, prev/next, breadcrumbs, 404, last-updated, edit links, search, cross-site nav) works correctly before any content is written.
**Depends on**: Phase 223
**Requirements**: BRAND-01, BRAND-02, BRAND-03, BRAND-04, SHELL-01, SHELL-02, SHELL-03, SHELL-04, SHELL-05, SEARCH-01, SEARCH-02, SEARCH-03, SEO-04
**Success Criteria** (what must be TRUE):
  1. The docs site accent color matches the marketing site primary blue (hue ~250) in both dark and light modes — verified visually and confirmed WCAG AA on body and link text
  2. Pressing `/` or `Ctrl+K` opens the Pagefind search dialog and returns relevant results; code blocks do not dominate search results
  3. Every page shows "Last updated" timestamp, an "Edit this page" GitHub link, and prev/next navigation
  4. The marketing site header contains a "Docs" link and the docs site header contains a "Back to getgeolens.com" link — cross-site navigation is complete
  5. A CI token-drift check script fails if the primary hue value in `custom.css` diverges from `global.css`
**Plans**: TBD
**UI hint**: yes

### Phase 225: API Reference
**Goal**: Auto-generated API reference pages are live under `/guides/api/`, rendered from a committed `openapi.json` snapshot, with hand-authored authentication and OGC endpoint sections — so developers can use the docs as their primary API integration reference without leaving the site.
**Depends on**: Phase 224
**Requirements**: API-01, API-02, API-03, API-04, API-05, CI-01
**Success Criteria** (what must be TRUE):
  1. Navigating to `/guides/api/` shows a structured API reference generated from the committed `openapi.json` snapshot — all endpoints are listed and browsable
  2. The authentication section contains working `curl` examples for JWT Bearer, `?api_key=` query param, and OAuth flows
  3. The OGC endpoints page lists OGC API Common, Records, Features, STAC, and tile endpoints with QGIS/GDAL connection examples
  4. API reference index page does not appear in Pagefind search results (code blocks excluded from index)
  5. The `docs/src/content/openapi/` README explains how to refresh the snapshot before each release
**Plans**: TBD

### Phase 226: Quickstart & Install Guide
**Goal**: A new visitor can follow the Quickstart guide from zero to a running GeoLens instance — including a topology diagram, copyable commands, and a screenshot of the expected first-login outcome — and the legacy `backend/docs/install.md` is replaced with a pointer stub so there is exactly one canonical source.
**Depends on**: Phase 224
**Requirements**: QUICK-01, QUICK-02, QUICK-03, QUICK-04, MIG-01 (install half)
**Success Criteria** (what must be TRUE):
  1. A user with Docker installed can follow the Quickstart page step-by-step and arrive at a running GeoLens UI — no steps are missing
  2. All `docker compose up` commands, `.env.example` setup, and first-login flow are in copyable code blocks with explicit language identifiers
  3. A topology diagram shows all six Docker Compose services (API, Worker, Frontend, Titiler, DB, backup sidecar) and their relationships
  4. `backend/docs/install.md` in the geolens monorepo contains only a one-line stub pointing to `docs.getgeolens.com/guides/install` — there is no duplicate canonical content
**Plans**: TBD

### Phase 227: User Guide & Admin Guide
**Goal**: Users can look up any GeoLens workflow — from searching datasets to configuring OAuth — in the docs site, and the legacy `backend/docs/admin.md` has been replaced with a stub, so all user-facing documentation has a single canonical home at `docs.getgeolens.com`.
**Depends on**: Phase 226
**Requirements**: USER-01, USER-02, USER-03, USER-04, USER-05, USER-06, USER-07, ADMIN-01, ADMIN-02, ADMIN-03, ADMIN-04, ADMIN-05, ADMIN-06, ADMIN-07, MIG-01 (admin half), MIG-03
**Success Criteria** (what must be TRUE):
  1. The User Guide sidebar section contains pages for: search & discovery, dataset detail, map builder, collections, importing data, and exports & integrations — all with static screenshots (no demo deep-links)
  2. The Admin Guide sidebar section contains pages for: user management & RBAC, OAuth/OIDC setup, settings reference, backups & restore, infrastructure dashboard, and cloud deployment notes
  3. `backend/docs/admin.md` contains only a one-line stub pointing to `docs.getgeolens.com/guides/admin` — legacy content is removed
  4. Repo `README.md` and `CONTRIBUTING.md` reference `docs.getgeolens.com` as the canonical home for user-facing documentation
  5. All internal links pass the `starlight-links-validator` CI check with zero broken links
**Plans**: TBD
**UI hint**: yes

### Phase 228: SEO, A11Y, Marketing Features Page & Launch
**Goal**: The docs site is fully indexed, accessible, and cross-linked from the marketing site — with the `/features` page live on `getgeolens.com` — so the documentation launch drives discoverability and the deferred Phase 216 marketing obligation is fully resolved.
**Depends on**: Phase 227
**Requirements**: SEO-01, SEO-02, SEO-03, SEO-06, A11Y-05, A11Y-06, A11Y-07, FEAT-01, FEAT-02, FEAT-03, CI-03
**Success Criteria** (what must be TRUE):
  1. Every docs page has a unique `<title>`, meta description, and an OG image (non-black, hex/RGB colors) visible when shared on social platforms
  2. An Axe accessibility scan of the docs site passes with zero critical or serious violations; code block copy buttons are keyboard-operable with screen-reader status announcements
  3. The `/features` page is live on `getgeolens.com`, covers catalog, search, map builder, AI chat, raster/VRT, and OGC compliance, and each capability section links into the corresponding docs page
  4. `sitemap.xml` is accessible at `docs.getgeolens.com/sitemap-index.xml` and has been submitted to Google Search Console
  5. Lighthouse CI scores Performance ≥ 90 and Accessibility = 100 on the homepage and at least one guide page
**Plans**: TBD
**UI hint**: yes

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 223. Bootstrap & Infrastructure Lock | 2/2 (file tasks) | Files complete; deploy verification deferred | 2026-04-25 (file tasks) |
| 224. Brand, Shell & Search | 0/? | Not started | - |
| 225. API Reference | 0/? | Not started | - |
| 226. Quickstart & Install Guide | 0/? | Not started | - |
| 227. User Guide & Admin Guide | 0/? | Not started | - |
| 228. SEO, A11Y, Marketing Features Page & Launch | 0/? | Not started | - |
