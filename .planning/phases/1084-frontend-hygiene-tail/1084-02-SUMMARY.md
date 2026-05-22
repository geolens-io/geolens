---
phase: 1084-frontend-hygiene-tail
plan: "02"
subsystem: ui
tags: [react-router, routing, frontend, builder, console-noise]

requires:
  - phase: 1084-01
    provides: "Pre-existing TS errors in test files documented as baseline (TD-09 scope)"

provides:
  - "Route-level redirect for /maps/new -> /maps, eliminating 422 noise from GET /api/maps/new"

affects: [1084-03, smoke-sessions]

tech-stack:
  added: []
  patterns:
    - "Static route before dynamic route: add path='maps/new' BEFORE path='maps/:id' to prevent 422 on reserved segments"

key-files:
  created: []
  modified:
    - frontend/src/App.tsx

key-decisions:
  - "Option A (route-level redirect) chosen over Option B (in-component guard): cleaner separation of concerns, zero MapBuilderPage changes, Navigate already imported in App.tsx"
  - "Use replace=true to prevent /maps/new from polluting browser history (back-button loop prevention)"

patterns-established:
  - "Static-before-dynamic route ordering: reserve /maps/new as a named redirect at the route table level so no component ever receives id='new'"

requirements-completed: [TD-11]

duration: 8min
completed: 2026-05-22
---

# Phase 1084 Plan 02: /maps/new 422 Elimination Summary

**Route-level redirect `maps/new -> /maps` eliminates 2 spurious `GET /api/maps/new` 422 responses by intercepting the reserved path before react-router can hand it to `MapViewerGate`**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-22T01:10:00Z
- **Completed:** 2026-05-22T01:18:00Z
- **Tasks:** 1 of 2 (Task 2 is a Playwright MCP checkpoint — handled by orchestrator)
- **Files modified:** 1

## Accomplishments

- Added one `<Route path="maps/new" element={<Navigate to="/maps" replace />} />` declaration in `App.tsx` immediately above the `<Route path="maps/:id">` line
- React Router v7 resolves static path segments before dynamic ones, so `/maps/new` now matches the redirect and never reaches `MapViewerGate` / `MapBuilderPage`
- `useMap('new', ...)` never fires; zero `GET /api/maps/new` requests reach the backend
- `Navigate` was already imported at `App.tsx:2` — no new imports needed
- Production data layer (`use-maps.ts`, `api/maps.ts`, `api/client.ts`) untouched

## Fix Shape: Option A (route-level redirect)

**Option A was implemented.** The two options from the plan's decision tree were:

| Option | Approach | Files changed | Risk |
|--------|----------|---------------|------|
| **A (chosen)** | `<Route path="maps/new" element={<Navigate to="/maps" replace />} />` in App.tsx | 1 (App.tsx) | None — Navigate already imported; react-router static-segment precedence is guaranteed |
| B (fallback) | `if (id === 'new') return <Navigate to="/maps" replace />;` in MapBuilderPage.tsx before `useMap` | 1 (MapBuilderPage.tsx) | Hook-ordering discipline; must stay before useMap call |

**Rationale for Option A:**
- Cleanest separation — the routing table owns "what URLs are valid", not individual page components
- `Navigate` was already imported in `App.tsx` (line 2); zero new imports needed
- Zero changes to `MapBuilderPage.tsx` removes any risk of disturbing the 1,000+ LOC builder component
- `replace` flag prevents the user getting stuck in a back-button loop between `/maps/new` and `/maps`

## Exact Line-Level Diff

```diff
--- a/frontend/src/App.tsx
+++ b/frontend/src/App.tsx
@@ -59,6 +59,7 @@ export const appRoutes = (
       <Route path="maps" element={<MapsPage />} errorElement={<RouteErrorBoundary />} />
+      <Route path="maps/new" element={<Navigate to="/maps" replace />} />
       <Route path="maps/:id" element={<MapViewerGate />} errorElement={<RouteErrorBoundary />} />
```

One line inserted. No other files modified.

## Task Commits

1. **Task 1: Implement Option A route-level redirect** - `f1a40347` (feat)

## Files Created/Modified

- `/Users/ishiland/Code/geolens/frontend/src/App.tsx` — Added `<Route path="maps/new" element={<Navigate to="/maps" replace />} />` before `<Route path="maps/:id">` (line 60)

## Build / Typecheck Results

- `npm run build` (tsc -b && vite build): exit 0, dist/ produced
- TS errors visible in output are all pre-existing test-file errors (TD-09 baseline, Plan 1084-01 scope) — none introduced by this change
- Source assertions:
  - `grep -c 'path="maps/new"' frontend/src/App.tsx` = **1** (option A route present)
  - `grep -c "id === 'new'" frontend/src/pages/MapBuilderPage.tsx` = **0** (option B not applied)
  - Sum = **1** (mutually exclusive constraint satisfied)
  - `git diff -- frontend/src/hooks/use-maps.ts frontend/src/api/maps.ts | wc -l` = **0** (data layer untouched)

## Playwright MCP Checkpoint Verification Instructions

**Task 2 is a `checkpoint:human-verify` — the orchestrator will run Playwright MCP after all Wave 1 plans complete.**

### What the verifier must assert

**Environment pre-check:** Stack must be up at `http://localhost:8080`.

**Step 1 — Zero 422 on /maps/new:**
1. Open Playwright MCP and authenticate as admin.
2. Open the browser's Network panel and CLEAR all entries.
3. In the address bar type `http://localhost:8080/maps/new` and press Enter (do NOT use `navigate()`).
4. Wait 3 seconds for the page to settle.
5. Assert ALL of the following against the network log:
   - `GET /api/maps/new` does **NOT** appear (zero requests with literal path segment `/api/maps/new`)
   - `GET /api/maps/new/<anything>` does **NOT** appear (zero requests with path prefix `/api/maps/new/`)
   - **Zero responses with status 422** in the entire log
   - The URL bar now shows `http://localhost:8080/maps` (Option A redirect fired)
   - The Maps list page renders normally (map cards visible if any maps exist; Create Map button visible for editors)

**Step 2 — Regression check for valid /maps/:uuid:**
1. From the Maps page, click any map card to navigate to `/maps/<uuid>`.
2. Assert:
   - `GET /api/maps/<uuid>` returns **200 OK** (visible in network log)
   - The builder mounts and renders the layer stack as before
   - **No new 422 responses** appear in the network log

**Expected pass output line:** `0 spurious 422s on /maps/new, 0 GET /api/maps/new requests, valid /maps/<uuid> still 200 OK + builder mounts`

**Fallback (if Option A does not eliminate 422s):** Revert `App.tsx` change and apply Option B in `MapBuilderPage.tsx` — insert `if (id === 'new') return <Navigate to="/maps" replace />;` immediately after `const { id } = useParams<{ id: string }>();` (line 80) and BEFORE the `useMap(id, ...)` call (line 82). Add `import { Navigate } from 'react-router';` if not already present.

## Deviations from Plan

None — plan executed exactly as written. Option A was the planner's preferred choice and was implemented without needing to fall back to Option B.

## Known Stubs

None.

## Threat Flags

None — this change only affects client-side routing (redirect at the browser). No new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check

- [x] `frontend/src/App.tsx` modified (1 line added): FOUND
- [x] Commit `f1a40347` exists: FOUND
- [x] `grep -c 'path="maps/new"' frontend/src/App.tsx` = 1: PASS
- [x] Build exit 0: PASS
- [x] Data layer untouched: PASS

## Self-Check: PASSED

---
*Phase: 1084-frontend-hygiene-tail*
*Completed: 2026-05-22*
