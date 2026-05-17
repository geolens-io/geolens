# Phase 1049: mcp-smoke-verification - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Fresh-stack interactive Playwright MCP smoke check against v1010 win surfaces produces a SMOKE-FINDINGS.md with classified findings (P0/P1/P2) for every observed gap; P0/P1 either ship inline or carry deferral rationale; final post-fix smoke confirms no regression.

**Requirements:** SMOKE-01 through SMOKE-07 (see REQUIREMENTS.md).

**Inputs (frozen by v1010):**
- v1010 archive: `.planning/milestones/v1010-ROADMAP.md`, `.planning/milestones/v1010-MILESTONE-AUDIT.md`
- v1010 Phase 1047 PERF before/after: `.planning/milestones/v1010-phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md`
- v1010 UI-REVIEW: `.planning/milestones/v1010-phases/1047-perf-and-code-quality-fixes/1047-UI-REVIEW.md`
- v1010 CLOSE evidence: `.planning/milestones/v1010-phases/1048-followups-and-closeout/1048-04-CLOSE-EVIDENCE.md`

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion — discuss phase skipped per `workflow.skip_discuss=true`.

### Hygiene-shape close (matches v1009.1 pattern)
- 1 phase, 1 plan (this phase) with sequential tasks; single batch close at end.
- Findings dispositioned inline; P0/P1 default to ship-inline; defer-with-rationale only when fix exceeds ~1hr OR introduces higher-risk regression surface.

### Fresh-stack rebuild
- `docker compose down -v` clears volumes (postgres included) — fresh DB state.
- `docker compose up -d --build` rebuilds all images.
- Wait for `/api/health` 200 before launching MCP browser.

### Test map seeding
- After fresh rebuild, the v1010 50-layer test fixture seeder (`e2e/fixtures/seed-large-builder-map.ts` exports `createLargeBuilderMap`) creates a representative map. Use it via Playwright API context with admin JWT (NOT via MCP browser — keep MCP for UI flow only).
- Alternative if seeder fails: use a smaller seeded map from `scripts/seed-thematic-demo.py` and note PERF-01 (50-layer FCP) as `not-exercised-this-pass` in findings.

### MCP browser flow
- Authenticate at `http://localhost:8080` using admin/admin (`GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD` from .env defaults).
- Navigate to `/maps/{id}` for the seeded large map.
- Drive 5 win surfaces (see specifics).
- Capture per-surface: screenshot, console messages, network requests filtered to API calls.

### Finding classification
- **P0:** breaks a user-task workflow or contradicts a v1010 milestone promise (e.g., lazy-load fallback never shows; bulk-delete sends N requests instead of 1; popup_config error toast missing).
- **P1:** noticeable UX gap or jank that v1010 should have fixed (e.g., visible repaint flicker during opacity drag, missing aria-busy on delete, debounce too aggressive).
- **P2:** cosmetic or minor (e.g., toast positioning, microcopy).

### Disposition rule
- P0: SHIP-INLINE unless effort > 2hr → escalate to new quick task with explicit rationale.
- P1: SHIP-INLINE if effort ≤ 1hr; otherwise defer-with-rationale.
- P2: defer to tech_debt unless trivial (< 15min) and bundled with a P0/P1 fix in same file.

### No new features / no design tokens
- Verification milestone; reuse v1010 + sketch-findings-geolens patterns.
- New backend endpoints out of scope.

</decisions>

<code_context>
## Existing Code Insights

**Stack rebuild:**
- `docker-compose.yml` — services: db, api, worker, titiler, frontend
- `.env` admin credentials default `admin`/`admin`

**v1010 surfaces to exercise:**
- Lazy-load (PERF-05): `frontend/src/pages/MapBuilderPage.tsx` lazy-imports DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, BasemapSublayerEditorScene, StyleJsonDialog. Trigger: open layer with DEM render mode (DEMEditorScene), click ⚙ Settings rail icon (SettingsEditorScene), open basemap group editor (BasemapGroupEditorScene).
- Debounce + rAF (PERF-04): `frontend/src/lib/builder/raf-coalesce.ts` (coalesceFrame); opacity slider at `LayerStyleEditor.tsx` (100ms debounce); color picker / filter editor (200ms debounce).
- Bulk-delete (PERF-03): backend `POST /api/maps/{map_id}/layers/bulk-delete` at `backend/app/modules/catalog/maps/router.py`; frontend `use-builder-layers.ts` handleBulkDelete; UI on `BulkActionBar.tsx`.
- LayerStyleEditor split (CODE-02/CB-07): orchestrator at `frontend/src/components/builder/LayerStyleEditor.tsx` (468 LOC); per-render-mode children under `frontend/src/components/builder/LayerStyleEditor/`.
- popup_config error (FOLLOWUP-01): `frontend/src/components/builder/hooks/use-builder-save.ts` pre-check (lines ~373-383) + backend 422 translation (lines ~449-463); i18n keys `toasts.popupConfigInvalidNamed`, `toasts.popupConfigBackendRejected`, `toasts.layerFallbackName`.

**Test map fixture:**
- `e2e/fixtures/seed-large-builder-map.ts` exports `createLargeBuilderMap(request, { name, layerCount })`.
- Seeds: random fill layers cloned from a NaturalEarth dataset. Returns `{ mapId, datasetId }`.

**Findings output location:**
- `.planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md`
- Screenshots: `.planning/phases/1049-mcp-smoke-verification/screenshots/` (gitignored — copy summarized ones to findings doc body if needed).

</code_context>

<specifics>
## Specific Ideas

- Single plan: `1049-01-mcp-smoke-and-fixes-PLAN.md` (suffix per memory entry `feedback_plan_naming_must_end_with_PLAN_md.md`).
- Tasks within the plan (sequential):
  1. **Rebuild stack** (`docker compose down -v && docker compose up -d --build`); wait for healthchecks.
  2. **Seed test map** via API + admin JWT; record map id.
  3. **MCP smoke pass A — Auth + map open** (validate route resolves, no auth gate regression).
  4. **MCP smoke pass B — Lazy-load surfaces** (DEM scene, Settings scene, Basemap group scene; capture chunk fetches + spinner).
  5. **MCP smoke pass C — Debounce + rAF** (opacity drag, color drag, filter edit — capture console + visual jank).
  6. **MCP smoke pass D — Bulk-delete batching** (select 5+ layers, delete, capture network = 1 request).
  7. **MCP smoke pass E — LayerStyleEditor split + popup_config** (toggle render modes; force invalid popup_config; capture toast + recovery).
  8. **Write SMOKE-FINDINGS.md** with P0/P1/P2 classifications + screenshots referenced.
  9. **Fix P0/P1 inline** OR file as deferred-with-rationale.
  10. **Post-fix smoke re-run** (only smoke passes touching fixed files; skip if no fixes).

- For each MCP pass: take a screenshot at the start (state baseline) and at the end (state result). Compare console errors before/after the action.

- Screenshots: store binary screenshots in `.planning/phases/1049-mcp-smoke-verification/screenshots/`; the screenshots directory is added to `.gitignore` so the binary files don't bloat the repo. Reference filenames in findings doc text.

</specifics>

<deferred>
## Deferred Ideas

- Mobile / touch verification — out of scope per REQUIREMENTS.md.
- Cross-browser sweep — Chromium MCP only.
- Re-running headless e2e:smoke:* — already green at v1010 close; this milestone adds interactive coverage.

</deferred>
