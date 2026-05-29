---
phase: 1140
slug: raster-terrain-editor-controls
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-28
---

# Phase 1140 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest (frontend, primary) + pytest (backend, raster tile proxy param) |
| **Config file** | `frontend/vitest.config.ts` ; `backend/pytest.ini` (+ `.env.test` recipe) |
| **Quick run command** | `cd frontend && npx vitest run src/<touched editor + adapter test globs>` |
| **Full suite command** | `cd frontend && npm run test` ; backend: `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 backend/tests/<raster tile tests>` |
| **Estimated runtime** | frontend focused ~10–30s ; backend focused ~30–60s |

---

## Sampling Rate

- **After every task commit:** Run the quick focused vitest (and focused pytest if the task touched the backend tile proxy).
- **After every plan wave:** Run the full frontend vitest suite + focused backend pytest.
- **Before verification:** Full frontend vitest green; touched backend pytest green; typecheck clean.
- **Max feedback latency:** ~60 seconds (focused runs).

---

## Per-Task Verification Map

> Populated by the planner / executor as tasks are defined. Each new control gets unit coverage; the backend colormap param gets a focused pytest. One row per task across all 4 plans (9 tasks, 3 waves).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1140-01-01 | 01 | 1 | EDITOR-RASTER-COLORMAP | — | band_count threaded read-only through the layer-row join (additive, no write surface) | unit | `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 backend/tests/test_maps.py -k "layer or response" -q` | ❌ W0 | ⬜ pending |
| 1140-01-02 | 01 | 1 | EDITOR-RASTER-COLORMAP | T-1140-01 | colormap_name/stretch validated against the 8-name allowlist (Literal + frozenset) before forwarding to Titiler; out-of-set → 422, Titiler never called | unit | `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 backend/tests/test_raster_colormap_proxy.py -q` | ❌ W0 | ⬜ pending |
| 1140-01-03 | 01 | 1 | EDITOR-RASTER-COLORMAP | T-1140-02 | nginx forwards colormap_name/stretch + keys the cache on them (allowlist caps fan-out at 24×) | config | `grep -n 'is_args\$args' frontend/nginx.conf && grep -n 'arg_colormap_name' frontend/nginx.conf && docker run --rm -v "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/test.conf:ro" nginx:alpine nginx -t` | ❌ W0 | ⬜ pending |
| 1140-02-01 | 02 | 1 | EDITOR-DEM-04 | T-1140-SC | maplibre-contour registry version + repo re-verified via `npm view` before install (audit `[OK]`); STOP on mismatch | unit | `cd frontend && npx vitest run src/components/builder/__tests__/contour-sync.test.ts` | ❌ W0 | ⬜ pending |
| 1140-02-02 | 02 | 1 | EDITOR-DEM-04 | T-1140-04 | interval/weight numeric bounds clamped at the slider; safe numeric fallbacks in contour-sync | unit | `cd frontend && npx vitest run src/components/builder/__tests__/DEMEditorScene.test.tsx src/components/builder/__tests__/map-sync.raster.test.ts src/i18n/resources.test.ts && npx tsc -b --noEmit` | ❌ W0 | ⬜ pending |
| 1140-03-01 | 03 | 2 | EDITOR-DEM-05 | T-1140-05 | _hypso-ramp falls back to a known ramp for any unknown name; picker emits only curated names | unit | `cd frontend && npx vitest run src/components/builder/__tests__/color-relief-sync.test.ts` | ❌ W0 | ⬜ pending |
| 1140-03-02 | 03 | 2 | EDITOR-DEM-05 | T-1140-06 | color-relief shares the DEM source only in hillshade mode (no setTerrain contention); hillshade-gated | unit | `cd frontend && npx vitest run src/components/builder/__tests__/DEMEditorScene.test.tsx src/components/builder/__tests__/map-sync.raster.test.ts src/i18n/resources.test.ts && npx tsc -b --noEmit` | ❌ W0 | ⬜ pending |
| 1140-04-01 | 04 | 3 | EDITOR-RASTER-COLORMAP | T-1140-07 | _colormap/_stretch stay OUT of RASTER_OWNED_PAINT_PROPERTIES (never reach setPaintProperty); only mutate the tile URL | unit | `cd frontend && npx vitest run src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` | ❌ W0 | ⬜ pending |
| 1140-04-02 | 04 | 3 | EDITOR-RASTER-COLORMAP | T-1140-01 | frontend emits only curated colormap/stretch values; minmax active, percentile/stddev disabled (no silent no-op); backend allowlist is the trust boundary | unit | `cd frontend && npx vitest run src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx src/i18n/resources.test.ts && npx tsc -b --noEmit` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Frontend: new `*.test.ts(x)` stubs alongside the touched editor + adapter files (contour, hypsometric, colormap URL-building).
- [ ] Backend: focused test for the raster tile proxy `colormap_name`/`stretch` param forwarding + allowlist validation.
- [ ] Existing vitest + pytest infrastructure otherwise covers this phase — no framework install needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Tiles visually re-render with the selected colormap/stretch | EDITOR-RASTER-COLORMAP | Needs a real WebGL canvas + live Titiler tiles (headless WebGL can't paint) | Verified at the Phase 1143 close-gate via orchestrator-driven Playwright MCP on the live builder; unit tests pin the tile-URL building + param forwarding |
| Contour lines render from the DEM at the chosen interval | EDITOR-DEM-04 | Client-side contour vector tiles need a live raster-dem source + canvas | Phase 1143 Playwright MCP; unit tests pin the toggle/companion-layer add/remove + paint keys |
| Hypsometric tint banding updates on the map | EDITOR-DEM-05 | `color-relief` layer needs live DEM + canvas | Phase 1143 Playwright MCP; unit tests pin ramp→color-stops derivation |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
</content>
