---
phase: quick
plan: 260331-o2b
subsystem: ci
tags: [lint, formatting, i18n, tests, security]
one_liner: "Fixed ruff lint/format errors, i18n parity gaps, ESLint a11y error, and MapCard test failures, then pushed clean tree to main"
key_files:
  modified:
    - backend/app/ai/chat_service.py
    - backend/app/ai/llm_loop.py
    - backend/app/ingest/tasks.py
    - backend/app/collections/router.py
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/pages/SearchPage.tsx
    - frontend/src/test/test-utils.tsx
decisions:
  - "Add TooltipProvider to test-utils wrapper globally rather than per-test (lower maintenance burden)"
  - "Move app imports before _LLM_TIMEOUT constant in llm_loop.py to satisfy E402 (imports after non-import statement)"
metrics:
  duration: "~15 minutes"
  completed: "2026-03-31"
  tasks_completed: 3
  files_modified: 41
---

# Quick Task 260331-o2b: Run All CI Checks Locally, Fix Any Issues

## Summary

Fixed ruff lint/format errors, i18n parity gaps, ESLint a11y error, and MapCard test failures caused by missing TooltipProvider in test wrapper. All CI checks now pass locally and changes are pushed to main.

## Tasks Completed

| Task | Name | Commit | Files Modified |
|------|------|--------|----------------|
| 1 | Run all CI lint and security checks, fix failures | 023db2a0 | backend/app/ai/*, backend/app/collections/router.py, backend/app/ingest/tasks.py, frontend/src/i18n/locales/*/builder.json, frontend/src/pages/SearchPage.tsx |
| 2 | Run frontend test suite with coverage | 023db2a0 | frontend/src/test/test-utils.tsx |
| 3 | Commit all changes and push | 023db2a0 | All 41 modified files |

## CI Check Results

| Check | Status | Notes |
|-------|--------|-------|
| `ruff check` | PASSED | Fixed after auto-fix + manual corrections |
| `ruff format --check` | PASSED | 13 files reformatted |
| `bandit` | PASSED | No high-severity issues |
| `pip-audit` | PASSED | No known vulnerabilities |
| `test:i18n` | PASSED | Fixed after adding 4 missing keys to de/es/fr |
| `check:i18n:changed` | PASSED | builder.json present in all locales |
| `eslint` | PASSED | Fixed 1 error (no-redundant-roles), 1 warning remains (pre-existing) |
| `tsc --noEmit` | PASSED | No type errors |
| `test:coverage` | PASSED | 86 test files, 821 tests pass |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] E741 ambiguous variable name `l` in chat_service.py**
- **Found during:** Task 1 — ruff check
- **Issue:** `l` used as loop variable (line 625), ambiguous per PEP 8
- **Fix:** Renamed to `lyr` in generator expression
- **Files modified:** `backend/app/ai/chat_service.py`

**2. [Rule 1 - Bug] E402 module-level imports after non-import statement in llm_loop.py**
- **Found during:** Task 1 — ruff check
- **Issue:** `_LLM_TIMEOUT = httpx.Timeout(...)` placed before app-level imports, causing E402 on all 4 subsequent imports
- **Fix:** Moved app imports before the constant definition
- **Files modified:** `backend/app/ai/llm_loop.py`

**3. [Rule 1 - Bug] F821 undefined name `asyncio` in ingest/tasks.py**
- **Found during:** Task 1 — ruff check (surfaced after ruff auto-removed unused `import hashlib`)
- **Issue:** `asyncio.to_thread()` called inside `reupload_file()` without a local `import asyncio`
- **Fix:** Added `import asyncio` inside the function body (matching the pattern used in two other functions in the same file)
- **Files modified:** `backend/app/ingest/tasks.py`

**4. [Rule 2 - Missing i18n keys] 4 keys missing from de/es/fr builder locales**
- **Found during:** Task 1 — npm run test:i18n
- **Issue:** `layerItem.dragToReorder`, `layerItem.hideLegend`, `layerItem.showLegend`, `layerItem.sortableLayer` present in English but absent in other 3 locales
- **Fix:** Added translations for all 4 keys in de, es, and fr builder.json files
- **Files modified:** `frontend/src/i18n/locales/de/builder.json`, `frontend/src/i18n/locales/es/builder.json`, `frontend/src/i18n/locales/fr/builder.json`

**5. [Rule 1 - Bug] jsx-a11y/no-redundant-roles error in SearchPage.tsx**
- **Found during:** Task 1 — eslint
- **Issue:** `<section role="region">` — section has implicit role of region; explicit declaration is redundant
- **Fix:** Removed `role="region"` attribute
- **Files modified:** `frontend/src/pages/SearchPage.tsx`

**6. [Rule 1 - Bug] MapCard tests failing: Tooltip must be used within TooltipProvider**
- **Found during:** Task 2 — npm run test:coverage
- **Issue:** MapCard component uses `<Tooltip>` which requires `<TooltipProvider>` ancestor. The test wrapper in test-utils.tsx did not include TooltipProvider, causing 6 tests to throw.
- **Fix:** Added `TooltipProvider` import and wrapper to both `customRender` and `customRenderHook` in test-utils.tsx
- **Files modified:** `frontend/src/test/test-utils.tsx`

## Git

- Commit: `023db2a0`
- Branch: main
- Push: origin main (cb25bf95 -> 023db2a0)
- Working tree: clean

## Self-Check

- Commit 023db2a0 exists in git log
- Working tree is clean (0 uncommitted tracked files)
- All CI checks confirmed passing before push

## Self-Check: PASSED
