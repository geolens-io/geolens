---
slug: builder-qa-smoke
quick_id: 260530-c5k
date: 2026-05-30
type: qa-smoke
driver: orchestrator-live-mcp
---

# Map Builder QA Smoke Pass (live Playwright MCP)

Thorough orchestrator-driven QA pass of the Map Builder against the 4 current maps.
Subagents lack `mcp__playwright__*` access — orchestrator drives all live MCP directly
(see memory: playwright-mcp-orchestrator-only).

## Test matrix (current maps)

| id | name | vis | layers | why |
|----|------|-----|--------|-----|
| 98f89306 | v1034 Raster Stretch QA | private | 2 | raster stretch/colormap — highest regression risk (silently broken v1031→v1033) |
| c39be324 | Adirondack High Peaks — Terrain & Trails | public | 5 | vector+raster+DEM marketing map |
| 8dd6a129 | Adirondack High Peaks — 3D Relief | private | 9 | most complex; terrain enabled |
| 75d86487 | test map | private | 0 | empty-state edge case |

## QA dimensions

1. **Builder entry / map load** — each map opens, renders, no console errors
2. **Configuration editing** — map settings: name, description, visibility, basemap, default view, ⚙ Settings flyout
3. **Layer editing** — open LayerEditorPanel per render mode (raster stretch/colormap, fill, line, circle); tweak paint and confirm live map updates
4. **Save** — Cmd/Ctrl+S + save button; **critical: set→save→reload round-trip** (not just in-session) per memory; verify builder-private `_`-paint keys (colormap/stretch/pmin) survive
5. **Layer stack ops** — visibility toggle, drag reorder, basemap-as-group, add-from-catalog, remove/bulk-delete
6. **Console/network** — monitor console + 4xx/5xx throughout; distinguish JWT expiry (re-login) from real regressions

## Method

Drive http://localhost:8080 via Playwright MCP. Login admin/admin (form). Snapshot → act → verify
map render + console + save round-trip. Record findings in FINDINGS.md with severity. Fix any
BLOCKER/MAJOR inline; file the rest.

## Deliverable

FINDINGS.md with per-map results, severity-classified issues, and round-trip evidence.
