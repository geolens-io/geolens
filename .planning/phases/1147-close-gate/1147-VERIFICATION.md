---
phase: 1147
phase_name: Close Gate
status: passed
verified: 2026-05-28
requirements: [QA-01, QA-02, QA-03]
method: orchestrator Playwright MCP + full gate suite
---

# Phase 1147 Verification — Close Gate

**Status: passed** — all quality gates green; live MCP confirms the milestone work; CHANGELOG + version decided.

## QA-01 — Live Playwright MCP smoke (orchestrator-driven)

- **Contour (cut):** DEM editor in Hillshade mode shows **no CONTOUR LINES section** (`hasContourLines:false`); HYPSOMETRIC TINT + SUN POSITION intact; **0 console errors** on mode switch (Phase 1145 live check).
- **Raster stretch:** reversible `is_dem=false` toggle → `minmax` (859 B near-blank) vs `percentile` (25 KB) vs `stddev` (27 KB) tiles render distinctly; `is_dem` reverted to `t` (Phase 1146 live check).
- **Builder health (authenticated):** fresh load of map `8dd6a129…` → **0 console errors**, map renders. (An interim 404 was a ~40-min JWT session expiry — anonymous `/api/maps/{id}` 404s by design; resolved by re-login.)

## QA-02 — Touched-surface gates

| Gate | Result |
|------|--------|
| Frontend `npm run typecheck` | 0 errors |
| Frontend `npm run lint` | 0 errors (1 pre-existing warning in `use-filtered-feature-count.ts`) |
| Frontend `npx vitest run` (full) | **2577 / 2577 pass** (238 files) |
| Frontend `npm run test:i18n` | 2 / 2 pass |
| Backend pytest (raster/tile suite) | 84 pass / 2 skip (`test_raster_colormap_proxy.py` 19 + raster/tiles 65) |
| `e2e:smoke:builder` | **26 / 26 pass** |

## QA-03 — CHANGELOG / OpenAPI / version

- **CHANGELOG:** `## [1.7.0] - 2026-05-28` added (Added: raster percentile/stddev stretch; Removed: contour control + `maplibre-contour` dep; Verification block).
- **OpenAPI:** `make openapi-check` exit 0 — **no drift**. The `stretch` param was already documented in v1031; only server-side behavior changed → no SDK regeneration required.
- **Version decision:** **1.7.0** (minor) — new working raster stretch capability is user-facing; the contour removal is internal (gated-off, never shipped enabled).

## Human verification needed

None — all gates and live MCP verification completed by the orchestrator.
