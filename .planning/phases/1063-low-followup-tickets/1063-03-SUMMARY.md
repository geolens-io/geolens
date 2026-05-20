---
phase: 1063-low-followup-tickets
plan: 03
subsystem: security
tags: [eslint, react, xss, gdal, header-injection, crlf, base64url, python, pytest]

# Dependency graph
requires:
  - phase: 1062-security-audit-2026-05-19-sec-s14
    provides: "SEC-S14 no-restricted-syntax ESLint pattern; eslint.config.js comment style"
  - phase: 1061-security-audit-2026-05-19-remediation
    provides: "SEC-S04 GDAL_HTTP_FOLLOWLOCATION=NO pattern in ogr.py env-composition block"
provides:
  - "eslint-plugin-react installed; react/no-danger:error active in eslint.config.js"
  - "_sanitize_authorization_token helper in ogr.py blocking CRLF token smuggling"
  - "SEC-FU-03 regression fixture (--no-inline-config verifiable)"
  - "6 SEC-FU-04 pytest unit tests for base64url sanitizer"
affects:
  - "1063-low-followup-tickets"

# Tech tracking
tech-stack:
  added:
    - "eslint-plugin-react@7.37.5 (devDependency)"
  patterns:
    - "react/no-danger:error lint rule with SEC-FU-XX inline comment + version detect setting"
    - "Regression fixture as .skip.tsx with inline eslint-disable; verified via --no-inline-config + inverted exit"
    - "_BASE64URL_CHARSET frozenset + _sanitize_authorization_token pure-function validator"

key-files:
  created:
    - "frontend/src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx"
  modified:
    - "frontend/eslint.config.js"
    - "frontend/package.json"
    - "frontend/package-lock.json"
    - "backend/app/processing/ingest/ogr.py"
    - "backend/tests/test_ingest_ogr_pure.py"

key-decisions:
  - "SEC-FU-03 regression fixture uses inline eslint-disable + --no-inline-config verification (same pattern as SEC-S14 in Phase 1062-06), not a .skip.tsx extension-based glob exclusion (glob **/*.{ts,tsx} matches .skip.tsx)"
  - "SEC-FU-04 sanitizer raises ValueError on empty/short tokens (<8 chars) and non-base64url characters; None passthrough preserves caller's no-token code path unchanged"
  - "_BASE64URL_CHARSET allows dots (.) for JWT segment separators (header.payload.sig) per RFC 7519"

patterns-established:
  - "ESLint regression fixture pattern for react rules: .skip.tsx suffix + inline disable + lint:sec-fu-XX-regression npm script"

requirements-completed:
  - SEC-FU-03
  - SEC-FU-04

# Metrics
duration: 18min
completed: 2026-05-20
---

# Phase 1063 Plan 03: SEC-FU-03 + SEC-FU-04 Summary

**eslint-plugin-react react/no-danger:error blocks dangerouslySetInnerHTML at lint time; GDAL Authorization bearer token sanitized to base64url charset before env-var composition, preventing CRLF header smuggling via libcurl**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-20T22:10:00Z
- **Completed:** 2026-05-20T22:28:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- SEC-FU-03: `eslint-plugin-react@7.37.5` added as devDependency; `react/no-danger: 'error'` wired in `eslint.config.js` with `plugins`, `settings.react.version: detect`, and SEC-FU-03 inline comment
- SEC-FU-03: Regression fixture `sec-fu-03-react-no-danger-regression.skip.tsx` verifiable via `npm run lint:sec-fu-03-regression` (inverted exit — succeeds only when ESLint fails on fixture)
- SEC-FU-04: `_BASE64URL_CHARSET` + `_sanitize_authorization_token` added to `ogr.py`; called immediately before `GDAL_HTTP_HEADERS` env composition; CRLF/unicode/whitespace tokens raise `ValueError` with SEC-FU-04 prefix before subprocess spawns
- SEC-FU-04: 6 pytest unit tests pass (happy-path JWT, CRLF, whitespace, unicode, empty, None passthrough); 86/86 total tests green

## Task Commits

Each task was committed atomically:

1. **Task 1: SEC-FU-03 eslint-plugin-react + react/no-danger + fixture** - `875d5654` (feat)
2. **Task 2 RED: SEC-FU-04 failing tests** - `eba6d71e` (test)
3. **Task 2 GREEN: SEC-FU-04 implementation** - `1771c636` (feat)

**Plan metadata:** (docs commit follows)

_Note: Task 2 is TDD — RED commit (test) precedes GREEN commit (feat)._

## Files Created/Modified

- `frontend/eslint.config.js` — Added `import react`, `plugins: { react }`, `settings.react.version: detect`, `react/no-danger: 'error'` with SEC-FU-03 inline comment
- `frontend/package.json` — Added `eslint-plugin-react@^7.37.5` devDependency; added `lint:sec-fu-03-regression` npm script
- `frontend/package-lock.json` — Updated lockfile for eslint-plugin-react install
- `frontend/src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx` — Regression fixture with inline disable; verify with `npm run lint:sec-fu-03-regression`
- `backend/app/processing/ingest/ogr.py` — Added `import string`, `_BASE64URL_CHARSET`, `_sanitize_authorization_token`; call site in `run_ogr2ogr_service` env block
- `backend/tests/test_ingest_ogr_pure.py` — Added `_sanitize_authorization_token` import + `TestSecFu04SanitizeAuthorizationToken` class (6 tests)

## Decisions Made

1. **Regression fixture uses inline-disable + --no-inline-config pattern**: The plan spec said `.skip.tsx` would be excluded by the `**/*.{ts,tsx}` glob, but this is incorrect — ESLint does match `.skip.tsx` files. Applied the same approach used in SEC-S14 (Phase 1062-06): inline `eslint-disable-next-line` keeps default `npm run lint` green; `npm run lint:sec-fu-03-regression` passes `--no-inline-config` so the disable is ignored and the rule fires. (Deviation Rule 1 — bug in plan's glob exclusion claim.)

2. **`_BASE64URL_CHARSET` includes dot (`.`)**: RFC 7519 JWTs are `header.payload.signature` (base64url segments separated by dots). The plan's interface definition correctly notes dot is required; the frozenset includes it.

3. **None passthrough preserved**: `token` is `None` when the calling code path has no auth token — `_sanitize_authorization_token(None)` returns `None` to let the `if token and service_type in (...)` guard work unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Regression fixture .skip.tsx exclusion claim incorrect**
- **Found during:** Task 1 (SEC-FU-03 eslint setup)
- **Issue:** Plan stated "`.skip.tsx` is NOT matched" by `**/*.{ts,tsx}` glob. This is wrong — ESLint does match `.skip.tsx` files via `**/*.tsx`. Initial fixture without inline disable caused `react/no-danger` error during `npm run lint`.
- **Fix:** Used the SEC-S14 pattern instead: inline `eslint-disable-next-line` in the fixture + `--no-inline-config` npm script for regression verification.
- **Files modified:** `frontend/src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx`, `frontend/package.json`
- **Verification:** `npm run lint` passes; `npm run lint:sec-fu-03-regression` exits 0 (confirms rule fires with `--no-inline-config`)
- **Committed in:** `875d5654` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in plan's glob exclusion claim)
**Impact on plan:** Minimal — same verification outcome, better approach. Regression fixture pattern now consistent with SEC-S14 sibling.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None — no external service configuration required. All changes are build-time (ESLint) or runtime guards (Python).

## Next Phase Readiness

- SEC-FU-03 and SEC-FU-04 closed; requirements marked complete
- Phase 1063 Plan 04 can proceed (next plan in the low-followup-tickets sequence)
- Pre-existing ESLint errors in non-SEC files (jsx-a11y, unused-vars) are out of scope for this plan — see deferred-items note below

**Deferred (out of scope):** Pre-existing lint errors in `BasemapGroupRow.tsx`, `EmptyStackState.tsx`, `FolderGroupRow.tsx`, `StackRow.tsx`, `UnifiedStackPanel.tsx` (jsx-a11y violations), and various test files (unused vars) are pre-existing and not caused by this plan.

---
*Phase: 1063-low-followup-tickets*
*Completed: 2026-05-20*
