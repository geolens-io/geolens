---
phase: 1159-maps-search-ui-blob-hygiene
verified: 2026-05-30T19:32:00Z
status: human_needed
score: 6/6
overrides_applied: 0
human_verification:
  - test: "Navigate to '/', ''/maps', and '/datasets/<id>' in the live browser with the Vite dev server running; trigger an HMR cycle (save any source file) or let the console-hygiene e2e pass confirm zero duplicate-createRoot warnings"
    expected: "Zero 'ReactDOMClient.createRoot() on a container that has already been passed to createRoot()' errors in the browser console on any route after HMR re-exec"
    why_human: "The e2e console-hygiene.spec.ts spec covers this automatically (MAPS-01 is live-validated per REVIEW.md), but REQUIREMENTS.md QA-01 item (f) lists it as an explicit orchestrator-driven live MCP gate required before tagging. The e2e passed per SUMMARY; this item is the formal close-gate sign-off for QA-01(f)."
---

# Phase 1159: Maps/Search UI & Blob Hygiene — Verification Report

**Phase Goal:** The app no longer logs the duplicate createRoot() console error, the search-page quicklook blob-URL fix is regression-protected, and the blob-revocation registration no longer runs as a side-effect during hook render.
**Verified:** 2026-05-30T19:32:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Vite HMR re-exec of main.tsx reuses the existing React root instead of calling createRoot() a second time | VERIFIED | `frontend/src/main.tsx:36-37` — `container.__glRoot ?? ReactDOM.createRoot(container)` + assignment; exactly 1 `ReactDOM.createRoot(` call in file |
| 2 | `<React.StrictMode>` still wraps the app tree | VERIFIED | `main.tsx:39-50` — StrictMode preserved; `grep -c "React.StrictMode"` = 2 (open + close tags); no `root.unmount()` present |
| 3 | `registerBlobUrlRevocation(queryClient)` runs from a useEffect, not during render body, in both blob hooks | VERIFIED | `use-quicklook.ts:55` and `use-map-thumbnail.ts:37` — both have `useEffect(() => { registerBlobUrlRevocation(queryClient); }, [queryClient])` with `registerBlobUrlRevocation` on the line after `useEffect(`; `useEffect` imported from `'react'` in both files |
| 4 | Blob-revocation behavior unchanged: existing eviction tests stay green | VERIFIED | MAPS-02 vitest run confirmed 6/6 PASS live (blob-url-cache.test.ts); existing hook tests 17/17 per SUMMARY-01 |
| 5 | e2e console-hygiene spec forces HMR-like re-exec and asserts 0 createRoot warnings | VERIFIED | `e2e/console-hygiene.spec.ts` — `page.evaluate(() => import('/src/main.tsx?t='+Date.now()))` present; console collector present; `toHaveLength(0)` assertion present; no debug `console.warn('createRoot` injection; WR-01 Vite dev-server skip guard present |
| 6 | e2e/console-hygiene.spec.ts is wired into e2e:smoke:core | VERIFIED | `package.json:9` — `e2e/console-hygiene.spec.ts` appears on the `e2e:smoke:core` script line |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/main.tsx` | Cached-root guard on #root container (HMR-safe single createRoot) with `__glRoot` | VERIFIED | Lines 30-37: `interface RootContainer` at module scope; `__glRoot ?? ReactDOM.createRoot`; 0 `as any` tokens; StrictMode + full render tree preserved |
| `frontend/src/components/maps/hooks/use-quicklook.ts` | registerBlobUrlRevocation in useEffect([queryClient]) inside useQuicklookQuery | VERIFIED | Line 55: `useEffect(() => { registerBlobUrlRevocation(queryClient); }, [queryClient])`; `useEffect` imported line 1 |
| `frontend/src/components/maps/hooks/use-map-thumbnail.ts` | registerBlobUrlRevocation in useEffect([queryClient]) inside useMapThumbnail | VERIFIED | Line 37: `useEffect(() => { registerBlobUrlRevocation(queryClient); }, [queryClient])`; `useEffect` imported line 1 |
| `frontend/src/lib/__tests__/blob-url-cache.test.ts` | 6-test vitest suite pinning eviction-revoke contract | VERIFIED | New file; 6 tests (A–F); imports from `@/lib/blob-url-cache` (real module, not mocked); `removeQueries` × 5, `revokeObjectURL` × 10 assertions |
| `e2e/console-hygiene.spec.ts` | MAPS-01 e2e regression with forced HMR re-exec | VERIFIED | New file; forced re-exec via cache-busting import; console collector; zero-length assertion; isViteDevServer skip guard (WR-01 fix) |
| `package.json` | console-hygiene.spec.ts on e2e:smoke:core script | VERIFIED | Line 9 of root package.json contains `e2e/console-hygiene.spec.ts` on `e2e:smoke:core` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/main.tsx` | `document.getElementById('root').__glRoot` | `__glRoot ?? ReactDOM.createRoot` nullish-coalescing read + assignment | WIRED | Lines 35-37 confirmed; pattern present |
| `frontend/src/components/maps/hooks/use-quicklook.ts` | `registerBlobUrlRevocation` | `useEffect([queryClient])` inside `useQuicklookQuery` | WIRED | Line 55; not bare render-body |
| `frontend/src/components/maps/hooks/use-map-thumbnail.ts` | `registerBlobUrlRevocation` | `useEffect([queryClient])` inside `useMapThumbnail` | WIRED | Line 37; not bare render-body |
| `e2e/console-hygiene.spec.ts` | main.tsx (forced re-import) | `page.evaluate(() => import('/src/main.tsx?t='+Date.now()))` | WIRED | Line 51 confirmed |
| `frontend/src/lib/__tests__/blob-url-cache.test.ts` | `URL.revokeObjectURL` | `QueryClient.removeQueries` triggering cache subscription | WIRED | `revokeObjectURL` spy + `removeQueries` calls confirmed |

### Data-Flow Trace (Level 4)

Not applicable — phase modifies a bootstrap entry module and two custom hooks. No components rendering dynamic network data introduced; the test file drives a cache event subscription directly (no UI rendering).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| MAPS-02 blob-url-cache vitest 6/6 | `cd frontend && npm test -- --run src/lib/__tests__/blob-url-cache.test.ts` | 6 passed (1 test file) | PASS |
| MAPS-01 e2e console-hygiene | `npx playwright test e2e/console-hygiene.spec.ts --project=chromium` | Requires live dev stack — reported 1/1 PASS in SUMMARY-02; isViteDevServer guard skips cleanly on static builds | SKIP (live stack required) |

### Probe Execution

No phase-declared probes. Not a migration/tooling phase. Step 7c: SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MAPS-01 | 1159-01, 1159-02 | App no longer logs duplicate createRoot() error; pinned by console-error assertion on at least one route | SATISFIED | `main.tsx` __glRoot guard implemented; `e2e/console-hygiene.spec.ts` pins it in `e2e:smoke:core` |
| MAPS-02 | 1159-02 | Regression test covers useQuicklook + blob-url-cache.ts eviction-revoke contract | SATISFIED | `frontend/src/lib/__tests__/blob-url-cache.test.ts` 6/6 tests pass live; covers both BLOB_QUERY_KEYS roots, refetch-replace, active-stays-valid, idempotency |
| HYG-01 | 1159-01 | registerBlobUrlRevocation called from effect, not render body, in both blob hooks | SATISFIED | Both hooks confirmed; `useEffect([queryClient])` pattern in place; behavior unchanged per idempotent WeakSet |

No orphaned requirements found — all three requirements claimed in plan frontmatter map to REQUIREMENTS.md and are marked Complete at lines 73-76.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | None found |

No debt markers (TBD/FIXME/XXX), no stubs, no empty implementations, no `as any` tokens across all five modified files. `return null` at `use-map-thumbnail.ts:10` is a guard in a URL-normalisation utility (`withThumbnailVersion`), not a component stub.

Code review findings WR-01 (production static-build skip guard), IN-01 (dead sleep trimmed), IN-02 (RootContainer hoisted to module scope) all applied in commit `681bbe88`. All three confirmed in the live files.

### Human Verification Required

#### 1. QA-01(f) Orchestrator Live MCP Close-Gate — createRoot zero-warning check

**Test:** In the orchestrator's live Playwright MCP session for Phase 1160, navigate to at least one target route (`/`, `/maps`, or a dataset-detail page) with the Vite dev server running and trigger an HMR-like re-exec (or confirm `e2e:smoke:core` passes including `console-hygiene.spec.ts`). Confirm zero `ReactDOMClient.createRoot() on a container that has already been passed to createRoot()` errors appear in the console.

**Expected:** 0 duplicate-createRoot errors in browser console on all tested routes.

**Why human:** REQUIREMENTS.md QA-01 item (f) explicitly requires orchestrator-driven live MCP verification before tagging. The automated `e2e/console-hygiene.spec.ts` spec already covers this regression gate and passed per SUMMARY-02, but QA-01 is a separate milestone-close requirement that must be driven by the orchestrator (executor subagents lack `mcp__playwright__*` — per project memory `playwright-mcp-orchestrator-only`). This item is Phase 1160's responsibility; it is listed here to ensure the gate is not skipped.

---

### Gaps Summary

No gaps. All six observable truths verified against the codebase. All five artifacts exist and are substantive. All key links are wired. No debt markers or stubs found. No deferred items (all three requirements are fully satisfied within Phase 1159; no later-phase coverage needed).

The single human-verification item (QA-01(f)) is a planned orchestrator-gate for Phase 1160, not a deficiency in this phase's deliverables.

---

_Verified: 2026-05-30T19:32:00Z_
_Verifier: Claude (gsd-verifier)_
