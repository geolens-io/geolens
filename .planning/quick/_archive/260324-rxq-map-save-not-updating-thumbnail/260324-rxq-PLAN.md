---
phase: quick-260324-rxq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/hooks/use-builder-save.ts
autonomous: true
requirements: [QUICK-FIX]

must_haves:
  truths:
    - "Saving a map captures a thumbnail that reflects the current map state"
    - "Thumbnail updates are visible on the maps listing page after save"
    - "Thumbnail capture works whether the map is idle or actively rendering"
  artifacts:
    - path: "frontend/src/hooks/use-builder-save.ts"
      provides: "captureThumbnail with reliable canvas capture"
      contains: "loaded"
  key_links:
    - from: "frontend/src/hooks/use-builder-save.ts"
      to: "/api/maps/{id}/thumbnail"
      via: "uploadThumbnail after canvas capture"
      pattern: "uploadThumbnail"
---

<objective>
Fix map save not updating the thumbnail image.

Purpose: The `captureThumbnail` function uses `map.triggerRepaint()` then `map.once('idle', ...)` to capture the canvas. When the map is already idle (common after metadata-only saves), `triggerRepaint()` may not cause MapLibre to transition through a non-idle state, so the `idle` event never fires and the thumbnail callback is never called. The fix: capture immediately when the map is already loaded/idle, and only wait for `idle` when the map is still rendering.

Output: Reliable thumbnail capture on every save.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/hooks/use-builder-save.ts
@frontend/src/api/maps.ts
@frontend/src/components/builder/BuilderMap.tsx (preserveDrawingBuffer: true is set)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix captureThumbnail to handle already-idle maps</name>
  <files>frontend/src/hooks/use-builder-save.ts</files>
  <action>
Rewrite the `captureThumbnail` function to handle the case where the map is already idle:

1. Replace the `map.triggerRepaint(); map.once('idle', ...)` pattern with a more reliable approach:
   - Extract the canvas-capture-and-upload logic into a helper (e.g., `doCapture(map, mapId, queryClient)`)
   - In `captureThumbnail`: check if the map is already in a loaded state via `map.loaded()` (returns true if all tiles, sprites, fonts are loaded and the map is idle)
   - If `map.loaded()` is true: call `doCapture` directly — the canvas already has the current rendered state thanks to `preserveDrawingBuffer: true`
   - If `map.loaded()` is false: use `map.once('idle', () => doCapture(...))` to wait for rendering to complete
   - Remove `map.triggerRepaint()` — it's unnecessary. The map canvas already reflects the current visual state. The `triggerRepaint` call was meant to ensure the latest frame, but `preserveDrawingBuffer: true` already guarantees canvas contents persist between frames.

2. Keep the existing crop/resize logic, the offscreen canvas approach, the JPEG quality (0.7), the silent error handling, and the `queryClient.invalidateQueries({ queryKey: ['maps'] })` call unchanged.

3. Also add a small safety timeout: if we wait for `idle` but it doesn't fire within 3 seconds, capture anyway. This prevents the callback from being silently dropped in edge cases.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run frontend/src/hooks/__tests__/use-builder-save.test.ts --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>captureThumbnail reliably captures the canvas whether the map is idle or still rendering; existing tests pass</done>
</task>

</tasks>

<verification>
- Existing use-builder-save tests pass
- `captureThumbnail` handles both idle and non-idle map states
- No regression in auto-capture on first load (`maybeAutoCaptureThumbnail`)
</verification>

<success_criteria>
- Saving a map always triggers thumbnail upload (no silent drops)
- Maps listing page shows updated thumbnail after save + navigation
</success_criteria>

<output>
After completion, create `.planning/quick/260324-rxq-map-save-not-updating-thumbnail/260324-rxq-SUMMARY.md`
</output>
