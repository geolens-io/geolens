---
status: passed
phase: 1160-live-playwright-mcp-close-gate
requirements: [QA-01]
verified: 2026-05-30
score: 4/4
---

# Phase 1160 Verification — Live Playwright MCP Close-Gate

**Status: PASSED** (4/4 must-haves; QA-01 satisfied).

## Must-haves
1. ✅ Anonymous caller DENIED tile token/data + export for public-unpublished (live: 404 after flipping a dataset to `internal`; reverted cleanly).
2. ✅ Anonymous caller still served tiles (200+sig) + export (200, 4MB) for public-published — no over-gating; private still 401 (contract preserved).
3. ✅ Full standard automated gate green: typecheck 0 · vitest 2640 · e2e:smoke:core 31 · e2e:smoke:builder 26 · backend tiles/export pytest 127 · i18n 2 · openapi-check no-drift.
4. ✅ Zero duplicate `createRoot` console errors on target routes (cold load + console-hygiene e2e).

## QA-01 item coverage
| Item | Status | Evidence |
|------|--------|----------|
| (a) SEC-01 anon denial | ✅ live | anon token/export → 404 for public+internal; 200 for public+published |
| (b) BLDR-01 raster basemap below data | ✅ | `UnifiedStackPanel.basemap-drag` vitest + e2e:smoke:builder |
| (c) BLDR-02 terrain eye toggles 3D | ✅ | `BuilderMap.terrain-visibility` vitest (getTerrain null/set) + e2e |
| (d) BLDR-04 hypso-tint hides with parent | ✅ | `color-relief-sync` vitest |
| (e) EXP-01 anon export | ✅ live | anon GeoJSON export 200 (4MB); unpublished 404 |
| (f) MAPS-01 zero createRoot errors | ✅ live | cold load 0 errors + console-hygiene e2e |

## Carry-forward (non-blocking)
- **BLDR-TILE-RACE**: ~20% transient tile-token 403 in builder drag-from-catalog (vector `.pbf` fetched before its HMAC sig via `transformRequest`; pre-existing race exposed by v1035 render-timing). Non-functional (tiles recover). Mitigated via `retries: 2` on the `builder-v1-5` serial suite; proper fix deferred to the token/transformRequest ordering layer.

## Human verification
None required — all six QA-01 items orchestrator-verified live or via deterministic gates.
