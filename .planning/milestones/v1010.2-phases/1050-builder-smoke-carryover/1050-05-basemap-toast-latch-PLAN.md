---
phase: 1050-builder-smoke-carryover
plan: 05
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx
autonomous: true
requirements: [SMOKE-12]

must_haves:
  truths:
    - "Saving a map whose basemap is fully loaded (visible tiles, no prior style error) produces only the 'Map saved' success toast — no 'Basemap connection issue' toast"
    - "Saving a map where the basemap actually IS broken (e.g. unreachable basemap URL on save) still fires the 'Basemap connection issue' toast — the warning is preserved for real outages"
    - "Round-trip: open → edit a layer's paint → save → reload → verify no spurious toast on next save"
    - "The load-latch resets when the user changes basemap (so a NEW basemap's first-load failure surfaces correctly)"
  artifacts:
    - path: "frontend/src/components/builder/BuilderMap.tsx"
      provides: "basemapLoadedAtRef latch — set on first successful style load, consulted in map error handler to suppress transient 5xx toasts"
      contains: "basemapLoadedAtRef"
    - path: "frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx"
      provides: "Test asserting basemap-loaded path suppresses transient 5xx toast; never-loaded path still surfaces it"
      contains: "basemapLoadedAtRef|Basemap connection issue"
  key_links:
    - from: "basemap style-fetch success branch"
      to: "basemapLoadedAtRef.current = Date.now()"
      via: "useRef latch"
      pattern: "basemapLoadedAtRef\\.current\\s*="
    - from: "errorHandlerRef (map.on('error'))"
      to: "early-return when basemapLoadedAtRef.current !== null"
      via: "transient-error suppression"
      pattern: "if\\s*\\(\\s*basemapLoadedAtRef\\.current"
---

<objective>
Saving a map whose basemap had already loaded successfully on mount does NOT surface a false-positive "Basemap connection issue" toast. Closes SF-08.

Purpose: Per SF-08 evidence (Pass E `evaluate(toasts)`, 2026-05-17): when saving the test map with the popup template fix, a toast appeared: `Basemap connection issue Your data layers are still editable. Check the basemap service or choose another basemap if the background stays blank.` The basemap (openfreemap-positron) had loaded successfully on mount — visible tiles rendered. The toast is a false positive triggered by a transient style-fetch error on save (likely the basemap style URL re-fetched during save's revalidation hit a transient 5xx), not a real basemap outage.

Per CONTEXT.md / PATTERNS.md decision: track `basemapLoadedAtRef: number | null` on first successful style load; suppress the connection-issue toast for transient style-fetch errors that occur AFTER the latch is set. Real first-load failures still surface (preserved warning behavior).

Output:
- `frontend/src/components/builder/BuilderMap.tsx` — new `basemapLoadedAtRef` useRef (sibling to `errorHandlerRef` at line 90), set in the style-fetch success branch (~line 156-158), consulted in the `errorHandlerRef` body (~line 397-401) to early-return on transient 5xx; reset to `null` at the START of the style-fetch effect (~line 137-147) when the user picks a different basemap
- `frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx` — test asserting basemap-loaded path suppresses transient 5xx toast; never-loaded path still surfaces it
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/1050-builder-smoke-carryover/1050-CONTEXT.md
@.planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md
@.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md

@frontend/src/components/builder/BuilderMap.tsx

<interfaces>
<!-- Existing ref-based latch pattern + basemap error handler. Executor copies the load-latch shape. -->

From BuilderMap.tsx:90-94 (existing useRef + useState patterns to mirror):
```typescript
const errorHandlerRef = useRef<((e: { error: { message?: string; status?: number } }) => void) | null>(null);
// ...
const [basemapNotice, setBasemapNotice] = useState<'style' | 'tiles' | null>(null);
```

From BuilderMap.tsx:155-167 (basemap style-fetch success/error branches — INSERTION POINT):
```typescript
.then((style) => {
  if (!cancelled) {
    setMapStyle(sanitizeMaplibreStyle(style));
    setBasemapNotice(null);
    // ADD: basemapLoadedAtRef.current = Date.now();
  }
})
.catch(() => {
  if (!cancelled) {
    setBasemapNotice('style');
  }
});
```

From BuilderMap.tsx:137-147 (style-fetch effect start — RESET INSERTION POINT):
```typescript
// At the start of this effect (or its body before fetch),
// when a NEW basemap URL is being loaded:
// ADD: basemapLoadedAtRef.current = null;
// (so the latch resets when the user changes basemap)
```

From BuilderMap.tsx:384-404 (errorHandlerRef — SUPPRESSION INSERTION POINT):
```typescript
errorHandlerRef.current = (e) => {
  const status = e?.error?.status;
  // ... existing checks
  if (!status || status >= 500) {
    // ADD: SF-08 transient-error suppression
    // if (basemapLoadedAtRef.current !== null) return;
    setBasemapNotice('tiles');
    toast.error(t('builderMap.mapError'), { id: 'builder-map-error' });
  }
};
```

Decision points (locked from PATTERNS.md):
- Latch resets on basemap CHANGE (yes) — set to `null` at the START of the style-fetch effect's new-URL fetch.
- Real 5xx outages on FIRST load still warn (yes) — latch starts at `null`, only set after success.
- `setBasemapNotice('style')` at line 164 (style-fetch failure path) is NOT gated — that's a first-load failure, latch shouldn't suppress it. Only the `'tiles'` notice in the error handler is suppressed once style-load has succeeded.

Imports already present (no new imports needed):
```typescript
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';
```

Test analog — BuilderMap.a11y.test.tsx:50:
```typescript
expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add basemapLoadedAtRef latch and suppress transient tile-toast post-load</name>
  <files>frontend/src/components/builder/BuilderMap.tsx, frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx</files>
  <read_first>
    - frontend/src/components/builder/BuilderMap.tsx (FULL FILE — confirm exact line numbers for the refs (~90), basemapNotice useState (~94), style-fetch effect (~137-167), errorHandlerRef (~384-404), and the inline banner UI (~850-865))
    - frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx (full file — locate the existing test that asserts `Basemap connection issue` banner text at line ~50; use this as the test prototype)
    - frontend/src/components/builder/__tests__/BuilderMap.unit.test.ts:18 (map mock prototype: `addSource: vi.fn((id: string, spec: ...))`; useful if the new test mocks `map.on('error')`)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 05 section — touch points + analog #1/#2 + decision points)
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md SF-08 (Observed evidence + Recommended fix)
  </read_first>
  <behavior>
    - Test 1 (NEW in BuilderMap.a11y.test.tsx): When basemap style fetch resolves successfully, the latch is set; firing a subsequent `map.on('error')` with status 503 does NOT surface the 'Basemap connection issue' banner and does NOT fire `toast.error`.
    - Test 2 (NEW): When basemap style fetch never resolves (or rejects), firing `map.on('error')` with status 503 DOES surface the banner and DOES fire `toast.error` (real-outage path preserved).
    - Test 3 (NEW): When the user changes basemap (new style URL), the latch resets to `null` at the start of the new fetch — a subsequent error on the NEW basemap's first load surfaces correctly.
    - Test 4 (regression): The style-fetch FAILURE path (line ~164 `setBasemapNotice('style')`) is NOT gated by the latch — first-load style failures still surface.
  </behavior>
  <action>
    In `frontend/src/components/builder/BuilderMap.tsx`:

    1. Add the new ref next to `errorHandlerRef` (~line 90). Place it directly after the `errorHandlerRef` declaration:
       ```typescript
       const basemapLoadedAtRef = useRef<number | null>(null);
       ```

    2. In the style-fetch effect success branch (~line 155-158, the `.then((style) => { ... })` block):
       After `setBasemapNotice(null);`, add:
       ```typescript
       basemapLoadedAtRef.current = Date.now();
       ```
       Inline comment: `// SF-08: latch first-load success so transient 5xx during save don't surface as outage`.

    3. At the START of the style-fetch effect (the body that issues the fetch for the new basemap URL — search for where the basemap URL dependency changes, ~line 137-147). Reset the latch BEFORE the fetch is initiated:
       ```typescript
       basemapLoadedAtRef.current = null;
       ```
       Inline comment: `// SF-08: reset latch on basemap change so new basemap's first-load failure surfaces correctly`.
       Place this in the effect body, before the `.then`/`.catch` chain begins.

    4. In `errorHandlerRef.current = (e) => {...}` (~line 397-401), inside the `if (!status || status >= 500)` branch, BEFORE the `setBasemapNotice('tiles')` and `toast.error(...)` calls, add:
       ```typescript
       // SF-08: suppress transient connection-issue toast if the basemap
       // already loaded successfully in this session.
       if (basemapLoadedAtRef.current !== null) return;
       ```

    5. DO NOT gate the `setBasemapNotice('style')` path at line ~164 — that's a first-load style failure path; the latch shouldn't suppress it (it never gets set in that path anyway because the latch is set only in the `.then` success branch).

    Add NEW tests to `frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx`:

    - **Test 1 — "suppresses transient tile error toast when basemap loaded successfully":**
      Mock the style-fetch to resolve. After the component renders and the style settles, fire `map.emit('error', { error: { status: 503 } })`. Assert: `screen.queryByRole('status')` does NOT have `Basemap connection issue` text; `toast.error` spy NOT called.

    - **Test 2 — "still surfaces tile error toast when basemap never loaded":**
      Mock the style-fetch to reject OR never resolve. Fire `map.emit('error', { error: { status: 503 } })`. Assert: `screen.getByRole('status')` has `Basemap connection issue` text; `toast.error` spy called.

    - **Test 3 — "resets latch on basemap change":**
      Mock first style-fetch to resolve. Then change the basemap URL prop (triggering the effect re-run). Mock second style-fetch to reject. Fire `map.emit('error', { error: { status: 503 } })`. Assert: banner IS shown (latch was reset before the new fetch attempted).

    Use `toast.error` spy via `vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))` or the existing mock setup from the test file.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run src/components/builder/__tests__/BuilderMap.a11y.test.tsx src/components/builder/__tests__/BuilderMap.unit.test.ts && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "basemapLoadedAtRef" frontend/src/components/builder/BuilderMap.tsx` returns ≥ 3 (declaration + success-branch set + error-handler check + effect-start reset).
    - `grep -n "if (basemapLoadedAtRef.current !== null) return;" frontend/src/components/builder/BuilderMap.tsx` returns ≥ 1 hit inside the errorHandlerRef body.
    - All 3 new tests in `BuilderMap.a11y.test.tsx` pass.
    - Existing `BuilderMap.a11y.test.tsx` tests (including the `Basemap connection issue` test at line ~50) continue to pass.
    - Typecheck exits 0.
  </acceptance_criteria>
  <done>
    `basemapLoadedAtRef` latch suppresses transient post-load 5xx toasts; first-load and basemap-change failure paths preserved; tests assert both happy and unhappy paths.
  </done>
</task>

</tasks>

<verification>
- Saving a clean-basemap map produces only `'Map saved'` toast, no `'Basemap connection issue'` toast (verified in Plan 06 via Playwright MCP).
- Saving a map whose basemap actually IS broken still fires the `'Basemap connection issue'` toast (verified by Test 2 in vitest; Plan 06 may not exercise this path live).
- Targeted vitest passes: `BuilderMap.a11y.test.tsx` (with 3 new tests) + `BuilderMap.unit.test.ts` (regression).
- e2e:smoke:builder unchanged (verified in Plan 06).
</verification>

<success_criteria>
1. `basemapLoadedAtRef` declared next to `errorHandlerRef`.
2. Latch set in style-fetch success branch; reset at effect start on basemap change.
3. errorHandlerRef body early-returns on transient 5xx when latch is set.
4. Tests cover: (a) loaded-then-error suppressed; (b) never-loaded-then-error surfaces; (c) basemap-change resets latch.
5. Typecheck clean; no regressions in BuilderMap tests.
</success_criteria>

<output>
Create `.planning/phases/1050-builder-smoke-carryover/1050-05-SUMMARY.md` when done — record:
- Lines modified in `BuilderMap.tsx` (declaration + success-set + reset + suppression).
- New test count in `BuilderMap.a11y.test.tsx`.
- Confirmation that `setBasemapNotice('style')` (first-load failure) is NOT gated.
</output>
