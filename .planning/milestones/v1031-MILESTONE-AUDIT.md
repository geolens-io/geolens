---
milestone: v1031
milestone_name: Builder Render-Mode & Share Polish
audited: 2026-05-28T18:10:00Z
status: tech_debt
scores:
  requirements: 8/9
  phases: 4/4
  integration: 12/12
  flows: 4/4
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1140-raster-terrain-editor-controls
    items:
      - "EDITOR-DEM-04 (contour-line overlay) DEFERRED → v1032 (user-approved scope decision, 2026-05-28 live close-gate). maplibre-contour worker emits ~28 MapLibre error events on enable; addProtocol bug fixed (716b1927) but worker/isoline tile integration needs hardening. UI gated off via CONTOUR_CONTROL_ENABLED=false; contour-sync.ts + 5 unit tests retained dormant. Re-enable = flip one boolean + un-skip 5 tests. Integration check confirms the dormant gate is clean (syncContourLayer no-ops when _contour-enabled absent; UI block never rendered)."
  - phase: REQUIREMENTS.md
    items:
      - "Traceability table (line 67) lists EDITOR-DEM-04 as 'Complete' while the requirement marker (line 15) is '[~] DEFERRED → v1032'. Stale inconsistency — reconcile traceability status to 'Deferred' for accuracy."
  - phase: nyquist-validation
    items:
      - "VALIDATION.md docs left in draft: 1140 nyquist_compliant=false, 1142 wave_0_complete=false; 1141 + 1143 have no VALIDATION.md. Non-blocking — actual coverage is strong (vitest 2599/2599, pytest 181/181, e2e:smoke:builder 26/26). Discovery-only; never auto-runs validate-phase."
  - phase: standing-blocker
    items:
      - "CI-01-v1030 (carry-forward from v1023): GH Actions billing must be resolved by operator at the org billing settings before the pytest-parallel-isolation CI gate can live-verify GREEN. Explicitly OUT of v1031 feature scope; standing ops blocker, unblock independently of milestone."
nyquist:
  compliant_phases: []
  partial_phases: ["1140", "1142"]
  missing_phases: ["1141", "1143"]
  overall: partial
---

# v1031 Builder Render-Mode & Share Polish — Milestone Audit

**Audited:** 2026-05-28
**Status:** `tech_debt` — all critical functionality delivered and verified; one requirement (EDITOR-DEM-04) deliberately deferred to v1032 by user-approved scope decision.

## Summary

The milestone achieved its definition of done. The canonical close-gate (Phase 1143) is `passed`: orchestrator-driven live Playwright MCP smoke consumed all `human_needed` live-render items from Phases 1140/1141/1142, all quality gates are green, CHANGELOG is written, and OpenAPI/SDK artifacts were regenerated. Cross-phase integration is clean (12/12 links wired, 4/4 E2E flows complete, 0 broken). One requirement — EDITOR-DEM-04 (contour overlay) — was deferred to v1032 mid-close-gate after the `maplibre-contour` worker proved unstable on enable; its code and tests are retained dormant behind a single boolean.

## Requirements Coverage (3-source cross-reference)

| Requirement | Phase | VERIFICATION | REQUIREMENTS.md | Final Status |
|-------------|-------|--------------|-----------------|--------------|
| EDITOR-FILL-01 | 1141 | human_needed → consumed by 1143 QA-01 | `[x]` | **Satisfied** |
| EDITOR-DEM-04 | 1140 | logic-verified; live render deferred | `[~]` DEFERRED → v1032 | **Deferred** (not a failure-gap) |
| EDITOR-DEM-05 | 1140 | human_needed → consumed by 1143 QA-01 | `[x]` | **Satisfied** |
| EDITOR-RASTER-COLORMAP | 1140 | human_needed → consumed by 1143 QA-01 | `[x]` | **Satisfied** |
| SHARE-08 | 1142 | human_needed → consumed by 1143 QA-01 | `[x]` | **Satisfied** |
| SHARE-10 | 1142 | passed (9/9) | `[x]` | **Satisfied** |
| QA-01 | 1143 | passed | `[x]` | **Satisfied** |
| QA-02 | 1143 | passed | `[x]` | **Satisfied** |
| QA-03 | 1143 | passed | `[x]` | **Satisfied** |

**Score: 8/9 satisfied, 1/9 deferred (user-approved).** Zero unsatisfied, zero orphaned. No FAIL-gate trigger — EDITOR-DEM-04 is a documented deferral (`[~]`), not an unverified/broken requirement.

## Phase Verification Roll-up

| Phase | Status | Score | Notes |
|-------|--------|-------|-------|
| 1140 Raster & Terrain Editor Controls | human_needed → closed by 1143 | 4/4 | Live render of contour/hypso/colormap deferred to 1143 close-gate (per design) |
| 1141 Fill-Pattern Editor Control | human_needed → closed by 1143 | 3/4 +1 | Live fill-pattern render deferred to 1143 close-gate (per design) |
| 1142 OG-Image Social Cards & SharePanel Typography | human_needed → closed by 1143 | 9/9 | OpenAPI/SDK refresh deferred to 1143 (per design); live /card + og-image deferred to 1143 |
| 1143 Quality Sweep & Playwright Close-Gate | **passed** | — | Consumed all upstream human_needed items; gates green; EDITOR-DEM-04 deferred |

All 4 phases have VERIFICATION.md. The `human_needed` statuses on 1140/1141/1142 were the explicit, by-design deferral of live-WebGL render checks to the Phase 1143 orchestrator-driven Playwright MCP close-gate, which `passed`.

## Cross-Phase Integration (gsd-integration-checker — CLEAN)

- **12/12 cross-phase links verified**, 0 orphaned, 0 missing.
- **4/4 E2E flows complete**, 0 broken:
  1. Edit layer style → save → reload reflects it
  2. Save map → og-image uploaded (PUT) → `/card` route serves absolute `og:image` URL
  3. Raster colormap selection → tile URL param → backend proxy allowlist → Titiler render
  4. Fill-pattern apply/clear via FillPatternPicker → fill-adapter owned-paint sync
- **Auth correct:** PUT `/maps/{id}/og-image/` owner-only (`require_permission("edit_metadata")` + `check_map_ownership`); GET og-image + `/card` public-by-design with 404 on non-public maps.
- **Migration 0024** chains cleanly from `0023_geolens_readonly_role`.
- **EDITOR-DEM-04 dormant gate is clean:** `syncContourLayer` is still imported/called from `map-sync.ts:919` but `contour-sync.ts` returns early (no-op + cleanup) when `_contour-enabled` is absent; the UI block is `{CONTOUR_CONTROL_ENABLED && ...}` and never renders. No half-wired path that could throw.

## Quality Gates (from Phase 1143 close-gate)

- Frontend typecheck: 0 errors
- Frontend lint: 0
- Frontend vitest: 2599/2599 (DEMEditorScene contour gate: 41 pass / 5 skip dormant)
- Backend pytest: 181/181 (incl. 2 BLOCKING og-image security tests)
- e2e:smoke:builder: 26/26
- i18n parity (en/de/es/fr): 2/2
- `make openapi-check` + `make sdks-check`: green
- No `@vercel/og` / `satori` added (STACK do-not-add list respected)

## Nyquist Coverage (discovery-only, non-blocking)

| Phase | VALIDATION.md | nyquist_compliant | Classification |
|-------|---------------|-------------------|----------------|
| 1140 | exists (draft) | false | PARTIAL |
| 1141 | missing | — | MISSING |
| 1142 | exists (draft) | true (wave_0 incomplete) | PARTIAL |
| 1143 | missing | — | MISSING |

The VALIDATION.md drafts were never finalized, but the underlying test coverage is strong and the close-gate verified behavior live. Optional: `/gsd:validate-phase 1140` / `1141` / `1143` if formal Nyquist artifacts are desired — not required to complete the milestone.

## Tech Debt / Deferred Items

1. **EDITOR-DEM-04 → v1032** (user-approved). Contour overlay gated off; code + 5 unit tests dormant; re-enable = one boolean + un-skip 5 tests. Root cause: `maplibre-contour` worker/isoline tile integration emits ~28 MapLibre error events on enable.
2. **REQUIREMENTS.md traceability inconsistency.** ~~Line 67 says EDITOR-DEM-04 "Complete"; line 15 says `[~] DEFERRED`.~~ **RESOLVED at audit (2026-05-28)** — traceability row reconciled to "Deferred → v1032" + coverage note added.
3. **Nyquist VALIDATION.md drafts** unfinalized (1140/1142) / missing (1141/1143). Non-blocking.
4. **CI-01-v1030 standing blocker** (carry-forward). GH Actions org billing — operator ops task, out of feature scope.

## Verdict

`tech_debt` — milestone delivered (8/9 requirements; close-gate passed; integration clean). The single deferred requirement (EDITOR-DEM-04) was a conscious, documented, user-approved scope decision with a trivial re-enable path. Safe to complete the milestone, carrying the deferred contour control and the listed debt items forward to v1032.

---

_Audited by Claude (gsd-audit-milestone orchestrator) — 2026-05-28_
