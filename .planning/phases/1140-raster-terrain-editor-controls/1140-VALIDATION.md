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

> Populated by the planner / executor as tasks are defined. Each new control gets unit coverage; the backend colormap param gets a focused pytest.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1140-01-01 | 01 | 1 | EDITOR-RASTER-COLORMAP | T-1140-01 | colormap_name/stretch validated against allowlist before forwarding to Titiler (no arbitrary passthrough) | unit | `cd backend && uv run pytest -k colormap` | ❌ W0 | ⬜ pending |
| 1140-02-01 | 02 | 1 | EDITOR-DEM-04 | — | N/A | unit | `cd frontend && npx vitest run` | ❌ W0 | ⬜ pending |
| 1140-03-01 | 03 | 1 | EDITOR-DEM-05 | — | N/A | unit | `cd frontend && npx vitest run` | ❌ W0 | ⬜ pending |

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
