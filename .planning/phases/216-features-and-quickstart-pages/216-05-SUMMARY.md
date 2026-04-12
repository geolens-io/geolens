---
phase: 216-features-and-quickstart-pages
plan: 05
subsystem: marketing-pages
tags: [astro, features-page, zig-zag-layout, ogc-compliance, marketing]

requires:
  - 216-03 (retrofitted SearchPreview, MapBuilderPreview, DatasetDetailPreview)
  - 216-04 (RasterVrtPreview, AiChatPreview, RbacPreview)
provides:
  - /features page at getgeolens.com/src/pages/features/index.astro
  - FeatureStripe.astro reusable zig-zag stripe component
  - OgcComplianceSection.astro with Features + Records families only (research Q8 corrected)
  - npm run build exits 0 with dist/features/index.html containing 6 <picture> elements
affects: []

tech-stack:
  added: []
  patterns:
    - "FeatureStripe component: eyebrow/heading/body/bullets/previewLeft/background props + slot for preview"
    - "Zig-zag layout: overflow-x-clip + max-w-7xl + grid-cols-12 + col-span-5/col-span-7 + lg:order-1/order-2"
    - "max-w-md mx-auto preview cap carried forward from Phase 215 Plan 04"
    - "OgcComplianceSection: 2-card grid, verified conformance class names, no Tiles/Maps/Processes"

key-files:
  created:
    - getgeolens.com/src/pages/features/index.astro
    - getgeolens.com/src/components/features/FeatureStripe.astro
    - getgeolens.com/src/components/features/OgcComplianceSection.astro

key-decisions:
  - "OGC section lists Features + Records families only — research Q8 verified against backend/app/ogc/router.py; Tiles/Maps/Processes explicitly excluded"
  - "Stripe 6 (RBAC) uses surface background to maintain alternating rhythm; OgcComplianceSection also surface — acceptable because the OGC section is visually distinct (centered, narrow, no preview)"
  - "WebPage jsonLd used for /features (not SoftwareApplication) — correct schema.org type for a marketing page"

metrics:
  duration: 20min
  completed: 2026-04-12
  tasks: 2
  files: 3
---

# Phase 216 Plan 05: /features Page Summary

**6 zig-zag capability stripes + OGC compliance section assembled from Plans 03/04 preview components, wrapped in SiteLayout; npm run build exits 0 with 6 `<picture>` elements in dist/features/index.html**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-04-12
- **Tasks:** 2
- **Files created:** 3 (all in getgeolens.com)

## Accomplishments

- Created `src/components/features/FeatureStripe.astro` — reusable zig-zag stripe component carrying the Phase 215 `overflow-x-clip + max-w-7xl + grid-cols-12 + col-span-5/col-span-7` rhythm verbatim
- Created `src/components/features/OgcComplianceSection.astro` — two-card OGC compliance section listing Features API (7 conformance classes) and Records API (3 conformance classes) only; file header documents the 2026-04-11 verification date and backend source
- Created `src/pages/features/index.astro` — 127-line page composition with all 6 preview components, SiteLayout with WebPage jsonLd, correct D-03 capability order and D-02 zig-zag alternation
- `npm run build` exits 0; `dist/features/index.html` verified to contain all 6 capability headings, 6 `<picture>` elements, Features API / Records API / CQL2 Text content, and zero Tiles/Maps/Processes claims

## Task Commits

1. **Task 1: Create FeatureStripe + OgcComplianceSection components** — `1cbace2` in getgeolens.com
   - `feat(216-05): add FeatureStripe + OgcComplianceSection components`

2. **Task 2: Build /features/index.astro page composition + verify build** — `c0b5bcf` in getgeolens.com
   - `feat(216-05): build /features page with 6 zig-zag stripes + OGC section`

## OGC Compliance Correction (T-216-05-01 mitigation)

The most critical requirement of this plan: the OGC compliance section advertises ONLY the families the backend actually declares at `/conformance`. Research Q8 verified against `backend/app/ogc/router.py` lines 131-151. The component file header documents the verification date (2026-04-11) and warns against adding Tiles/Maps/Processes without re-verification.

Build-time grep confirms zero occurrences of "Tiles API", "Maps API", or "Processes API" in `dist/features/index.html`.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

**AiChatPreview** (inherited from Plan 04) — `ai-chat.png` shows the map builder view without the AI chat panel open (D-15 fallback). The AI Chat capability stripe is present and accurate in copy, but the preview image doesn't visually show an active conversation. Upgrade path: set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `geolens/.env`, restart the api container, re-run `npm run capture`, and update `src/assets/screenshots/ai-chat.png`.

## Threat Review

- **T-216-05-01** (false OGC compliance claims): Mitigated — OgcComplianceSection has only Features + Records cards; grep verification confirms Tiles/Maps/Processes absent from built HTML
- **T-216-05-02** (copy overstating capabilities): Mitigated — RBAC bullets note OAuth/SAML are enterprise-edition; AI Chat bullets note BYO key
- **T-216-05-05** (page transfer size): Mitigated — all 6 `<Picture>` components use `loading="lazy"` (set in Plans 03/04); AVIF/WebP derivation confirmed from prior builds

## Self-Check: PASSED

- FOUND: getgeolens.com/src/components/features/FeatureStripe.astro
- FOUND: getgeolens.com/src/components/features/OgcComplianceSection.astro
- FOUND: getgeolens.com/src/pages/features/index.astro
- FOUND commit: 1cbace2 in getgeolens.com (feat(216-05): add FeatureStripe + OgcComplianceSection)
- FOUND commit: c0b5bcf in getgeolens.com (feat(216-05): build /features page)
- CONFIRMED: npm run build exits 0
- CONFIRMED: dist/features/index.html exists with 6 <picture> elements
- CONFIRMED: all 6 capability headings present in built HTML
- CONFIRMED: Features API, Records API, CQL2 Text present; Tiles/Maps/Processes absent

---
*Phase: 216-features-and-quickstart-pages*
*Completed: 2026-04-12*
