# Widget Ecosystem

A modular framework for adding interactive widgets to the map builder. Widgets are React components that developers register in code. Admins control which are available; map authors toggle them per-map.

## Architecture

```
Developer registers widget (code)
        │
        ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Registry    │────▶│  Admin Settings   │────▶│  Map Builder │
│  (module)    │     │  enabled_widgets  │     │  WidgetHost  │
└─────────────┘     └──────────────────┘     └─────────────┘
                                                     │
                                              ┌──────┴──────┐
                                              │ WidgetPanel  │ (chrome)
                                              │ ErrorBoundary│
                                              │ Your Widget  │
                                              └─────────────┘
```

**Three-tier control:**
1. **Developer** — registers widgets in code via `registerWidget()`
2. **Admin** — enables/disables globally at Settings > Map > Map Widgets
3. **Map Author** — toggles per-map via the toolbar button; saved with the map

## Creating a Widget

### 1. Create the component

```tsx
// src/components/map-widgets/builtin/MyWidget.tsx
import type { WidgetContext } from '../types';

export function MyWidget({ ctx }: { ctx: WidgetContext }) {
  return (
    <div className="text-xs space-y-1">
      <p>Map: {ctx.mapId}</p>
      <p>Layers: {ctx.layers.length}</p>
    </div>
  );
}
```

### 2. Register it

Add to `src/components/map-widgets/register-widgets.ts`:

```tsx
import { Ruler } from 'lucide-react';
import { registerWidget } from './registry';
import { MyWidget } from './builtin/MyWidget';

registerWidget({
  id: 'my-widget',           // Stable string ID (persisted in maps and admin settings)
  label: 'My Widget',        // Shown in toolbar and panel header
  icon: Ruler,               // Any lucide-react icon
  slot: 'top-right',         // Where it renders on the map
  component: MyWidget,
  defaultVisible: false,      // true = auto-open on new maps
});
```

### 3. That's it

The widget automatically appears in:
- The map builder toolbar (popover toggle)
- The admin Settings > Map > Map Widgets section
- Saved/restored per-map when the author hits Save

## WidgetContext

Every widget receives a `ctx` prop with:

| Field | Type | Description |
|-------|------|-------------|
| `mapInstance` | `MaplibreMap \| null` | The MapLibre GL map instance. May be `null` during initial render — check before using. |
| `layers` | `MapLayerResponse[]` | Current map layers (from the builder's local state). |
| `mapId` | `string` | The map's UUID. |

## Slots

Fixed positions on the map. No drag-and-drop.

| Slot | Position | CSS offset |
|------|----------|------------|
| `top-left` | Top-left corner (below sidebar edge) | `top-3 left-3` |
| `top-right` | Top-right corner (below zoom controls) | `top-14 right-3` |
| `bottom-left` | Above the map legend (`bottom-20`) | `bottom-20 left-4` |
| `bottom-right` | Bottom-right corner | `bottom-4 right-4` |
| `sidebar-bottom` | True bottom-left corner (`bottom-4`) | `bottom-4 left-4` |
| `map-overlay` | Full-width bar at bottom, z-20 |

## Error Handling

Each widget is wrapped in an error boundary. If your widget throws during render, only your widget shows a fallback — other widgets and the map are unaffected. Errors are logged to the console with the widget ID.

## Content Constraints

`WidgetPanel` wraps your component in a container with `max-h-64 overflow-auto` (256px max height with scroll). If your widget needs more space (e.g., an attribute table), consider using `map-overlay` slot which spans the full width, or request a custom panel via the `WidgetDefinition` API.

The panel provides a header (icon + label + close button) and a `p-2.5` padded content area. Your component receives the full width of the panel (`min-w-48`).

## Widget ID Rules

- Must be a stable, unique string (e.g., `measurement`, `attribute-table`)
- Persisted in two places: `map.widgets` (per-map) and `enabled_widgets` (admin setting)
- If you rename an ID, existing maps and admin config referencing the old ID will silently ignore it
- Dead IDs are filtered on load — no errors, just invisible

## Files

| File | Purpose |
|------|---------|
| `types.ts` | `WidgetSlot`, `WidgetContext`, `WidgetDefinition` |
| `registry.ts` | Module-level `Map<string, WidgetDefinition>` |
| `register-widgets.ts` | Side-effect imports that register built-in widgets |
| `index.ts` | Barrel export (triggers registration on import) |
| `WidgetHost.tsx` | Slot-based renderer with error boundary |
| `WidgetToolbar.tsx` | Popover button for toggling widgets |
| `WidgetPanel.tsx` | Shared chrome (header, close button) |
| `builtin/PlaceholderWidget.tsx` | Proof-of-concept (safe to delete) |

## Persistence

- **Per-map:** `map.widgets` field (JSONB). `null` = use defaults, `[]` = none, `["id"]` = explicit.
- **Admin:** `enabled_widgets` setting. `null` = all enabled (default), `[]` = none, `["id"]` = only those.
- **Session:** `useWidgetStore` (zustand, no localStorage). Cleared on page navigation.
