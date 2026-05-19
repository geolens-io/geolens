---
gsd_state_version: 1.0
milestone: v1012
milestone_name: New-User Hardening + Reupload
status: "Roadmap defined — ready for `/gsd:plan-phase 1053`"
last_updated: "2026-05-19T22:21:32.564Z"
last_activity: 2026-05-19 — v1012 roadmap created (4 phases, 23 requirements)
progress:
  total_phases: 9
  completed_phases: 2
  total_plans: 18
  completed_plans: 16
  percent: 22
---

# State

## Current Position

Phase: 1053 (Quickstart Docs + Environment Hardening) — Not started
Plan: —
Status: Roadmap defined — ready for `/gsd:plan-phase 1053`
Last activity: 2026-05-19 — v1012 roadmap created (4 phases, 23 requirements)

```
Progress: [█████████░] 89%
```

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1012 New-User Hardening + Reupload (Phases 1053-1056, public tag v1.3.0)

## Last Shipped Milestone

**Version:** v1011.1 Builder Hygiene Carryover
**Shipped:** 2026-05-18
**Phase:** 1052 (1 phase, 7 plans, 5/5 reqs: EMRG-FN-01..04 + CTRL-01)
**Tag:** v1011.1 (local, at `567c701e`)
**Archive:** `.planning/milestones/v1011.1-ROADMAP.md`

**Previous:** v1011 Map Builder Polish & Bug Sweep (shipped 2026-05-18, tag `v1011` local, archive `.planning/milestones/v1011-ROADMAP.md`)

## v1012 Phase Map

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 1053 | Quickstart Docs + Environment Hardening | DOC-01..05, BU-03, EW-01, EW-04 | Not started |
| 1054 | Seeder + Console + Route + Import Polish | SEED-02..04, UX-01, CONSOLE-01, ROUTE-01..04, IMPORT-02, IMPORT-03, IMPORT-05, EW-05 | Not started |
| 1055 | Reupload Feature | IMPORT-04 | Not started |
| 1056 | Close Gate | CTRL-01 | Not started |

**Cross-repo:** DOC-01..05 and EW-01 (Phase 1053) require PRs in `~/Code/getgeolens.com/.planning/`. Track here for traceability; actual doc edits land in that repo.

## Accumulated Context

### Active Milestone Notes

- **3 Critical fixes already shipped on `main`** — BU-01 (`7b168bde`), BU-02 (`b4ad03d9`), SEED-01 (`787f4e43`), folded into `[1.2.0]` CHANGELOG via `89f37cca`. v1012 starts after v1.2.0 tag.
- **Source of truth for all findings:** `.planning/M001-7n8vpc-dry-run-audit.md` (gitignored, 815 lines). Each REQ-ID maps to a finding ID in that report. Executor agents should reference it during plan-phase.
- **IMPORT-04 Reupload** is the only net-new feature — needs new backend endpoint(s) + frontend UI affordance on dataset detail page. All other requirements are audit-cleanup or docs.
- **Phase 1053 cross-repo dependency:** getgeolens.com docs PRs must be coordinated. EW-04 (`.env.example`) lives in this repo.
- **v1.3.0 public tag** created at CTRL-01 close (Phase 1056). Minor bump justified by IMPORT-04 feature.

### Pending Todos

- **Recreate public repo before launch** (2026-05-05) — `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`. Outside v1012 scope.

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260518-qz1 | Tile cols= opt-in follow-ups (F1 heatmap live, F2 backend integration tests, F3 viewer end-to-end) | 2026-05-18 | 414c7ff7 | Verified | [260518-qz1-tile-cols-opt-in-followups-f1-f2-f3](./quick/260518-qz1-tile-cols-opt-in-followups-f1-f2-f3/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Feature | BasemapSublayerEditorScene Path B FIX (full sublayer styling persistence) | Out of v1011.1 scope — 3-5 day feature phase; prioritize separately if/when needed | 2026-05-18 (v1011.1 EMRG-FN-01 REMOVE close) |

## Operator Next Steps

1. Run `/gsd:plan-phase 1053` to generate the plan for Phase 1053 (Quickstart Docs + Environment Hardening). Remember Phase 1053 requires cross-repo coordination with `~/Code/getgeolens.com/.planning/` for DOC-01..05 and EW-01.
2. Optionally push the local `v1011.1` tag: `git push origin v1011.1`.
3. Optionally push the local `v1011` tag if not already pushed: `git push origin v1011`.
4. Address the Dependabot moderate vulnerability surfaced on push (alert 40 at https://github.com/geolens-io/geolens/security/dependabot/40).
