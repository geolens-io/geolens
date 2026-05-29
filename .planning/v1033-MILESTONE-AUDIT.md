---
milestone: v1033
milestone_name: Builder Terrain, Label & Render-Mode QA
audited: 2026-05-29
status: tech_debt
scores:
  requirements: 9/9
  phases: 4/4
  integration: 9/9
  flows: 4/4
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1149-layer-label-indicator
    items:
      - "SUMMARY/CONTEXT cite map-sync.ts:795 for the label gate; the actual gate is line 827 (line drifted). Documentation-only; predicates are functionally equivalent (both gate on label_config.column && render_mode not heatmap/symbol)."
  - phase: 1150-builder-polish-raster-cache-hygiene
    items:
      - "POLISH-02 (hillshade dual-consumer backfillBorder spam) could not be reproduced live during the audit (Map B clean; user-observed on Map A's terrain+hillshade combo). Guard + note are unit-tested and the predicate is provably inactive when terrain is off, but the raw error was not reproduced to confirm suppression end-to-end."
      - "LayerStyleEditor/types.ts retains a now-unused optional onRenderModeChange?: (mode: PointRenderMode) member after the dropdown removal. Dead but typecheck-clean (no caller); left to avoid churn across editor type consumers."
  - phase: cross-cutting
    items:
      - "band_count reports '1 band' for the RGB ortho on the get_dataset_meta path (v1032-noted, RASTER-META-01 Future). Cosmetic; colormap correctly hidden for imagery."
nyquist:
  compliant_phases: 0
  partial_phases: 0
  missing_phases: 4
  overall: "VALIDATION.md not authored for 1148-1151 (nyquist not enabled in config; coverage is strong via unit + e2e + live MCP). Non-blocking."
---

# Milestone v1033 — Audit (tech_debt)

## Verdict

**9/9 requirements satisfied · 4/4 phases complete · integration CLEAN (9/9 wired, 4/4 E2E flows) · 0 blockers.**
Graded `tech_debt` solely for minor, non-blocking residuals (a SUMMARY line-number drift, the POLISH-02 narrow-edge not reproduced live, a dead optional type member, and the pre-existing band_count cosmetic). None affect shipped behavior.

## Requirements coverage (3-source cross-reference)

All 9 REQ-IDs: VERIFICATION.md `passed` + listed in phase SUMMARY + REQUIREMENTS.md traceability `Complete`. No orphans, no unsatisfied.

| REQ | Phase | VERIFICATION | Traceability | Final |
|-----|-------|--------------|--------------|-------|
| RMODE-01 | 1148 | passed | Complete | satisfied (live MCP: getTerrain non-null on fresh load) |
| RMODE-02 | 1148 | passed | Complete | satisfied (live MCP: DEM editor shows Terrain, not Image) |
| RMODE-03 | 1148 | passed | Complete | satisfied (cast/comment removed; round-trip + guard tests) |
| LABEL-01 | 1149 | passed | Complete | satisfied (live MCP: indicator present/absent correctly) |
| POLISH-01 | 1150 | passed | Complete | satisfied (live MCP: single render-as control) |
| POLISH-02 | 1150 | passed | Complete | satisfied (guard wired both arms; Map B unaffected) |
| HYG-01 | 1150 | passed | Complete | satisfied (LRUCache; 3 backend tests) |
| QA-01 | 1151 | passed | Complete | satisfied (live MCP both maps, 0 errors) |
| QA-02 | 1151 | passed | Complete | satisfied (all code gates green) |

## Cross-phase integration (gsd-integration-checker)

6 exports connected, 0 orphaned, 0 missing. 4 E2E flows COMPLETE:
1. Open DEM map → terrain renders → DEM editor shows Terrain — COMPLETE (live, `mapA-03` evidence).
2. Label indicators on labeled rows only — COMPLETE (live).
3. Single render-as control on points — COMPLETE (live; `onRenderModeChange` + Select grep = 0).
4. Hillshade+terrain dual-consumer guard; Map B hillshade unaffected — COMPLETE (live, 0 errors).

Key wiring confirmed real (not just claimed): 1148 `RENDER_MODES`/union → `normalizeLayerStyleState` (api/maps.ts) → both `applyTerrainConfig` (map render) AND `currentMode` (editor display); 1150 `isHillshadeTerrainBound` → map-sync skip arm + MapBuilderPage→DEMEditorScene note arm.

## Close-gate evidence

- Frontend: typecheck 0 · vitest 2601/2601 (238 files) · i18n 2/2 · lint 0-err (1 pre-existing warning) · e2e:smoke:builder 26/26.
- Backend: raster+tile pytest 76 passed; `make openapi-check` exit 0 (no drift — frontend-only render_mode change).
- Live Playwright MCP (orchestrator-driven): Map A + Map B, 0 console errors each. Evidence: `.planning/audits/v1033-evidence/`.

## Disposition

CLEAR-TO-TAG. Tech debt is documented above and carried as Future requirements (RASTER-META-01, RASTER-STRETCH-03, etc. in REQUIREMENTS.md). No new closure phase required.
