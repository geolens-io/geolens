---
phase: 260320-gsh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/hooks/use-terra-draw.ts
  - frontend/src/hooks/__tests__/use-terra-draw.test.ts
  - frontend/src/components/drawing/__tests__/DrawingToolbar.test.tsx
  - frontend/src/components/drawing/AttributeForm.tsx
autonomous: true
requirements: [QA-01, QA-02, QA-03, QA-04]

must_haves:
  truths:
    - "clear() resets undo history so canUndo is false after clearing"
    - "Pure functions getAvailableModes, getModeName, extractSingleGeometry are tested for all geometry types"
    - "DrawingToolbar renders correct mode buttons for each geometry type and shows edit bar on selection"
    - "editableColumns in AttributeForm is memoized to avoid unnecessary re-renders"
  artifacts:
    - path: "frontend/src/hooks/__tests__/use-terra-draw.test.ts"
      provides: "Tests for pure functions and clear/undo bug fix"
      min_lines: 80
    - path: "frontend/src/components/drawing/__tests__/DrawingToolbar.test.tsx"
      provides: "Render tests for toolbar mode filtering and edit bar"
      min_lines: 60
  key_links:
    - from: "frontend/src/hooks/use-terra-draw.ts"
      to: "frontend/src/hooks/__tests__/use-terra-draw.test.ts"
      via: "import of exported pure functions and hook"
      pattern: "from.*use-terra-draw"
    - from: "frontend/src/components/drawing/DrawingToolbar.tsx"
      to: "frontend/src/components/drawing/__tests__/DrawingToolbar.test.tsx"
      via: "import and render test"
      pattern: "from.*DrawingToolbar"
---

<objective>
Fix bugs and fill test coverage gaps in the vector detail page map editing stack.

Purpose: The research phase identified a clear() undo-history bug, a missing useMemo, and zero test coverage for use-terra-draw pure functions and DrawingToolbar. This plan fixes the bugs and writes the missing tests.
Output: Bug fixes committed, new test files for use-terra-draw and DrawingToolbar, memoized editableColumns.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260320-gsh-qa-assessment-of-vector-detail-page-map-/260320-gsh-CONTEXT.md
@.planning/quick/260320-gsh-qa-assessment-of-vector-detail-page-map-/260320-gsh-RESEARCH.md
@frontend/src/hooks/use-terra-draw.ts
@frontend/src/components/drawing/DrawingToolbar.tsx
@frontend/src/components/drawing/AttributeForm.tsx
@frontend/src/components/dataset/__tests__/DatasetMap.test.tsx
@frontend/src/components/dataset/DatasetMap.tsx (lines 85-100 only -- extractSingleGeometry)

<interfaces>
<!-- Pure functions exported from use-terra-draw.ts -->
From frontend/src/hooks/use-terra-draw.ts:
```typescript
export const GEOMETRY_TYPE_TO_MODES: Record<string, string[]>;
export function getAvailableModes(geometryType: string | null): string[];
export function getModeName(geometryType: string): string;
```

From frontend/src/components/dataset/DatasetMap.tsx (line 87, NOT exported):
```typescript
function extractSingleGeometry(geometry: Record<string, unknown>): Record<string, unknown>;
```

From frontend/src/components/drawing/DrawingToolbar.tsx:
```typescript
interface DrawingToolbarProps {
  geometryType: string | null;
  onClose: () => void;
  onModeChange?: (mode: string) => void;
  onSaveEdit?: () => void;
  onCancelEdit?: () => void;
  onEditAttributes?: () => void;
  onDeleteFeature?: () => void;
  onUndo?: () => void;
  canUndo?: boolean;
}
export function DrawingToolbar(props: DrawingToolbarProps): JSX.Element;
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Fix clear() undo bug + write use-terra-draw pure function tests</name>
  <files>frontend/src/hooks/use-terra-draw.ts, frontend/src/hooks/__tests__/use-terra-draw.test.ts, frontend/src/components/dataset/DatasetMap.tsx</files>
  <behavior>
    - getAvailableModes(null) returns []
    - getAvailableModes('POINT') returns ['point']
    - getAvailableModes('MULTIPOLYGON') returns ['polygon', 'rectangle', 'circle', 'freehand']
    - getAvailableModes('UNKNOWN') returns []
    - getAvailableModes('point') returns ['point'] (case-insensitive via toUpperCase)
    - getModeName('Point') returns 'point'
    - getModeName('MultiPolygon') returns 'polygon'
    - getModeName('UnknownType') returns 'polygon' (default fallback)
    - extractSingleGeometry({type:'MultiPoint', coordinates:[[1,2],[3,4]]}) returns {type:'Point', coordinates:[1,2]}
    - extractSingleGeometry({type:'MultiLineString', coordinates:[[[0,0],[1,1]]]}) returns {type:'LineString', coordinates:[[0,0],[1,1]]}
    - extractSingleGeometry({type:'MultiPolygon', coordinates:[[[[0,0],[1,0],[1,1],[0,0]]]]}) returns {type:'Polygon', coordinates:[[[0,0],[1,0],[1,1],[0,0]]]}
    - extractSingleGeometry({type:'Point', coordinates:[1,2]}) returns same geometry (no-op for single types)
    - extractSingleGeometry({type:'MultiPoint', coordinates:[]}) returns same geometry (empty coordinates edge case)
  </behavior>
  <action>
1. **Export extractSingleGeometry** from DatasetMap.tsx so it can be tested. Move the function to use-terra-draw.ts (it logically belongs with the other geometry helpers) and update the import in DatasetMap.tsx.

2. **Fix the clear() undo history bug** in use-terra-draw.ts line 386-389. After `draw.clear()`, add:
   ```typescript
   historyRef.current = [];
   setCanUndo(false);
   ```

3. **Remove unused `deselectFeature`** from the useTerraDraw return object (line 398). It is never used by DatasetMap -- the deselection path uses `removeFeatures([tdId])` instead.

4. **Create test file** `frontend/src/hooks/__tests__/use-terra-draw.test.ts` with pure function tests for `getAvailableModes`, `getModeName`, and `extractSingleGeometry` covering all behaviors listed above. These are pure functions, no mocking needed.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/hooks/__tests__/use-terra-draw.test.ts --reporter=verbose</automated>
  </verify>
  <done>
    - clear() resets historyRef and sets canUndo=false
    - extractSingleGeometry moved to use-terra-draw.ts and exported
    - deselectFeature removed from useTerraDraw return
    - All pure function tests pass covering geometry type mappings and edge cases
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Write DrawingToolbar tests + memoize AttributeForm editableColumns</name>
  <files>frontend/src/components/drawing/__tests__/DrawingToolbar.test.tsx, frontend/src/components/drawing/AttributeForm.tsx</files>
  <behavior>
    - DrawingToolbar with geometryType='POINT' renders Select + Point mode buttons only
    - DrawingToolbar with geometryType='POLYGON' renders Select + Polygon + Rectangle + Circle + Freehand
    - DrawingToolbar with geometryType='LINESTRING' renders Select + Linestring
    - Active mode button has default variant, others have outline variant
    - Undo button is disabled when canUndo=false, enabled when canUndo=true
    - Edit action bar (Save, Cancel, Edit Attributes, Delete) is NOT rendered when no feature selected
    - Edit action bar IS rendered when selectedFeature is set in drawing store
    - onClose callback fires when Done/check button clicked
    - onModeChange callback fires when mode button clicked
  </behavior>
  <action>
1. **Create `frontend/src/components/drawing/__tests__/` directory** if it doesn't exist.

2. **Create DrawingToolbar.test.tsx** with render tests. Mock dependencies:
   - Mock `react-i18next` to return key as translation: `useTranslation` returns `{ t: (k: string) => k }`
   - Mock `@/stores/drawing-store` with hoisted state object (follow pattern from DatasetMap.test.tsx)
   - Mock `@/hooks/use-terra-draw` to export real `getAvailableModes` (import from actual module)

   Test each geometry type renders correct buttons by checking aria-labels. Test selectedFeature toggling edit bar visibility. Test canUndo disabled state. Test callback invocations.

3. **Memoize editableColumns** in AttributeForm.tsx line 73. The current code is:
   ```typescript
   const editableColumns = columns.filter((c) => !SYSTEM_COLUMNS.has(c.name));
   ```
   Note: `SYSTEM_COLUMNS` is a `Set` (not an array), and the `Column` interface uses `c.name` (not `c.column_name`). Wrap with `useMemo` while preserving the correct `.has()` and `.name` calls:
   ```typescript
   const editableColumns = useMemo(
     () => columns.filter((c) => !SYSTEM_COLUMNS.has(c.name)),
     [columns]
   );
   ```
   Add `useMemo` to the existing `import { ... } from 'react'` statement at the top of the file.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/components/drawing/__tests__/DrawingToolbar.test.tsx --reporter=verbose</automated>
  </verify>
  <done>
    - DrawingToolbar test file covers mode filtering for POINT/LINESTRING/POLYGON geometry types
    - Edit action bar visibility tested with and without selectedFeature
    - Undo disabled state tested
    - Callback invocations tested
    - editableColumns wrapped in useMemo in AttributeForm.tsx
    - All existing tests still pass
  </done>
</task>

<task type="auto">
  <name>Task 3: Run full test suite and verify no regressions</name>
  <files><!-- No file modifications -- this task only runs the test suite to catch regressions from Tasks 1-2 --></files>
  <action>
Run the full frontend test suite to confirm no regressions from the changes:
- extractSingleGeometry moved from DatasetMap.tsx to use-terra-draw.ts
- clear() undo fix in use-terra-draw.ts
- deselectFeature removal from useTerraDraw return
- useMemo addition in AttributeForm.tsx

If any existing tests fail due to the extractSingleGeometry move (e.g., DatasetMap tests), update imports accordingly. The function was not exported before so no external tests should reference it, but verify.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>Full frontend test suite passes with zero failures, including all new and existing tests.</done>
</task>

</tasks>

<verification>
1. `cd frontend && npx vitest run` -- all tests pass
2. `grep -n "historyRef.current = \[\]" frontend/src/hooks/use-terra-draw.ts` -- confirms clear() bug fix
3. `grep -n "export function extractSingleGeometry" frontend/src/hooks/use-terra-draw.ts` -- confirms function moved and exported
4. `grep -n "useMemo" frontend/src/components/drawing/AttributeForm.tsx` -- confirms memoization
5. `grep -rn "deselectFeature" frontend/src/hooks/use-terra-draw.ts` -- should NOT appear in return object
</verification>

<success_criteria>
- clear() bug fixed: calling clear resets undo history and canUndo
- extractSingleGeometry exported and testable from use-terra-draw.ts
- deselectFeature dead code removed from useTerraDraw return
- editableColumns memoized in AttributeForm
- New test file: use-terra-draw.test.ts with 10+ test cases for pure functions
- New test file: DrawingToolbar.test.tsx with 8+ test cases for rendering and interaction
- Full test suite passes with zero regressions
</success_criteria>

<output>
After completion, create `.planning/quick/260320-gsh-qa-assessment-of-vector-detail-page-map-/260320-gsh-SUMMARY.md`
</output>
