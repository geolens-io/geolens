# Phase 1159: Maps/Search UI & Blob Hygiene - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) — enriched with REQUIREMENTS.md + STATE.md + `.planning/backlog/quick-260530-ezw-lowpri.md` + a dedicated MAPS-01 root-cause investigation (empirically validated on the live dev server).

<domain>
## Phase Boundary

Three frontend hygiene fixes (existing files only; no new features; no ui-phase/ui-review — bug/hygiene fixes, live-verified in Phase 1160):
- **MAPS-01 (#122):** eliminate the duplicate `ReactDOMClient.createRoot()` console warning.
- **MAPS-02 (QZ-LP-01):** regression-protect the search-page quicklook blob-URL fix so it can't regress to `ERR_FILE_NOT_FOUND`.
- **HYG-01 (QZ-LP-04):** move `registerBlobUrlRevocation(queryClient)` out of hook-render into an effect/memo (behavior unchanged; removes side-effect-in-render smell).

</domain>

<decisions>
## Implementation Decisions

### MAPS-01 — ROOT CAUSE (validated) + fix
- **Root cause:** the ONLY `ReactDOM.createRoot` in the app is `frontend/src/main.tsx:30` (inside `bootstrap()`, runs on module import, inside `<React.StrictMode>`). **Vite HMR re-executes `main.tsx`** (it has no `import.meta.hot` guard), which calls `createRoot(#root)` again on a container that already holds a root (React 19 stores `__reactContainer$…` on `#root`) → the warning. It is a **DEV-ONLY HMR artifact**: a cold load (and any production build) emits 0 warnings; the QA "~3× per load on `/`, `/maps`, dataset detail" is accumulated HMR re-execs (app-wide because `main.tsx` is the single shared entry — not route-specific). Ruled out: no library (`@vis.gl/react-maplibre`, `maplibre-gl`, etc.) calls `createRoot`; single `react-dom` 19.2.5 install.
- **Fix (validated empirically — recommended Option A):** cache/reuse the root on the container so HMR re-exec reuses it instead of re-rooting:
  ```
  const container = document.getElementById('root')!;
  const root = (container as any).__glRoot ?? ReactDOM.createRoot(container);
  (container as any).__glRoot = root;
  root.render(<React.StrictMode>…</React.StrictMode>);
  ```
  Validated: `sameRootReused: true`, 0 warnings (vs 1 unguarded). This is React's documented guidance for this exact warning.
- **Gotchas:** PRESERVE `<React.StrictMode>` (it double-invokes render/effects but calls createRoot once — NOT the cause). Do NOT use `root.unmount()` then re-`createRoot` (causes a teardown/remount flash every HMR tick). Production mount path is unchanged.
- **Related (optional, same root cause):** the paired `Widget "measurement"/"legend" already registered, overwriting` warnings from `frontend/src/components/map-widgets/registry.ts:8` (via the `import './register-widgets'` side-effect at `map-widgets/index.ts:2`) come from the same HMR re-exec. Quieting them is OPTIONAL (not in MAPS-01's literal scope, which is the createRoot warning). If trivially cleaned (e.g., guard/no-op the duplicate-register warn on re-registration) include it; otherwise leave for a follow-up — do NOT expand scope.

### MAPS-02 — pin the quicklook blob-URL fix
- The blob-URL revoke-on-eviction fix (quick task 260530-ezw, commit `cc321149`) was live-verified on the maps list (`/maps`) but NOT on the search page (`/`) quicklooks. Both consume the same hook pattern + `frontend/src/lib/blob-url-cache.ts`.
- Add a regression test covering `useQuicklook` + `blob-url-cache.ts` so the revoke-on-eviction cannot regress into `ERR_FILE_NOT_FOUND` (e.g., assert that evicting a cache entry revokes its blob URL and that an active/un-evicted entry's URL stays valid). Prefer a deterministic vitest unit test around the cache eviction/revoke contract; an e2e search-page scroll/re-query smoke can be the Phase 1160 live check.

### HYG-01 — side-effect-out-of-render
- `registerBlobUrlRevocation(queryClient)` is currently called during hook render in `frontend/src/components/maps/hooks/use-map-thumbnail.ts` and `use-quicklook.ts`. It is idempotent (module-level `WeakSet`), so behavior is correct — this is purely removing the side-effect-in-render smell.
- Move the call into a `useEffect` (or a memoized init) keyed on `queryClient`. Behavior must stay identical. Keep typecheck + vitest green.

</decisions>

<code_context>
## Existing Code Insights

### Files to change
- `frontend/src/main.tsx` (MAPS-01 — cached-root guard at the `createRoot` call ~line 30)
- `frontend/src/lib/blob-url-cache.ts` + `frontend/src/components/maps/hooks/use-quicklook.ts` (MAPS-02 test target)
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts` + `use-quicklook.ts` (HYG-01 — move `registerBlobUrlRevocation` into effect)
- New/extended test files (MAPS-01 e2e console spec; MAPS-02 vitest).

### Test patterns (verified)
- **MAPS-01 e2e console-assertion:** reuse the `page.on('console', msg => …)` collector from `e2e/builder-hardening.spec.ts:74-76` / `e2e/builder-unified-stack.spec.ts:43-45`; assertion idiom `expect(errors).toHaveLength(0)` (`e2e/mcp-smoke-1136.spec.ts:299`). A cold load is already 0, so the test MUST force an HMR-like re-exec to catch regression: after `goto`, `await page.evaluate(() => import('/src/main.tsx?t=' + Date.now()))` then assert 0 `/createRoot\(\) on a container that has already been passed/` warnings. Add to `e2e:smoke:core` (root `package.json:9`) — or a new `e2e/console-hygiene.spec.ts`. `main.tsx` is excluded from vitest coverage, so jsdom/vitest can't reproduce this — it MUST be e2e.
- **MAPS-02 vitest:** unit-test the `blob-url-cache.ts` eviction→revoke contract + `useQuicklook` consumption (deterministic, no browser needed).
- **HYG-01:** existing vitest for the hooks; assert behavior unchanged after moving to effect.

### Recipe + hazards
- From `frontend/`: `npm run typecheck` (0), `npm test` (vitest), e2e via Playwright.
- **Stale-bundle hazard (project memory):** the dockerized frontend can serve a bundle predating recent commits (macOS Docker HMR miss). Restart `geolens-frontend-1` before trusting any live/e2e MAPS-01 pass. (The Phase 1160 orchestrator-driven MCP gate will restart the frontend first.)

</code_context>

<specifics>
## Specific Ideas

- MAPS-01: 0 `createRoot` warnings on a target route even under an HMR re-exec; preserve StrictMode; production unaffected.
- MAPS-02: eviction revokes the blob URL; active entry stays valid; no `ERR_FILE_NOT_FOUND`.
- HYG-01: `registerBlobUrlRevocation` invoked from an effect/memo, not during render; behavior identical (idempotent WeakSet).
- GitHub issue #122 (MAPS-01); QZ-LP-01 (MAPS-02), QZ-LP-04 (HYG-01) from `quick-260530-ezw-lowpri.md`.

</specifics>

<deferred>
## Deferred Ideas

- Broader StrictMode/HMR mount refactor beyond eliminating the createRoot warning — out of scope (MAPS-01 fixes the duplicate-root call only).
- Quieting the paired widget-registry HMR warnings — optional/follow-up unless a trivial guard (do not expand scope).

</deferred>
