# Requirements: v1010.1 Live Playwright MCP Smoke

**Defined:** 2026-05-16
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Drive a fresh-stack, interactive Playwright MCP smoke check against v1010's headline win surfaces (lazy-load, debounce/rAF coalesce, bulk-delete batching, LayerStyleEditor split, popup_config error toast) to catch anything the headless e2e specs missed; classify findings P0/P1/P2; ship P0/P1 inline or defer-with-rationale. Mirrors the v1009 → v1009.1 hygiene-close pattern.

## v1010.1 Requirements

### Verification (SMOKE)

- [ ] **SMOKE-01**: Docker stack is rebuilt fresh (`docker compose down -v && docker compose up -d --build`) and healthy before any Playwright MCP browser action; backend `/api/health` returns 200 and frontend responds at `http://localhost:8080`.
- [ ] **SMOKE-02**: An interactive Playwright MCP browser session (mcp__playwright__browser_*) authenticates as admin and reaches the Map Builder route on at least one saved map representative of v1010's perf gains (50+ layers OR a seeded large map fixture).
- [ ] **SMOKE-03**: All five v1010 win surfaces are exercised with MCP and recorded (screenshot + console + network capture per surface):
  - Lazy-load (PERF-05): trigger DEMEditorScene / SettingsEditorScene / BasemapGroupEditorScene; confirm `SceneSpinnerFallback` shows during chunk load; confirm chunk fetches in Network tab.
  - Debounce + rAF coalesce (PERF-04): drag opacity slider on a fill layer, drag color picker on a data-driven style, type into expression / filter editor; confirm no perceptible jank and no per-pixel repaints.
  - Bulk-delete batching (PERF-03): multi-select 5+ layers, trigger bulk-delete; confirm exactly **one** `POST /api/maps/{id}/layers/bulk-delete` in network; confirm Loader2 spinner + success toast.
  - LayerStyleEditor split (CODE-02/CB-07): change render mode on a layer (Fill ↔ Line ↔ Symbol etc.); confirm per-render-mode editor swaps without unmount/remount artifacts; opacity debounce still wired after split.
  - popup_config error surface (FOLLOWUP-01): save with invalid `popup_config` (placeholder referencing missing column); confirm named error toast; fix expression; confirm success toast.
- [ ] **SMOKE-04**: A `SMOKE-FINDINGS.md` document exists with every observation classified P0 / P1 / P2 (severity definitions: P0 = blocks user task or breaks v1010 promise; P1 = noticeable jank/UX gap; P2 = cosmetic). Each finding has: ID, severity, surface, what-was-observed, screenshot path, recommended fix, disposition (`shipped-inline` | `deferred-with-rationale` | `not-reproducible`).
- [ ] **SMOKE-05**: All P0 findings are shipped inline OR explicitly escalated as new quick tasks before milestone close. All P1 findings are shipped inline OR deferred-with-rationale. No silent skips.
- [ ] **SMOKE-06**: Console-error budget: zero unhandled errors during normal flows (warnings allowed if pre-existing). Console capture filed in SMOKE-FINDINGS.md.
- [ ] **SMOKE-07**: Final smoke-after-fix re-run if any P0/P1 was shipped — confirm fix didn't regress other surfaces. Skip if no inline fixes shipped.

## Out of Scope

| Feature | Reason |
|---------|--------|
| New visual vocabulary / design tokens | v1010 already shipped; reuse `sketch-findings-geolens` |
| Backend schema / API changes | Verification milestone — code surfaces only inspected |
| Mobile / touch verification | Out of scope per v1010 REQUIREMENTS.md |
| Cross-browser sweep (Firefox/Safari) | Chromium MCP only — matches normal smoke |
| Full e2e:smoke:* re-run | Already passed at v1010 close; this milestone adds *interactive* coverage |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SMOKE-01 | Phase 1049 | Pending |
| SMOKE-02 | Phase 1049 | Pending |
| SMOKE-03 | Phase 1049 | Pending |
| SMOKE-04 | Phase 1049 | Pending |
| SMOKE-05 | Phase 1049 | Pending |
| SMOKE-06 | Phase 1049 | Pending |
| SMOKE-07 | Phase 1049 | Pending |

**Coverage:** 7/7 mapped.

---
*Requirements defined: 2026-05-16*
