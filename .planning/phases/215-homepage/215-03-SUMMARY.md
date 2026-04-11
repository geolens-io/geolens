---
phase: 215-homepage
plan: "03"
subsystem: getgeolens.com (marketing site)
tags: [astro, homepage, index, seo, composition, integration, json-ld]
requirements: [HOME-01, HOME-02, HOME-03, HOME-04, HOME-05]

dependency_graph:
  requires:
    - 215-01 (HeroSection, TrustSignalBar, QuickstartTeaser components)
    - 215-02 (ProductPreviewSection, FeatureHighlightsSection components)
    - 213-01 (SiteLayout + SEO infrastructure — title, description, ogImage, jsonLd props)
    - 213-02 (og:image generation pipeline)
  provides:
    - getgeolens.com/src/pages/index.astro — composed homepage (HOME-01 through HOME-05)
  affects:
    - dist/index.html (build artifact, not committed)
    - 215-04 (human visual verification checkpoint — can now proceed)

tech_stack:
  added: []
  patterns:
    - Composition root pattern: index.astro imports zero-prop components and renders them in locked order
    - jsonLd.description kept in sync with SiteLayout description prop (single string update point)

key_files:
  created: []
  modified:
    - getgeolens.com/src/pages/index.astro

decisions:
  - "Used Write tool (full file replace) not Edit tool — the entire file was being restructured with 5 new imports and full body replacement; Write is cleaner for near-total rewrites"
  - "dist/ output not committed — confirmed gitignored in getgeolens.com/.gitignore; build serves as verification only"
  - "jsonLd.description updated to match meta description verbatim — Phase 213 left a shorter subset; UI-SPEC requires identity match"

metrics:
  duration: "~5 minutes"
  completed: "2026-04-11"
  tasks_completed: 2
  files_created: 0
  files_modified: 1
---

# Phase 215 Plan 03: Homepage Composition (index.astro) Summary

**One-liner:** Replaced placeholder index.astro with ordered composition of all five homepage section components, updated SiteLayout title/description to UI-SPEC verbatim, and verified the production build embeds every locked content string in dist/index.html.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Modify index.astro to compose homepage sections and update SEO props | 430ab41 (getgeolens.com) | `src/pages/index.astro` |
| 2 | Build and verify dist/index.html contains all homepage strings | (no commit — build artifact) | `dist/index.html` (gitignored) |

---

## What Was Built

**index.astro** (modified in place) — the composition root for the homepage:

- Imports all five home components from `../components/home/`:
  - `HeroSection` (Plan 01)
  - `TrustSignalBar` (Plan 01)
  - `ProductPreviewSection` (Plan 02)
  - `FeatureHighlightsSection` (Plan 02)
  - `QuickstartTeaser` (Plan 01)
- Renders them in locked order as self-closing tags inside `<SiteLayout>`
- `SiteLayout title` updated to `"GeoLens — Find Any Geospatial Dataset in Seconds"` (em-dash, UI-SPEC verbatim)
- `SiteLayout description` updated to `"Self-hosted, open-source GIS data catalog with OGC API compliance, semantic search, and map builder. Apache 2.0. Deploy anywhere."` (UI-SPEC verbatim)
- `jsonLd.description` updated to match meta description verbatim (Phase 213 left a shorter version)
- `const ogImage` declaration preserved unchanged
- All other `jsonLd` fields preserved: `@context`, `@type: SoftwareApplication`, `name: GeoLens`, `url`, `applicationCategory`, `operatingSystem`, `license`, `codeRepository`, `softwareVersion: 14.0`, `offers`
- Placeholder `<section>` with inline `<h1>GeoLens</h1>` and `github.com/geolens-io/geolens#readme` CTA removed

**Build verification (Task 2)** — `npm run build` exits 0. All 28 grep checks against `dist/index.html` passed:

- Hero: headline, eyebrow, primary CTA, secondary CTA, GitHub URL
- Trust bar: Apache 2.0, OGC API Compliant, Self-Hosted badges
- Product preview: eyebrow, h2, body paragraph
- SearchPreview embed: Nys Aquifers, Nys Address Points, Bulletin, app.geolens.io/search
- Feature highlights: eyebrow, h2, Search & Semantic Discovery card, Map Builder card, OGC API Compliant card
- Quickstart teaser: h2, body, CTA
- SEO head: `<title>`, `<meta name="description">`, `application/ld+json`, `og:image`
- Security: `rel="noopener noreferrer"` present (T-215-09/T-215-10 regressions confirmed absent)
- Sitemap: `sitemap-0.xml` exists, homepage URL present, no `/og/` leakage (Phase 213 contract preserved)

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Known Stubs

None. All five section components are fully wired with hardcoded copy from the UI-SPEC. index.astro is a pure composition root with no display logic of its own. The `/quickstart` link will 404 until Phase 216 builds that page — this is expected per UI-SPEC note.

---

## Threat Surface Scan

No new surface beyond the plan's threat model. T-215-09 (Phase 213 SEO regression) and T-215-10 (tabnabbing mitigation regression) both confirmed mitigated:
- `og:image`, `application/ld+json`, and the full meta description string all present in `dist/index.html`
- `rel="noopener noreferrer"` confirmed present in built HTML (Plans 01 + 02 mitigations survived the build)
- T-215-11 (JSON-LD XSS) remains accepted — jsonLd is a fully hardcoded object, no user input
- Sitemap integrity confirmed: no `/og/` entries leaked

---

## Self-Check: PASSED

Files modified exist:
- FOUND: /Users/ishiland/Code/getgeolens.com/src/pages/index.astro

Commits exist (getgeolens.com repo):
- FOUND: 430ab41 (index.astro composition)

`astro check` result: 0 errors, 0 warnings, 0 hints (19 files checked)
`npm run build` result: exit 0, 2 pages built
All 28 content verification greps: PASSED
