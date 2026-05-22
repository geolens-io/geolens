---
gsd_state_version: 1.0
milestone: v1020
milestone_name: Fixture Isolation
status: planning
last_updated: "2026-05-22T13:42:23.500Z"
last_activity: 2026-05-22
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-22 — Milestone v1020 started

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1084 — Frontend Hygiene Tail (first phase of v1019)

## Last Shipped Milestone

**Version:** v1019 Hygiene Tail — v1018 Frontend + xdist + Process
**Shipped:** 2026-05-22
**Phases:** 1084-1086 (3 phases, 7 plans, 6/6 reqs)
**Tag:** `v1019` (local) + `v1.5.4` (public) — pending orchestrator tag-cut after MCP smoke 5/5
**Close-gate doc:** `.planning/phases/1086-process-tightening-close-gate/1086-02-CLOSE-GATE.md`

**Previous:** v1018 Hygiene — v1017 Tech-Debt Tail (shipped 2026-05-21, public tag `v1.5.3` at `d1b76061`, archive `.planning/milestones/v1018-ROADMAP.md`)

## Phase Plan (v1019)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1084 | Frontend Hygiene Tail (TS errors + /maps/new 422s + /api/api/ prefix) | TD-09, TD-11, TD-12 | — |
| 1085 | pytest -n auto Stabilization (xdist spike + chosen fix) | TD-10 | 1084 |
| 1086 | Process Tightening + Close Gate (retro + skill update + TD-07 runtime rebuild + tags) | TD-13, TD-14 | 1084, 1085 |

**Coverage:** 6/6 requirements mapped — no orphans.

## Accumulated Context

### Decisions

- **2026-05-22 (v1019 roadmap):** Phase 1084 groups TD-09 + TD-11 + TD-12 — all three are frontend-only, zero backend dependency. TD-09 is pure typecheck; TD-11 and TD-12 are console-noise suppressions verified by Playwright MCP network log. Running them in one phase lets 1085 start from a clean joint frontend+backend baseline.
- **2026-05-22 (v1019 roadmap):** Phase 1085 is spike-first per REQUIREMENTS.md mandate (TD-10): Plan 1085-01 commits PYTEST-XDIST-SPIKE-v1019.md with measured numbers before any fix lands; Plan 1085-02 implements whichever of the three fix shapes (pool sizing / max_connections bump / cap -n) the evidence supports.
- **2026-05-22 (v1019 roadmap):** Phase 1086 bundles TD-13 (process tightening: retro + 3 global GSD skill file updates) + TD-14 (TD-07 runtime symmetry probe via container rebuild) into the close gate — both are low-risk, non-code-change deliverables that belong at close rather than disrupting earlier phases.
- **2026-05-22 (v1019 roadmap):** Public tag target `v1.5.4` (patch) — hygiene only; no user-facing features, no migrations, no schema changes.
- **2026-05-22 (v1019 roadmap):** No fresh /sec-audit or /ingest-audit needed — v1016 ran both clean; v1018 audit verdict PASSED; v1019 is hygiene-only.
- **2026-05-22 (v1019 roadmap):** Close-gate pytest target is 3025+ / 0 failures (sequential), matching v1018 close baseline. xdist fix (1085) must not degrade sequential mode.

### Pending Todos

None at roadmap time. All 6 TD items are dispositioned in REQUIREMENTS.md and mapped to phases.

### Blockers/Concerns

None — v1019 roadmap is complete and ready for plan-phase.

## Session Continuity

Last session: 2026-05-22T03:45:30.763Z
Stopped at: Roadmap defined; ready for /gsd:plan-phase 1084
Resume file: None

## Operator Next Steps

- Run `/gsd:plan-phase 1084` to begin Phase 1084: Frontend Hygiene Tail

## Deferred Items

Carried into v1019 from v1018 close (2026-05-21):

- **TD-09** — 36 pre-existing TS errors across 14 frontend test files — deferred at v1018 close-gate per user decision
- **TD-10** — `pytest -n auto` 16-worker xdist cascade — deferred at v1018 close-gate (environmental cap risk)
- **TD-11** — `/maps/new` 422 console-noise (2 spurious requests before Create dialog short-circuit) — deferred at v1018 close-gate
- **TD-12** — `/api/api/` double-prefix on quicklook proxy endpoints — deferred at v1018 close-gate
- **TD-13** — Process tightening: REQ authoring node-ID pinning + executor SUMMARY checkbox flip — surfaced by v1018 docs/code drift bugs
- **TD-14** — TD-07 runtime symmetry: verify `ssl=False` baked into deployed api/worker images (v1018 Phase 1080-02 fix predated the running stack at audit time)
