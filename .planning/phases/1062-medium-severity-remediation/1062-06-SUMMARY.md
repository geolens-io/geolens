---
phase: 1062-medium-severity-remediation
plan: "06"
subsystem: frontend-security
tags: [eslint, security, sec-s14, localStorage, jwt, httpOnly]
dependency_graph:
  requires: []
  provides: [SEC-S14-lint-guard]
  affects: [frontend/eslint.config.js, docs-internal/audits/security-lessons.md]
tech_stack:
  added: []
  patterns:
    - ESLint no-restricted-syntax with AST selector for Literal first-arg matching
    - Regression-test files that intentionally violate lint rules (--no-inline-config pattern)
    - Per-file ESLint flat-config override for test fixture exemption
key_files:
  created:
    - frontend/src/__tests__/sec-s14-eslint-regression.ts
    - frontend/src/__tests__/sec-s14-eslint-regression.skip.ts
  modified:
    - frontend/eslint.config.js
    - frontend/package.json
    - docs-internal/audits/security-lessons.md
decisions:
  - "no-restricted-syntax selector requires arguments.0.type='Literal' — identifier and template-literal first args slip through (documented known gap, acceptable per audit framing)"
  - "Regression file uses inline eslint-disable-next-line comments so npm run lint passes for everyday workflow; --no-inline-config flag in the regression-check script overrides them"
  - "Per-file exemption on auth-store.test.ts (not a glob) to stay minimal"
  - "httpOnly-cookie migration deferred: trigger conditions are (a) an XSS sink introduced in SPA or (b) SaaS/Cloud tier with shared origin"
metrics:
  duration: ~15 minutes
  completed: "2026-05-20"
  tasks_completed: 4
  files_changed: 5
---

# Phase 1062 Plan 06: SEC-S14 localStorage Token Guard Summary

ESLint `no-restricted-syntax` rule banning `localStorage.setItem(<token|jwt|auth>, ...)` with regression-test files and httpOnly migration plan.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add ESLint no-restricted-syntax rule + per-file exemption | 68e2691e | frontend/eslint.config.js |
| 2 | Create regression-test file demonstrating the rule fires | f9db3424 | frontend/src/__tests__/sec-s14-eslint-regression.ts, frontend/package.json |
| 3 | Create safe-pattern file demonstrating no false-positives | 6768d20c | frontend/src/__tests__/sec-s14-eslint-regression.skip.ts |
| 4 | Document SEC-S14 in security-lessons.md + httpOnly migration plan | f9c1ae52 | docs-internal/audits/security-lessons.md |

## Verification Results

- `npm run lint` — 0 new errors from the new rule (existing 34 pre-existing problems unchanged)
- `npm run lint:sec-s14-regression` — exits 0; ESLint fires 4 `no-restricted-syntax` errors on regression file
- `npm run lint:sec-s14-no-false-positive` — exits 0 (9 safe patterns pass cleanly)
- `grep -c "no-restricted-syntax" frontend/eslint.config.js` — 2
- `grep -c "SEC-S14" docs-internal/audits/security-lessons.md` — 4
- `grep -c "httpOnly" docs-internal/audits/security-lessons.md` — 5

## Implementation Details

### ESLint Rule (frontend/eslint.config.js)

AST selector: `CallExpression[callee.object.name='localStorage'][callee.property.name='setItem'][arguments.0.type='Literal'][arguments.0.value=/token|jwt|auth/i]`

All existing legitimate localStorage uses pass:
- `theme-provider.tsx:70` — `localStorage.setItem(storageKey, t)` — identifier, not literal
- `use-builder-dialogs.ts:18` — `localStorage.setItem(SIDEBAR_COLLAPSED_KEY, ...)` — identifier
- `i18n.ts:114` — `window.localStorage.setItem(detectionOptions.lookupLocalStorage, ...)` — identifier
- `MapsPage.tsx:87` — `localStorage.setItem(VIEW_STORAGE_KEY, value)` — identifier

Per-file exemption: `src/stores/__tests__/auth-store.test.ts` (`rules: { 'no-restricted-syntax': 'off' }`) for zustand fixture setup that writes `'geolens-auth'` key.

### Known Gaps

Documented in both test files and security-lessons.md:
1. Identifier-as-key (`const KEY = 'token'; localStorage.setItem(KEY, ...)`) — passes
2. Template-literal-as-key (`` localStorage.setItem(`token-${id}`, ...) ``) — passes

Both acceptable per the audit framing (catch accidental regression, not motivated evasion). Closing requires a custom ESLint plugin (deferred to Phase 1063+).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- frontend/eslint.config.js — FOUND
- frontend/src/__tests__/sec-s14-eslint-regression.ts — FOUND
- frontend/src/__tests__/sec-s14-eslint-regression.skip.ts — FOUND
- docs-internal/audits/security-lessons.md — FOUND
- Commits 68e2691e, f9db3424, 6768d20c, f9c1ae52 — all present in git log
