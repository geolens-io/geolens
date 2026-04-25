# Requirements: v15.0 Documentation Site (docs.getgeolens.com)

**Defined:** 2026-04-25
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v15.0 Requirements

A documentation site at `docs.getgeolens.com` covering install/quickstart, user guide, admin guide, and auto-generated API reference. Built on Astro Starlight inside the existing `getgeolens-com` repo, deployed as a separate Cloudflare Pages project. Single "latest" version. Re-uses the brand identity established in v14.0.

This milestone also delivers the marketing-side half of deferred Phase 216 — a new `/features` page on `getgeolens.com` cross-linking into the docs site.

### Bootstrap & Infrastructure

- [x] **BOOT-01
**: Astro Starlight 0.38.4 site bootstrapped in `docs/` subdirectory of the existing `getgeolens-com` repo with its own `package.json`, `astro.config.mjs`, `tsconfig.json`, and `wrangler.toml` — no npm/pnpm workspace
- [x] **BOOT-02
**: Astro version pinned to a Starlight 0.38.x-compatible major (Astro 6.x) with `npx astro check` running in CI to catch upgrade drift
- [x] **BOOT-03
**: URL structure uses a `/guides/` prefix (e.g. `/guides/install`, not `/install`) so future versioning can be added without breaking external links
- [x] **BOOT-04
**: `astro.config.mjs` sets `site: 'https://docs.getgeolens.com'` so canonical URLs and sitemap entries resolve correctly from day one

### Deploy & Hosting

- [ ] **DEPLOY-01**: Second Cloudflare Pages project (e.g. `geolens-docs`) created from the same `getgeolens-com` repo, with `rootDirectory: docs` and `Build Watch Paths` configured so docs and marketing builds do not cross-trigger
- [ ] **DEPLOY-02**: GitHub Actions workflow `deploy-docs.yml` filters on `paths: ['docs/**']` so only docs changes trigger docs deploys; existing marketing-site workflow gets a corresponding `paths-ignore` for `docs/**`
- [ ] **DEPLOY-03**: Custom domain `docs.getgeolens.com` mapped via Cloudflare Pages with TLS auto-provisioning verified in production
- [ ] **DEPLOY-04**: PR preview deploys work for docs PRs at `*.pages.dev`, mirroring the existing marketing-site workflow

### Brand & Theming

- [ ] **BRAND-01**: `docs/src/styles/custom.css` registered via Starlight's `customCss` array, mapping GeoLens OKLCH primary blue (~hue 250) into Starlight's `--sl-color-accent-*` 50–950 scale — no `@astrojs/starlight-tailwind` plugin
- [ ] **BRAND-02**: Inter variable font loaded via `@fontsource-variable/inter` and applied via `--sl-font` so docs typography matches marketing site
- [ ] **BRAND-03**: Dark and light modes verified to use GeoLens blue accent (not Starlight default purple) and meet WCAG AA contrast on body and link text
- [ ] **BRAND-04**: A CI check (or documented manual diff) flags drift between `geolens-com/src/styles/global.css` and `docs/src/styles/custom.css` token values, given both are manual copies of the geolens monorepo source

### Site Shell & Navigation

- [ ] **SHELL-01**: Top-level sidebar groups: Quickstart, User Guide, Admin Guide, API Reference — using Starlight's `sidebar` config
- [ ] **SHELL-02**: Each page has prev/next page navigation, breadcrumbs, and an "Edit this page" link pointing to GitHub
- [ ] **SHELL-03**: Custom 404 page with search box and links to top-level categories
- [ ] **SHELL-04**: `lastUpdated: true` enabled so every page shows last-modified timestamp from git history
- [ ] **SHELL-05**: Marketing site (`getgeolens.com`) header gains a "Docs" link routing to `docs.getgeolens.com`; docs site header has a "Back to getgeolens.com" link

### Search

- [ ] **SEARCH-01**: Pagefind static search built into Starlight pages with no external service dependency
- [ ] **SEARCH-02**: Code-block content excluded or de-prioritized in Pagefind index using `data-pagefind-ignore` where appropriate so search results favor prose over snippets
- [ ] **SEARCH-03**: Keyboard shortcut (default `/` or `Ctrl+K`) opens search dialog, verified working

### Quickstart & Install (resolves deferred QUICK-01/02/03)

- [ ] **QUICK-01**: Step-by-step guide from zero to a running GeoLens instance via `docker compose`, migrated and expanded from `backend/docs/install.md`
- [ ] **QUICK-02**: Copyable code blocks with `.env.example` setup, `docker compose up` commands, first-login flow, and admin password rotation
- [ ] **QUICK-03**: Expected outcome description (what the user sees after completing the quickstart) with screenshots
- [ ] **QUICK-04**: Docker Compose service topology diagram (API, Worker, Frontend, Titiler, DB + backup sidecar) so admins understand what runs where

### User Guide

- [ ] **USER-01**: Search & discovery page — using filters, faceted search, semantic search, saved searches
- [ ] **USER-02**: Dataset detail page — overview/data/metadata tabs, exports, related datasets, change history
- [ ] **USER-03**: Map builder page — creating maps, layers, styles, filters, AI chat, sharing
- [ ] **USER-04**: Collections page — creating, managing membership, browsing
- [ ] **USER-05**: Importing data page — upload flow, service URLs (WFS/ArcGIS), creating empty layers, re-upload
- [ ] **USER-06**: Exports & integrations page — formats, OGC API access patterns, STAC, machine clients (QGIS, GDAL, scripts)
- [ ] **USER-07**: All user-guide screenshots are static — no deep-links into `demo.getgeolens.com` to avoid link-rot

### Admin Guide

- [ ] **ADMIN-01**: User management & RBAC page — roles, permissions, self-registration approval, API keys
- [ ] **ADMIN-02**: OAuth/OIDC setup page — Google, Microsoft, generic OIDC, group-to-role mapping
- [ ] **ADMIN-03**: Settings reference — basemaps, map defaults, feature toggles, LLM provider, log levels, persistent config
- [ ] **ADMIN-04**: Backups & restore page — schedule config, S3 off-site replication, retention, restore validation
- [ ] **ADMIN-05**: Infrastructure dashboard & monitoring page — Prometheus metrics, S3/Redis/OIDC connectivity validation
- [ ] **ADMIN-06**: Cloud deployment notes — AWS / GCP / DigitalOcean tips migrated from existing docs
- [ ] **ADMIN-07**: Migrated and expanded from `backend/docs/admin.md`; legacy file replaced with stub redirecting to `docs.getgeolens.com/guides/admin`

### API Reference

- [ ] **API-01**: `openapi.json` snapshot committed to `docs/src/content/openapi/geolens.json` from a running geolens instance via a documented `scripts/fetch-openapi.ts` script (manual run, not CI-fetched at build time)
- [ ] **API-02**: `starlight-openapi@0.25.0` plugin renders the snapshot into static reference pages under `/guides/api/`
- [ ] **API-03**: Hand-authored API auth section documenting JWT, API key (`?api_key=` query param + `Authorization` header), and OAuth flows with curl examples
- [ ] **API-04**: Hand-authored OGC endpoints landing page summarizing OGC API Common, Records, Features, STAC, and tile endpoints with QGIS / GDAL connection examples
- [ ] **API-05**: Snapshot freshness documented — README in `docs/src/content/openapi/` explains how to refresh the snapshot before each release

### SEO & Discoverability

- [ ] **SEO-01**: Unique `<title>` and meta description on every page
- [ ] **SEO-02**: OG images generated per page at build time using hex/RGB color values (Satori does not support OKLCH); pattern reuses v14.0 marketing-site Satori pipeline
- [ ] **SEO-03**: `sitemap.xml` generated automatically by Astro and `robots.txt` allows crawl; sitemap submitted to Google Search Console after launch
- [ ] **SEO-04**: `llms.txt` published at site root with high-level navigation for AI-assisted developer tooling
- [x] **SEO-05
**: Canonical URLs in `<head>` resolve to `docs.getgeolens.com` so duplicate indexing of the legacy `backend/docs/*.md` is suppressed
- [ ] **SEO-06**: GA4 same-Measurement-ID strategy enabled on docs site for cross-subdomain conversion tracking parity with marketing site

### Accessibility (continues v14.0 A11Y track)

- [ ] **A11Y-05**: WCAG 2.1 AA audit of docs site — keyboard navigation, focus indicators, contrast, semantic HTML — Axe scan passes with zero critical/serious violations
- [ ] **A11Y-06**: Code blocks have accessible labels and the copy button is keyboard-operable with screen-reader-friendly status announcement
- [ ] **A11Y-07**: Search dialog is keyboard-trappable, Escape closes, focus returns to trigger

### Marketing Features Page (deferred Phase 216 — marketing half)

- [ ] **FEAT-01**: New `/features` page on `getgeolens.com` covering catalog, search, map builder, AI chat, raster/VRT, OGC, with screenshots reusing v14.0 product previews where possible
- [ ] **FEAT-02**: Each capability section cross-links into the relevant docs page on `docs.getgeolens.com`
- [ ] **FEAT-03**: OGC API compliance and standards section listing supported conformance classes and standards (OGC API Features Part 1+3, Records Core, STAC 1.1, CQL2)

### Migration & Legacy Cleanup

- [ ] **MIG-01**: `backend/docs/install.md` and `backend/docs/admin.md` in the geolens monorepo are replaced with one-line stubs pointing to `docs.getgeolens.com/guides/install` and `/guides/admin` immediately on launch
- [x] **MIG-02
**: A `_redirects` file in `docs/public/` covers any legacy URL patterns that may have been linked from external sites (e.g. `/install` → `/guides/install`)
- [ ] **MIG-03**: Repo README and `CONTRIBUTING.md` reference `docs.getgeolens.com` as the canonical home for user-facing documentation; raw markdown sources retained only for the bootstrap path

### CI & Quality Gates

- [ ] **CI-01**: `starlight-links-validator` (or equivalent) runs in CI to catch broken internal links before merge
- [x] **CI-02
**: `npx astro check` runs in docs CI to catch type errors and Starlight schema violations
- [ ] **CI-03**: Lighthouse CI (or equivalent) checks Performance ≥ 90 and Accessibility = 100 on the homepage and one representative guide page

## Future Requirements (Deferred from v15.0)

- **VERSION-01**: Versioned documentation (per-release snapshots) once two GeoLens majors are simultaneously in production use — `starlight-versions` plugin is the planned vehicle
- **OASDIFF-01**: `oasdiff` drift-detection CI job in the geolens monorepo that compares old/new `openapi.json` on PRs and posts to a docs-update PR
- **TRY-IT-01**: Interactive "Try it out" API console (`starlight-openapi-navigator` or Scalar Playground) — requires auth wiring decisions and adds build complexity
- **I18N-01**: Localized docs (es / fr / de) once translation workflow is established; currently the geolens app is i18n-enabled but docs ship en-only
- **SEARCH-ALGOLIA-01**: Algolia DocSearch upgrade if Pagefind relevance proves insufficient at content scale

## Out of Scope

- **Mintlify, Docusaurus, VitePress, GitBook, Custom-from-scratch** — Starlight is locked; competing frameworks rejected for ecosystem fit and Astro reuse
- **`@astrojs/starlight-tailwind` plugin** — raw `customCss` is sufficient for token sharing; avoid coupling docs to marketing-site Tailwind build
- **npm/pnpm workspace setup in getgeolens-com** — independent subdirectory with its own `package.json` is simpler; workspaces add tooling overhead for zero shared JavaScript
- **Live `openapi.json` fetch from production at build time** — committed snapshot is deterministic and avoids Cloudflare→backend network dependency at build
- **Docs-site CMS or in-browser editor** — markdown + GitHub PR workflow is the authoring model
- **Comments, rating widgets, ads, paywalls, login-required pages** — open-source docs stay open and ad-free
- **Deep-linking user-guide pages into `demo.getgeolens.com`** — static screenshots only; demo is unstable enough that link-rot risk is unacceptable
- **Algolia DocSearch in v15.0** — Pagefind ships zero-config and is sufficient at current content scale
- **Versioned docs in v15.0** — single "latest" only; URL prefix `/guides/` is chosen so versioning can be retrofitted later without external link breakage
- **`oasdiff` CI job in v15.0** — drift detection deferred until docs site has shipped and stabilized
- **Phone-specific docs UI** — Starlight responsive defaults are sufficient
- **Self-hosted analytics** — GA4 only, matching marketing site

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BOOT-01 | Phase 223 | Pending |
| BOOT-02 | Phase 223 | Pending |
| BOOT-03 | Phase 223 | Pending |
| BOOT-04 | Phase 223 | Pending |
| DEPLOY-01 | Phase 223 | Pending |
| DEPLOY-02 | Phase 223 | Pending |
| DEPLOY-03 | Phase 223 | Pending |
| DEPLOY-04 | Phase 223 | Pending |
| MIG-02 | Phase 223 | Pending |
| SEO-05 | Phase 223 | Pending |
| SEO-06 | Phase 223 | Pending |
| CI-02 | Phase 223 | Pending |
| BRAND-01 | Phase 224 | Pending |
| BRAND-02 | Phase 224 | Pending |
| BRAND-03 | Phase 224 | Pending |
| BRAND-04 | Phase 224 | Pending |
| SHELL-01 | Phase 224 | Pending |
| SHELL-02 | Phase 224 | Pending |
| SHELL-03 | Phase 224 | Pending |
| SHELL-04 | Phase 224 | Pending |
| SHELL-05 | Phase 224 | Pending |
| SEARCH-01 | Phase 224 | Pending |
| SEARCH-02 | Phase 224 | Pending |
| SEARCH-03 | Phase 224 | Pending |
| SEO-04 | Phase 224 | Pending |
| API-01 | Phase 225 | Pending |
| API-02 | Phase 225 | Pending |
| API-03 | Phase 225 | Pending |
| API-04 | Phase 225 | Pending |
| API-05 | Phase 225 | Pending |
| CI-01 | Phase 225 | Pending |
| QUICK-01 | Phase 226 | Pending |
| QUICK-02 | Phase 226 | Pending |
| QUICK-03 | Phase 226 | Pending |
| QUICK-04 | Phase 226 | Pending |
| MIG-01 (install) | Phase 226 | Pending |
| USER-01 | Phase 227 | Pending |
| USER-02 | Phase 227 | Pending |
| USER-03 | Phase 227 | Pending |
| USER-04 | Phase 227 | Pending |
| USER-05 | Phase 227 | Pending |
| USER-06 | Phase 227 | Pending |
| USER-07 | Phase 227 | Pending |
| ADMIN-01 | Phase 227 | Pending |
| ADMIN-02 | Phase 227 | Pending |
| ADMIN-03 | Phase 227 | Pending |
| ADMIN-04 | Phase 227 | Pending |
| ADMIN-05 | Phase 227 | Pending |
| ADMIN-06 | Phase 227 | Pending |
| ADMIN-07 | Phase 227 | Pending |
| MIG-01 (admin) | Phase 227 | Pending |
| MIG-03 | Phase 227 | Pending |
| SEO-01 | Phase 228 | Pending |
| SEO-02 | Phase 228 | Pending |
| SEO-03 | Phase 228 | Pending |
| A11Y-05 | Phase 228 | Pending |
| A11Y-06 | Phase 228 | Pending |
| A11Y-07 | Phase 228 | Pending |
| FEAT-01 | Phase 228 | Pending |
| FEAT-02 | Phase 228 | Pending |
| FEAT-03 | Phase 228 | Pending |
| CI-03 | Phase 228 | Pending |
