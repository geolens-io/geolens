---
phase: 1048-followups-and-closeout
plan: "01"
subsystem: builder-ui
tags: [followup, popup-config, i18n, bulk-action-bar, ui-polish, e2e]
dependency_graph:
  requires: []
  provides: [FOLLOWUP-01-implementation, ui-review-polish-3-items]
  affects: [use-builder-save, BulkActionBar, builder-i18n]
tech_stack:
  added: []
  patterns: [instanceof-ApiError-catch, t-interpolation-toast, TDD-RED-GREEN]
key_files:
  created:
    - e2e/builder.spec.ts (test added; file pre-existed)
    - .planning/phases/1048-followups-and-closeout/1048-01-SUMMARY.md
  modified:
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
    - frontend/src/components/builder/BulkActionBar.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "ApiError.body (not .detailRaw) is the field holding raw backend detail; plan had wrong field name — auto-corrected."
  - "deletePartialFailure suffix uses em-dash before 'Tap to retry' for all 4 locales to match the existing copy tone."
  - "Test A/B assert toast key not interpolation since t() mock returns key string; interpolation verified at source level."
metrics:
  duration_minutes: 15
  completed_date: "2026-05-16T22:24:03Z"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 8
---

# Phase 1048 Plan 01: popup_config Error Surface + UI-REVIEW Polish Summary

**One-liner:** popup_config pre-check toast now names the offending layer + backend 422 popup_config rejection routes to a distinct translated toast; 3 BulkActionBar UI-REVIEW items closed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Save-hook structured popup_config error surface | 7d696403 | use-builder-save.ts, test, 4 locales |
| 2 | BulkActionBar UI-REVIEW polish | f60636b0 | BulkActionBar.tsx, 4 locales |
| 3 | e2e success-path round-trip for popup_config | 4ae05b82 | e2e/builder.spec.ts |

## FOLLOWUP-01 Implementation

**Status:** Implementation complete; live e2e execution deferred to CLOSE-01 Docker gate.

**Pre-check surface (frontend):**
- `handleSave()` now calls `t('toasts.popupConfigInvalidNamed', { layerName })` where `layerName = invalidLayer.display_name ?? t('layerFallbackName')`.
- Toast options unchanged: `{ id: 'popup-config-invalid', duration: 6000 }` — dedupe and observability paths preserved.

**Backend rejection surface:**
- catch block changed from `catch {` to `catch (err) {`.
- If `err instanceof ApiError && err.status === 422 && Array.isArray(err.body)`, the body is inspected for a `loc` array containing `'popup_config'`.
- Match: `toast.error(t('toasts.popupConfigBackendRejected', { field }))` where `field` is the joined loc segments after `'popup_config'` (e.g., `popup_config.expression`).
- No match / unexpected shape: falls through to `toast.error(t('toasts.saveFailed'))`.
- Both branches still call `setLastSaveFailed(true)`.

**Deviation:** Plan referenced `ApiError.detailRaw` but the actual field is `ApiError.body` (raw `detail` from FastAPI response). Auto-corrected per Rule 1.

## New i18n Keys

12 new keys added across 4 locales (en/de/es/fr), all at key-count parity (781 keys each):

| Key | Namespace |
|-----|-----------|
| `toasts.popupConfigInvalidNamed` | builder |
| `toasts.popupConfigBackendRejected` | builder |
| `layerFallbackName` | builder (root) |

## Vitest Cases Added (4)

| Test | Assertion |
|------|-----------|
| Test A: named layer in pre-check | `toast.error('toasts.popupConfigInvalidNamed', { id, duration })` |
| Test B: null display_name fallback | Same key — fallback name taken from `t('layerFallbackName')` |
| Test C: backend 422 popup_config | `toast.error('toasts.popupConfigBackendRejected', ...)` not `saveFailed` |
| Test D: non-popup ApiError 500 | `toast.error('toasts.saveFailed')` — generic path preserved |

## Playwright Test Added

**Name:** `popup_config success-path round-trip (FOLLOWUP-01)`
**File:** `e2e/builder.spec.ts` (appended inside existing `Map Builder` `test.describe.serial` block)
**Discovery:** Confirmed with `--list` flag — picks up 1 test in the chromium project.
**Gate:** Will execute in CLOSE-01 (Plan 04) under `npm run e2e:smoke:builder` against Docker stack.

## UI-REVIEW Carry-Over Items (3 of 3 closed)

| Item | Fix | Done Criteria |
|------|-----|---------------|
| cursor-not-allowed container scope | `isDeleting ? 'cursor-not-allowed' : ''` added to BulkActionBar container `cn()` | `grep -c cursor-not-allowed BulkActionBar.tsx` = 2 |
| text-[13px] → text-xs | Selected-count label at line 227 changed from `text-[13px]` to `text-xs` | `grep -c 'text-\[13px\]' BulkActionBar.tsx` = 0 |
| deletePartialFailure suffix | All 4 locales: suffix appended (" — Tap to retry." / de/es/fr equivalents) | Verified via grep on en/de/es/fr |

## Verification Results

| Check | Result |
|-------|--------|
| vitest use-builder-save.test.ts (39 tests) | PASS |
| vitest BulkActionBar.test.tsx (25 tests) | PASS |
| tsc --noEmit | PASS (0 errors) |
| i18n parity (en/de/es/fr) | PASS (781 keys each) |
| Playwright --list (popup_config test) | FOUND |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ApiError field name mismatch**
- **Found during:** Task 1 implementation
- **Issue:** Plan specified `err.detailRaw` for introspecting backend error body, but the actual `ApiError` class uses `err.body` (set from `body.detail` in `apiFetch`).
- **Fix:** Used `err.body` throughout catch block logic.
- **Files modified:** `use-builder-save.ts`
- **Commit:** 7d696403

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface added.

## Self-Check: PASSED

- `frontend/src/components/builder/hooks/use-builder-save.ts` — exists, modified
- `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` — exists, modified
- `frontend/src/components/builder/BulkActionBar.tsx` — exists, modified
- `frontend/src/i18n/locales/en/builder.json` — exists, modified
- `e2e/builder.spec.ts` — exists, modified
- Commits: 7d696403, f60636b0, 4ae05b82 — all present in git log
