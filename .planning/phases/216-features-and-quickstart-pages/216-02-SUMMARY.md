---
phase: 216-features-and-quickstart-pages
plan: 02
subsystem: marketing-assets
tags: [playwright, screenshot-capture, astro, png-assets]

requires:
  - 216-01 (capture-screenshots.ts script)
provides:
  - 7 PNG files in getgeolens.com/src/assets/screenshots/
  - Confirmed astro build succeeds with PNGs present
affects: [216-03, 216-04, 216-06]

tech-stack:
  added: []
  patterns:
    - "API paths via Vite proxy: /api/* (NOT /api/v1/*) — fixed in capture script"
    - "Raster dataset filter: /api/search/datasets/?record_type=raster_dataset (not ?type=raster)"
    - "AI probe: /api/admin/ai-status/ returning {enabled, configured} (not /settings/ai-enabled)"

key-files:
  created:
    - getgeolens.com/src/assets/screenshots/search.png
    - getgeolens.com/src/assets/screenshots/map-builder.png
    - getgeolens.com/src/assets/screenshots/data-ingestion.png
    - getgeolens.com/src/assets/screenshots/raster-vrt.png
    - getgeolens.com/src/assets/screenshots/ai-chat.png
    - getgeolens.com/src/assets/screenshots/rbac.png
    - getgeolens.com/src/assets/screenshots/quickstart-outcome.png
  modified:
    - getgeolens.com/scripts/capture-screenshots.ts

key-decisions:
  - "D-15 variant captured for ai-chat.png — AI not configured in running instance (enabled=true but configured=false); map view screenshot taken instead of chat panel"
  - "quickstart-outcome.png is aliased to search.png per D-13 — identical content (same / route), confirmed via md5 hash match"
  - "capture-screenshots.ts API paths fixed from /api/v1/ to /api/ prefix — Rule 1 auto-fix; script was authored against wrong path assumption"
  - "Chromium binary updated from 1208 to 1217 — Playwright package had been bumped, requiring fresh browser download"

duration: 12min
completed: 2026-04-11
---

# Phase 216 Plan 02: Screenshot Capture Summary

**7 Playwright-captured PNGs (1600x900 and 1600x800) committed to getgeolens.com/src/assets/screenshots/ after fixing capture script API paths from /api/v1/ to /api/; astro build passes; AI chat captured as D-15 map-view fallback**

## Performance

- **Duration:** ~12 min (including chromium binary download + capture run)
- **Completed:** 2026-04-11
- **Tasks:** 1 (Task 2 — Task 1 was a human-action checkpoint cleared by orchestrator)
- **Files modified:** 8 (7 new PNGs + 1 script fix)

## Accomplishments

- Ran `npm run capture` against live GeoLens at http://localhost:8080 — 7 succeeded, 0 failed
- Fixed 4 API path bugs in capture-screenshots.ts before running (all were `/api/v1/` → should be `/api/`)
- Installed updated Playwright chromium binary (1208 → 1217) after package bump
- Validated all 7 PNGs: correct dimensions, all valid PNG, all > 20KB
- Confirmed `quickstart-outcome.png` aliases `search.png` (identical MD5 hash per D-13)
- `npm run build` exits 0; no PNG-related errors
- `public/screenshots/` does NOT exist (Pitfall 1 guard passed)

## Task Commits

1. **Task 2: Run capture, fix API paths, commit PNGs** — `d7d6d42` in getgeolens.com
   - `feat(216-02): add 7 capability screenshots from Playwright capture`

## PNG File Inventory

| File | Dimensions | Size | Notes |
|------|-----------|------|-------|
| `search.png` | 1600×900 | 80,205 B | Catalog search page with seeded datasets |
| `map-builder.png` | 1600×900 | 559,812 B | Map builder with layers loaded |
| `data-ingestion.png` | 1600×800 | 259,981 B | Vector dataset detail page |
| `raster-vrt.png` | 1600×800 | 99,525 B | Raster dataset detail page |
| `ai-chat.png` | 1600×900 | 559,812 B | Map builder view (D-15 fallback — chat panel not opened) |
| `rbac.png` | 1600×800 | 22,363 B | Admin users page |
| `quickstart-outcome.png` | 1600×900 | 80,205 B | Alias of search.png (same route, identical content) |

All files: valid PNG per `file` command. All sizes > 20KB.

## AI Chat Variant

**D-15 captured** — empty-panel / map-view fallback variant.

The running GeoLens instance has AI `enabled=true` but `configured=false` (no LLM key set in the container at capture time). The `probeAiAvailable()` function correctly returned `false`, triggering the D-15 branch. The script attempted to click the chat panel toggle but the locator did not match (`Could not open chat panel — taking screenshot of map view`), so `ai-chat.png` shows the map builder view without the chat panel open.

To upgrade to D-14 (full conversation): set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `geolens/.env`, restart the api container, and re-run `npm run capture`.

## Seeder Status

The Phase 218 seeder was used (operator confirmed 223 datasets seeded). Evidence: `map-builder.png` shows a populated map (559KB — indicates map content rendered), `data-ingestion.png` shows a vector dataset detail page (260KB), and `raster-vrt.png` shows a raster dataset (100KB).

## Astro Build

`npm run build` exited 0. Output:
```
22:13:32 [build] 2 page(s) built in 879ms
22:13:32 [build] Complete!
```

No PNG-related errors. Note: no components reference the screenshots yet (Plans 03/04 do that), so no AVIF/WebP derivatives were produced — expected.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 4 wrong API URL prefixes in capture-screenshots.ts**
- **Found during:** Task 2 (pre-flight API verification)
- **Issue:** Script used `${BASE_URL}/api/v1/...` paths but GeoLens Vite proxy exposes routes at `${BASE_URL}/api/...` (without `/v1/`). The `/api` → backend strip removes the `/api` prefix, mapping `/api/maps/` to `/maps/` on the backend. Using `/api/v1/maps/` would strip to `/v1/maps/` which returns 404.
- **Fixes applied:**
  - `probeAiAvailable`: `/api/v1/settings/ai-enabled` → `/api/admin/ai-status/`; check `configured` field (not `has_key`)
  - `getFirstMapId`: `/api/v1/maps/` → `/api/maps/`
  - `getFirstVectorDatasetId`: `/api/v1/datasets/?type=vector` → `/api/search/datasets/?record_type=vector_dataset`; response parsed as GeoJSON FeatureCollection (`features[0].id`)
  - `getFirstRasterDatasetId`: `/api/v1/datasets/?type=raster` → `/api/search/datasets/?record_type=raster_dataset`; same GeoJSON parse
- **Files modified:** `getgeolens.com/scripts/capture-screenshots.ts`
- **Commit:** `d7d6d42` (included in the PNG commit)

**2. [Rule 3 - Blocking] Updated Playwright chromium binary from 1208 to 1217**
- **Found during:** Task 2 (first capture attempt)
- **Issue:** `npm run capture` failed with "Executable doesn't exist at chromium_headless_shell-1217". The Playwright npm package had been updated (1.59.1 → version requiring binary 1217) since the orchestrator pre-flight check confirmed only binary 1208 was present.
- **Fix:** `cd /Users/ishiland/Code/getgeolens.com && npx playwright install chromium` — downloaded 165MB Chrome for Testing + 92MB headless shell for arm64.
- **Impact:** ~3 minute download delay before capture run. No code changes.

### quickstart-outcome.png

The script independently captures the `/` route for `quickstart-outcome.png` (same as `search.png`). Both files have identical MD5 hashes (`b018c0c12b4c21800396f54b8df11c44`), confirming the alias per D-13. The plan's manual `cp` step was unnecessary — the script already handled it.

## Known Stubs

**ai-chat.png** — Shows the map builder view without chat panel open (D-15 fallback). The image is valid for plans 03/04 as a placeholder but does not demonstrate the AI chat capability. Re-capture with LLM key configured to upgrade to D-14 before v14.0 launch.

## Threat Review (T-216-02-01)

Operator visual review confirms:
- search.png: dataset catalog with Natural Earth / seeded synthetic data — no PII visible
- map-builder.png: map view with layers — no user emails, no API keys in view
- data-ingestion.png: dataset detail (vector) — generic metadata, no sensitive content
- raster-vrt.png: raster dataset detail — topographic/bathymetric data only
- ai-chat.png: map builder view — no chat visible (D-15), no sensitive content
- rbac.png: admin users page showing only the `admin` user — no real user data
- quickstart-outcome.png: identical to search.png — same review applies

T-216-02-01 mitigated: all screenshots use seeded synthetic data, no PII or credentials visible.

## Next Phase Readiness

Plans 03 and 04 are unblocked — 7 PNG files are committed at `getgeolens.com/src/assets/screenshots/`.
Plan 06 is unblocked for `quickstart-outcome.png` import.

Plans 03/04 consumers should import via `astro:assets` pattern:
```astro
import searchImg from '../assets/screenshots/search.png';
```

## Self-Check: PASSED

- FOUND: getgeolens.com/src/assets/screenshots/search.png (80,205 B, 1600×900)
- FOUND: getgeolens.com/src/assets/screenshots/map-builder.png (559,812 B, 1600×900)
- FOUND: getgeolens.com/src/assets/screenshots/data-ingestion.png (259,981 B, 1600×800)
- FOUND: getgeolens.com/src/assets/screenshots/raster-vrt.png (99,525 B, 1600×800)
- FOUND: getgeolens.com/src/assets/screenshots/ai-chat.png (559,812 B, 1600×900)
- FOUND: getgeolens.com/src/assets/screenshots/rbac.png (22,363 B, 1600×800)
- FOUND: getgeolens.com/src/assets/screenshots/quickstart-outcome.png (80,205 B, 1600×900)
- FOUND commit: d7d6d42 in getgeolens.com (feat(216-02): add 7 capability screenshots)
- CONFIRMED: public/screenshots does NOT exist
- CONFIRMED: npm run build exits 0

---
*Phase: 216-features-and-quickstart-pages*
*Completed: 2026-04-11*
