# Phase 1155: Close-Gate - Context

**Gathered:** 2026-05-29
**Status:** Ready (orchestrator-driven verification phase)
**Mode:** Auto-generated (discuss skipped)

<domain>
## Phase Boundary

The complete raster stretch/colormap feature is verified end-to-end against real data with Playwright MCP — tile URLs carry the expected params, tile output visibly differs across stretch modes, and all standard gates are green — so the milestone can be tagged.

Requirements: **VERIFY-01**, **QA-01**.
</domain>

<decisions>
## Implementation Decisions

### This is an orchestrator-driven phase — NOT delegated to a subagent
QA-01 requires live Playwright MCP, and per project memory `playwright-mcp-orchestrator-only`, gsd-executor subagents lack `mcp__playwright__*` access (they fabricate PASS/FAIL or write spec files instead). The ORCHESTRATOR runs every gate and every MCP step directly. No executor is spawned for the live verification.

### Close-gate checklist
**Automated gates (orchestrator runs):**
- `npm run typecheck` → 0 errors
- `npm run test` (vitest) → green
- `npm run test:i18n` → 2/2 parity
- `e2e:smoke:builder` → green
- focused backend raster/tile pytest → green
- `make openapi-check` → no-drift (note: 1153 added 3 query params; snapshot was regenerated in 1153 — confirm no further drift)
- **SDK regen check**: the OpenAPI snapshot changed in 1153 (3 new optional query params on the tile route). Verify whether `make sdks` / `make sdks-check` flags drift; regen if needed (Python + TS clients).

**Live Playwright MCP (orchestrator drives; admin/admin; localhost:8080):**
- VERIFY-01: single-band fixture `GRAY_50M_SR.tif` — switch stretch minmax/percentile/stddev + a non-gray colormap; confirm the emitted Titiler tile URL carries `rescale=` / `colormap_name=`; distinct tile output across modes; configurable pmin/pmax (e.g. 5/95) changes the URL + re-renders.
- QA-01: multi-band RGB ortho `adk_high_peaks_ny_orthos_3857.tif` — stretch section visible, colormap hidden, percentile produces 3 `rescale=` fragments.
- 0 console errors per surface. (Project memory: long MCP sessions can hit JWT expiry → 401 burst; re-login if so.)
</decisions>

<specifics>
## Specific Ideas
- Test data live: single-band `GRAY_50M_SR.tif` (band_count=1, is_dem=f), RGB ortho `adk_high_peaks_ny_orthos_3857.tif` (band_count=3).
- Capture Titiler tile request URLs via the MCP network panel to assert `rescale=`/`colormap_name=`/`pmin=`/`pmax=`/`sigma=` params (not merely HTTP 200).
</specifics>

<deferred>
## Deferred Ideas
None.
</deferred>
