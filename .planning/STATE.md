---
gsd_state_version: 1.0
milestone: v1010.2
milestone_name: Builder Smoke Carryover
status: executing
stopped_at: Completed 1050-04-PLAN.md
last_updated: "2026-05-17T15:50:00.000Z"
last_activity: 2026-05-17
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 6
  completed_plans: 3
  percent: 0
---

# State

## Current Position

Phase: 1050 (builder-smoke-carryover) — EXECUTING
Plan: 4 of 6
Status: Ready to execute
Last activity: 2026-05-17

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — opened milestone v1010.2 Builder Smoke Carryover)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1050 — builder-smoke-carryover

## Last Shipped Milestone

**Version:** v1010.1 Live Playwright MCP Smoke
**Shipped:** 2026-05-17
**Phases:** 1049 (1 phase, 1 plan, 7/7 SMOKE-0X reqs)
**Tag:** v1010.1 (local)
**Archive:** `.planning/milestones/v1010.1-ROADMAP.md`

## Accumulated Context

### Decisions

- **v1010.2 is a hygiene-close milestone.** Single phase (1050), 6 sequential plans (5 SF closures + 1 CTRL-01 close gate). Mirrors v1009.1 Phase 1045 and v1010.1 Phase 1049 shape per `feedback_hygiene_milestone_pattern.md`.
- **Phase numbering continues at 1050.** v1010.1 ended at Phase 1049.
- **Plan 01 (SMOKE-08 / SF-04) is the largest scope** — only P1 in the milestone; touches `use-builder-layers.ts`, `swapLayerOnMap`, `removeSource`, cluster-source override, and tile-token signing. Migration may be needed if source-id keying contract changes.
- **Plans 02-05 are P2 polish noise closures** from v1010.1 SF-05..08 — small surface-area fixes.
- **Plan 06 (CTRL-01) is the close gate** — typecheck / vitest / e2e:smoke:builder / Playwright MCP re-verify of all 5 SF surfaces against fresh stack. CHANGELOG `[Unreleased]` note lives here, not as a separate plan.
- **Out of scope:** SP-03 / M-02 (fresh-add maplibre sync race, v1009.1 escalation, predates v1010.1); SP-07 backend `has_quicklook` predicate; SP-12 representative-fraction pane (new feature); any new feature work.
- [Phase ?]: 1050-02: Copied use-quicklook.ts:67-74 useEffect cleanup verbatim to use-map-thumbnail.ts; revoke fires on data change AND unmount; closes SF-05.
- [Phase ?]: 1050-03: SF-06 anonymous probes closed — useSavedSearches gated on !!token (use-saved-searches.ts:13); useAIStatus consumer-side gated on { enabled: !!token && isAdmin } (AIStatusCard.tsx:22, SettingsAITab.tsx:50). Hook signature use-admin.ts:186 unchanged per caller-controlled contract.
- [Phase 1050-04]: SF-07 double-PUT closed — Fix Option C (module-level `autoCapturedMapIds: Set<string>` guard in use-builder-save.ts:142). Root cause: Vite-dev StrictMode unmounts/remounts the hook, the per-instance `thumbCaptured` ref resets to false, and the module-level `pendingCaptures` Map was already cleared by the first capture's setTimeout — so the second hook instance fires a second PUT. The new module-level guard survives hook remount. 3 new tests (1259 lines total in use-builder-save.test.ts).

### Pending Todos

None at roadmap creation.

### Blockers/Concerns

None at roadmap creation. Source-of-scope (v1010.1 SMOKE-FINDINGS.md SF-04..08) has root cause + recommended fix already documented for each item.

## Session Continuity

Last session: 2026-05-17T15:50:00.000Z
Stopped at: Completed 1050-04-PLAN.md
Resume file: None

## Operator Next Steps

- Plan Phase 1050: `/gsd:plan-phase 1050`
- After planning: execute plans 01..05 sequentially (one per SF carryover), then run Plan 06 CTRL-01 batch gate.
