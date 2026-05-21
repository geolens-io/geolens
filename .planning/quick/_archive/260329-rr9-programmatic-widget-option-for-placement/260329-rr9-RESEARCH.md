# Quick Task 260329-rr9: Programmatic Widget Placement - Research

**Researched:** 2026-03-29
**Domain:** Widget system type refactor + sidebar panel
**Confidence:** HIGH

## Summary

The current widget system uses a flat `slot: WidgetSlot` field on `WidgetDefinition` to position widgets in absolute map corners. The task replaces this with a structured `placement` object supporting two modes: `floating` (current behavior, anchored to a corner) and `sidebar` (new slide-over panel). The codebase is small and self-contained -- 6 files, ~200 lines total -- making this a clean refactor.

**Primary recommendation:** Migrate the type system first, update registrations, then split WidgetHost rendering into floating vs sidebar paths, adding a new WidgetSidebar component for the sidebar mode.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Replace flat `slot: WidgetSlot` with structured `placement` object
- `placement: { mode: 'floating', anchor: WidgetSlot }` for map-corner widgets
- `placement: { mode: 'sidebar', side: 'left' | 'right' }` for sidebar widgets
- Sidebar overlays the map (does NOT resize it)
- Multiple sidebar widgets stack vertically
- Panel auto-collapses when all sidebar widgets are closed
- Placement is fixed at registration time, users toggle visibility only

### Specific Ideas
- WidgetHost groups by mode first, then by anchor/side
- New WidgetSidebar component rendered alongside WidgetHost
- Smooth open/close animation
- WidgetPanel works in both floating and sidebar contexts
</user_constraints>

## Architecture: Current State

### File Inventory
| File | Lines | Role |
|------|-------|------|
| `types.ts` | 30 | `WidgetSlot`, `WidgetContext`, `WidgetDefinition` types |
| `registry.ts` | 17 | Simple `Map<string, WidgetDefinition>` store |
| `WidgetHost.tsx` | 95 | Groups widgets by slot, renders in absolute-positioned containers |
| `WidgetPanel.tsx` | 33 | Header (icon + title + close) + scrollable content wrapper |
| `register-widgets.ts` | 17 | Registers `measurement` (top-left) and `legend` (bottom-left) |
| `WidgetToolbar.tsx` | 70 | Popover menu to toggle widget visibility |
| `map-widget-store.ts` | 30 | Zustand store: `activeWidgets: Set<string>`, toggle/open/close |
| `index.ts` | 9 | Re-exports + side-effect import of register-widgets |

### Current WidgetSlot Values
```typescript
type WidgetSlot = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'sidebar-bottom' | 'map-overlay';
```

Note: `sidebar-bottom` and `map-overlay` exist as slot names but are just absolute positions on the map -- they are NOT actual sidebar panels.

## Architecture Patterns

### Type Migration Strategy

The `WidgetSlot` type currently serves as both the position identifier AND the CSS class lookup key. The new `placement` object separates concerns:

```typescript
/** Anchor positions for floating widgets (subset of old WidgetSlot) */
export type WidgetAnchor =
  | 'top-left'
  | 'top-right'
  | 'bottom-left'
  | 'bottom-right';

/** Placement configuration */
export type WidgetPlacement =
  | { mode: 'floating'; anchor: WidgetAnchor }
  | { mode: 'sidebar'; side: 'left' | 'right' };

export interface WidgetDefinition {
  id: string;
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
  placement: WidgetPlacement;
  component: React.ComponentType<{ ctx: WidgetContext }>;
  defaultVisible?: boolean;
}
```

**Decision point -- `map-overlay` and `sidebar-bottom`:** These two legacy slot values don't map cleanly to either floating anchors or sidebar panels. Options:
1. Keep `WidgetAnchor` extended: add `'map-overlay' | 'sidebar-bottom'` to the union -- simplest, no behavior change
2. Drop them if unused -- grep shows no widget registered with these slots currently

Recommendation: Drop them from the type since no widget uses them. If needed later, `WidgetAnchor` can be extended.

### WidgetHost Split

Current WidgetHost does one thing: group by slot, render in absolute containers. New WidgetHost should:

1. Partition `definitions` into `floating` and `sidebar` arrays based on `placement.mode`
2. Render floating widgets exactly as today (using `ANCHOR_POSITIONS` lookup)
3. Pass sidebar widgets to a new `<WidgetSidebar>` component

```typescript
// In WidgetHost
const floating = definitions.filter(w => w.placement.mode === 'floating');
const sidebarLeft = definitions.filter(w => w.placement.mode === 'sidebar' && w.placement.side === 'left');
const sidebarRight = definitions.filter(w => w.placement.mode === 'sidebar' && w.placement.side === 'right');

return (
  <>
    {/* Floating widgets -- same as before */}
    {anchors.map(anchor => { ... })}
    {/* Sidebar panels */}
    {sidebarLeft.length > 0 && <WidgetSidebar side="left" widgets={sidebarLeft} ctx={ctx} />}
    {sidebarRight.length > 0 && <WidgetSidebar side="right" widgets={sidebarRight} ctx={ctx} />}
  </>
);
```

### WidgetSidebar Component

The sidebar should be a simple overlay panel -- NOT the shadcn Sheet (which uses Radix Dialog and adds an overlay/backdrop + focus trap, which is wrong for a persistent widget panel).

Pattern: absolute-positioned div with Tailwind translate transition:

```typescript
// WidgetSidebar.tsx
interface WidgetSidebarProps {
  side: 'left' | 'right';
  widgets: WidgetDefinition[];
  ctx: WidgetContext;
}

export function WidgetSidebar({ side, widgets, ctx }: WidgetSidebarProps) {
  const isRight = side === 'right';

  return (
    <div
      className={cn(
        'absolute top-0 bottom-0 z-20 w-72 bg-background/95 backdrop-blur-sm border shadow-lg',
        'flex flex-col overflow-hidden',
        'transition-transform duration-200 ease-out',
        isRight ? 'right-0 border-l' : 'left-0 border-r',
      )}
    >
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {widgets.map(w => (
          <WidgetPanel key={w.id} def={w} onClose={() => useWidgetStore.getState().close(w.id)}>
            <WidgetErrorBoundary widgetId={w.id}>
              <w.component ctx={ctx} />
            </WidgetErrorBoundary>
          </WidgetPanel>
        ))}
      </div>
    </div>
  );
}
```

**Auto-collapse:** The sidebar renders only when `widgets.length > 0`. Since WidgetHost already filters to active widgets, closing all sidebar widgets removes them from the array, and the sidebar unmounts. For the slide-out animation, use a two-phase approach: render with translate-x-full, then remove translate on next frame (or use a `data-open` attribute approach).

### Animation Approach

Tailwind transitions are sufficient. No need for framer-motion or react-spring.

For mount/unmount animation, the simplest reliable pattern:
1. Always render the sidebar container when there are sidebar widget registrations (even if none active)
2. Use `translate-x-full` / `translate-x-0` controlled by whether any sidebar widgets are active
3. Add `pointer-events-none` when translated off-screen

This avoids the mount/unmount animation complexity entirely.

```typescript
const hasActiveSidebar = sidebarWidgets.some(w => activeWidgets.has(w.id));

<div className={cn(
  'absolute top-0 bottom-0 z-20 w-72 ...',
  'transition-transform duration-200 ease-out',
  isRight ? 'right-0' : 'left-0',
  hasActiveSidebar
    ? 'translate-x-0'
    : isRight ? 'translate-x-full' : '-translate-x-full',
  !hasActiveSidebar && 'pointer-events-none',
)}>
```

### WidgetPanel Reuse

`WidgetPanel` already works as a generic header+content wrapper. It needs no changes for sidebar context. In sidebar mode, the `min-w-48` and `rounded-lg border shadow-lg` styling is slightly redundant (sidebar provides the container), but it looks fine nested and provides visual separation between stacked widgets.

Optional refinement: pass a `variant` prop (`'floating' | 'sidebar'`) to WidgetPanel to drop the shadow/border in sidebar mode. This is cosmetic and can be deferred.

## Implementation Order

1. **types.ts** -- Replace `WidgetSlot` with `WidgetAnchor` + `WidgetPlacement`, update `WidgetDefinition`
2. **register-widgets.ts** -- Migrate existing registrations to new placement format
3. **WidgetHost.tsx** -- Split rendering by mode, extract `WidgetErrorBoundary` (shared)
4. **WidgetSidebar.tsx** -- New component for sidebar rendering
5. **WidgetToolbar.tsx** -- No changes needed (works on widget IDs, not placement)
6. **index.ts** -- Export new types + WidgetSidebar
7. **MapBuilderPage.tsx** -- No changes needed (WidgetHost handles everything internally)

## Common Pitfalls

### Pitfall 1: Z-index conflicts with map controls
**What goes wrong:** Sidebar panel renders under maplibre controls or the WidgetToolbar.
**How to avoid:** Use z-20 (matches existing `map-overlay` slot). The WidgetToolbar is z-10 -- sidebar at z-20 overlays it, which is correct since the toolbar popover is z-50 via Radix.

### Pitfall 2: Mount animation flash
**What goes wrong:** Sidebar appears at full position then snaps to translated position on first render.
**How to avoid:** Use the always-rendered + translate approach described above rather than conditional mount/unmount.

### Pitfall 3: Breaking the barrel export
**What goes wrong:** Removing `WidgetSlot` from exports breaks external consumers.
**How to avoid:** Keep `WidgetSlot` as a deprecated type alias if any file outside map-widgets imports it. Check with grep first.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Slide-over animation | Custom JS animation | Tailwind `transition-transform` + `translate-x-full` |
| Focus management | Manual focus trap | Nothing -- sidebar is persistent, not a dialog |
| Widget stacking | Custom layout engine | Simple flexbox column with gap |

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all 8 widget system files
- Existing MapBuilderPage.tsx patterns (chat panel sidebar, Sheet usage)
- Tailwind transition utilities (well-established pattern in this codebase)

## Metadata

**Confidence breakdown:**
- Type system design: HIGH - straightforward discriminated union, matches CONTEXT.md decisions exactly
- Sidebar rendering: HIGH - simple absolute-positioned div, pattern already used in codebase
- Animation: HIGH - Tailwind transitions used throughout codebase
- Integration: HIGH - changes are contained within map-widgets module

**Research date:** 2026-03-29
**Valid until:** 2026-04-28
