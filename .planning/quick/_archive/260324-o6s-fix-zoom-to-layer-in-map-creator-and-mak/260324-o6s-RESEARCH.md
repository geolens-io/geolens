# Quick Task: Fix Zoom to Layer & Resizable Sidebar - Research

**Researched:** 2026-03-24
**Domain:** Map Builder UI (React, MapLibre GL)
**Confidence:** HIGH

## Summary

Two independent fixes in the Map Builder page. The zoom-to-layer functionality is implemented but may silently fail when `dataset_extent_bbox` is null (per user decision, it should skip silently). The sidebar uses fixed Tailwind widths (`w-64 lg:w-80`) with no resize capability. No resizable panel library exists in the project; a lightweight CSS+mouse-event drag handle is the right approach.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Zoom: Skip silently when no features/bounds are available -- do not show a toast or warning
- Sidebar: Vertical drag handle on the right edge of the sidebar -- standard resizable panel pattern
- Keep the current default width unchanged -- just make it resizable from that starting point
</user_constraints>

## Bug 1: Zoom to Layer

### Code Path

1. **Trigger:** `LayerItem.tsx` line 249 -- dropdown menu item calls `onZoomToLayer(layer.id)`
2. **Handler:** `use-builder-layers.ts` lines 511-521 -- `handleZoomToLayer(layerId)`
3. **Logic:** Finds layer in `localLayers`, checks `dataset_extent_bbox`, calls `map.fitBounds()`

### Current Implementation (use-builder-layers.ts:511-521)

```typescript
function handleZoomToLayer(layerId: string) {
  const map = mapInstanceRef.current;
  if (!map) return;
  const layer = localLayers.find((l) => l.id === layerId);
  if (!layer?.dataset_extent_bbox) return;
  const bbox = layer.dataset_extent_bbox;
  map.fitBounds(
    [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
    { padding: 40, maxZoom: 18 },
  );
}
```

### Likely Root Cause

The code itself looks correct. Potential failure modes to investigate during implementation:

1. **`dataset_extent_bbox` is null** -- The backend populates this from `Record.spatial_extent`. If a record lacks spatial_extent (e.g., ingestion issue), the bbox is null and zoom silently does nothing. This is the most likely cause. Check actual API response data.

2. **Stale closure** -- `handleZoomToLayer` is a plain function inside the hook, not wrapped in `useCallback`. It captures `localLayers` from the current render. If layers were just added and state hasn't settled, the find could fail. However, this would be a transient issue.

3. **Map ref timing** -- `mapInstanceRef.current` is set on map load. If somehow called before load, it returns early. Unlikely since the user is interacting with layer items.

### Investigation Steps for Implementation

- Add a `console.log` in `handleZoomToLayer` to check: (a) is `map` non-null, (b) what is `layer?.dataset_extent_bbox`, (c) does the layer even exist in `localLayers`.
- Hit the API endpoint `GET /api/maps/{id}` and inspect the JSON -- check if `dataset_extent_bbox` is null or populated for the failing layers.

## Bug 2: Sidebar Resizability

### Current Sidebar Implementation (MapBuilderPage.tsx:151-158)

```tsx
<div className={cn(
  "relative border-r bg-background flex flex-col shrink-0 overflow-hidden transition-all duration-200",
  dialogs.sidebarCollapsed ? "w-0 border-r-0" : "w-64 lg:w-80"
)}
```

- Default width: `w-64` (256px), `lg:w-80` (320px on large screens)
- Already has collapse/expand toggle (button at right edge, lines 160-169)
- On transition end, calls `map.resize()` (line 156)

### Approach: CSS Drag Handle (no library)

No resizable panel library exists in the project. Adding one (react-resizable-panels, allotment, etc.) is overkill for a single sidebar. Use a mouse/pointer event-based drag handle.

### Implementation Pattern

```typescript
// State: sidebarWidth (default from current Tailwind class: 256 or 320 based on lg breakpoint)
const [sidebarWidth, setSidebarWidth] = useState(() =>
  window.innerWidth >= 1024 ? 320 : 256
);

// Drag handler
const handleDragStart = useCallback((e: React.PointerEvent) => {
  e.preventDefault();
  const startX = e.clientX;
  const startWidth = sidebarWidth;

  const onMove = (moveEvent: PointerEvent) => {
    const newWidth = Math.min(Math.max(startWidth + moveEvent.clientX - startX, 200), 600);
    setSidebarWidth(newWidth);
  };

  const onUp = () => {
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    mapInstanceRef.current?.resize();
  };

  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', onUp);
}, [sidebarWidth]);
```

### Key Details

- **Min width:** ~200px (enough for layer names + controls)
- **Max width:** ~600px (don't let it eat the whole map)
- **Drag handle:** 4-6px wide transparent/subtle bar on the right edge of the sidebar, `cursor: col-resize`
- **Replace Tailwind width** with inline `style={{ width: sidebarWidth }}` when not collapsed
- **Call `map.resize()`** after drag ends so MapLibre recalculates viewport
- **Persist width?** Not required by the user. Keep it session-only (useState).
- The existing collapse button (`-right-3.5`) overlaps the right edge -- position the drag handle behind/around it, or make the collapse button part of the drag handle area

### Interaction with Existing Collapse Toggle

The existing collapse/expand button sits at `absolute -right-3.5 top-1/2`. The drag handle should be the full height of the sidebar right edge. Two options:
1. **Separate elements:** Drag handle is the full-height right edge; collapse button floats on top of it
2. **Combined:** The collapse button area also serves as the drag initiation point

Option 1 is cleaner and more discoverable. The drag handle is a thin vertical bar; the collapse button sits independently.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/hooks/use-builder-layers.ts` | Debug/fix `handleZoomToLayer` -- likely needs to handle null bbox per user decision (already does, but verify) |
| `frontend/src/pages/MapBuilderPage.tsx` | Add sidebar width state, drag handle element, replace Tailwind width with inline style |

## Common Pitfalls

### MapLibre resize after width change
After changing sidebar width (drag or collapse), `map.resize()` MUST be called. The existing code already does this on `onTransitionEnd`. For drag, call it on pointer-up. During drag, you may also want to call it on each frame for smooth feedback, but it's expensive -- throttle or just call on end.

### Pointer capture
Use `setPointerCapture` on the drag handle for reliable pointer tracking even if cursor leaves the element. This prevents the drag from "sticking" if the user moves the mouse fast.

## Sources

All findings from direct codebase inspection (HIGH confidence).
- `frontend/src/pages/MapBuilderPage.tsx` -- sidebar layout, collapse toggle
- `frontend/src/hooks/use-builder-layers.ts` -- handleZoomToLayer implementation
- `frontend/src/components/builder/LayerItem.tsx` -- zoom trigger in dropdown menu
- `frontend/src/components/builder/BuilderMap.tsx` -- map ref setup, fitBounds usage
- `backend/app/maps/router.py` + `service.py` -- dataset_extent_bbox population
