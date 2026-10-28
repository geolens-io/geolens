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
`title` is at most 120 characters; no other keys are allowed. A type that needs
more, such as a dashboard widget's layer id, adds those keys to the server model
and to `parseStoredWidget` together. The document that holds the instances, a
story or a map's `dashboard_config`, has its own `version`.

A type is a `WidgetDefinition` (`contract.ts`) with:

- `type`: a stable id. Never rename or reuse a shipped one.
- `v`: the newest config version. Bump it when the config shape changes, and
  make `parseConfig` read every older version and return the current shape.
- `surfaces`: `story`, `dashboard` or both.
- `parseConfig(config, v)`: a hand-written validator that returns the config
  or `null`. It rejects keys it doesn't know and caps strings and lists, the
  same as the type's server model (`extra="forbid"`).
- `defaultConfig`: what a newly added instance starts with.
- `dataRequest(config)` (optional): the aggregate endpoint request body
  (`WidgetDataRequest`, from the generated API types) without `filter` and
  `bbox`, which the host adds.
- `loadRenderer`: `() => import('./my-widget/MyWidgetRenderer')`. Anything
  heavy, including a new dependency, is imported only from the renderer so it
  stays out of the main bundle.
- `Fallback`: an accessible text or table version of the widget. It renders
  while the renderer loads, if the renderer fails, and wherever a host offers
  a text view. A chart's fallback is its data table.
- `labelKey` and `i18nKeys`: every key the widget uses, in the `widgets`
  namespace.

`registry.ts` reads instances for the hosts:

- `parseStoredWidget(raw, surface)` never throws. An instance this build can't
  read (an unknown type, a newer `v`, an invalid config) comes back as
  `{ ok: false, reason }` and is shown as a notice. The server already leaves
  those out of its responses and puts them back when the document is saved, so
  this is a backstop.
- `checkWidgetWrite(submitted, surface)` is the server's write rule: a
  submitted instance must parse, or the server answers 422. There's no
  exception for stored instances.

`defineWidget` wraps `loadRenderer` in `React.lazy` as the definition's
`Renderer`. `WidgetView` renders a parsed instance with its fallback around
that renderer.

## Adding a widget type

1. Create `my-widget/definition.ts` with `defineWidget<MyConfig>({ ... })`,
   plus `MyWidgetFallback.tsx` and `MyWidgetRenderer.tsx` (default export).
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
