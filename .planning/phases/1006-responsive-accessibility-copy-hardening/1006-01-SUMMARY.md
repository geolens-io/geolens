---
phase: 1006-responsive-accessibility-copy-hardening
plan: 01
subsystem: frontend
tags: [map-builder, accessibility, responsive, auth-shell, i18n]
requires:
  - phase: 1002-kepler-guided-builder-workflow-audit-and-triage
    provides: F-1002-02, F-1002-03, F-1002-06, F-1002-08 routed findings
  - phase: 1003-map-stack-inspector-interaction-polish
    provides: data-first empty stack and inspector focus state
  - phase: 1005-preview-save-share-output-parity
    provides: stable save/share output state
provides:
  - Authenticated map route shell state that no longer shows signed-out footer artifacts while user state is restoring
  - Mobile builder sheet sizing that leaves more map context visible
  - 44px mobile save and rail controls for touched builder shell actions
  - Non-blocking basemap recovery copy with complete en/es/fr/de locale keys
affects: [phase-1007-qa-gate]
tech-stack:
  added: []
  patterns: [route-gate loading for token/user-null state, scoped BuilderMap status notice]
key-files:
  created:
    - frontend/src/pages/__tests__/MapViewerGate.test.tsx
    - frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx
  modified:
    - frontend/src/hooks/use-auth.ts
    - frontend/src/pages/MapViewerGate.tsx
    - frontend/src/components/layout/AppLayout.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/test/setup.ts
requirements-completed: [A11Y-01, A11Y-02, A11Y-03, A11Y-04, A11Y-05, A11Y-06]
duration: 23 min
completed: 2026-05-11T21:01:43Z
---

# Phase 1006 Plan 01: Responsive, Accessibility, and Copy Hardening Summary

**Builder route state, mobile shell targets, and basemap recovery copy now meet the focused Phase 1006 accessibility and responsive bar.**

## Accomplishments

- Restored `user` into auth state after `getMe` succeeds for persisted tokens, preventing token/user-null sessions from keeping the shell in a signed-out state.
- Kept `/maps/:id` in a loading state while authenticated user data is restoring, and suppressed the app footer on authenticated map routes to close the footer artifact from F-1002-02/F-1002-06.
- Preserved anonymous public map behavior while loading the builder only for editor/admin users.
- Narrowed mobile builder sheets from `calc(100vw - 3rem)` to `calc(100vw - 5rem)` so more map context remains visible.
- Raised touched mobile save and rail buttons to 44px target dimensions.
- Added a scoped BuilderMap status notice for basemap style/tile failures, with recovery-oriented copy and complete builder locale keys in en, es, fr, and de.

## Task Commits

1. **Task 1: Auth shell state** - `70bbf46f` (fix)
2. **Task 2: Mobile builder shell targets** - `36f2010a` (fix)
3. **Task 3: Basemap recovery copy** - `dedc3ea3` (fix)

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- The GSD `phase complete` helper inferred stale milestone metadata before the summary existed. The Phase 1006 artifacts and state were corrected manually afterward.

## Verification

- `cd frontend && npm run test -- use-auth auth-store AppLayout MapViewerGate MapBuilderPage.header-actions BuilderMap.a11y BuilderMap.unit resources --run` - passed, 8 files / 54 tests.
- `cd frontend && npm run lint` - passed.

## Next Phase Readiness

Phase 1007 can build durable QA gates over the now-stabilized responsive, accessibility, auth shell, and i18n surfaces.

## Self-Check: PASSED
