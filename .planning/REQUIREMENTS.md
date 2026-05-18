# Milestone v1011.1 Requirements — Builder Hygiene Carryover

**Milestone version:** v1011.1
**Milestone name:** Builder Hygiene Carryover
**Defined:** 2026-05-18
**Goal:** Close all 4 EMRG-FN findings carried forward from v1011 Phase 1051 Plan 12 (EMRG-01 triage) — settle the Phase 1038 `BasemapSublayerEditorScene` dead-stub disposition, drop the orphan i18n key, prune the pre-existing eslint-disable noise, and explicitly close out the `SublayerConfigIndicators` null branch.

**Shape:** Hygiene milestone, single phase (likely 1052), sequential plans, single CTRL-01 close gate per `feedback_hygiene_milestone_pattern.md`. Mirrors v1009.1 Phase 1045, v1010.1 Phase 1049, v1010.2 Phase 1050, and v1011 Phase 1051.

**Execution path:** `/gsd-discuss-phase` first (to settle EMRG-FN-01 Path A vs Path B), then `/gsd-plan-phase`, then `/gsd-autonomous` or `/gsd-execute-phase`.

**Source:** v1011 Phase 1051 Plan 12 EMRG-01 triage — `.planning/milestones/v1011-phases/1051-map-builder-polish-bug-sweep/FINDINGS.md` § EMRG-FN-01..04.

---

## v1011.1 Requirements

Each item is a discrete deliverable carried forward from v1011 Phase 1051 Plan 12 EMRG-01 triage. All requirements verified via smoke gate + Playwright MCP on `http://localhost:8080` against a real stack before close.

### Phase 1038 Dead-Stub Resolution (EMRG-FN)

- [x] **EMRG-FN-01**: BasemapSublayerEditorScene Phase 1038 dead-stub callbacks are resolved via a single dispositioned path.
  - **Path A REMOVE** (mirror INV-01 precedent): delete 5 callbacks at `MapBuilderPage.tsx:845-850` (`onStrokeColorChange` / `onStrokeWidthChange` / `onCasingColorChange` / `onCasingWidthChange` / `onZoomChange`), matching props from `BasemapSublayerEditorScene` interface + signature destructure, the STROKE / CASING / ZOOM `<section>` JSX blocks, the entire `editorScene === 'basemap-sublayer'` branch in `MapBuilderPage.tsx:828-872`, 6 i18n keys × 4 locales, and vitest cases referencing the removed surfaces — add a REMOVE-disposition regression test (positive-form `queryBy*` assertion that the surface stays gone) + inline disposition comment per the INV-01 pattern.
  - **Path B FIX** (implement Phase 1038): persist `stroke_color` / `stroke_width` / `casing_color` / `casing_width` / `min_zoom` / `max_zoom` per sublayer in `MapBasemapConfig.sublayer_overrides[sublayerId]` (jsonb-additive per Phase 1051 Plan 06 UX-03 precedent — zero backend migration); wire each callback to update the corresponding field via `setBasemapConfig` (auto-marks dirty via WR-02 fix in `use-builder-layers.ts`); plumb each field through `applyBasemapConfigToMap` in `map-sync.ts:222` for live MapLibre dispatch across the basemap-preset-aware sublayer style filtering.
  - **Path decision deferred to `/gsd-discuss-phase`.** Tracking: `.planning/todos/pending/2026-05-18-basemap-sublayer-phase-1038-dead-stubs.md`.

- [ ] **EMRG-FN-02**: `settings.toggleWidget` orphan i18n key (from Phase 1051 Plan 07 UX-04) is removed from all 4 locales (`frontend/src/i18n/locales/{en,de,es,fr}/builder.json`). Trivial 4-file edit, no tests. i18n parity check passes 2/2.

- [ ] **EMRG-FN-03**: Pre-existing UnifiedStackPanel.tsx unused-eslint-disable warnings at lines 679 + 720 (from Phase 1041, SCOPE BOUNDARY-correct deferral) are removed. Single-file 2-line removal. Frontend lint passes with 0 warnings on the affected file.

- [ ] **EMRG-FN-04**: `SublayerConfigIndicators` `layer={null}` branch is explicitly closed out.
  - Auto-resolved if EMRG-FN-01 lands **Path A** (BasemapSublayerEditorScene removed → no callsite passes `layer={null}` to SublayerConfigIndicators anymore).
  - If EMRG-FN-01 lands **Path B**, add an explicit regression test asserting `SublayerConfigIndicators` safely renders nothing (or appropriate fallback) when `layer={null}`.

### Close Gate (CTRL)

- [ ] **CTRL-01**: Single batched close gate runs at end of phase:
  - `typecheck` (0 errors)
  - `vitest` (full suite green, including any new regression tests added by EMRG-FN-01 chosen path or EMRG-FN-04)
  - `e2e:smoke:builder` (≥26/26 — may grow if Path A adds REMOVE-disposition regression spec)
  - `i18n` parity (2/2)
  - Playwright MCP re-verify of any user-visible UI surface changed by EMRG-FN-01 Path A vs Path B (basemap-sublayer flyout if Path A removed it; live style mutation evidence if Path B)
  - CHANGELOG `[Unreleased]` populated with v1011.1 close notes
  - Per `feedback_review_findings_inline.md`: any code-review findings surfaced during gate get fixed inline before close, not deferred to v1011.2
  - Local `v1011.1` tag created

---

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New Map Builder features beyond the 4 carryforward items | v1011.1 is a hygiene carryforward close, not feature work — defer renderer expansion, AI capability, time-series, collaboration to dedicated milestones |
| Backend/API changes outside what EMRG-FN-01 Path B strictly requires | Path A is API-free; Path B caps at jsonb-additive `MapBasemapConfig.sublayer_overrides[sublayerId]` (zero backend migration per UX-03 precedent) |
| Refactoring `MapBuilderPage`, builder hooks, or layer-adapters except where directly required to land EMRG-FN-01 Path A or Path B | Hygiene close, not structural cleanup — avoid v1010-style code-quality audit scope |
| Other v1011 open candidates: v1.7 Marketplace unpause (Phase 40 AWS AMI), Phase 999.6 tenant scoping, Phase 999.13/14/15/16 enterprise backlog, public-repo recreate todo (2026-05-05) | Each warrants its own scoped milestone — v1011.1 is narrowly the EMRG-01 carryforward |
| New i18n keys beyond what EMRG-FN-01 Path A removal or Path B addition strictly requires | Translations added only for new visible strings introduced by chosen path; EMRG-FN-02 only removes a dead key |
| Mobile-phone optimization (<800 px portrait) | v1011 RESP-01..03 targeted tablet + narrow desktop; phone-portrait is separate scope per PROJECT.md |

---

## Traceability

All 5 v1011.1 requirements are mapped to **Phase 1052: builder-hygiene-carryover** (single hygiene phase).

| Requirement | Phase | Status |
|-------------|-------|--------|
| EMRG-FN-01 | Phase 1052 | Planning |
| EMRG-FN-02 | Phase 1052 | Planning |
| EMRG-FN-03 | Phase 1052 | Planning |
| EMRG-FN-04 | Phase 1052 | Planning |
| CTRL-01 | Phase 1052 | Planning |

**Coverage:**
- v1011.1 requirements: 5 total
- Mapped: 5/5 ✓ (100% coverage, no orphans)
- Source: v1011 Phase 1051 Plan 12 EMRG-01 triage (FINDINGS.md, 2026-05-18)
- Path decision for EMRG-FN-01: deferred to `/gsd-discuss-phase`
- Phases: 1 (Phase 1052, single hygiene phase per `feedback_hygiene_milestone_pattern.md`)
