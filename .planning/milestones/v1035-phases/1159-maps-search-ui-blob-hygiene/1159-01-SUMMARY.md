---
phase: 1159-maps-search-ui-blob-hygiene
plan: "01"
subsystem: ui
tags: [react, vite, hmr, blob-url, react-query, frontend]

requires: []
provides:
  - HMR-safe single React root mount via __glRoot cache on container
  - registerBlobUrlRevocation wired via useEffect instead of render body in both blob hooks
affects: [1160-live-playwright-mcp-close-gate]

tech-stack:
  added: []
  patterns:
    - "cached-root guard: container.__glRoot ?? ReactDOM.createRoot(container) prevents duplicate createRoot on HMR re-exec"
    - "side-effect-in-useEffect: idempotent registration calls belong in useEffect, not render body"

key-files:
  created: []
  modified:
    - frontend/src/main.tsx
    - frontend/src/components/maps/hooks/use-quicklook.ts
    - frontend/src/components/maps/hooks/use-map-thumbnail.ts

key-decisions:
  - "MAPS-01: Used RootContainer interface (not as any) for typed __glRoot property on HTMLElement; import { type Root } from 'react-dom/client' provides the type"
  - "HYG-01: useEffect keyed on [queryClient] is the correct pattern; queryClient is a stable singleton so the effect fires once per mount"

patterns-established:
  - "RootContainer interface pattern: extend HTMLElement with cache properties for HMR-safe root reuse"
  - "useEffect([queryClient]) for idempotent QueryClient side-effects in custom hooks"

requirements-completed: [MAPS-01, HYG-01]

duration: 1min
completed: 2026-05-30
---

# Phase 1159 Plan 01: Maps/Search UI & Blob Hygiene (MAPS-01 + HYG-01) Summary

**HMR-safe cached React root via container.__glRoot and registerBlobUrlRevocation moved from render body into useEffect in both blob hooks**

## Performance

- **Duration:** ~1 min
- **Started:** 2026-05-30T19:15:31Z
- **Completed:** 2026-05-30T19:16:56Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- MAPS-01: `main.tsx` now caches the React root on `container.__glRoot` — Vite HMR re-exec of `main.tsx` reuses the existing root instead of calling `ReactDOM.createRoot()` a second time, eliminating the dev-console warning. `<React.StrictMode>` preserved; production cold-load path unchanged.
- HYG-01: `registerBlobUrlRevocation(queryClient)` moved from render body to `useEffect(() => { ... }, [queryClient])` in both `use-quicklook.ts` and `use-map-thumbnail.ts`. Blob-revocation behavior is identical (idempotent WeakSet; stable queryClient singleton fires the effect once).
- All 17 existing hook tests (use-quicklook + use-map-thumbnail) pass, including Tests 6/7 (eviction revokes blob URL; no-revoke-on-unmount).

## Task Commits

1. **Task 1: MAPS-01 — cached-root guard in main.tsx** - `5de4b8d8` (fix)
2. **Task 2: HYG-01 — move registerBlobUrlRevocation into useEffect** - `aa99bb60` (refactor)

**Plan metadata:** (see final commit below)

## Files Created/Modified
- `frontend/src/main.tsx` - Added RootContainer interface + __glRoot read-or-create guard; preserved full render tree and StrictMode
- `frontend/src/components/maps/hooks/use-quicklook.ts` - Added `import { useEffect } from 'react'`; wrapped registerBlobUrlRevocation in useEffect inside useQuicklookQuery
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts` - Added `import { useEffect } from 'react'`; wrapped registerBlobUrlRevocation in useEffect inside useMapThumbnail

## Decisions Made
- Used a typed `RootContainer` interface (`interface RootContainer extends HTMLElement { __glRoot?: Root }`) with `import { type Root } from 'react-dom/client'` rather than `as any` — zero `as any` tokens, satisfies the acceptance criterion.
- Container property name `__glRoot` chosen per CONTEXT.md to align with the Phase 1160 e2e regression test that keys off this name.
- `useEffect` (not `useMemo`) for the registration because the WeakSet registration is a side effect, not a computation — React 19 semantics + Rules of Hooks both require effects for side effects outside render.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. Both changes are purely client-side, DEV-mode-visible, and HMR-scoped (MAPS-01) or refactor-only (HYG-01).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 1159 Plan 02 (MAPS-02: blob-URL regression test for search-page quicklook eviction) is unblocked and ready to execute.
- Phase 1160 live Playwright MCP close-gate should restart the frontend container before MCP smoke to avoid stale-bundle hazard.

---
*Phase: 1159-maps-search-ui-blob-hygiene*
*Completed: 2026-05-30*

## Self-Check: PASSED

- `frontend/src/main.tsx` — exists, contains `__glRoot ?? ReactDOM.createRoot`, StrictMode preserved, 0 `as any`
- `frontend/src/components/maps/hooks/use-quicklook.ts` — exists, useEffect wraps registerBlobUrlRevocation
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts` — exists, useEffect wraps registerBlobUrlRevocation
- Commits `5de4b8d8` and `aa99bb60` — both present in git log
- typecheck: 0 errors
- vitest: 17/17 passed
