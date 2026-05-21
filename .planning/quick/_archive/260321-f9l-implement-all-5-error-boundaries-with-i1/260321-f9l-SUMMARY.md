---
phase: quick-260321-f9l
plan: 01
subsystem: frontend/error-handling
tags: [error-boundaries, i18n, resilience, react]
dependency_graph:
  requires: []
  provides: [error-boundaries, crash-recovery]
  affects: [main.tsx, App.tsx, MapBuilderPage.tsx]
tech_stack:
  added: []
  patterns: [class-component-error-boundary, functional-fallback-with-hooks, chunk-load-auto-retry]
key_files:
  created:
    - frontend/src/components/error/AppErrorBoundary.tsx
    - frontend/src/components/error/MapErrorBoundary.tsx
    - frontend/src/components/error/RouteErrorBoundary.tsx
    - frontend/src/components/error/LazyLoadErrorBoundary.tsx
    - frontend/src/components/error/index.ts
    - frontend/src/components/error/__tests__/ErrorBoundaries.test.tsx
  modified:
    - frontend/src/i18n/locales/en/common.json
    - frontend/src/i18n/locales/es/common.json
    - frontend/src/i18n/locales/fr/common.json
    - frontend/src/i18n/locales/de/common.json
    - frontend/src/main.tsx
    - frontend/src/App.tsx
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - AppErrorBoundary uses functional inner fallback with try/catch around useTranslation for above-i18n-provider resilience
  - MapErrorBoundary accepts hasUnsavedChanges prop to warn builder users before reload
  - LazyLoadErrorBoundary auto-retries chunk load errors once with 1s delay before showing manual retry
  - RouteErrorBoundary is functional (not class) since it uses react-router useRouteError hook
metrics:
  duration: 4min
  completed: 2026-03-21T15:08:00Z
---

# Quick Task 260321-f9l: Error Boundaries with i18n Summary

Layered React error boundaries with i18n-supported fallback UIs preventing white-screen crashes at global, route, map, and lazy-load levels.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add i18n keys and create all error boundary components | 804e42e3 | 9 files (4 locale JSONs, 4 components, barrel) |
| 2 | Wire error boundaries into main.tsx, App.tsx, MapBuilderPage.tsx | cbe9869e | 3 files |
| 3 | Add unit tests for error boundary components | 171700df | 1 file (12 tests) |

## Architecture

```
StrictMode
  AppErrorBoundary          <-- catches everything (hardcoded English fallback)
    QueryClientProvider
      ThemeProvider
        TooltipProvider
          BrowserRouter
            LazyLoadErrorBoundary  <-- catches chunk load failures with auto-retry
              Suspense
                Routes
                  datasets/:id  errorElement={RouteErrorBoundary}
                  maps/:id      errorElement={RouteErrorBoundary}
                    MapBuilderPage
                      MapErrorBoundary  <-- catches WebGL/map crashes
                        BuilderMap
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
