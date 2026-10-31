# Widgets

Story blocks and dashboard widgets come from this one registry. A widget type
ships with GeoLens and arrives by pull request; nothing here loads code at
runtime, so the CSP keeps `script-src 'self'`.

`components/map-plugins/` is a separate mechanism for the map Builder's
toolbar and is not part of this registry.

## The contract

The server owns the stored shape (`backend/app/modules/catalog/widgets/schemas.py`),
and `registry.ts` mirrors it. Each instance is `{ id, type, v, title?, config }`:
`id` is a UUID the client makes and keeps across saves, unique within a list;
`title` is at most 120 characters. A dashboard widget also has a `layer_id`,
the map layer it summarizes, and a `scope`, `layer` (the default) or `view`; no
other keys are allowed. A `layerless` type (text) takes neither on a dashboard:
the host makes no data request for it, picks and view scope don't reach it,
and it never leaves the panel when a layer is hidden or removed. A type that
needs more adds those keys to the server model and to `parseStoredWidget`
together. The document that holds the instances, a story or a map's
`dashboard_config`, has its own `version`.

A chart is SVG drawn by its renderer, with no chart library: one tab stop,
arrow keys to move between its marks, colours from theme tokens, and its data
table as the fallback (see `bar-chart/` and `histogram/`). `chart-marks.ts`
handles the keys and clicks, and `ValueTable.tsx` draws the table.

### Picks

In the viewer, dashboard widgets are linked. A renderer that receives
`onSelect` lets the reader pick: a bar's value, a histogram bin's range, or
selector values, as a `WidgetSelection` with the label its filter chip shows.
The viewer passes `onSelect` only when the type names a `picksColumn` the
server can filter on. Enter or Space picks the active mark, and picking a
picked mark passes null. The
viewer (`viewer/linked-filters.ts`) turns each pick into a temporary filter on
the widget's layer: the map draws the layer with its saved filter and the
picks, and every other widget on the layer adds them to its request. The
widget that made a pick doesn't filter its own numbers by it, so it keeps
showing every value, with the pick marked by a check mark and the other marks
faded. Picks are never saved; their chips stay in the panel's header while
it is collapsed. Without `onSelect`, as in the Builder's preview, a widget is
read-only.

A type is a `WidgetDefinition` (`contract.ts`) with:

- `type`: a stable id. Never rename or reuse a shipped one.
- `v`: the newest config version. Bump it when the config shape changes, and
  make `parseConfig` read every older version and return the current shape.
- `surfaces`: `story`, `dashboard` or both.
- `layerless` (optional): on a dashboard the instance names no layer. The
  renderer gets `headingLevel`, the level of the first heading it may draw,
  one below the heading it sits under.
- `parseConfig(config, v)`: a hand-written validator that returns the config
  or `null`. It rejects keys it doesn't know and caps strings and lists, the
  same as the type's server model (`extra="forbid"`).
- `defaultConfig`: what a newly added instance starts with.
- `initialConfig(columns)` (optional): changes to `defaultConfig` for an
  instance added to a layer, such as which column it reads.
  `initial-columns.ts` picks a category or numeric column. A column's
  `samples` holds up to ten sampled values, so a column with fewer has few
  categories.
- `dataRequest(config)` (optional): the aggregate endpoint request body
  (`WidgetDataRequest`, from the generated API types) without `filter` and
  `bbox`, which the host adds.
- `loadRenderer`: `() => import('./my-widget/MyWidgetRenderer')`. Anything
  heavy, including a new dependency, is imported only from the renderer so it
  stays out of the main bundle.
- `heading(config, t, columnLabel)` (optional): what a dashboard shows for an
  instance with no title; the layer name moves to the line under it. Display
  only, never stored.
- `picksColumn(config)` (optional): the column a reader's pick on the widget
  filters. A type without it takes no picks.
- `readsColumns(config)` (dashboard types): the columns the config reads, each
  marked `numeric` when it must hold numbers. The Builder checks them against
  the layer and holds the save until they match.
- `loadEditor` (dashboard types): `() => import('./my-widget/MyWidgetEditor')`,
  the config form the Builder's Dashboard panel shows, with the layer's
  columns. `editor-fields.tsx` has the statistic and column pickers.
- `Fallback`: an accessible text or table version of the widget. It renders
  while the renderer loads, if the renderer fails, and wherever a host offers
  a text view. A chart's fallback is its data table.
- `labelKey` and `i18nKeys`: every key the widget uses, in the `widgets`
  namespace.

`registry.ts` reads instances for the hosts:

- `parseStoredWidget(raw, surface)` never throws. An instance this build can't
  read (an unknown type, a newer `v`, an invalid config) comes back as
  `{ ok: false, reason }` and is shown as a notice. A save without it deletes
  it, so the server has to keep such instances out of its responses and put
  them back on save. Dashboards do that for instances the server can't parse
  and for types it doesn't accept on write yet. Stories do it only for blocks
  the server can't parse, so register a block type here before the server
  parses it.
- `checkWidgetWrite(submitted, surface)` is the server's write rule: a
  submitted instance must parse, or the server answers 422. There's no
  exception for stored instances.

`defineWidget` wraps `loadRenderer` and `loadEditor` in `React.lazy` as the
definition's `Renderer` and `Editor`. `WidgetView` renders a parsed instance
with its fallback around that renderer.

## Adding a widget type

1. Create `my-widget/definition.ts` with `defineWidget<MyConfig>({ ... })`,
   plus `MyWidgetFallback.tsx` and `MyWidgetRenderer.tsx` (default export),
   and for a dashboard type `MyWidgetEditor.tsx` (default export).
2. Add the definition to `widgetDefinitions` in `registry.ts`.
3. Add its strings under `types.<type>` in `src/i18n/locales/*/widgets.json`
   for all five locales, and list them in `labelKey` and `i18nKeys`.
4. Add an example config to `examples` in
   `__tests__/widget-contract.test.tsx`. That suite runs every registered type
   through the contract: configs validate, an unknown type is refused on
   write, an unreadable instance gets the notice, the fallback renders, and the
   i18n keys exist in every locale.
5. Add a test file for the widget's own behavior, like
   `__tests__/markdown.test.tsx`.

Run `npx vitest run src/components/widgets`, `npm run test:i18n` and
`npm run knip`, then the frontend gates in `AGENTS.md`.
