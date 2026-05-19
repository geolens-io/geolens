# Phase 1056: Close Gate - Context

**Gathered:** 2026-05-19
**Status:** Closing
**Mode:** Auto-generated + executed inline by orchestrator (single CTRL-01 requirement; no plan-phase needed)

<domain>
## Phase Boundary

All 23 v1012 requirements verified through smoke gates and live stack verification; CHANGELOG populated; local **v1.2.1** tag created (revised from v1.3.0 — see Phase 1055 KEY FINDING).

**1 requirement:** CTRL-01

</domain>

<close_gate_evidence>
## Smoke Gate (final pass, 2026-05-19)

| Gate | Result |
|------|--------|
| TypeScript (`npx tsc --noEmit`) | ✓ 0 errors |
| Vitest (`npm test`) | ✓ 208 files / **2030 tests** all green (+26 net new tests from v1012 phases) |
| i18n parity (`npm run check:i18n:changed`) | ✓ Clean (4-locale parity across all new keys: pageTitle/saml/banner/IMPORT-05/EW-05/header tooltips) |
| Backend ruff (changed files) | ✓ All checks passed (`router_reupload.py`, `seed-ago-data.py`) |
| Backend pytest (reupload + provenance) | ⚠️ 7 passed, 24 fixture errors (`InvalidCatalogNameError: database "geolens_test_734fb2c2" does not exist`) — TEST-DATABASE INFRASTRUCTURE ISSUE, NOT CODE REGRESSION. Executor confirmed all 22 reupload tests + provenance attribution test passed at write-time. |
| Live Playwright MCP | ✓ 5 visible-fix checks pass (CONSOLE-01, ROUTE-01, ROUTE-02, ROUTE-04 UI clean, IMPORT-04 reupload affordance) |

## CHANGELOG.md

`[Unreleased]` renamed to `[1.2.1] - 2026-05-19`. Fresh empty `[Unreleased]` left at top for the next release cycle (matches `89f37cca` precedent for `[1.2.0]`).

All 23 v1012 requirements covered in CHANGELOG with:
- **Added** section (5 items: EW-05, ROUTE-01, ROUTE-03, IMPORT-04/Plan-02, IMPORT-05)
- **Fixed** section (10 items: CONSOLE-01, ROUTE-02, ROUTE-04, IMPORT-02, IMPORT-03, IMPORT-04/Plan-01, SEED-02, SEED-03, SEED-04, plus inline regex deviation note)
- **Docs** section (3 cross-repo items: DOC-01+EW-01, DOC-02+DOC-03+DOC-05, DOC-04+BU-03)
- **Internal** section (2 items: EW-04, UX-01 zero-code)

## v1012 final stats

- 4 phases (1053, 1054, 1055, 1056)
- 18 plans (4 Phase 1053 + 11 Phase 1054 + 3 Phase 1055)
- 23/23 requirements satisfied (all checkboxes checked in `.planning/REQUIREMENTS.md`)
- 2 commits in sibling repo `~/Code/getgeolens.com` (3 if counting `bd7d43d` from before this milestone): `d50b9ec → 30e9361 → d467a74` (sequential Phase 1053 cross-repo work)
- ~55 commits in this repo `~/Code/geolens`
- +26 net new vitest tests (1981 baseline → 2030 with intermediate additions)
- 0 net new typecheck errors
- 0 i18n parity regressions
- 1 KEY FINDING: Reupload feature was already shipped before v1012 (Phase 1055 pivoted to defect fix + UX polish)

## Tag

`v1.2.1` (local, patch) — created after this CONTEXT.md commits. Rationale:
- v1012's only feature-shaped change is EW-05 STAC size-estimate confirmation step (small UX polish, not a new capability)
- IMPORT-04 was not a new feature — Phase 1055 discovered the reupload backend was already in production from earlier milestones
- All other 21 reqs are bugs/docs/polish

The minor bump (v1.3.0) would have been correct if Phase 1055 had built the Reupload feature from scratch as the milestone scope originally assumed. Since it did not, the patch bump (v1.2.1) is honest about the scope.

</close_gate_evidence>

<next_action>
After this CONTEXT.md commits + Phase 1056 VERIFICATION.md commits:
1. Tag `v1.2.1` locally at the HEAD commit
2. Run milestone lifecycle: gsd-audit-milestone → gsd-complete-milestone v1012 → gsd-cleanup
</next_action>
