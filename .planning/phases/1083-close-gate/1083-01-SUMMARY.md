# Phase 1083-01: Close Gate — Plan Summary

**Status:** Complete
**Closed:** 2026-05-21
**Requirements satisfied:** TD-08
**Plans completed:** 1/2 (Plan 01 executor-scoped; Plan 02 orchestrator-scoped live MCP smoke)

## What shipped

This plan delivered v1018's close gate: post-v1018 pytest baseline captured,
CHANGELOG `[1.5.3] - 2026-05-21` entry written, and both local (`v1018`) and
public (`v1.5.3`) tags cut at the same commit SHA. All 7 named TD test
invocations pass together in one sequential run. Frontend gates match v1017
baseline exactly. Full close-gate green — zero deferred items for v1019
from this plan.

## Close-gate test counts

| Gate | Result |
|------|--------|
| Backend `pytest tests/` (sequential) | **3025 passed / 0 failed / 38 skipped / 0 InvalidCatalogNameError** in 539.01 s |
| 7 named TD invocations (combined) | **16 collected, 16 passed**, exit 0 (5.24 s) |
| Frontend `npx tsc -b` | exit 0 (36 pre-existing errors in 14 untouched test files — v1019 candidate, matches v1017 baseline) |
| Frontend `npx vitest run` | **2105/2105 passed** (213 test files) |
| `npm run e2e:smoke:builder` | **25 passed / 1 skipped** (matches v1017 baseline of 25/1) |
| CHANGELOG `[1.5.3]` | Written and committed (`d1b76061`) |

### Frontend `npx tsc -b` note

`tsc -b` exits 0 (build succeeds) but surfaces 36 TypeScript errors in 14
untouched test files:

- `src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx`
- `src/api/__tests__/maps.normalize.test.ts`
- `src/components/builder/__tests__/` (5 files)
- `src/components/dataset/__tests__/DatasetDetailHeader.test.tsx`
- `src/components/import/__tests__/` (2 files)
- `src/lib/__tests__/tile-utils.test.ts`
- `src/lib/builder/__tests__/basemap-style-mutation.test.ts`
- `src/pages/__tests__/RegisterPage.alreadySignedIn.test.tsx`

These are pre-existing errors deferred by user decision per REQUIREMENTS.md
"Future Requirements" section. No new errors introduced in v1018. Candidate
for a dedicated frontend hygiene milestone (v1019).

## Inline-fix bonuses note

Two additional fixes landed in v1018 outside the 8-TD scope, discovered
during Phase 1080 code review:

- **WR-01** (commit `4f9160cf`): Justified the broad-except at
  `tasks_common.py:1030` (missed by TD-01 — macOS `git grep -E` `\s`
  blind spot confirmed); fixed the layering test regex from `\s+` to
  `[ \t]+` (portable ERE, works on macOS and Linux).
- **WR-02** (commit `200b829a`): `test_verify_full_returns_ssl_context_with_verify`
  now actually calls `database_connect_args` on a verify-full settings
  object — a pre-existing defect in TD-07-touched code.

Both documented in the CHANGELOG `[1.5.3]` entry.

## Tags

| Tag | Commit SHA | Type |
|-----|-----------|------|
| `v1018` (local) | `d1b76061` | Annotated (local milestone marker) |
| `v1.5.3` (public) | `d1b76061` | Annotated (public semver) |

Both tags anchor to the same commit `d1b76061b5aa03299da87cab9da552e8f9e9754c`
(the CHANGELOG + baseline commit).

Verified: `git rev-parse v1018^{commit} == git rev-parse v1.5.3^{commit}` — SAME COMMIT.

Tags are NOT pushed — push manually per project convention:
```bash
git push origin v1018 v1.5.3
```

## REQUIREMENTS.md reconciliation

TD-02 and TD-03 test-name drift reconciled. REQUIREMENTS.md names
`test_register_password_too_short` and `test_register_password_diversity` —
these test names do not exist in the codebase. The actual fixed tests are
`test_register_emits_user_register_audit` and
`test_register_disabled_does_not_emit_audit`. Cross-reference:
`.planning/audits/PYTEST-BASELINE-v1018.md` NEW-DISCOVERY table (disposition:
"Name drift — docs stale; no functional impact — same SEC-S16 fix shape
applies").

## Deferred to v1019

None — full close-gate green. Zero new failures discovered during the
sequential baseline run.

The following pre-existing v1017-deferred items are NOT in v1018 scope
and pass forward as-is:
- Frontend TS hygiene (36 errors in 14 test files) — explicitly deferred
  per REQUIREMENTS.md
- `pytest -n auto` xdist parallel-mode cap — environmental, not a regression

## Commits (this plan)

| Commit | Message | Files |
|--------|---------|-------|
| `d1b76061` | `docs(1083-01): CHANGELOG [1.5.3] + v1018 pytest baseline` | `CHANGELOG.md`, `.planning/audits/PYTEST-BASELINE-v1018.md` |

## References

- `.planning/audits/PYTEST-BASELINE-v1018.md` — full sequential baseline with
  NEW-DISCOVERY table and REQUIREMENTS.md reconciliation
- `CHANGELOG.md [1.5.3]` — release notes for v1018
- `.planning/phases/1083-close-gate/1083-CONTEXT.md` — phase scope and decisions
- `.planning/phases/1083-close-gate/1083-02-PLAN.md` — orchestrator-scoped live
  MCP smoke (Plan 02, not in executor scope)

## Self-Check: PASSED

- [x] `.planning/audits/PYTEST-BASELINE-v1018.md` exists with `milestone: v1018`, `InvalidCatalogNameError` documented, 12 TD-0[1-7] references
- [x] `CHANGELOG.md` has `[1.5.3]` entry, `[1.5.2]` still present (not clobbered), 13 TD-0[1-8] references, WR-01 and WR-02
- [x] `v1018` tag exists — `git tag --list 'v1018'` returns `v1018`
- [x] `v1.5.3` tag exists — `git tag --list 'v1.5.3'` returns `v1.5.3`
- [x] Both tags at same commit SHA `d1b76061b5aa03299da87cab9da552e8f9e9754c`
- [x] `1083-01-SUMMARY.md` exists with 113 lines (>= 30), TD-08 present
- [x] Commits `d1b76061` (CHANGELOG+baseline) and `be6263a9` (SUMMARY) exist in git log
