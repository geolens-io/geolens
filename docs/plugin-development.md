# Plugin Development Guide

This guide explains how the map **plugin platform** works and how to author a new
plugin. The platform lives in `frontend/src/components/map-plugins/` and provides a
pluggable system for in-map tools (measurement, legend, and anything you add).

## 1. Overview

A *plugin* is a self-contained, registry-driven map tool. The platform has three
moving parts:

- **Registry** (`registry.ts`) — an in-memory map of plugin id → definition.
- **Host / panel** (`PluginHost.tsx`, `PluginPanel.tsx`, `PluginErrorBoundary.tsx`)
  — renders the currently-open, available plugins onto the map.
- **Availability gating** (`plugin-availability.ts`) — restricts which registered
  plugins are surfaced based on a deployment's `enabled_plugins` setting.

The built-in plugins **at the time of writing** are `measurement` and `legend`.
**`register-plugins.ts` is the source of truth for the built-in set** — treat any
built-in list written in prose (including this sentence) as informational only.
The plugin IDs `measurement` and `legend` are preserved literals and must not be
renamed.

## 2. The registry (`registry.ts`)

The registry exposes three functions:

| Function | Signature | Behavior |
| --- | --- | --- |
| `registerPlugin` | `(def: PluginDefinition): void` | Registers a plugin by `def.id`. On a duplicate id it overwrites and, in DEV builds only, emits a `console.warn`. |
| `getPlugins` | `(): PluginDefinition[]` | Returns every registered plugin. The result is **memoized**; the cache is invalidated whenever `registerPlugin` runs. |
| `getPlugin` | `(id: string): PluginDefinition \| undefined` | Looks up a single plugin by id. |

The getter for the full set is `getPlugins` (no other getter name exists).

## 3. Registering built-ins (`register-plugins.ts`)

`register-plugins.ts` is imported for its side effects: at import time it calls
`registerPlugin(...)` once per built-in. Today it registers:

- `measurement` — component `MeasurementPlugin`, `labelKey: 'plugins.measurement.label'`,
  floating top-left, `defaultVisible: false`.
- `legend` — component `LegendPlugin`, `labelKey: 'plugins.legend.label'`,
  floating bottom-left, `defaultVisible: true`.

The IDs `measurement` and `legend` are preserved literals (v1036 invariant). To add
a new built-in, add another `registerPlugin({ ... })` call here.

```ts
import { Ruler } from 'lucide-react';
import { registerPlugin } from './registry';
import { MeasurementPlugin } from './builtin/MeasurementPlugin';

registerPlugin({
  id: 'measurement',
  labelKey: 'plugins.measurement.label',
  icon: Ruler,
  placement: { mode: 'floating', anchor: 'top-left' },
  component: MeasurementPlugin,
  defaultVisible: false,
});
```

## 4. The `PluginDefinition` shape (`types.ts`)

A plugin is described by the `PluginDefinition` interface, which is declared in
`types.ts`:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `string` | Unique registry key. Preserved literal for built-ins. |
| `labelKey` | `string` | i18n key under the `builder` namespace, e.g. `'plugins.measurement.label'`. |
| `icon` | `React.ComponentType<{ className?: string }>` | Header icon (a lucide-react icon works). |
| `placement` | `PluginPlacement` | Where the plugin renders (see below). |
| `component` | `React.ComponentType<{ ctx: PluginContext }>` | The plugin body; receives a `PluginContext`. |
| `defaultVisible` | `boolean` (optional) | Whether the plugin opens by default. |

`PluginPlacement` is a discriminated union:

```ts
type PluginPlacement =
  | { mode: 'floating'; anchor: PluginAnchor }   // anchored to a map corner
  | { mode: 'sidebar' };                          // rendered in the builder's left sidebar
```

`PluginAnchor` is `'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'`.

Every plugin component receives a `PluginContext`:

| Field | Type | Notes |
| --- | --- | --- |
| `mapInstance` | `Map \| null` (maplibre-gl) | The live map, or `null` before load. |
| `layers` | `MapLayerResponse[]` | The map's current layers. |
| `mapId` | `string` | The current map's id. |

## 5. Availability gating (`plugin-availability.ts`)

A deployment can restrict which plugins are surfaced via the `enabled_plugins`
setting. The semantics of that value are:

- `null` (or `undefined`) — **no restriction**; every registered plugin is available.
- `[]` — **no plugins** available.
- `['legend', ...]` — only the listed ids are available.

The helpers (all operate against the registry via `getPlugins()`):

| Function | Purpose |
| --- | --- |
| `getEnabledPluginDefinitions(enabledPluginIds)` | The subset of registered plugins permitted by `enabledPluginIds` (`null` ⇒ all). |
| `isPluginIdAvailable(id, enabledPluginIds)` | Whether a single id is currently available. |
| `resolveAvailablePluginIds(pluginIds, enabledPluginIds)` | Filters + de-dupes an iterable of ids down to the available, registered ones (order preserved). |
| `getDefaultPluginIds(enabledPluginIds)` | The available plugins whose `defaultVisible` is true — used to seed the open set. |
| `samePluginIds(a, b)` | Order-sensitive equality check for two id arrays. |

The per-id availability helper is named `isPluginIdAvailable` (it takes the id plus
the enabled-ids list).

## 6. The host / panel contract

`PluginHost` (in `PluginHost.tsx`) renders the floating plugins anchored to map
corners. The companion `usePartitionedPlugins()` hook computes which plugins are
both **active** (open, from `usePluginStore`) and **available** (per
`resolveAvailablePluginIds`), then partitions them by placement into `byAnchor`
(floating) and `sidebar` buckets. `PluginSidebar` renders the sidebar bucket inside
the builder's left sidebar.

Each visible plugin is wrapped twice:

1. `PluginPanel` — the chrome: a header row with the plugin's `icon`, the translated
   `labelKey`, and a close button (which calls `usePluginStore.getState().close(id)`),
   plus a scrollable body containing the plugin component. Plugin authors do **not**
   import `PluginPanel` directly; the host applies it.
2. `PluginErrorBoundary` — a class component that isolates crashes. If a plugin
   throws during render, the boundary catches it (logging via `logger.error`) and
   renders a localized fallback instead of taking down the host.

The open/active set is managed by the `usePluginStore` zustand store
(`frontend/src/stores/map-plugin-store.ts`, imported as `@/stores/map-plugin-store`).
It tracks an `activePlugins: Set<string>` and exposes `open(id)`, `close(id)`,
`toggle(id)`, and `replace(ids)`. Seeding the default-open set is the caller's job —
typically by passing `getDefaultPluginIds(...)` to `replace(...)`.

## 7. How to register a new plugin

1. **Author a panel component** that accepts `{ ctx }: { ctx: PluginContext }`.
   Read `ctx.layers` / `ctx.mapInstance` / `ctx.mapId` as needed. Add map sources
   and layers in a `useEffect`, and clean them up in the effect's teardown.
2. **Build a `PluginDefinition`** with a unique `id`, a `labelKey`, an `icon`, a
   `placement`, the `component`, and an optional `defaultVisible`.
3. **Register it** by calling `registerPlugin(def)`. For a built-in, add the call to
   `register-plugins.ts` (imported for side effects, so the registration runs at
   startup).
4. **Add the `labelKey` translation** across all four locales — en, de, es, fr —
   under the `builder` namespace (e.g. `frontend/src/i18n/locales/<locale>/builder.json`)
   to keep i18n parity.
5. The host surfaces the plugin automatically once it is registered, active (open),
   and passes availability gating.

```ts
const MyPlugin: PluginDefinition = {
  id: 'my-plugin',
  labelKey: 'plugins.myPlugin.label',
  icon: MyIcon,
  placement: { mode: 'floating', anchor: 'top-right' },
  component: MyPluginPanel,
  defaultVisible: false,
};
registerPlugin(MyPlugin);
```

## 8. Public exports (`index.ts`)

The barrel at `frontend/src/components/map-plugins/index.ts` re-exports:

- **Types:** `PluginAnchor`, `PluginPlacement`, `PluginContext`, `PluginDefinition`
  (from `types.ts`).
- **Registry:** `registerPlugin`, `getPlugins`, `getPlugin` (from `registry.ts`).
- **Host:** `PluginHost`, `PluginSidebar`, `usePartitionedPlugins` (from `PluginHost.tsx`).
- **Panel:** `PluginPanel` (from `PluginPanel.tsx`).
- **Availability:** `getDefaultPluginIds`, `getEnabledPluginDefinitions`,
  `isPluginIdAvailable`, `resolveAvailablePluginIds`, `samePluginIds`
  (from `plugin-availability.ts`).

Importing `index.ts` also triggers `register-plugins.ts` as a side effect, so the
built-in plugins are registered as soon as the barrel is loaded.
