---
phase: quick-260322-mb0
plan: 01
subsystem: frontend/nginx, frontend/builder
tags: [maplibre, raster-tiles, error-handling, nginx]
dependency_graph:
  requires: []
  provides: [raster-tile-error-suppression]
  affects: [builder-map, nginx-proxy]
tech_stack:
  added: []
  patterns: [proxy_intercept_errors, map-error-event-listener]
key_files:
  created: []
  modified:
    - frontend/nginx.conf
    - frontend/src/components/builder/BuilderMap.tsx
decisions:
  - "Only intercept 404 at nginx (not 500) so real Titiler failures still surface"
  - "Error listener uses source-id prefix matching rather than URL pattern for resilience across dev/prod"
metrics:
  duration: 1min
  completed: 2026-03-22
---

# Quick Task 260322-mb0: Fix Noisy MapLibre AJAX Errors Summary

Nginx converts Titiler 404 no-data tile responses to 204 at proxy layer; BuilderMap adds defense-in-depth error listener suppressing expected tile errors.

## What Changed

### Task 1: nginx proxy_intercept_errors for Titiler 404s (50d1fed8)

Added `proxy_intercept_errors on` and `error_page 404 = @empty_tile` to the raster-tiles location block. The `@empty_tile` named location returns HTTP 204 (no content), which MapLibre treats as an empty tile rather than an error. Only 404 is intercepted -- 500s still propagate so real Titiler failures remain visible.

### Task 2: BuilderMap error event listener (73983649)

Added `map.on('error', ...)` inside `handleLoad` after `setTransformRequest` and before `onMapRef`. The handler checks if the error message contains a managed source ID prefix (`source-`) or has a 404 status, and suppresses those silently. Non-tile errors are logged with `console.warn` for debugging. No user-visible UI changes.

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Verification

1. `grep -n 'proxy_intercept_errors' frontend/nginx.conf` -- confirmed in raster-tiles block
2. `grep -n "map.on('error'" frontend/src/components/builder/BuilderMap.tsx` -- confirmed in handleLoad
3. `npx tsc --noEmit -p frontend/tsconfig.json` -- passes with no errors

## Self-Check: PASSED
