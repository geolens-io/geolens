# Widget Development Guide

Widgets extend the Map Builder with custom tools and panels. This guide covers creating, registering, and configuring widgets.

## Architecture

Widgets are React components registered at import time via a module-level registry. The system supports two placement modes:

- **Floating** — positioned over the map at a corner anchor (top-left, top-right, bottom-left, bottom-right)
- **Sidebar** — rendered as a section in the builder's left sidebar, below the Layers panel

All widgets appear in the Widgets toolbar popover, where users can toggle them on/off. Admin settings can restrict which widgets are available.

### Key files

| File | Purpose |
|------|---------|
| `frontend/src/components/map-widgets/types.ts` | Type definitions |
| `frontend/src/components/map-widgets/registry.ts` | Registration API |
| `frontend/src/components/map-widgets/register-widgets.ts` | Built-in widget registrations |
| `frontend/src/components/map-widgets/WidgetHost.tsx` | Floating widget renderer + sidebar section |
| `frontend/src/components/map-widgets/WidgetPanel.tsx` | Widget wrapper (header, close button) |
| `frontend/src/components/map-widgets/WidgetToolbar.tsx` | Toolbar popover (toggle widgets on/off) |
| `frontend/src/components/map-widgets/builtin/` | Built-in widget components |

## Creating a widget

### 1. Write the component

Create a file in `frontend/src/components/map-widgets/builtin/`:

```tsx
// builtin/MyWidget.tsx
import type { WidgetContext } from '../types';

export function MyWidget({ ctx }: { ctx: WidgetContext }) {
  // ctx.mapInstance — MapLibre GL map instance (may be null during load)
  // ctx.layers     — current map layers (MapLayerResponse[])
  // ctx.mapId      — map ID for API calls

  return (
    <div className="text-xs">
      <p>Map has {ctx.layers.length} layers</p>
    </div>
  );
}
```

Every widget receives a `WidgetContext` prop with access to the map instance, layer data, and map ID.

### 2. Register the widget

Add the registration to `register-widgets.ts`:

```ts
import { MyIcon } from 'lucide-react';
import { MyWidget } from './builtin/MyWidget';

registerWidget({
  id: 'my-widget',
  labelKey: 'widgets.myWidget.label',
  icon: MyIcon,
  placement: { mode: 'floating', anchor: 'top-left' },
  component: MyWidget,
  defaultVisible: false,
});
```

### 3. Add the i18n label

Add the label to each locale file in `frontend/src/i18n/locales/{lang}/builder.json` under the `widgets` key:

```json
{
  "widgets": {
    "myWidget": {
      "label": "My Widget"
    }
  }
}
```

## Registration options

```ts
interface WidgetDefinition {
  id: string;               // Unique identifier
  labelKey: string;          // i18n key under 'builder' namespace
  icon: ComponentType;       // Lucide icon or custom SVG component
  placement: WidgetPlacement;
  component: ComponentType<{ ctx: WidgetContext }>;
  defaultVisible?: boolean;  // Auto-open on page load (default: false)
}
```

### Placement modes

**Floating** — overlays the map at a fixed corner:

```ts
placement: { mode: 'floating', anchor: 'top-left' }
// anchor options: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
```

**Sidebar** — renders in the builder's left sidebar (reserved for future use):

```ts
placement: { mode: 'sidebar' }
```

## Widget context

The `WidgetContext` provides everything a widget needs:

```ts
interface WidgetContext {
  mapInstance: MaplibreMap | null;  // MapLibre GL instance
  layers: MapLayerResponse[];       // Current map layers
  mapId: string;                    // Map ID for API calls
}
```

- **`mapInstance`** — may be `null` during initial load. Guard accordingly.
- **`layers`** — reactive; updates when layers are added, removed, or reordered.
- **`mapId`** — use with `apiFetch()` for map-specific API calls.

## Built-in widgets

| Widget | ID | Placement | Default visible |
|--------|----|-----------|-----------------|
| Measurement | `measurement` | `floating: top-left` | No |
| Legend | `legend` | `floating: bottom-left` | Yes |

## Error handling

Each widget is wrapped in a `WidgetErrorBoundary`. If a widget throws during render, it shows an error fallback without affecting other widgets. Errors are logged to the console with the widget ID.

## Admin control

Admins can restrict which widgets are available via the `enabled_widgets` setting:

- **`null`** (default) — all registered widgets are available
- **`["measurement", "legend"]`** — only listed widgets appear in the toolbar
- **`[]`** — no widgets available

This is configured via `PUT /api/settings/` with `{"settings": {"enabled_widgets": [...]}}`.

## Tips

- Keep widgets small and focused — one concern per widget.
- Use `useTranslation('builder')` for all user-facing text.
- Floating widgets should be compact; sidebar widgets can be taller.
- The `WidgetPanel` wrapper provides the header and close button automatically — don't add your own.
- Test with the widget toggled on/off to verify cleanup (especially for widgets that add map layers or event listeners).
