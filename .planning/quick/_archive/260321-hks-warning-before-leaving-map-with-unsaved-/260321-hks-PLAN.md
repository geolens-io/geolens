---
phase: quick-260321-hks
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/hooks/use-builder-save.ts
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
autonomous: true
requirements: [QUICK-260321-HKS]

must_haves:
  truths:
    - "Browser tab/refresh shows native confirmation dialog when map has unsaved changes"
    - "In-app navigation (clicking links/back button) shows confirmation dialog when map has unsaved changes"
    - "No warning appears when map has no unsaved changes"
    - "User can cancel navigation and stay on the builder page"
    - "User can confirm navigation and leave despite unsaved changes"
  artifacts:
    - path: "frontend/src/hooks/use-builder-save.ts"
      provides: "beforeunload handler and useBlocker for in-app navigation guard"
      contains: "beforeunload"
    - path: "frontend/src/i18n/locales/en/builder.json"
      provides: "i18n keys for unsaved changes warning dialog"
      contains: "leaveWarning"
  key_links:
    - from: "frontend/src/hooks/use-builder-save.ts"
      to: "layers.hasUnsavedChanges"
      via: "SaveState interface receives hasUnsavedChanges boolean"
      pattern: "hasUnsavedChanges"
    - from: "frontend/src/hooks/use-builder-save.ts"
      to: "react-router useBlocker"
      via: "blocks in-app navigation when dirty"
      pattern: "useBlocker"
---

<objective>
Add an unsaved-changes guard to the Map Builder so users are warned before accidentally losing work by navigating away or refreshing.

Purpose: Prevent data loss when users have made map edits (layers, name, basemap, etc.) but haven't saved.
Output: Two guards -- browser `beforeunload` for tab close/refresh, and react-router `useBlocker` for in-app navigation -- plus a confirmation dialog for in-app nav.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/hooks/use-builder-save.ts
@frontend/src/pages/MapBuilderPage.tsx
@frontend/src/hooks/use-builder-layers.ts
@frontend/src/i18n/locales/en/builder.json

<interfaces>
From frontend/src/hooks/use-builder-save.ts:
```typescript
interface SaveState {
  mapId: string | undefined;
  localLayers: MapLayerResponse[];
  localBasemap: string;
  localName: string;
  localDescription: string;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  setHasUnsavedChanges: (v: boolean) => void;
}

export function useBuilderSave(state: SaveState): {
  handleSave: () => void;
  handleExportPNG: () => void;
  handleFork: () => Promise<void>;
  isSaving: boolean;
  isForkPending: boolean;
};
```

From frontend/src/hooks/use-builder-layers.ts:
```typescript
// Returns object with:
hasUnsavedChanges: boolean;
setHasUnsavedChanges: (v: boolean) => void;
markDirty: () => void;
```

DatasetPage already has a beforeunload pattern (lines 294-302) that can be referenced but NOT react-router blocking.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add navigation guards to useBuilderSave and i18n keys</name>
  <files>frontend/src/hooks/use-builder-save.ts, frontend/src/pages/MapBuilderPage.tsx, frontend/src/i18n/locales/en/builder.json, frontend/src/i18n/locales/de/builder.json, frontend/src/i18n/locales/es/builder.json, frontend/src/i18n/locales/fr/builder.json</files>
  <action>
1. **Extend SaveState interface** in `use-builder-save.ts`: Add `hasUnsavedChanges: boolean` field.

2. **Add beforeunload guard** in `useBuilderSave`: Add a `useEffect` that listens for `beforeunload` when `state.hasUnsavedChanges` is true, calling `e.preventDefault()`. Pattern matches DatasetPage lines 294-302.

3. **Add react-router useBlocker** in `useBuilderSave`: Import `useBlocker` from `react-router`. Call `useBlocker(state.hasUnsavedChanges)` -- react-router v7 signature is `useBlocker(boolean | BlockerFunction)`, passing the boolean directly (do NOT pass an object like `{ when: ... }` which would make the blocker always-active). This returns a `blocker` object with `state` ('blocked' | 'unblocked' | 'proceeding'), `proceed()`, and `reset()` methods. Return `blocker` from the hook.

4. **Update useBuilderSave return**: Add `blocker` to the returned object.

5. **Update MapBuilderPage.tsx**: Pass `hasUnsavedChanges: layers.hasUnsavedChanges` in the `useBuilderSave` call. Render a confirmation dialog when `save.blocker.state === 'blocked'`:
   - Use the existing `Dialog` / `DialogContent` / `DialogHeader` / `DialogTitle` / `DialogDescription` components already imported
   - Dialog open when `save.blocker.state === 'blocked'`
   - Title: `t('leaveWarning.title')` -- "Unsaved changes"
   - Description: `t('leaveWarning.description')` -- "You have unsaved map changes that will be lost."
   - Two buttons in a `flex justify-end gap-2` footer:
     - "Stay" (`variant="outline"`) calls `save.blocker.reset()` -- key: `t('leaveWarning.stay')`
     - "Leave" (`variant="destructive"`) calls `save.blocker.proceed()` -- key: `t('leaveWarning.leave')`

6. **Add i18n keys** to all 4 locale files under a new `"leaveWarning"` section:
   - en: `{ "title": "Unsaved changes", "description": "You have unsaved map changes that will be lost.", "stay": "Stay", "leave": "Leave" }`
   - de: `{ "title": "Nicht gespeicherte Aenderungen", "description": "Nicht gespeicherte Kartenänderungen gehen verloren.", "stay": "Bleiben", "leave": "Verlassen" }`
   - es: `{ "title": "Cambios sin guardar", "description": "Los cambios no guardados del mapa se perderán.", "stay": "Quedarse", "leave": "Salir" }`
   - fr: `{ "title": "Modifications non enregistrées", "description": "Les modifications non enregistrées de la carte seront perdues.", "stay": "Rester", "leave": "Quitter" }`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - beforeunload prevents tab close/refresh with unsaved changes
    - useBlocker prevents in-app navigation with unsaved changes
    - Confirmation dialog renders with Stay/Leave options when blocked
    - All 4 locale files have leaveWarning keys
    - TypeScript compiles without errors
  </done>
</task>

<task type="auto">
  <name>Task 2: Verify guards work with existing test infrastructure</name>
  <files>frontend/src/hooks/__tests__/use-builder-save.test.ts</files>
  <action>
Check if `frontend/src/hooks/__tests__/use-builder-save.test.ts` exists. If it does, add test cases:
- Test that `blocker` is returned from hook
- Test that beforeunload listener is added when hasUnsavedChanges=true and removed when false

If no test file exists, verify by running the existing builder test suite to confirm no regressions.

Run the full frontend test suite to confirm nothing breaks.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>
    - All existing tests pass
    - No regressions in builder hooks or components
  </done>
</task>

</tasks>

<verification>
- TypeScript compiles: `cd frontend && npx tsc --noEmit`
- All tests pass: `cd frontend && npx vitest run`
- Manual: Open map builder, make a change (e.g. rename), try navigating away -- dialog should appear
- Manual: With no changes, navigate freely -- no dialog
</verification>

<success_criteria>
- Browser beforeunload fires on tab close/refresh with unsaved changes
- react-router useBlocker shows confirmation dialog on in-app navigation with unsaved changes
- User can cancel (stay) or confirm (leave) via dialog
- No warning when map is clean (no unsaved changes)
- All i18n strings present in en/de/es/fr
</success_criteria>

<output>
After completion, create `.planning/quick/260321-hks-warning-before-leaving-map-with-unsaved-/260321-hks-SUMMARY.md`
</output>
