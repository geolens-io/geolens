---
phase: 1051
plan: 12
requirement: EMRG-01
authored: 2026-05-17
reference_shape: .planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md (v1009.1 close)
---

# Phase 1051 — Emergent Findings (EMRG-01)

**Authored:** 2026-05-17
**Plan:** 1051-12
**Reviewed against:** Plans 01-11 SUMMARY entries + per-plan deferred sections + Plan 11 § EMRG-01 Followup
**Baseline commit:** `cb46f3fa` (HEAD on 2026-05-17 before Plan 12 commit)
**Scope:** Issues surfaced during Plans 01-11 work that were not in scope for any of those plans, but were observed and explicitly punted to EMRG-01 triage.

## Summary

- **Total emergent findings:** 4
- **Fix-now:** 0
- **Defer:** 4
- **MCP-only (orchestrator owes verification):** see § Orchestrator-Deferred MCP Backlog

All 4 findings are P2 (polish / dead-code / pre-existing tech debt). No P0 / P1 emergents surfaced during the 11 user-reported-item plans — the only P-class items in v1011 are the 11 enumerated requirements (BUG-01..03, UX-01..04, RESP-01..03) plus INV-01, all of which shipped or were dispositioned in Plans 01-11.

Defer rationale across the board: per Plan 12's `<lesson_from_phase>` — "Default to deferring large items to follow-up phases rather than expanding scope mid-phase." Each defer either creates a tracking artifact (pending todo or PROJECT.md entry) or references an existing one.

## Severity Legend

| Severity | Meaning |
|---|---|
| **P0** | Blocks shipping — must fix-now before CTRL-01 gate |
| **P1** | Degraded UX or maintainability — fix-now preferred, defer with justification acceptable |
| **P2** | Polish / cleanup — default defer with tracking artifact |

## Findings

### EMRG-FN-01: BasemapSublayerEditorScene sibling Phase 1038 no-op callbacks

- **Severity:** P2
- **Scope:** `frontend/src/pages/MapBuilderPage.tsx:845-850` — 5 sibling callbacks all bearing the identical `TODO(Phase 1038): markDirty() once sublayer styling is persisted` comment: `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange`. Each is wired to a live UI control in the `BasemapSublayerEditorScene` flyout (stroke color picker, stroke width slider, casing color picker, casing width slider, min/max zoom inputs); each control accepts user input and dispatches the callback, which does nothing — no state mutation, no MapLibre style update, no dirty flag.
- **Disposition:** defer
- **Rationale:** Same shape as INV-01 (DETAIL LEVEL dead wiring removed in commit `6078b82a`). Plan 11's `<action>` explicitly scoped INV-01 to DETAIL LEVEL only and flagged these 5 sibling callbacks for EMRG-01 triage as a separate Phase 1038 dead-stub cleanup scope. Removing them within v1011 would expand Plan 12 from a single-file FINDINGS.md authoring plan into a code+test+i18n removal sweep (same shape and effort as the full Plan 11), which Plan 12's `<lesson_from_phase>` directive explicitly prohibits: "Default to deferring large items to follow-up phases rather than expanding scope mid-phase." The dead wiring has shipped since v1008 — it is not a regression introduced by v1011 and does not block CTRL-01.
- **Follow-up:** `.planning/todos/pending/2026-05-18-basemap-sublayer-phase-1038-dead-stubs.md` — documents both REMOVE (Path A, ~1 plan ~10min) and FIX (Path B, ~3-5 days) paths with recommendation to REMOVE on the same precedent as INV-01, when a future hygiene milestone or builder-polish cycle picks it up.
- **Discovered during:** Plan 11 Task 2 grep enumeration (cited in `1051-11-SUMMARY.md` § EMRG-01 Followup).

### EMRG-FN-02: Orphan `settings.toggleWidget` i18n key

- **Severity:** P2
- **Scope:** `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — `settings.toggleWidget` key (composite "{{action}} {{name}} widget" template). Replaced in v1011 Plan 07 (UX-04) by two state-specific keys (`settings.enableWidget`, `settings.disableWidget`) for better per-locale grammar. The composite key is no longer referenced in source code but the entries remain in all 4 locale files.
- **Disposition:** defer
- **Rationale:** Plan 07 SUMMARY § "deferred" explicitly tracked this as out-of-scope for the polish plan to avoid an unrelated i18n diff in a focused fix. 4 orphan entries × 4 locales = 16 total strings. Low blast radius (no runtime impact, no parity-script failure), so the deferral is appropriate. Cleanup should ride with the next i18n sweep that touches these locale files for an unrelated reason.
- **Follow-up:** Tracked in `1051-07-SUMMARY.md` § "deferred". No separate pending-todo authored — the SUMMARY entry is the durable cross-reference, and the cleanup is trivial (4 file edits, no tests) when a future i18n change touches these files.
- **Discovered during:** Plan 07 Task 2 implementation (UX-04 — i18n key swap).

### EMRG-FN-03: Pre-existing unused-eslint-disable warnings in UnifiedStackPanel.tsx

- **Severity:** P2
- **Scope:** `frontend/src/components/builder/UnifiedStackPanel.tsx:679` + `:720` — 2 unused-eslint-disable warnings reported by `npx eslint`. Pre-existing from Phase 1041 selection effects, NOT introduced by any v1011 plan diff.
- **Disposition:** defer
- **Rationale:** Per `<deviation_rules>` SCOPE BOUNDARY in the executor instructions: "Pre-existing warnings, linting errors, or failures in unrelated files are out of scope." The 2 warnings predate v1011 (Phase 1041 lineage) and were correctly not auto-fixed by Plan 05 (UX-02) per the SCOPE BOUNDARY rule. Logging here for visibility so a future cleanup sweep (or a CI hardening pass that promotes warnings → errors) does not lose the reference.
- **Follow-up:** Tracked in `1051-05-SUMMARY.md` § "Issues Encountered" (specifically the "Lint warnings (2) are pre-existing and out of scope" entry). No separate pending-todo authored — single-file 2-line removal, trivial to bundle into any future UnifiedStackPanel edit.
- **Discovered during:** Plan 05 Task 2 vitest + eslint runs (UX-02 — SublayerConfigIndicators + slider swap).

### EMRG-FN-04: SublayerConfigIndicators receives `layer={null}` for basemap sublayers

- **Severity:** P2
- **Scope:** `frontend/src/components/builder/UnifiedStackPanel.tsx` SublayerRow (Cell 6 of the basemap-sublayer grid). `BasemapSublayerInfo` carries only `id/name/visible/opacity/kind` — not the full `MapLayerResponse` shape needed by `SublayerConfigIndicators` to render badges. Plan 05 (UX-02) intentionally passed `layer={null}` per UI-SPEC §UX-02 footnote ("render nothing when no condition is met"), so basemap sublayer rows always show an empty indicator strip in v1011.
- **Disposition:** defer
- **Rationale:** Documented as "deferred enhancement opportunity (NOT a blocker)" in `1051-05-SUMMARY.md` § "Next Phase Readiness". The component itself works correctly against any `MapLayerResponse | null` — future work can swap in the live layer with zero changes to `SublayerConfigIndicators.tsx`. Plumbing the full layer through requires extending `BasemapSublayerInfo` (or passing a parallel `layer` prop) plus a touch to `BasemapGroupRow` — out of v1011 scope per REQUIREMENTS.md Out-of-Scope row 1 ("no feature work beyond the 11 polish items"). The enhancement only becomes meaningful once basemap sublayers gain user-editable filter/label config (likely a follow-up of either Phase 1038 dead-stub cleanup — see EMRG-FN-01 — or a dedicated basemap-sublayer-styling milestone).
- **Follow-up:** Tracked in `1051-05-SUMMARY.md` § "Next Phase Readiness". No separate pending-todo authored — the enhancement is dependent on either EMRG-FN-01 resolution (which unlocks user-editable basemap sublayer config) or an independent product decision to enable basemap sublayer styling.
- **Discovered during:** Plan 05 Task 2 implementation (UX-02 — SublayerConfigIndicators authoring).

## Orchestrator-Deferred MCP Backlog

Plans 01-11 each deferred Playwright MCP pre/post-fix verification to the orchestrator per the phase 1051 pattern (MCP is orchestrator-scoped per v1010.1 lesson). EMRG-01 itself surfaced no MCP-only findings — but the accumulated MCP backlog from Plans 01-11 is owed before Plan 13 (CTRL-01) close gate.

These are NOT EMRG-FN findings (they are deferred verification of in-scope plan deliverables) but are documented here so CTRL-01 has a single aggregation reference:

| Plan | MCP verification owed |
|------|-----------------------|
| 01 BUG-01 | Live MCP repro at `/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` confirming visibility toggle dispatches MapLibre layout update |
| 02 BUG-02 | Live MCP delete + sidebar-row-disappears + reload confirms persistence |
| 03 BUG-03 | Live MCP kebab → Rename → input focused on first click (no second click needed) |
| 04 UX-01 | Live MCP `getBoundingClientRect()` on caret button ≥ 24×24 px at all ≥800px viewports |
| 05 UX-02 | Live MCP screenshot of empty indicator strip for basemap sublayers + LayerEditorPanel opacity surface still reachable |
| 06 UX-03 | Live MCP basemap drag → reload round-trip persists position; `map.getStyle().layers` reflects top-vs-bottom inversion |
| 07 UX-04 | Live MCP enable/disable each widget + verify on-map appearance/disappearance |
| 08 RESP-01 | Live MCP NavigationControl top-left visible + no BuilderRail collision at 1200/1100/1024/900/800px |
| 09 RESP-02 | Live MCP MapCoordReadout pill + NavigationControl disjoint in BuilderMap + viewer-context load-bearing-offset spot-check |
| 10 RESP-03 | Live MCP Sheet overlay close-button count = 1 at 780px for all 4 editor scenes + mobile-rail Sheet + Escape-to-close preservation |
| 11 INV-01 | Live MCP BasemapSublayerEditorScene opens directly to STROKE (no DETAIL LEVEL surface); i18n switcher de/es/fr/en spot-check for no orphan-key text |

This MCP backlog is the orchestrator's responsibility per the documented Phase 1051 protocol — Plan 13 (CTRL-01) gate enforcement should drive these from the live `localhost:8080` stack.

## Acceptance

- [x] FINDINGS.md exists at canonical path
- [x] Every finding has severity, scope, disposition, rationale, follow-up, discovered-during
- [x] Fix-now count (0) matches actual per-entry dispositions
- [x] Defer count (4) matches actual per-entry dispositions
- [x] Every defer entry references a tracking artifact (pending todo for EMRG-FN-01; SUMMARY cross-reference for EMRG-FN-02, EMRG-FN-03, EMRG-FN-04)
- [x] Severity assignment present on every entry
- [x] MCP backlog from Plans 01-11 aggregated for CTRL-01 reference (NOT counted as emergent findings)

---

*Phase 1051 Plan 12 — EMRG-01 emergent-findings triage complete.*
