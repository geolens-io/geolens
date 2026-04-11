---
phase: 215-homepage
plan: "02"
subsystem: ui
tags: [astro, tailwind, oklch, marketing, homepage, responsive, product-preview, feature-highlights]

# Dependency graph
requires:
  - phase: 214-product-preview-assets
    provides: SearchPreview.astro and BrowserFrame.astro already built; SearchPreview is zero-prop, BrowserFrame provides aria-hidden and perspective tilt internally
  - phase: 212-repo-bootstrap-and-design-system
    provides: getgeolens.com repo structure, global.css CSS custom properties (--primary-700, --foreground, --muted-foreground, --surface-0, --border)
provides:
  - ProductPreviewSection.astro — two-column (5/7 lg grid) section embedding SearchPreview with locked copy (HOME-04)
  - FeatureHighlightsSection.astro — three-card feature grid with inline SVG icons and locked copy (HOME-03)
affects: [215-03-homepage-composition, 217-accessibility-audit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Embed zero-prop Astro component (SearchPreview) in a sizing wrapper without double-wrapping its internal BrowserFrame"
    - "color-mix(in oklch, var(--primary) 10%, transparent) for icon background tint — same pattern as SearchPreview badges"
    - "All brand colors via var(--*) CSS custom properties, never raw hex or Tailwind color utilities"

key-files:
  created:
    - getgeolens.com/src/components/home/ProductPreviewSection.astro
    - getgeolens.com/src/components/home/FeatureHighlightsSection.astro
  modified: []

key-decisions:
  - "ProductPreviewSection uses lg:grid-cols-12 with col-span-5/col-span-7 split (5/7) rather than explicit lg:w-5/12 columns — cleaner grid semantics, same visual outcome"
  - "FeatureHighlightsSection requires no frontmatter imports — empty --- block used"
  - "T-215-06 mitigation confirmed: ProductPreviewSection does NOT import BrowserFrame directly; SearchPreview wraps it internally"

patterns-established:
  - "Marketing section pattern: full-width <section> with py-20 sm:py-28 px-4 sm:px-6 lg:px-8, inner max-w-7xl mx-auto container"
  - "Feature card pattern: flex flex-col gap-4 p-6 with size-12 rounded-xl icon wrapper using color-mix tint"

requirements-completed: [HOME-03, HOME-04]

# Metrics
duration: 5min
completed: 2026-04-11
---

# Phase 215 Plan 02: Homepage Sections (Product Preview + Feature Highlights) Summary

**Two-column ProductPreviewSection embedding SearchPreview and three-card FeatureHighlightsSection with inline SVG icons — both using locked UI-SPEC copy and OKLCH CSS custom properties throughout**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-11T19:06:00Z
- **Completed:** 2026-04-11T19:07:30Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments
- `ProductPreviewSection.astro` — two-column lg grid (5/7 copy/preview), embeds `<SearchPreview />` once without double-wrapping BrowserFrame, T-215-06 mitigation confirmed (no BrowserFrame import)
- `FeatureHighlightsSection.astro` — exactly three feature cards (Search & Semantic Discovery, Map Builder, OGC API Compliant) in locked order with inline SVG icons, `aria-hidden="true" focusable="false"` on every icon, `color-mix(in oklch, var(--primary) 10%, transparent)` icon backgrounds
- `npm run check` exits 0 (0 errors, 0 warnings, 0 hints) with 19 files checked

## Task Commits

Each task was committed atomically in `getgeolens.com` repo:

1. **Task 1: Create ProductPreviewSection.astro (HOME-04)** - `ce7647a` (feat)
2. **Task 2: Create FeatureHighlightsSection.astro (HOME-03)** - `f062513` (feat)

## Files Created/Modified
- `getgeolens.com/src/components/home/ProductPreviewSection.astro` — Two-column marketing section with copy (eyebrow + h2 + body) on left and SearchPreview on right at lg+; single column on mobile
- `getgeolens.com/src/components/home/FeatureHighlightsSection.astro` — Three-card feature grid with centered section header, inline SVG icons per card, sm:grid-cols-3 responsive layout

## Copy Strings Confirmation (Verbatim Match with UI-SPEC)

**ProductPreviewSection:**
- Eyebrow: `Search & Discover` (literal `&`, not `&amp;`)
- h2: `Find any dataset in seconds`
- Body: contains em-dash `—` in `geometry type — vector, raster, or table — and`

**FeatureHighlightsSection:**
- Eyebrow: `What GeoLens does`
- h2: `Everything your team needs to work with geospatial data`
- Card 1 h3: `Search & Semantic Discovery`
- Card 2 h3: `Map Builder`
- Card 3 h3: `OGC API Compliant`
- Card 3 description contains em-dash `—` in `OGC API — Features, Tiles, and Maps`

## CSS Custom Properties Referenced
- `var(--background)` — section backgrounds
- `var(--foreground)` — headings and card titles
- `var(--muted-foreground)` — subtitle, body, and description text
- `var(--primary-700)` — eyebrow text, SVG icon stroke color
- `var(--primary)` — inside `color-mix()` for icon tint background
- `color-mix(in oklch, var(--primary) 10%, transparent)` — icon wrapper background

## Double-Wrap Prevention Confirmed (T-215-06)
`ProductPreviewSection.astro` does NOT import `BrowserFrame.astro`. `SearchPreview` wraps its content in `BrowserFrame` internally. The outer `<div class="w-full max-w-lg lg:max-w-none">` is a sizing wrapper only with no `aria-hidden`, no transform, no glow.

## Decisions Made
- Used `lg:grid-cols-12` with `lg:col-span-5` / `lg:col-span-7` for the 5/7 split — cleaner than explicit percentage widths
- Empty frontmatter `---` block used for FeatureHighlightsSection (no imports needed)
- No `<style>` blocks needed in either component — all styling via Tailwind utilities + inline CSS custom properties

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None. Both components are fully wired with static hardcoded copy per the UI-SPEC contract. No data sources to wire. No placeholders.

## Threat Flags

None. Both components are pure static Astro with no user input, no forms, no external links, and no `set:html` usage. All strings are hardcoded text literals. T-215-06 (double-wrap prevention) confirmed by grep.

## Next Phase Readiness
- Plan 01 (HeroSection, TrustSignalBar, QuickstartTeaser) is in parallel wave 1 — both Plan 01 and Plan 02 must complete before Plan 03 (index.astro composition)
- Plan 03 can import `<ProductPreviewSection />` and `<FeatureHighlightsSection />` directly with no further changes needed to these files
- Plan 04 (human visual verification checkpoint) follows Plan 03

---
*Phase: 215-homepage*
*Completed: 2026-04-11*
