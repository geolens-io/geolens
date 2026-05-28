---
milestone: v1032
milestone_name: Builder Carry-Forward Resolution
audited: 2026-05-28T22:35:00Z
status: tech_debt
scores:
  requirements: 7/7
  phases: 4/4
  integration: 7/7
  flows: 2/2
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1146-raster-stretch-stats
    items:
      - "Stretch is a no-op when the colormap is left at the default 'gray' — buildColormapTileUrl (raster-adapter.ts) only forwards stretch= alongside a non-gray colormap. The RasterEditor shows the stretch control regardless. A user selecting Percentile/Stddev on the gray colormap sees no change. PRE-EXISTING coupling (not a v1032 regression); RASTER-STRETCH-01/02 ('selecting percentile/stddev computes a rescale') are satisfied for the intended single-band colormap-display use case. Refinement: decouple stretch from colormap so it applies to grayscale too, or gate the control on a non-gray colormap. Logged as Future RASTER-STRETCH-UI-02."
  - phase: nyquist-validation
    items:
      - "No VALIDATION.md for any phase (1144-1147) — Nyquist formal artifacts intentionally skipped per REQUIREMENTS.md Out of Scope. Non-blocking: coverage is strong (full vitest 2577/2577, backend raster/tile 84 pass/2 skip, e2e:smoke:builder 26/26, orchestrator live MCP). Discovery-only."
  - phase: 1146-raster-stretch-stats
    items:
      - "No non-DEM single-band raster is seeded, so UI-driven stretch could only be live-verified via a reversible is_dem=false DB toggle (used + reverted in Phase 1146). If a non-DEM single-band COG is added later, spot-check the stretch UI flow end-to-end."
nyquist:
  compliant_phases: []
  partial_phases: []
  missing_phases: ["1144", "1145", "1146", "1147"]
  overall: missing
---

# v1032 Builder Carry-Forward Resolution — Milestone Audit

**Audited:** 2026-05-28
**Status:** `tech_debt` — all 7 requirements delivered and verified; no blockers; a few minor deferred items noted.

## Summary

v1032 closed the v1031 carry-forward tail in 4 phases (1144-1147). The contour control was **cut** (spike-first proved `maplibre-contour@0.1.0` is incompatible with maplibre-gl 5.x with no upstream fix), and single-band raster `percentile`/`stddev` stretch was **implemented** via Titiler `/cog/statistics`. Cross-phase integration is clean (7/7 wired, 0 orphaned, 2/2 E2E flows complete). The close-gate passed all quality gates plus orchestrator-driven live Playwright MCP verification.

## Requirements Coverage (3-source cross-reference)

| Requirement | Phase | VERIFICATION | REQUIREMENTS.md | Integration | Final |
|-------------|-------|--------------|-----------------|-------------|-------|
| CONTOUR-01 | 1144 | passed | `[x]` | WIRED | **Satisfied** |
| CONTOUR-02 | 1145 | passed | `[x]` | WIRED (clean cut) | **Satisfied** |
| RASTER-STRETCH-01 | 1146 | passed | `[x]` | WIRED | **Satisfied** |
| RASTER-STRETCH-02 | 1146 | passed | `[x]` | WIRED | **Satisfied** |
| QA-01 | 1147 | passed | `[x]` | WIRED | **Satisfied** |
| QA-02 | 1147 | passed | `[x]` | WIRED | **Satisfied** |
| QA-03 | 1147 | passed | `[x]` | WIRED | **Satisfied** |

**Score: 7/7 satisfied, 0 unsatisfied, 0 orphaned.** No FAIL-gate trigger.

## Phase Verification Roll-up

| Phase | Status | Notes |
|-------|--------|-------|
| 1144 Contour Spike | passed | Audit-only; reproduced 28-error burst, root-caused, recommended CUT |
| 1145 Contour Disposition | passed | Clean cut (dep + module + call site + flag/gate + dead enum + i18n + 5 tests); live-verified |
| 1146 Raster Stretch Stats | passed | percentile/stddev via Titiler /statistics (cached); live tile-render diff |
| 1147 Close Gate | passed | All gates green; CHANGELOG [1.7.0]; openapi no-drift |

All 4 phases have VERIFICATION.md + SUMMARY.md.

## Cross-Phase Integration (gsd-integration-checker — CLEAN)

- **7/7 requirement integration paths WIRED**, 0 orphaned, 0 missing.
- **2/2 E2E flows complete:**
  1. Select percentile/stddev stretch → `buildColormapTileUrl` forwards `stretch=` → `raster_tile_proxy` computes stats-based rescale via Titiler → render.
  2. DEM editor in hillshade/terrain renders **no contour control**; hypsometric tint + hillshade controls intact; no broken imports.
- **Contour cut verified complete** — zero live references to any deleted symbol (`syncContourLayer`, `contour-sync`, `CONTOUR_CONTROL_ENABLED`, `maplibre-contour`, `relief-contour`, `_contour-`); only test regression-pin labels + an audit-ref comment remain.
- **Color-relief (hypsometric tint) preserved** — `syncColorReliefLayer` import + call intact in `map-sync.ts` (not collateral-damaged by the cut).

## Quality Gates (Phase 1147)

- Frontend typecheck: 0 · lint: 0 errors (1 pre-existing warning) · vitest: **2577/2577** · i18n parity: 2/2
- Backend pytest (raster/tile): 84 pass / 2 skip
- `e2e:smoke:builder`: **26/26**
- `make openapi-check`: no drift (no SDK regeneration needed — `stretch` param pre-dated this milestone)
- Live Playwright MCP (orchestrator): contour absent + 0 console errors; stretch tiles render distinctly (minmax 859 B / percentile 25 KB / stddev 27 KB)

## Tech Debt / Deferred Items

1. **Stretch ↔ gray-colormap coupling** (pre-existing): stretch is a no-op when colormap = gray. Core requirements satisfied; refinement logged as Future RASTER-STRETCH-UI-02.
2. **Nyquist VALIDATION.md** missing for all 4 phases — intentionally skipped (REQUIREMENTS.md Out of Scope); coverage strong.
3. **No non-DEM single-band raster seeded** — live UI stretch exercised via a reversible `is_dem` toggle; spot-check if such a dataset is added.

## Verdict

`tech_debt` — milestone delivered (7/7 requirements; close-gate passed; integration clean). The deferred items are minor (one pre-existing UX coupling + optional docs + a test-data gap). Safe to complete and tag `v1032` (local), carrying the listed debt forward.

---

_Audited by Claude (gsd-audit-milestone orchestrator) — 2026-05-28_
