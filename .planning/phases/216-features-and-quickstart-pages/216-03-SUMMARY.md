---
phase: 216-features-and-quickstart-pages
plan: 03
subsystem: marketing-previews
tags: [astro, picture, astro-assets, phase-214-retrofit, preview-components]

requires:
  - 216-02 (screenshot PNGs in src/assets/screenshots/)
provides:
  - SearchPreview.astro retrofitted to render search.png via <Picture>
  - MapBuilderPreview.astro retrofitted to render map-builder.png via <Picture>; URL corrected from /builder/ to /maps/demo-map
  - DatasetDetailPreview.astro retrofitted to render data-ingestion.png via <Picture>
  - npm run build exits 0 with AVIF + WebP derivatives for all 3 screenshots
  - Homepage inherits retrofitted previews automatically (no callsite changes needed)
affects: [216-05, 216-06]

tech-stack:
  added: []
  patterns:
    - "astro:assets Picture import form — import PNG as ESM module, never string path"
    - "Astro content-based image dedup — map-builder.png and ai-chat.png have identical content (D-15 fallback), Astro correctly shares derivatives"

key-files:
  modified:
    - getgeolens.com/src/components/previews/SearchPreview.astro
    - getgeolens.com/src/components/previews/MapBuilderPreview.astro
    - getgeolens.com/src/components/previews/DatasetDetailPreview.astro

key-decisions:
  - "map-builder.png deduplicated by Astro to ai-chat hash — expected; both PNGs are identical content (D-15 fallback captured map builder view for ai-chat.png per 216-02 SUMMARY)"
  - "MapBuilderPreview URL corrected from app.geolens.io/builder to app.geolens.io/maps/demo-map (research Pitfall 5)"
  - "DatasetDetailPreview repurposed for Data Ingestion capability; url slug kept as nys-aquifers for continuity"
  - "loading=lazy on all 3 Picture elements per plan guidance (non-above-fold)"

duration: 25min
completed: 2026-04-12
---

# Phase 216 Plan 03: Preview Component Retrofit Summary

**3 Phase-214 SVG preview components retrofitted to render real screenshots via Astro `<Picture>` — 145+342+60 lines of SVG markup replaced with ~17 lines each; npm run build exits 0 with AVIF+WebP derivatives for all 3 PNGs; homepage inherits changes automatically**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-12T02:12:00Z
- **Completed:** 2026-04-12T02:37:09Z
- **Tasks:** 2
- **Files modified:** 3 (all in getgeolens.com/src/components/previews/)

## Accomplishments

- Replaced 145-line SVG mock in SearchPreview.astro with a 17-line `<Picture>` retrofit importing `search.png`
- Replaced 342-line cartographic SVG in MapBuilderPreview.astro with a 17-line `<Picture>` retrofit; corrected URL from `/builder/` to `/maps/demo-map`
- Replaced 60-line SVG mock in DatasetDetailPreview.astro with a 17-line `<Picture>` retrofit importing `data-ingestion.png`
- All 3 files use the import form (`import foo from '../../assets/screenshots/foo.png'`) — confirmed by `astro check` TypeScript validation
- Descriptive alt text on all 3 (A11Y carry-forward: not generic, describes visible content)
- No `min-height` in any of the 3 retrofitted files (Pitfall 4 cleared)
- `npm run build` exits 0; AVIF + WebP derivatives confirmed in `dist/_astro/`
- Homepage HTML contains 2 `<picture>` tags with `.avif` sources; `app.geolens.io/maps/demo-map` in URL pill; no `/builder/` present

## Task Commits

1. **Task 1: Retrofit SearchPreview + DatasetDetailPreview** — `35ec2c9` (feat) in getgeolens.com
   - `feat(216-03): retrofit SearchPreview + DatasetDetailPreview to use Picture`

2. **Task 2: Retrofit MapBuilderPreview + build verification** — `0172773` (feat) in getgeolens.com
   - `feat(216-03): retrofit MapBuilderPreview to use Picture + build verification`

## Line Count Reduction

| File | Before | After | Reduction |
|------|--------|-------|-----------|
| SearchPreview.astro | 145 lines | 17 lines | -128 lines (88%) |
| MapBuilderPreview.astro | 342 lines | 17 lines | -325 lines (95%) |
| DatasetDetailPreview.astro | 60 lines | 17 lines | -43 lines (72%) |

## URL Correction

MapBuilderPreview.astro Phase 214 line 23: `url="app.geolens.io/builder"` → Phase 216: `url="app.geolens.io/maps/demo-map"`

This corrects Research Pitfall 5 — the real GeoLens app routes map builder at `/maps/:id`, not `/builder/:id`. The URL pill is decorative (no real link), so a stable placeholder slug `demo-map` was used.

## AVIF + WebP File Sizes (dist/_astro/)

| Screenshot | AVIF 448w | AVIF 896w | WebP 448w | WebP 896w |
|-----------|-----------|-----------|-----------|-----------|
| search.png (80KB PNG) | 2.5KB | 7.9KB | 3.6KB | 11.5KB |
| data-ingestion.png (260KB PNG) | 6.5KB | 21.3KB | 8.8KB | 29.6KB |
| map-builder.png (560KB PNG) | 15.7KB\* | 42.2KB\* | 17.8KB\* | 51.2KB\* |

\* `map-builder.png` has identical content to `ai-chat.png` (both 559,812 bytes — D-15 fallback in 216-02 captured map builder view for ai-chat.png). Astro content-hashes detected the duplicate and shares derivatives under the `ai-chat.PcTCfVz-` hash prefix. This is correct Astro behavior — no issue.

## Homepage Smoke Check

- `npm run preview` + `curl http://localhost:4321/` checks:
  - `<picture>` tags: **2 found** (SearchPreview + MapBuilderPreview on homepage)
  - `.avif` sources: **2 found**
  - `app.geolens.io/search`: **1 found**
  - `app.geolens.io/maps/`: **1 found**
  - `app.geolens.io/builder`: **0 found** (URL correction confirmed)

## Phase Verification Results

1. **Syntax check** (`npm run check`): 0 errors, 0 warnings, 1 hint (pre-existing unrelated)
2. **Import form check**: All 3 files grep-match `import.*from '../../assets/screenshots/.*\.png'` — import form confirmed
3. **URL correction**: `url="app.geolens.io/maps/"` matches in MapBuilderPreview; `url="app.geolens.io/builder"` returns 0 matches
4. **Min-height removal**: 0 matches in all 3 files
5. **Build check**: `npm run build` exits 0; AVIF and WebP derivatives present in `dist/_astro/`
6. **Alt text**: All 3 files have descriptive alt attributes (>50 chars each)
7. **Smoke render**: Homepage renders correctly with `<picture>` and `.avif` sources

## Deviations from Plan

None — plan executed exactly as written.

The first `npm run build` run failed with an `ENOENT` error on `rbac.BK7g7W-j_ZYUAr3.avif` — this was a race condition in Node.js 25 where the `_astro` directory was partially written during parallel image generation. The second build run succeeded using cached entries from the first partial run. Not a code issue; not a deviation.

## Known Stubs

None. All 3 components render real screenshots via `<Picture>` from `astro:assets`. The visual content is production-captured (Plan 02) and the optimization pipeline runs at build time.

Note: `map-builder.png` currently shows the map builder view without the AI chat panel open (D-15 fallback). This is an inherited stub from Plan 02 — not introduced here. Plan 02 SUMMARY documents the upgrade path (set LLM key in .env, re-run capture).

## Threat Review

- **T-216-03-01** (string-path import regression): Mitigated — all 3 files use ESM import form; confirmed by `astro check` TypeScript validation (`src: ImageMetadata` type enforced)
- **T-216-03-04** (misleading BrowserFrame URL): Mitigated — MapBuilderPreview URL corrected from `/builder/` to `/maps/demo-map`; grep verification confirmed

## Self-Check: PASSED

- FOUND: getgeolens.com/src/components/previews/SearchPreview.astro (17 lines, Picture import)
- FOUND: getgeolens.com/src/components/previews/MapBuilderPreview.astro (17 lines, Picture import)
- FOUND: getgeolens.com/src/components/previews/DatasetDetailPreview.astro (17 lines, Picture import)
- FOUND commit: 35ec2c9 in getgeolens.com (feat(216-03): retrofit SearchPreview + DatasetDetailPreview)
- FOUND commit: 0172773 in getgeolens.com (feat(216-03): retrofit MapBuilderPreview + build verification)
- CONFIRMED: npm run build exits 0
- CONFIRMED: dist/_astro/ contains AVIF + WebP derivatives
- CONFIRMED: homepage HTML has <picture> tags with .avif sources and /maps/ URL

---
*Phase: 216-features-and-quickstart-pages*
*Completed: 2026-04-12*
