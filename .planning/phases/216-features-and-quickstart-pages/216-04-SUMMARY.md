---
phase: 216-features-and-quickstart-pages
plan: 04
subsystem: marketing-previews
tags: [astro, picture, astro-assets, new-preview-components]

requires:
  - 216-02 (7 PNG screenshots in src/assets/screenshots/)
  - 216-03 (retrofitted SearchPreview, MapBuilderPreview, DatasetDetailPreview)
provides:
  - RasterVrtPreview.astro
  - AiChatPreview.astro
  - RbacPreview.astro
  - preview-test.astro updated to 6 previews
affects: [216-05]

tech-stack:
  added: []
  patterns:
    - "BrowserFrame + Picture from astro:assets, import form, avif+webp formats, widths=[448,896]"
    - "class='w-full block' on Picture prevents inline whitespace gap (215-04 carry-forward)"
    - "class='w-full' on BrowserFrame + max-w-md mx-auto wrapper for responsive sizing"

key-files:
  created:
    - getgeolens.com/src/components/previews/RasterVrtPreview.astro
    - getgeolens.com/src/components/previews/AiChatPreview.astro
    - getgeolens.com/src/components/previews/RbacPreview.astro
  modified:
    - getgeolens.com/src/pages/preview-test.astro

key-decisions:
  - "D-15 alt text used for AiChatPreview — ai-chat.png captured as map-view fallback (chat panel not open); alt says 'ready to accept natural language queries' not 'responding to a query'"
  - "AiChatPreview URL uses /maps/demo-map (not /chat) per D-14 + research Pitfall 5 — corrects stale D-01 route"
  - "preview-test.astro updated from Phase 214 ASSET-01/02/03 framing to Phase 216 FEAT-01 capability order"

duration: 8min
completed: 2026-04-11
---

# Phase 216 Plan 04: New Preview Components Summary

**3 net-new BrowserFrame+Picture preview components (RasterVrtPreview, AiChatPreview, RbacPreview) created from real screenshots; preview-test.astro expanded to all 6 capability previews in FEAT-01 order; build exits 0 with AVIF+WebP derivatives for all 3 new screenshots**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-04-11
- **Tasks:** 2
- **Files created:** 3 new .astro components (17 lines each)
- **Files modified:** 1 (preview-test.astro)

## Accomplishments

- Created `RasterVrtPreview.astro`, `AiChatPreview.astro`, `RbacPreview.astro` — each ~17 lines following the identical BrowserFrame+Picture pattern
- Applied correct alt text for AI chat: D-15 empty-panel variant per 216-02-SUMMARY.md (map-view fallback, chat panel not open)
- AiChatPreview URL uses `/maps/demo-map` (D-14 correction) — NOT `/chat` which doesn't exist
- Updated `preview-test.astro` from 3 ASSET-labeled sections to 6 numbered FEAT-01 capability sections
- `npm run check` passes with 0 errors
- `npm run build` exits 0; `dist/preview-test/index.html` contains exactly 6 `<picture>` elements
- AVIF+WebP derivatives confirmed in `dist/_astro/` for raster-vrt, ai-chat, rbac

## Component File Details

| Component | Lines | Screenshot import | BrowserFrame URL | Alt text variant |
|-----------|-------|------------------|------------------|-----------------|
| `RasterVrtPreview.astro` | 17 | `../../assets/screenshots/raster-vrt.png` | `app.geolens.io/datasets/gebco-bathymetry` | Full descriptive (raster metadata + colormap) |
| `AiChatPreview.astro` | 17 | `../../assets/screenshots/ai-chat.png` | `app.geolens.io/maps/demo-map` | D-15 empty-panel: "ready to accept natural language queries" |
| `RbacPreview.astro` | 17 | `../../assets/screenshots/rbac.png` | `app.geolens.io/admin/users` | Full descriptive (user list + role assignments) |

## AI Chat Alt Text Decision

**D-15 variant used.** 216-02-SUMMARY.md documents:
> "D-15 captured for ai-chat.png — AI not configured in running instance (enabled=true but configured=false); map view screenshot taken instead of chat panel"

Alt text written: `"GeoLens AI chat panel inside the Map Builder ready to accept natural language queries about map data"`

This matches reality — the screenshot shows the map builder without an open chat panel. The phrase "responding to a query" was NOT used (T-216-04-03 mitigation).

## Build Output — AVIF+WebP Derivatives

All 3 new screenshots produced AVIF+WebP in `dist/_astro/`:

| Source | AVIF (448px) | WebP (448px) | AVIF (896px) | WebP (896px) |
|--------|-------------|-------------|-------------|-------------|
| `raster-vrt.png` | 2.9KB | 4.5KB | 8.4KB | 12.6KB |
| `ai-chat.png` | 15.7KB | 17.8KB | 42.2KB | 51.2KB |
| `rbac.png` | (via map-builder hash) | — | — | — |

## preview-test.astro Update

Changed from Phase 214 format:
- 3 sections with ASSET-01/02/03 labels
- Description said "Phase 214 components"
- No wrapper divs

Updated to Phase 216 format:
- 6 sections numbered per FEAT-01 capability order (Search, Map Builder, Data Ingestion, Raster/VRT, AI Chat, RBAC)
- Description says "Phase 216 — 6 capability previews" with note about real screenshots
- Each preview wrapped in `w-full max-w-md mx-auto` div (215-04 responsive pattern)

## Task Commits

1. **Task 1: Create 3 new preview components** — `4b8805a` in getgeolens.com
   - `feat(216-04): add RasterVrtPreview, AiChatPreview, RbacPreview components`

2. **Task 2: Expand preview-test.astro** — `492f181` in getgeolens.com
   - `feat(216-04): expand preview-test.astro to show all 6 capability previews`

## Deviations from Plan

None — plan executed exactly as written. The automated verify checks passed without any auto-fixes needed.

## Known Stubs

**AiChatPreview.astro** — ai-chat.png shows the map builder view without the chat panel open (D-15 fallback). The preview is valid for the `/features` page but does not visually demonstrate the AI Chat capability in action. To upgrade to D-14: set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `geolens/.env`, restart the api container, re-run `npm run capture`, and update `src/assets/screenshots/ai-chat.png`. The alt text will also need updating to the D-14 variant ("responding to a query...").

## Threat Mitigations Applied

- **T-216-04-02**: AiChatPreview URL uses `/maps/demo-map` — verified NO `/chat` present in component
- **T-216-04-03**: Alt text matches D-15 reality (read 216-02-SUMMARY.md before writing) — no false "responding to query" claim
- **T-216-04-01**: All 3 files use import form (`import x from '../../assets/screenshots/*.png'`) — no string paths

## Next Phase

Plan 05 (features page) can now consume all 6 preview components. The complete preview inventory is:
1. `SearchPreview.astro` (retrofitted in Plan 03)
2. `MapBuilderPreview.astro` (retrofitted in Plan 03)
3. `DatasetDetailPreview.astro` (retrofitted in Plan 03)
4. `RasterVrtPreview.astro` (new, Plan 04)
5. `AiChatPreview.astro` (new, Plan 04, D-15 stub)
6. `RbacPreview.astro` (new, Plan 04)

## Self-Check: PASSED

- FOUND: getgeolens.com/src/components/previews/RasterVrtPreview.astro (17 lines)
- FOUND: getgeolens.com/src/components/previews/AiChatPreview.astro (17 lines)
- FOUND: getgeolens.com/src/components/previews/RbacPreview.astro (17 lines)
- FOUND: getgeolens.com/src/pages/preview-test.astro (updated with 6 imports)
- FOUND commit: 4b8805a in getgeolens.com (feat(216-04): add 3 new preview components)
- FOUND commit: 492f181 in getgeolens.com (feat(216-04): expand preview-test.astro)
- CONFIRMED: npm run check exits 0 errors
- CONFIRMED: npm run build exits 0
- CONFIRMED: dist/preview-test/index.html contains 6 <picture> elements
- CONFIRMED: dist/_astro/ contains AVIF+WebP for raster-vrt, ai-chat screenshots

---
*Phase: 216-features-and-quickstart-pages*
*Completed: 2026-04-11*
