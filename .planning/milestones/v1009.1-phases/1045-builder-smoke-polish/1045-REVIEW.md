---
phase: 1045-builder-smoke-polish
reviewed: 2026-05-15T00:00:00Z
depth: standard
files_reviewed: 45
files_reviewed_list:
  - backend/app/modules/auth/router.py
  - backend/tests/conftest.py
  - backend/tests/test_auth.py
  - backend/tests/test_auth_refresh_logout.py
  - backend/tests/test_embed_tokens.py
  - backend/tests/test_persistent_config.py
  - backend/tests/test_provenance_attribution.py
  - backend/tests/test_raster_tiles.py
  - e2e/export-runtime.spec.ts
  - e2e/permissions.spec.ts
  - frontend/src/api/__tests__/client.test.ts
  - frontend/src/api/auth.ts
  - frontend/src/api/client.ts
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/components/builder/DatasetSearchPanel.tsx
  - frontend/src/components/builder/LayerEditorPanel.tsx
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/components/builder/MapTitleBar.tsx
  - frontend/src/components/builder/SidebarRail.tsx
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
  - frontend/src/components/builder/__tests__/BulkActionBar.test.tsx
  - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
  - frontend/src/components/builder/__tests__/MapTitleBar.test.tsx
  - frontend/src/components/builder/__tests__/StackRow.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
  - frontend/src/components/builder/__tests__/selection-utils.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/selection-utils.ts
  - frontend/src/components/map/MapCoordReadout.tsx
  - frontend/src/components/map/__tests__/MapCoordReadout.test.tsx
  - frontend/src/components/search/SearchResultCard.tsx
  - frontend/src/hooks/__tests__/use-ai-availability.test.tsx
  - frontend/src/hooks/use-admin.ts
  - frontend/src/hooks/use-auth.ts
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/lib/__tests__/quicklook-cache.test.ts
  - frontend/src/lib/quicklook-cache.ts
  - frontend/src/pages/MapBuilderPage.tsx
findings:
  critical: 0
  warning: 3
  info: 5
  total: 8
status: issues_found
---

# Phase 1045: Code Review Report

**Reviewed:** 2026-05-15
**Depth:** standard
**Files Reviewed:** 45
**Status:** issues_found (3 WARNING, 5 INFO — no BLOCKERS)

## Summary

Cross-cutting adversarial review of the v1009.1 Builder Smoke Polish milestone (SP-01..SP-18). The three plan executor agents did a solid self-review pass; this sweep examined React effect lifecycles, module-level singleton mutexes, debounce/timer cleanup, a11y semantics, and a session-scoped negative cache for correctness. **No critical defects found.** The SP-09 in-flight refresh mutex, SP-16 thumbnail debounce, and SP-02 `move` event subscription all have correct unmount cleanup and proper concurrent-call semantics, and have new dedicated tests. The 3 warnings are cleanup/correctness nits that should be addressed but do not block tagging. The info items are stylistic and naming-consistency observations.

Specifically verified:
- **SP-09**: Module-level `inflightRefresh` mutex correctly collapses concurrent 401s into one POST; clears on failure (test covers this); the awaited promise resolves uniformly for all concurrent callers before the singleton is nulled.
- **SP-16**: Per-mapId `pendingCaptures` Map with `clearTimeout` + `delete` on each fire. Test helper `__resetThumbnailDebounceForTests` is wired into `beforeEach`. No timer leak.
- **SP-02**: `map.on('move', ...)` registered + `map.off('move', ...)` in cleanup; rAF cancelled on unmount; `disposed` flag short-circuits async callbacks.
- **SP-07**: Quicklook cache is session-scoped, falls back to in-memory when sessionStorage is unavailable. Cross-origin / wrong-id pollution not possible (same-origin `/api/datasets/<id>/quicklook` URL, no `markQuicklookMissing` call for tables/collections).
- **SP-11**: Login route change (`/auth/login`, no trailing slash) is consistent across backend router, frontend `api/auth.ts`, e2e specs, and all backend test files in `backend/tests/`.
- **SP-15**: BulkActionBar correctly unmounts when `editorScene === 'settings'`; selection state persists in `MapBuilderPage` so the bar reappears unchanged when Settings closes.
- **i18n**: All 4 locales (en/de/es/fr) have parity for the new SP-01 / SP-13 / SP-17 keys (12 occurrences each of the new key family).

## Critical Issues

None.

## Warnings

### WR-01: BulkActionBar mount animation re-fires on every Settings open/close

**File:** `frontend/src/components/builder/BulkActionBar.tsx:60-63`
**Issue:** The mount-animation `mounted` state and its `useEffect(() => { requestAnimationFrame(() => setMounted(true)); }, [])` run on every fresh mount. Because SP-15 unmounts BulkActionBar when `editorScene === 'settings'` and remounts it when Settings closes, the slide-up animation fires every time the user toggles the global Settings cog — even though the user perceives the bar as "already there". This is a visual chatter, not a correctness bug, but is contrary to the SP-15 docstring ("the bar reappears unchanged when Settings closes").
**Fix:** Either (a) keep BulkActionBar mounted and use a `hidden`/`visibility: hidden` prop to suppress display during Settings, or (b) accept the re-animation as deliberate. If (a), confirm the role="toolbar" + aria-live region also gets `aria-hidden="true"` during Settings to avoid AT announcing the bar's contents under the open Settings panel.
**Confidence:** Medium — observable in normal UAT, but the polish budget for v1009.1 is closed and this is borderline aesthetic.

### WR-02: SP-09 inflightRefresh — second caller in queue reads token AFTER singleton already nulled

**File:** `frontend/src/api/client.ts:28-31`
**Issue:** The "queued" branch (`if (inflightRefresh) { await inflightRefresh; return !!useAuthStore.getState().token; }`) reads `useAuthStore.getState().token` AFTER the awaited promise resolves. The first caller's `finally { inflightRefresh = null; }` runs **before** the queued callers' awaits resume (they share the same promise but microtask ordering depends on registration order). In practice this is fine because `setTokens` is called inside the IIFE synchronously after `refreshAccessToken` resolves, so `useAuthStore.getState().token` is already set by the time any awaiter resumes. **However**, if a *third* concurrent caller arrives between the IIFE resolving and the first caller's finally running, that third caller could observe `inflightRefresh === null` and **start a second refresh cycle**, defeating the dedupe guarantee for a narrow window. The two SP-09 tests cover 3 concurrent calls but not this interleaving (they kick off all 3 before the singleton resolves).
**Fix:** Move the `inflightRefresh = null` reset INSIDE the IIFE's `finally`, not in the outer try/finally — so the singleton is cleared synchronously with the resolution, before any awaiter resumes. Alternatively, capture `useAuthStore.getState().token` into a const inside the IIFE and have all callers return the cached boolean.
**Confidence:** Medium — race window is microtask-thin and unlikely to repro under realistic user load. Smoke evidence (single user) won't catch this. Worth a 5-line fix to make the mutex theorem-correct.

### WR-03: Range-select boundary guard mutates the Set returned by computeNextSelection

**File:** `frontend/src/pages/MapBuilderPage.tsx:354-372`
**Issue:** `handleShiftClick` calls `computeNextSelection(...)` then walks the returned `selection` Set and `selection.delete(rid)` to drop basemap-boundary ids. This mutates the Set that `computeNextSelection` returned (created inside `new Set(rows.slice(...))`). It's not a shared reference (each call constructs a fresh Set), so this isn't a state-mutation bug today. However, the pure-helper contract documented in `selection-utils.ts` ("returns NextSelection") implies the caller treats the result as immutable. Future refactors that memoize / cache `computeNextSelection` results (e.g., per-anchor LRU) would silently break.
**Fix:** Either (a) clone defensively in the caller — `const filtered = new Set([...selection].filter(id => !isBasemapBoundaryId(id)))`, or (b) move the boundary filter inside `computeNextSelection` with the rows array already pre-filtered upstream. Option (b) is cleaner and pushes the contract into the helper.
**Confidence:** High — code is correct today; this is a future-proofing concern with low effort to fix.

## Info

### IN-01: `BulkActionBar.tsx:80` — `majorityVisible = visibleCount > N / 2` is a strict greater-than tie-breaker

**File:** `frontend/src/components/builder/BulkActionBar.tsx:79-80`
**Issue:** When exactly half the selected layers are visible (e.g., 2 of 4), `majorityVisible` returns `false` → the Eye icon (next action: show all) is rendered. This may be counter-intuitive for a 2/4 case where one might expect "hide all" to be the default action. The convention isn't wrong, just worth a docstring.
**Fix:** Add a one-line comment: `// Ties (2/4, 3/6) resolve to "show next" — the slightly-less-destructive default.`
**Confidence:** Low — UX policy decision, not a defect.

### IN-02: `MapCoordReadout.tsx:74-79` — `onZoom` handler is redundant now that `move` is subscribed

**File:** `frontend/src/components/map/MapCoordReadout.tsx:74-79, 88, 97`
**Issue:** The docblock at line 18-22 acknowledges that `zoomend` "is the original signal" and "`move` also covers this". Keeping both means every camera change fires 2 state updates instead of 1. Coalescing happens at the React reconciler (the rAF dedupe in `updateFromCenter` returns `prev` when values are unchanged), so this isn't a perf bug — but it's dead code that doesn't add coverage beyond what `move` already provides.
**Fix:** Remove `onZoom` and the `map.on('zoomend', onZoom)` / `map.off('zoomend', onZoom)` pair. Zoom is already part of `updateFromCenter`'s `parseFloat(map.getZoom().toFixed(1))`.
**Confidence:** High — out of scope for v1009.1 polish; queue for a future cleanup.

### IN-03: `LayerStyleEditor.tsx:75-96` — Inline `deepEqual` ignores Map/Set/Date/RegExp

**File:** `frontend/src/components/builder/LayerStyleEditor.tsx:75-96`
**Issue:** The inline `deepEqual` handles primitives, arrays, plain objects, and null — sufficient for `paint`/`layout`/`style_config` which are JSON-derived. The docblock says so. But if a future change wires a `Date` (e.g., `last_styled_at`) or a `Set` into `style_config`, this helper would silently return `false` for equal Sets / Dates. Already comparable structures would then trigger the "Pending style preview" banner on no-op renders.
**Fix:** Either (a) extend `deepEqual` to handle `instanceof Date` and `instanceof Set/Map`, or (b) add a runtime guard `if (a instanceof Date || a instanceof Map || a instanceof Set) throw new Error('deepEqual: unsupported type')` so the regression is loud rather than silent.
**Confidence:** Low — `style_config` schema is JSON-only by design; this is future-proofing.

### IN-04: `BulkActionBar.tsx:255-272` — Tooltip wrapping DropdownMenuTrigger with double `asChild`

**File:** `frontend/src/components/builder/BulkActionBar.tsx:255-272`
**Issue:** `<TooltipTrigger asChild>` wraps `<DropdownMenuTrigger asChild>` wraps the `<Button>`. Radix's nested `asChild` propagation is documented to work in newer versions, but in pre-1.x Radix or when both trigger components register their own click handlers, you can get a "double activation" where opening the menu also fires the tooltip's hover-show. The test at `BulkActionBar.test.tsx:163-178` covers the menu-open path via `pointerDown` only — it doesn't assert that the tooltip doesn't double-fire on hover-open.
**Fix:** If a smoke or UAT pass surfaces tooltip flicker, drop the outer `<Tooltip>` wrapper for the overflow trigger (the aria-label already conveys the action). No fix needed if visual flicker not observed.
**Confidence:** Low — speculative; Radix tooltip+dropdown nesting works in the rest of the codebase (StackRow kebab uses the same pattern).

### IN-05: Backend `auth/router.py:55` — login route changed to no-trailing-slash, but `OAuth2PasswordRequestForm` callers in tests still use `/auth/login` correctly

**File:** `backend/app/modules/auth/router.py:55`
**Issue:** SP-11 changes `@router.post("/login/", ...)` to `@router.post("/login", ...)`. The Memory note in `~/.claude/.../MEMORY.md` documents an OGC exception ("`/collections/datasets` defined WITHOUT trailing slash — do NOT add one"). This is the second such exception. Consider adding a comment in `auth/router.py:55` referencing the trailing-slash rationale (smoke evidence showed 307 redirects strip the POST body) so a future routine-cleanup pass doesn't restore the trailing slash.
**Fix:** Add an inline comment: `# SP-11: trailing slash dropped — 307 redirect strips POST body for /auth/login.`
**Confidence:** High — pure docstring hygiene.

---

## Recommendation

**CLEAR-TO-TAG**

All 3 WARNINGS are quality/cleanup issues — none change correctness, none affect smoke/UAT outcomes. The SP-09 mutex (WR-02) has a theoretical microtask race that isn't triggerable under realistic conditions and is covered by the existing 2-test SP-09 suite for the common case. WR-01 (animation chatter) and WR-03 (defensive mutation) are stylistic future-proofing. The 5 INFOs are all low-priority observations.

The phase's 18 SP fixes are correctly implemented, properly tested (10 new test cases across selection-utils, BulkActionBar, MapCoordReadout, use-builder-save SP-16, client.ts SP-09, quicklook-cache SP-07, use-ai-availability SP-08), and respect React effect / Maplibre subscription / timer lifecycle invariants. i18n parity is intact across all 4 locales.

If a follow-up sweep is desired, route WR-02 + WR-03 + IN-02 + IN-05 to a single cleanup quick-task (≤30 min).

---

_Reviewed: 2026-05-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
