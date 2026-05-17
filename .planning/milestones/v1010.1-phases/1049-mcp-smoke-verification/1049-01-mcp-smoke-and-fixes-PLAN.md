---
phase: 1049-mcp-smoke-verification
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md
  - .planning/phases/1049-mcp-smoke-verification/screenshots/
autonomous: false
requirements: [SMOKE-01, SMOKE-02, SMOKE-03, SMOKE-04, SMOKE-05, SMOKE-06, SMOKE-07]
must_haves:
  truths:
    - "Docker stack rebuilt fresh from images (down -v then up -d --build); /api/health returns 200; frontend reachable at http://localhost:8080"
    - "Playwright MCP session authenticated as admin reaches the Map Builder route on a representative saved map"
    - "All 5 v1010 win surfaces (lazy-load, debounce+rAF, bulk-delete, LayerStyleEditor split, popup_config) exercised with MCP and recorded (screenshot + console + network)"
    - "SMOKE-FINDINGS.md exists with every finding classified P0/P1/P2 + disposition (shipped-inline | deferred-with-rationale | not-reproducible)"
    - "P0 findings shipped inline or escalated (no silent skips); P1 shipped inline or deferred-with-rationale; P2 deferred to tech_debt"
    - "Console-error budget respected (zero unhandled errors during normal flows) or any errors captured + classified in findings"
    - "Post-fix smoke re-run confirms no regression (skipped only if no inline fixes shipped)"
---

# Plan 01 — MCP Smoke + Findings + Fixes (Phase 1049, Wave 1)

## Objective

Run a fresh-stack interactive Playwright MCP smoke check against the five v1010 win surfaces. Produce a classified `SMOKE-FINDINGS.md` report. Ship P0/P1 fixes inline (or defer-with-rationale). Re-smoke after any fixes to confirm no regression. Close v1010.1 with a clean inline artifact.

## Wave + dependencies

Single wave. No upstream dependencies — v1010 already shipped + tagged.

## Tasks

<task id="1" type="auto" autonomous="true">
<name>Rebuild Docker stack fresh + wait for healthchecks</name>
<read_first>
- docker-compose.yml (service inventory)
- .env (admin credentials)
- backend/scripts/api-entrypoint.sh (healthcheck timing)
</read_first>
<action>
Run `docker compose down -v` to clear volumes (including postgres). Then `docker compose up -d --build` to rebuild and start all services. Poll `docker compose ps` until all five services (db, api, worker, titiler, frontend) report `(healthy)`. Verify `curl -sf http://localhost:8001/api/health` returns 200 with body containing `"status":"ok"` (port 8001 is the host-mapped backend). Verify `curl -sf http://localhost:8080/` returns 200 with HTML body containing `<title>`. If frontend healthcheck flakes (Vite cold-start), restart only `frontend` and re-check.
</action>
<acceptance_criteria>
- `docker compose ps` shows all 5 services `(healthy)`
- `curl -sf http://localhost:8001/api/health` returns 200
- `curl -sf http://localhost:8080/` returns 200
- No new ports clash (8001 / 8080 / 5434 free before `up -d` ran)
</acceptance_criteria>
<verify>
docker compose ps && curl -sf http://localhost:8001/api/health && curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:8080/
</verify>
</task>

<task id="2" type="auto" autonomous="true">
<name>Seed large builder test map via admin JWT</name>
<read_first>
- e2e/fixtures/seed-large-builder-map.ts (exports createLargeBuilderMap)
- backend/app/modules/auth/router.py (login endpoint)
- frontend/src/api/client.ts (apiFetch shape — for auth pattern)
</read_first>
<action>
Login to backend via `curl -sf -X POST http://localhost:8001/api/auth/login/ -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}'` to obtain a JWT token; extract the `access_token` field. Use that token to create a representative large saved map (≥ 30 layers) using the existing Playwright fixture programmatically OR via direct API calls to POST `/api/catalog/maps/` then add layers via PUT. If the fixture is reusable from a node script, prefer that. Record the resulting `map_id` to `.planning/phases/1049-mcp-smoke-verification/.test-map-id` (gitignored via .planning/ gate). If 30+ layer seeding takes > 2 min OR fails, fall back to a smaller seeded map (8-12 layers) and note in the findings: PERF-01 (50-layer FCP) not-exercised-this-pass — the v1010 e2e:smoke:perf already validated PERF-01..03 in headless mode.
</action>
<acceptance_criteria>
- A valid JWT token was obtained from `/api/auth/login/`
- A saved map exists with ≥ 10 layers (target: 30+)
- The map id is recorded for later MCP navigation
- `GET /api/catalog/maps/{map_id}` returns 200 with layer count matching target
</acceptance_criteria>
<verify>
test -s .planning/phases/1049-mcp-smoke-verification/.test-map-id && MAP_ID=$(cat .planning/phases/1049-mcp-smoke-verification/.test-map-id) && curl -sf "http://localhost:8001/api/catalog/maps/${MAP_ID}" -H "Authorization: Bearer $(cat .planning/phases/1049-mcp-smoke-verification/.test-jwt)" | python3 -c "import json,sys; d=json.load(sys.stdin); print('layers:', len(d.get('layers', [])))"
</verify>
</task>

<task id="3" type="auto" autonomous="true">
<name>MCP Smoke Pass A — Auth + Builder route reachable</name>
<read_first>
- frontend/src/pages/MapBuilderPage.tsx (route entry)
- frontend/src/components/auth/LoginPage.tsx OR wherever the login form lives
</read_first>
<action>
Use `mcp__playwright__browser_navigate` to `http://localhost:8080/login`. Take a screenshot baseline. Use `mcp__playwright__browser_fill_form` (or browser_type) to enter admin/admin credentials; click submit. Wait for redirect to `/dashboard` or similar. Then navigate to `/maps/{map_id}` (using the id from Task 2). Wait for the builder to load. Take a screenshot showing the unified stack with multiple layers visible. Capture `browser_console_messages` and `browser_network_requests`. Save screenshots to `.planning/phases/1049-mcp-smoke-verification/screenshots/01-A-*.png`. Record observations: any console errors, slow request, layout regression — append to running findings notes (in-memory or a draft file).
</action>
<acceptance_criteria>
- Browser reached `/maps/{map_id}` and rendered the builder (StackRow elements visible in DOM snapshot)
- 2 screenshots saved (login page baseline, builder loaded with layers)
- Console messages captured (any errors flagged)
- Network requests captured (initial bundle + map fetch)
</acceptance_criteria>
<verify>
ls .planning/phases/1049-mcp-smoke-verification/screenshots/01-A-*.png 2>/dev/null | wc -l | awk '$1 >= 2 {print "ok"; exit 0} {print "fail: <2 screenshots"; exit 1}'
</verify>
</task>

<task id="4" type="auto" autonomous="true">
<name>MCP Smoke Pass B — Lazy-load surfaces (PERF-05)</name>
<read_first>
- frontend/src/pages/MapBuilderPage.tsx (lazy imports)
- frontend/src/components/builder/SceneSpinnerFallback.tsx (Suspense fallback)
</read_first>
<action>
Still in the same MCP session from Pass A. (a) Click the ⚙ Settings rail icon — observe SceneSpinnerFallback briefly visible, then SettingsEditorScene renders. Capture network tab during the click — confirm a JS chunk fetch (Vite hashed filename). (b) Open a DEM layer (if seeded) OR click any raster layer with DEM-eligible source; if no DEM layer present, click into LayerStyleEditor and check that the basemap group editor opens — capture chunk fetch for BasemapGroupEditorScene. (c) Take screenshots before and after each scene transition. Capture all network requests filtered to `assets/*.js`. Capture console — confirm no `ChunkLoadError`. Save to `screenshots/01-B-*.png`.
</action>
<acceptance_criteria>
- At least 1 SceneSpinnerFallback occurrence captured visually OR documented why not (e.g., chunk cached after first load — note as observation)
- At least 1 JS chunk fetch captured in network log per scene transition (DEM / Settings / BasemapGroup)
- 3+ screenshots: scene-pre, scene-during, scene-post
- Console clean of ChunkLoadError (or any error logged + classified)
</acceptance_criteria>
<verify>
ls .planning/phases/1049-mcp-smoke-verification/screenshots/01-B-*.png 2>/dev/null | wc -l | awk '$1 >= 3 {print "ok"; exit 0} {print "fail"; exit 1}'
</verify>
</task>

<task id="5" type="auto" autonomous="true">
<name>MCP Smoke Pass C — Debounce + rAF coalescing (PERF-04)</name>
<read_first>
- frontend/src/components/builder/LayerStyleEditor.tsx (opacity slider)
- frontend/src/lib/builder/raf-coalesce.ts (coalesceFrame)
- frontend/src/components/builder/DataDrivenStyleEditor.tsx (color pickers)
- frontend/src/components/builder/LayerFilterEditor.tsx (filter editor)
</read_first>
<action>
Open a fill layer's LayerStyleEditor in the MCP session. (a) Drag the master opacity slider from 1.0 → 0.3 over ~1 second using `browser_drag` (or multiple `browser_evaluate` with input dispatch events on the range input). Capture screenshots at start/mid/end. Capture console + network during drag (network should be quiet — no per-pixel saves). (b) Open DataDrivenStyleEditor on a categorical column — drag a color picker; observe no visible flicker. (c) Open filter editor — type a filter expression; observe no jank. Compare network tab: confirm no save requests fire during these interactions (would indicate broken debounce). Capture screenshots to `screenshots/01-C-*.png`.
</action>
<acceptance_criteria>
- Opacity drag completes; final value reflected in slider position
- No save (`PUT /api/catalog/maps/{id}` or `PUT .../layers/{id}`) requests during the drag interaction (debounced as expected)
- No console errors during opacity drag, color drag, or filter typing
- 4+ screenshots covering all 3 sub-interactions
</acceptance_criteria>
<verify>
ls .planning/phases/1049-mcp-smoke-verification/screenshots/01-C-*.png 2>/dev/null | wc -l | awk '$1 >= 4 {print "ok"; exit 0} {print "fail"; exit 1}'
</verify>
</task>

<task id="6" type="auto" autonomous="true">
<name>MCP Smoke Pass D — Bulk-delete batching (PERF-03 + PERF-02)</name>
<read_first>
- frontend/src/components/builder/BulkActionBar.tsx
- frontend/src/components/builder/hooks/use-builder-layers.ts (handleBulkDelete)
- backend/app/modules/catalog/maps/router.py (bulk-delete endpoint)
</read_first>
<action>
Multi-select 3-5 layer rows using shift-click via `mcp__playwright__browser_click` with modifier keys (use `browser_press_key` for shift). BulkActionBar should appear. Take screenshot. Click the bulk-delete action (may be inside the overflow popover per v1009.1 SP-01). Confirm in any confirm dialog. Capture network requests during the delete — count `POST */layers/bulk-delete` requests. MUST be exactly 1. Capture toast text (success/partial). Capture aria-busy + Loader2 spinner on the delete button mid-flight (may require fast screenshot). Save to `screenshots/01-D-*.png`. If the seeded map runs out of deletable layers, re-seed via API (Task 2 helper) and retry on a fresh map.
</action>
<acceptance_criteria>
- Exactly 1 `POST */layers/bulk-delete` request in network log for the bulk delete action
- HTTP response 200 with `{deleted: [...], failed: []}` shape
- Success or partial-failure toast appeared (text captured)
- Selected layers removed from the UI after toast
- 3+ screenshots: pre-select, mid-delete (spinner), post-delete
</acceptance_criteria>
<verify>
ls .planning/phases/1049-mcp-smoke-verification/screenshots/01-D-*.png 2>/dev/null | wc -l | awk '$1 >= 3 {print "ok"; exit 0} {print "fail"; exit 1}'
</verify>
</task>

<task id="7" type="auto" autonomous="true">
<name>MCP Smoke Pass E — LayerStyleEditor split + popup_config error</name>
<read_first>
- frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx
- frontend/src/components/builder/LayerStyleEditor/index.ts
- frontend/src/components/builder/hooks/use-builder-save.ts (popup_config 422 path)
- frontend/src/i18n/locales/en/builder.json (toast keys)
</read_first>
<action>
Open a layer in LayerStyleEditor. (a) Toggle render mode via the renderer switcher (Fill → Line → Circle → Symbol — whatever the layer's geometry allows). Each toggle should swap the per-mode child editor without unmount-flicker. Capture screenshots per toggle. Verify the opacity slider remains wired (drag it again briefly post-toggle — no save fired = debounce intact). (b) Force a popup_config error: open the Popup tab (or equivalent UI), enter a placeholder referencing a non-existent column (e.g., `{{NONEXISTENT_COLUMN}}`), and click Save. Confirm the toast appears with the layer name (per `toasts.popupConfigInvalidNamed` i18n key). Take a screenshot of the toast. Clear the popup_config (back to empty / disabled), save again — confirm success toast. Save to `screenshots/01-E-*.png`.
</action>
<acceptance_criteria>
- Render mode toggle works for ≥ 2 modes; per-mode editor visible after each toggle
- No console errors during toggle
- popup_config invalid save shows toast with text containing the layer name (or generic invalid-popup text from `toasts.popupConfigInvalidNamed`)
- popup_config cleared save succeeds (success toast)
- 4+ screenshots covering both sub-flows
</acceptance_criteria>
<verify>
ls .planning/phases/1049-mcp-smoke-verification/screenshots/01-E-*.png 2>/dev/null | wc -l | awk '$1 >= 4 {print "ok"; exit 0} {print "fail"; exit 1}'
</verify>
</task>

<task id="8" type="auto" autonomous="true">
<name>Write SMOKE-FINDINGS.md with classified findings + disposition</name>
<read_first>
- All screenshots from Tasks 3-7 in `.planning/phases/1049-mcp-smoke-verification/screenshots/`
- Notes/observations from each MCP pass
</read_first>
<action>
Synthesize all observations from Passes A-E into `.planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md`. Use frontmatter `phase: 1049`, `status: in_progress | clean | issues_found`, `findings_total: N`, `severity: { p0: N, p1: M, p2: K }`. Document each finding with: ID (`SF-NN`), severity (P0/P1/P2), surface (LAZY-LOAD / DEBOUNCE / BULK-DELETE / LAYER-STYLE-SPLIT / POPUP-CONFIG / GENERAL), what-observed (one paragraph), screenshot reference, recommended fix (file:line if known), and disposition placeholder (`TBD` for now — will fill in Task 9). If ALL surfaces passed cleanly (no findings), still write the doc with `findings_total: 0` and `status: clean` — and note observations confirming each surface worked.
</action>
<acceptance_criteria>
- File exists at the configured path
- YAML frontmatter has `phase`, `status`, `findings_total`, `severity`
- Every finding has all required fields (ID, severity, surface, observed, screenshot, recommended fix)
- The 5 v1010 win surfaces are each addressed (either with findings OR with explicit "clean — observed working: <one-line>")
</acceptance_criteria>
<verify>
test -f .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md && grep -q "findings_total:" .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md
</verify>
</task>

<task id="9" type="auto" autonomous="true">
<name>Fix P0/P1 findings inline OR defer-with-rationale</name>
<read_first>
- .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md (your findings list)
- Files referenced by each finding's recommended-fix
</read_first>
<action>
For each P0 finding: ship the fix inline as a separate commit with subject `fix(1049): SF-NN <one-line>`. If fix exceeds 2hr OR introduces higher-risk regression surface, file as escalated quick task and document in SMOKE-FINDINGS.md disposition. For each P1: same default; ship inline if ≤1hr; defer-with-rationale otherwise. For each P2: defer to tech_debt with one-line rationale. Update SMOKE-FINDINGS.md per-finding `disposition` field to: `shipped-inline | escalated-as-quick-task | deferred-with-rationale | not-reproducible`. Update frontmatter `status` to `clean` if all P0 + P1 are shipped or properly deferred; else `issues_found`.
</action>
<acceptance_criteria>
- Every finding has a final disposition (no `TBD` values remaining)
- All P0 findings are either shipped-inline OR escalated-as-quick-task with rationale
- All P1 findings are either shipped-inline OR deferred-with-rationale
- All inline fixes are committed atomically with `fix(1049):` subject
- SMOKE-FINDINGS.md frontmatter `status` is finalized
</acceptance_criteria>
<verify>
grep -c "^disposition: TBD" .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md | awk '$1 == 0 {print "ok"; exit 0} {print "fail: TBD remain"; exit 1}'
</verify>
</task>

<task id="10" type="auto" autonomous="true">
<name>Post-fix smoke re-run (skipped if no inline fixes shipped)</name>
<read_first>
- .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md (which surfaces had fixes)
</read_first>
<action>
If no inline fixes shipped in Task 9, skip this task and document the skip with rationale in SMOKE-FINDINGS.md (post_fix_re_smoke: skipped — no inline fixes shipped). Otherwise: identify the surfaces touched by the inline fixes; rerun only those MCP passes (e.g., if only popup_config fix shipped, rerun Pass E). Confirm no regression. Append a "Post-fix re-smoke" section to SMOKE-FINDINGS.md with per-surface verdict.
</action>
<acceptance_criteria>
- Either: post-fix re-smoke ran for all touched surfaces and a per-surface verdict was added
- OR: skip was documented with rationale (no fixes shipped)
- SMOKE-FINDINGS.md has a "Post-fix re-smoke" section either way
</acceptance_criteria>
<verify>
grep -q "Post-fix re-smoke" .planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md
</verify>
</task>

<task id="11" type="checkpoint:human-verify">
<name>Confirm findings + dispositions — gate for milestone close</name>
<gate_type>checkpoint:human-verify</gate_type>
<what_built>
SMOKE-FINDINGS.md with classified findings and final dispositions. Any P0/P1 either shipped inline (committed) or deferred-with-rationale. Post-fix re-smoke documented if fixes shipped.
</what_built>
<how_to_verify>
Read `.planning/phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md`. Confirm:
- Findings count + severity breakdown looks right
- Each P0/P1 disposition is acceptable (no silent skips)
- Screenshots referenced are accessible at `.planning/phases/1049-mcp-smoke-verification/screenshots/`
- If any fix was shipped inline, the commits look right via `git log --oneline | head -10`
</how_to_verify>
<resume_signal>
Type "approved" to close Phase 1049 + proceed to v1010.1 milestone close (audit → complete → cleanup → tag v1010.1).
If issues: describe what needs revision and the workflow returns to Task 8 (re-edit findings) or Task 9 (re-fix).
</resume_signal>
</task>

## Done

When all tasks complete + checkpoint approved: file SUMMARY.md, mark plan complete, mark phase complete, hand off to milestone-close lifecycle.
