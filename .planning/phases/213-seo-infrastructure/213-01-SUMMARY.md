---
phase: 213-seo-infrastructure
plan: "01"
subsystem: marketing-site-seo
tags: [seo, meta-tags, open-graph, twitter-card, json-ld, sitemap, astro]
dependency_graph:
  requires: [212-02]
  provides: [SEO-01, SEO-03, SEO-04]
  affects: [all-future-pages]
tech_stack:
  added: []
  patterns:
    - SiteLayout.astro SEO prop extension (ogImage, canonical, jsonLd)
    - JSON-LD via set:html + is:inline on script tag
    - Astro.site-based absolute OG image URL construction
    - sitemap filter function to exclude /og/ routes
key_files:
  created: []
  modified:
    - /Users/ishiland/Code/getgeolens.com/src/components/layout/SiteLayout.astro
    - /Users/ishiland/Code/getgeolens.com/src/pages/index.astro
    - /Users/ishiland/Code/getgeolens.com/astro.config.mjs
decisions:
  - "is:inline required on JSON-LD script tag alongside set:html to suppress Astro hint about unprocessed scripts"
  - "resolvedOgImage defaults to /og/home.png via new URL(..., Astro.site).href — absolute URL required for social crawlers"
  - "Sitemap filter pattern: (page) => !page.includes('/og/') — prevents future OG image endpoints from polluting sitemap"
metrics:
  duration_minutes: 5
  completed_date: "2026-04-05"
  tasks_completed: 2
  files_modified: 3
---

# Phase 213 Plan 01: SEO Infrastructure — Full SEO Head and JSON-LD Summary

**One-liner:** Full SEO head (canonical, OG, Twitter Card) + SoftwareApplication JSON-LD wired into SiteLayout.astro and homepage with sitemap /og/ filter.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend SiteLayout.astro with full SEO head and sitemap filter | 7aa4d84 | SiteLayout.astro, astro.config.mjs |
| 2 | Add JSON-LD SoftwareApplication structured data to homepage | 482ed1b | index.astro |

## What Was Built

**SiteLayout.astro** now accepts three new optional props:
- `ogImage?: string` — absolute URL to OG image (defaults to `https://getgeolens.com/og/home.png`)
- `canonical?: string` — canonical URL override (defaults to `Astro.url.href`)
- `jsonLd?: Record<string, unknown>` — optional JSON-LD object rendered in `<head>` when provided

Every page using SiteLayout automatically gets: `<link rel="canonical">`, `og:type`, `og:url`, `og:title`, `og:description`, `og:image`, `og:image:width`, `og:image:height`, `og:site_name`, `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`.

**astro.config.mjs** sitemap integration updated with `filter: (page) => !page.includes('/og/')` to prevent future OG image static endpoints from appearing in `sitemap-0.xml`.

**index.astro** defines a `const jsonLd` SoftwareApplication block (schema.org, with name, description, url, applicationCategory, operatingSystem, license, codeRepository, softwareVersion, offers) and passes it to SiteLayout. The JSON-LD renders correctly as unescaped JSON via `set:html` in the built `dist/index.html`.

## Verification

- `npx astro check`: 0 errors, 0 warnings, 0 hints
- `npm run build`: exit 0, 1 page built
- `dist/index.html` contains: `rel="canonical"`, `og:title`, `og:description`, `og:image`, `og:url`, `og:type`, `og:site_name`, `twitter:card`, `twitter:title`, `twitter:image`, `application/ld+json`
- `dist/sitemap-0.xml` contains only `https://getgeolens.com/` — no `/og/` entries
- JSON-LD parses as valid JSON with `@type: SoftwareApplication`, `name: GeoLens`, `offers.price: "0"`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical annotation] Added `is:inline` to JSON-LD script tag**
- **Found during:** Task 1 verification (`npx astro check`)
- **Issue:** Astro emits a hint (not an error) when a `<script>` tag has attributes like `type` and `set:html` without `is:inline`. The hint indicates the script is treated as inline anyway, but recommends being explicit to silence it.
- **Fix:** Added `is:inline` to `<script is:inline type="application/ld+json" set:html={...}>` — a no-op in terms of behavior but eliminates the hint and makes intent explicit.
- **Files modified:** `src/components/layout/SiteLayout.astro`
- **Commit:** 7aa4d84 (included in same commit)

## Known Stubs

None. The `og:image` meta tag references `/og/home.png` which does not yet exist as a generated file — this is intentional. Phase 213 Plan 02 (OG image generation via satori) will create that file. Until then, social crawlers will receive a 404 for the image only; all other SEO metadata is fully functional.

## Self-Check: PASSED

- `src/components/layout/SiteLayout.astro` — FOUND (verified modified)
- `src/pages/index.astro` — FOUND (verified modified)
- `astro.config.mjs` — FOUND (verified modified)
- Commit 7aa4d84 — FOUND (`git log` confirmed)
- Commit 482ed1b — FOUND (`git log` confirmed)
- `dist/index.html` og:title — FOUND
- `dist/index.html` twitter:card — FOUND
- `dist/index.html` rel="canonical" — FOUND
- `dist/index.html` application/ld+json — FOUND with valid SoftwareApplication JSON
- `dist/sitemap-0.xml` no /og/ entries — CONFIRMED
