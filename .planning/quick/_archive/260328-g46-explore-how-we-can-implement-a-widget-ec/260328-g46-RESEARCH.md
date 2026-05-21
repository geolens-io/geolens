# Quick Task 260328-g46: Widget Ecosystem for Map Creation - Research

**Researched:** 2026-03-28
**Domain:** React widget framework for map builder UI
**Confidence:** HIGH

## Summary

The GeoLens map builder (`MapBuilderPage.tsx`) already has several "widget-like" elements positioned around the map: `MapLegend` (bottom-left absolute), `DrawingToolbar` (top-center absolute), `EphemeralBadge` (overlay), `NavigationControl` (top-right via MapLibre), and `FeaturePopup` (lat/lng anchored). These are hardcoded in position with inline `absolute` classes. The proposed widget ecosystem formalizes this into a registry + slot layout so new tools (query results, measurement, attribute table, data viz) can be added without modifying the builder page itself.

No external widget framework library is needed. The existing stack (React 19, zustand, Tailwind, shadcn/ui) provides everything required. The pattern is a lightweight registry object + a `<WidgetHost>` component that renders registered widgets into named CSS Grid / absolute-positioned slots.

**Primary recommendation:** Build a ~150-line widget infrastructure layer (types, registry, host component, shared context) using only existing dependencies. Each widget is a regular React component that receives a typed context prop.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- General-purpose modular widget framework, not limited to a fixed set
- Initial target widgets: layer query + results display, measurement tool, attribute table, data visualization (charts/stats)
- Fixed slot positions (top-left, bottom-right, sidebar, etc.) -- no drag-and-drop or floating panel logic
- Predefined layout zones -- no z-index/overlap management
- Dev-only extensibility: widgets are React components registered in code
- Type-safe widget API with clean registration pattern
- Ships with the app -- no dynamic loading, no plugin marketplace, no admin config UI

### Claude's Discretion
- None -- all areas discussed

### Deferred Ideas (OUT OF SCOPE)
- None listed
</user_constraints>

## Architecture Patterns

### Recommended Structure

```
frontend/src/
  components/
    widgets/
      types.ts              # WidgetDefinition, WidgetSlot, WidgetContext interfaces
      registry.ts           # Widget registry (Map<string, WidgetDefinition>)
      WidgetHost.tsx         # Renders widgets into slot positions on the map
      WidgetPanel.tsx        # Shared panel chrome (header, collapse, close)
      index.ts              # Public API barrel
      builtin/
        QueryResultsWidget.tsx
        MeasurementWidget.tsx
        AttributeTableWidget.tsx
        DataVizWidget.tsx
```

### Pattern: Widget Definition Type

Each widget is described by a plain object satisfying a `WidgetDefinition` interface. No classes, no inheritance, no HOCs.

```typescript
// widgets/types.ts

/** Named positions where widgets can render */
export type WidgetSlot =
  | 'top-left'
  | 'top-right'
  | 'bottom-left'
  | 'bottom-right'
  | 'sidebar-bottom'   // below the layer panel in the sidebar
  | 'map-overlay';     // full-width strip above the map (attribute table)

/** Context every widget receives */
export interface WidgetContext {
  mapInstance: MaplibreMap | null;
  layers: MapLayerResponse[];
  mapId: string;
  // Extend as needed -- keep narrow
}

/** A registered widget */
export interface WidgetDefinition {
  id: string;                                    // unique key, e.g. 'measurement'
  label: string;                                 // human-readable name (i18n key)
  icon: React.ComponentType<{ className?: string }>;
  slot: WidgetSlot;                              // default position
  component: React.ComponentType<{ ctx: WidgetContext }>;
  /** Whether widget is shown by default when map opens */
  defaultVisible?: boolean;
}
```

### Pattern: Registry as Plain Map

```typescript
// widgets/registry.ts
import type { WidgetDefinition } from './types';

const registry = new Map<string, WidgetDefinition>();

export function registerWidget(def: WidgetDefinition) {
  if (registry.has(def.id)) {
    console.warn(`Widget "${def.id}" already registered, overwriting.`);
  }
  registry.set(def.id, def);
}

export function getWidgets(): WidgetDefinition[] {
  return Array.from(registry.values());
}

export function getWidget(id: string): WidgetDefinition | undefined {
  return registry.get(id);
}
```

### Pattern: Widget Host Component

```typescript
// widgets/WidgetHost.tsx
// Reads active widgets from a zustand store, groups by slot, renders into
// absolute-positioned containers that mirror existing MapLegend / DrawingToolbar placement.

export function WidgetHost({ ctx }: { ctx: WidgetContext }) {
  const activeWidgets = useWidgetStore((s) => s.activeWidgets);
  const definitions = getWidgets().filter((w) => activeWidgets.has(w.id));

  // Group by slot
  const bySlot = groupBy(definitions, (w) => w.slot);

  return (
    <>
      {SLOT_POSITIONS.map(({ slot, className }) => {
        const widgets = bySlot[slot] ?? [];
        if (widgets.length === 0) return null;
        return (
          <div key={slot} className={className}>
            {widgets.map((w) => (
              <WidgetPanel key={w.id} def={w} onClose={() => toggle(w.id)}>
                <w.component ctx={ctx} />
              </WidgetPanel>
            ))}
          </div>
        );
      })}
    </>
  );
}
```

### Pattern: Widget Visibility Store (zustand)

```typescript
// stores/widget-store.ts
interface WidgetState {
  activeWidgets: Set<string>;
  toggle: (id: string) => void;
  open: (id: string) => void;
  close: (id: string) => void;
}

export const useWidgetStore = create<WidgetState>()((set) => ({
  activeWidgets: new Set<string>(),
  toggle: (id) => set((s) => {
    const next = new Set(s.activeWidgets);
    next.has(id) ? next.delete(id) : next.add(id);
    return { activeWidgets: next };
  }),
  open: (id) => set((s) => {
    const next = new Set(s.activeWidgets);
    next.add(id);
    return { activeWidgets: next };
  }),
  close: (id) => set((s) => {
    const next = new Set(s.activeWidgets);
    next.delete(id);
    return { activeWidgets: next };
  }),
}));
```

### Slot Position Layout

Fixed positions using absolute/Tailwind classes (matches existing patterns like `MapLegend`):

| Slot | CSS Position | Example Widget |
|------|-------------|----------------|
| `top-left` | `absolute top-3 left-3 z-10` | Measurement results |
| `top-right` | `absolute top-14 right-3 z-10` (below nav control) | Query tool |
| `bottom-left` | `absolute bottom-4 left-4 z-10` | Legend (existing) |
| `bottom-right` | `absolute bottom-4 right-4 z-10` | Data viz minicard |
| `sidebar-bottom` | Flex child in sidebar column | Attribute mini-table |
| `map-overlay` | `absolute bottom-0 left-0 right-0 z-20` | Full attribute table |

### Integration with MapBuilderPage

Minimal change to the existing page. Inside the `{/* Map */}` relative container, add:

```tsx
<WidgetHost ctx={{ mapInstance: mapInstanceRef.current, layers: layers.localLayers, mapId: id! }} />
```

And add a widget toolbar/toggle row (small icon buttons) in the sidebar header area, next to the existing AI chat button.

### Anti-Patterns to Avoid

- **Don't use React Context for the registry.** A plain module-level Map is simpler, tree-shakeable, and avoids re-render cascades. Context is for runtime-varying values (active widget state belongs in zustand, not the registry).
- **Don't create a widget "base class."** This is React -- composition via typed props, not inheritance.
- **Don't put widget state in the widget store.** Each widget manages its own internal state. The store only tracks which widgets are visible. Widget-specific state (measurement points, query results) lives inside the widget component or in dedicated stores.
- **Don't couple widgets to BuilderMap internals.** Widgets receive the MapLibre instance via `WidgetContext`. They should use public MapLibre APIs, not internal refs from map-sync.ts.

## Existing Code to Migrate / Coexist With

| Current Component | Relationship to Widget System |
|---|---|
| `MapLegend` | Could become `bottom-left` slot widget, but also works as-is. Migrate later if needed. |
| `DrawingToolbar` | Stays separate -- it's a mode toolbar, not an informational widget. |
| `FeaturePopup` | Stays as MapLibre Popup (geo-anchored). Not a slot widget. |
| `EphemeralBadge` | Stays -- it's a transient notification, not a persistent widget. |
| `ChatPanel` | Stays as sidebar rail. Could later be a widget but has unique layout (full-height rail). |

The widget system coexists with these. No need to migrate existing overlays in the first pass.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Panel chrome (collapse, close, drag-to-resize) | Custom panel container | shadcn Card + existing Tailwind patterns | Already have the pattern in sidebar resize |
| Measurement calculations | Custom distance/area math | `@turf/length`, `@turf/area` (tree-shakeable) | Geodesic calculations are non-trivial |
| Attribute table | Custom table rendering | `@tanstack/react-table` (already installed) | Virtualization, sorting, filtering for free |
| State management | Custom pub/sub or context | zustand (already installed) | Consistent with rest of app |
| Charts | Custom SVG chart components | Lightweight library TBD per widget | Charting is a solved problem |

## Common Pitfalls

### Pitfall 1: Widget Bloating WidgetContext
**What goes wrong:** Adding every possible callback and data source to WidgetContext, making it a god object.
**How to avoid:** Keep WidgetContext minimal (map instance, layers, mapId). Widgets that need more (e.g., the query widget needs feature API access) should import their own hooks (`useFeatures`, etc.) directly. The context provides map-specific shared state only.

### Pitfall 2: Z-Index Wars
**What goes wrong:** Multiple widgets in adjacent slots overlap or hide each other on small screens.
**How to avoid:** Fixed slot system already prevents this by design. Each slot has one z-index level. If two widgets share a slot, stack them vertically within the slot container with a gap. Set a max-height on each widget panel and make content scrollable.

### Pitfall 3: Map Resize Not Triggered
**What goes wrong:** Opening/closing a sidebar widget or bottom overlay changes the map viewport dimensions but MapLibre doesn't know.
**How to avoid:** Call `mapInstance.resize()` whenever a widget that affects map container size opens/closes. The existing sidebar already does this pattern (see `onTransitionEnd` in MapBuilderPage).

### Pitfall 4: Stale Map Instance
**What goes wrong:** Widget receives null map instance on first render because the map hasn't loaded yet.
**How to avoid:** WidgetHost should only render slot containers after mapReady is true (already tracked in BuilderMap via `useState`). Pass mapReady as part of context, or conditionally render.

### Pitfall 5: Widget Registration Timing
**What goes wrong:** Widgets registered after WidgetHost mounts don't appear.
**How to avoid:** Register all built-in widgets in a single `register-widgets.ts` file imported at app startup (before router). The registry is static for built-in widgets. No dynamic registration at runtime is needed per the decisions.

## Widget Implementation Notes

### Query Results Widget
- Uses existing `apiFetch` / TanStack Query to call the features API
- Displays results in a scrollable list with click-to-highlight on map
- Interacts with map via `mapInstance.queryRenderedFeatures()` or backend feature query
- Slot: `top-right` or `sidebar-bottom`

### Measurement Widget
- Leverages existing `terra-draw` integration (already installed)
- Calculates distance/area using `@turf/length` and `@turf/area` (need to add)
- Displays live measurements as user draws
- Slot: `top-left`

### Attribute Table Widget
- Uses `@tanstack/react-table` (already installed)
- Fetches features for selected layer via existing features API
- Slot: `map-overlay` (bottom sheet pattern, resizable height)
- Highlight row on map click, pan to feature on table row click

### Data Viz Widget
- Charts/stats for numeric columns of a selected layer
- Slot: `bottom-right` or `sidebar-bottom`
- Library decision deferred -- recharts or lightweight alternative

## New Dependencies

| Library | Purpose | Confidence |
|---------|---------|------------|
| `@turf/length` | Geodesic line distance | HIGH -- standard, tree-shakeable |
| `@turf/area` | Geodesic polygon area | HIGH -- standard, tree-shakeable |
| `@turf/helpers` | GeoJSON type constructors | HIGH -- peer dep of above |

No framework dependencies needed. The widget system is ~150 lines of custom code on top of existing zustand + React patterns.

## Open Questions

1. **Should MapLegend become a widget?** It currently renders unconditionally. Making it a widget adds toggle behavior but is not required for v1. Recommend: leave as-is, migrate later.
2. **Attribute table height management:** Bottom overlay widgets reduce map viewport. Need to decide on a fixed height (e.g., 250px) vs user-resizable. Recommend: start with fixed height + collapse toggle, add resize later.
3. **Widget toolbar placement:** Where do the toggle buttons go? Options: (a) in sidebar header next to AI chat button, (b) as a floating toolbar on the map, (c) in a dedicated "Tools" section in the sidebar. Recommend: (a) for consistency with existing UI.
4. **Charts library for data viz widget:** recharts (popular, 200KB) vs lightweight alternatives. Can defer until data viz widget is actually built.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `MapBuilderPage.tsx`, `BuilderMap.tsx`, `MapLegend.tsx`, `DrawingToolbar.tsx`, `drawing-store.ts`
- Existing patterns: zustand stores, shadcn/ui components, absolute positioning for map overlays
- Package.json: confirmed `@tanstack/react-table`, `terra-draw`, `zustand` already installed

### Secondary (MEDIUM confidence)
- Turf.js tree-shakeability: well-established pattern for `@turf/*` modular packages

## Metadata

**Confidence breakdown:**
- Architecture: HIGH -- follows existing codebase patterns exactly
- Widget types: HIGH -- all target widgets map to existing APIs and libraries
- Pitfalls: HIGH -- derived from actual codebase analysis of existing overlay components

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable patterns, no external dependency churn)
