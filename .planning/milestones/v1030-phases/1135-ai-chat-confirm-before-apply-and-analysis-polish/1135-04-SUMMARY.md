---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
plan: "04"
subsystem: frontend/builder/ai
tags:
  - builder
  - ai
  - suggestions
  - viewport

dependency_graph:
  requires:
    - "frontend/src/components/builder/chat-suggestions.ts (HEAD — function + geometry dispatch)"
    - "frontend/src/components/builder/ChatPanel.tsx (Plan 03 — errorBanner state, getSmartSuggestions call site)"
    - "frontend/src/components/builder/BuilderRail.tsx (Plan 03 — AIDisabledState, ChatPanel mount)"
    - "frontend/src/pages/MapBuilderPage.tsx (existing mapInstance + layers.expandedLayerId state)"
  provides:
    - "frontend/src/components/builder/chat-suggestions.ts (ViewportContext export + viewport-aware getSmartSuggestions)"
    - "frontend/src/components/builder/__tests__/chat-suggestions.test.ts (8 new AI-05 regression tests)"
    - "frontend/src/components/builder/ChatPanel.tsx (viewport?: ViewportContext prop + getSmartSuggestions 3rd arg)"
    - "frontend/src/components/builder/BuilderRail.tsx (viewport?: ViewportContext prop + ChatPanel forwarding)"
    - "frontend/src/pages/MapBuilderPage.tsx (500ms-debounced viewport state + expandedLayerId selectedLayerName sync)"
    - "frontend/src/i18n/locales/{en,de,es,fr}/builder.json (2 new suggestion keys)"
  affects:
    - "Plans 05-06: Playwright smoke + backend docstring — viewport-aware chips are live and testable"

tech_stack:
  added: []
  patterns:
    - "ViewportContext as additive optional prop — no callers broken; undefined viewport yields byte-equal behavior"
    - "500ms idle-debounce via setTimeout cleared per idle event — collapses consecutive idles to one setState"
    - "Functional setState for viewport — preserves selectedLayerName across idle events and camera updates"
    - "Priority-ordered suggestion assembly: selectedLayerName → nearby features → geometry-type → addDataset"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/chat-suggestions.ts
    - frontend/src/components/builder/__tests__/chat-suggestions.test.ts
    - frontend/src/components/builder/ChatPanel.tsx
    - frontend/src/components/builder/BuilderRail.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/__tests__/MapBuilderPage.notes-ai-rail.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "formatLayerNameForMention(name: string) parallel to mentionName(layer) — viewport.selectedLayerName is a raw string, not a MapLayerResponse, so a string-only helper avoids needing to pass a fake layer object"
  - "Functional setViewport in the idle effect — preserves prev.selectedLayerName across camera updates without adding selectedLayerName to the effect's dependency array"
  - "selectedLayerName effect guards 'if (!prev) return prev' — if camera idle hasn't fired yet, skip; the idle handler will fold selectedLayerName into the viewport on next idle"
  - "viewport added to railProps useMemo dep array — ensures suggestion chips update when viewport changes without stale closure"

requirements-completed:
  - AI-05

metrics:
  duration: "~10 minutes"
  completed: "2026-05-27"
  tasks_completed: 3
  files_created: 0
  files_modified: 10
---

# Phase 1135 Plan 04: Viewport-Aware Suggestion Chips — Summary

**ViewportContext (zoom, bounds, selectedLayerName) flows MapBuilderPage idle events → BuilderRail → ChatPanel → getSmartSuggestions to deliver viewport-aware suggestion chips with 500ms debounce, closing AI-05.**

## Performance

- **Duration:** ~10 minutes
- **Started:** 2026-05-27T18:52:00Z
- **Completed:** 2026-05-27T18:58:00Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- `getSmartSuggestions` extended with optional `viewport?: ViewportContext` param; backward compat path byte-equal to HEAD when viewport is undefined
- Priority order: selectedLayerName summarize → zoom≥12 nearby features → geometry-type → addDataset; 4-chip cap unchanged
- MapBuilderPage: map idle (500ms debounce) + expandedLayerId change both drive viewport state; passes via railProps spread to BuilderRail to ChatPanel
- 8 new vitest cases pin AI-05 behavior; 16/16 chat-suggestions tests pass; 83/83 full suite tests pass
- 2 new i18n keys (`summarizeLayer`, `nearbyFeatures`) with 4-locale parity (en/de/es/fr)
- Pitfall #3: BuilderActionSource union UNCHANGED; Pitfall #4: zero new TanStack query consumers

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | chat-suggestions.ts ViewportContext + AI-05 regression tests | `aa9edc59` | chat-suggestions.ts, chat-suggestions.test.ts, 4× builder.json |
| 2 | ChatPanel + BuilderRail viewport prop pass-through | `9a8b6740` | ChatPanel.tsx, BuilderRail.tsx |
| 3 | MapBuilderPage debounced viewport state + wire to BuilderRail | `0d7fcce7` | MapBuilderPage.tsx, MapBuilderPage.notes-ai-rail.test.tsx |

## Artifact Details

### Task 1: chat-suggestions.ts ViewportContext

**New export:** `ViewportContext` interface with `zoom: number`, `bounds: [west, south, east, north]`, `selectedLayerName?: string`.

**New signature:**
```ts
export function getSmartSuggestions(
  layers: MapLayerResponse[],
  t: AnyTFunction,
  viewport?: ViewportContext,
): string[]
```

**Priority logic (each step adds only if `suggestions.length < 4`):**
1. `viewport.selectedLayerName` → `t('chat.suggestions.summarizeLayer', { name: mention })` — leads the list
2. `viewport.zoom >= 12 && hasVectorGeometry(layers)` → `t('chat.suggestions.nearbyFeatures')`
3. Per-layer geometry dispatch (unchanged)
4. `addDataset` fallback (unchanged)

**`formatLayerNameForMention(name: string)`** — parallel to `mentionName(layer)` for raw display_name strings from viewport.selectedLayerName.

**8 new test cases:**
1. Backward compat: no viewport → geometry-only list, no summarize/nearby
2. `selectedLayerName` leads list → `out[0] === 'Summarize @Counties attributes'`
3. `selectedLayerName` with spaces → bracket-mention `@[NYC Subway]`
4. zoom ≥ 12 + vector layer → nearby features appears
5. zoom ≥ 12 but raster-only → nearby features does NOT appear
6. zoom < 12 → nearby features does NOT appear
7. 4-chip cap holds with both viewport priority items
8. (Original test retained: backward compat no-arg call)

### Task 2: ChatPanel + BuilderRail

**ChatPanel prop added:**
```ts
viewport?: ViewportContext;
```
Call site modified: `getSmartSuggestions(layers, t, viewport)` — viewport flows to the 3rd arg.

**BuilderRail prop added:**
```ts
viewport?: ViewportContext;
```
ChatPanel mount updated: `<ChatPanel ... viewport={viewport} />`.

### Task 3: MapBuilderPage

**New state:**
```ts
const [viewport, setViewport] = useState<ViewportContext | undefined>(undefined);
```

**Idle effect:**
- Subscribes to `mapInstance.on('idle', handler)` when mapInstance becomes non-null
- Handler debounces 500ms via `clearTimeout + setTimeout`
- Reads `mapInstance.getZoom()` + `mapInstance.getBounds()` on fire
- Functional setState preserves `prev.selectedLayerName` across camera updates
- Cleanup: `clearTimeout + mapInstance.off('idle', handler)` on mapInstance change

**selectedLayerName effect:**
- Reacts to `layers.expandedLayerId` + `layers.localLayers`
- Looks up `display_name ?? dataset_name` for the expanded layer
- If `prev` is undefined (camera not yet settled), skips — idle handler will fold it in
- Guards against no-op updates (`prev.selectedLayerName === name`)

**railProps update:**
```ts
const railProps = useMemo(() => ({
  // ... existing fields ...
  viewport,
}), [..., viewport]);
```
Both BuilderRail instances (`{!isEditorHidden && <BuilderRail {...railProps} />}` and `<BuilderRail {...railProps} showRail={false} />`) receive viewport via the spread.

### 2 New i18n Keys (4 locales: en/de/es/fr)

| Key | en default |
|-----|-----------|
| `chat.suggestions.summarizeLayer` | "Summarize {{name}} attributes" |
| `chat.suggestions.nearbyFeatures` | "Show nearby features in this area" |

## Verification Results

```
✓ cd frontend && npm test -- chat-suggestions.test.ts ChatPanel.test.tsx BuilderRail.test.tsx MapBuilderPage --run
  Test Files: 7 passed (7)
  Tests: 83 passed (83)
  (16 chat-suggestions: 8 original + 8 new AI-05)
  (35 ChatPanel: unchanged from Plan 03)
  (13 BuilderRail: unchanged from Plan 03)
  (19 MapBuilderPage: 18 original + 1 fixed)

✓ cd frontend && npm run typecheck
  exit 0 (clean)

✓ cd frontend && npm run test:i18n
  Tests: 2 passed (2) — 4-locale parity holds with 2 new keys

✓ git diff -- frontend/src/components/builder/builder-action-contract.ts
  EMPTY — BuilderActionSource union UNCHANGED (Pitfall #3 protection)

✓ grep -rnE "'ai-pending'|'ai-committed'" frontend/src --include="*.ts*"
  Zero matches outside chat-action-staging.ts comment

✓ git diff -- frontend/src/hooks/
  EMPTY — zero new TanStack query consumers (Pitfall #4 sweep)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] MapBuilderPage.notes-ai-rail.test.tsx asserting removed disabled-state copy**

- **Found during:** Task 3 (MapBuilderPage tests run)
- **Issue:** Test "opens the AI unavailable message from the mobile rail button" was checking for `rail.aiUnavailableTitle` text — the old plain-text disabled state removed by Plan 03. Plan 03's `AIDisabledState` replaced it with reason-based structured copy. The mock returned `{ isAIAvailable: false }` without `reason`, causing `AIDisabledState` to render a spinner (reason=null path). Test had been broken since commit `87103e4c` (Plan 03 Task 1).
- **Fix:** (1) Updated mock to `{ isAIAvailable: false, reason: 'env_disabled', isLoading: false }` so `AIDisabledState` renders structured content; (2) Updated assertion to check `rail.aiDisabledTitle` (the new title for `env_disabled`). Test's core assertion — ChatPanel NOT mounted when AI unavailable — preserved.
- **Files modified:** `frontend/src/components/builder/__tests__/MapBuilderPage.notes-ai-rail.test.tsx`
- **Committed in:** `0d7fcce7` (Task 3 commit)

**Total deviations:** 1 auto-fixed (Rule 1 — bug in test left by Plan 03)
**Impact on plan:** Fix was necessary for Task 3 verification to pass. Test accurately reflects Plan 03's behavior going forward.

## BuilderActionSource Unchanged Confirmation

```
git diff -- frontend/src/components/builder/builder-action-contract.ts
(empty)
```

`BuilderActionSource = 'manual' | 'ai' | 'system'` — byte-equal to pre-plan state. No 'ai-pending', no 'ai-committed'. v1030 hard invariant #5 holds.

## Pitfall #4 Sweep Result

No new TanStack query consumers introduced. `viewport` is a pure `useState` + `useEffect` with MapLibre event subscription. `layers.expandedLayerId` and `layers.localLayers` are values from `useBuilderLayers` (existing). No `useQuery`, `useMutation`, or `useQueryClient` calls added.

## Cross-References

- UI-SPEC Surface 5 (lines 333-385): viewport-aware suggestion chips — fully implemented
- ROADMAP AI-05: "Suggestion chips become viewport-aware" — CLOSED by this plan
- Phase 1135-03-SUMMARY.md: ChatPanel/BuilderRail as modified targets (Plans 01-03 dependency chain complete)
- Pitfall #3: BuilderActionSource invariant — verified EMPTY
- Pitfall #4 sweep: zero new AI consumer hooks (viewport = useState + map event)

## Self-Check

**Files exist:**
- `frontend/src/components/builder/chat-suggestions.ts`: FOUND (modified)
- `frontend/src/components/builder/__tests__/chat-suggestions.test.ts`: FOUND (modified)
- `frontend/src/components/builder/ChatPanel.tsx`: FOUND (modified)
- `frontend/src/components/builder/BuilderRail.tsx`: FOUND (modified)
- `frontend/src/pages/MapBuilderPage.tsx`: FOUND (modified)
- `frontend/src/i18n/locales/en/builder.json`: FOUND (modified)

**Commits exist:**
- `aa9edc59`: chat-suggestions ViewportContext + AI-05 tests
- `9a8b6740`: ChatPanel + BuilderRail viewport pass-through
- `0d7fcce7`: MapBuilderPage debounced viewport state

## Self-Check: PASSED
