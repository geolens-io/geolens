# /plugin-audit - Map Plugin Platform Audit

Audit the GeoLens map plugin platform end to end: plugin registration, authoring contract, host rendering, built-in plugin behavior, admin enablement, saved-map persistence, i18n/docs parity, and test coverage. This command owns `frontend/src/components/map-plugins/**` and plugin-specific builder integration; use `/builder-audit` for the wider map builder and `/map-audit` for a specific saved map.

**Usage:** `/plugin-audit` (full audit) or `/plugin-audit <scope>` where scope is `registry`, `host`, `lifecycle`, `builtins`, `admin`, `ux`, `docs`, or `tests`

Arguments: $ARGUMENTS

- Empty -> full audit
- `registry` -> plugin definition, registration, ID, and i18n contract
- `host` -> `PluginHost`, `PluginPanel`, placement, anchoring, and error isolation
- `lifecycle` -> active plugin state, default visibility, cleanup, save/load behavior
- `builtins` -> built-in plugin correctness; derive the current built-in set from `register-plugins.ts` (do not assume a hardcoded list)
- `admin` -> `enabled_plugins`, admin settings UI, backend validation, and governance
- `ux` -> accessibility, keyboard behavior, responsive layout, visual overlap, and map control interaction
- `docs` -> plugin development guide, command drift, and locale parity
- `tests` -> unit, integration, and E2E plugin coverage

If `$ARGUMENTS` matches a scope keyword above, run only the corresponding audit area after completing the full intake. In the synthesis, grade only the relevant dimension and note the scoped execution.

---

## INTAKE (Serial - do this first)

### Step 1: Determine scope

```bash
SCOPE=$(echo "$ARGUMENTS" | awk '{print $1}')
case "$SCOPE" in
  ""|registry|host|lifecycle|builtins|admin|ux|docs|tests) ;;
  *)
    echo "Usage: /plugin-audit [registry|host|lifecycle|builtins|admin|ux|docs|tests]"
    exit 1
    ;;
esac
echo "Scope: ${SCOPE:-full}"
```

### Step 2: Read the plugin platform

Read these files first:

- `frontend/src/components/map-plugins/index.ts`
- `frontend/src/components/map-plugins/types.ts`
- `frontend/src/components/map-plugins/registry.ts`
- `frontend/src/components/map-plugins/register-plugins.ts`
- `frontend/src/components/map-plugins/plugin-availability.ts`
- `frontend/src/stores/map-plugin-store.ts`
- `frontend/src/components/map-plugins/PluginHost.tsx`
- `frontend/src/components/map-plugins/PluginPanel.tsx`
- `frontend/src/components/map-plugins/PluginErrorBoundary.tsx`
- `frontend/src/components/map-plugins/builtin/MeasurementPlugin.tsx`
- `frontend/src/components/map-plugins/builtin/LegendPlugin.tsx`
- `frontend/src/components/map-plugins/__tests__/registry.test.ts`
- `frontend/src/components/map-plugins/__tests__/plugin-availability.test.ts`
- `frontend/src/components/map-plugins/__tests__/PluginHost.test.tsx`
- `frontend/src/stores/__tests__/map-plugin-store.test.ts`

### Step 3: Read builder integration

- `frontend/src/pages/MapBuilderPage.tsx`
- `frontend/src/components/builder/BuilderMap.tsx`
- `frontend/src/components/builder/MapToolbar.tsx`
- `frontend/src/components/builder/hooks/use-builder-save.ts`
- `frontend/src/hooks/use-settings.ts`
- `frontend/src/api/settings.ts`
- `frontend/src/lib/query-keys.ts`
- `frontend/src/types/api.ts`

### Step 4: Read admin and backend configuration

- `frontend/src/components/admin/settings/SettingsMapTab.tsx`
- `backend/app/core/persistent_config.py`
- `backend/app/modules/settings/router.py`
- `backend/app/modules/settings/schemas.py`
- `backend/app/modules/catalog/maps/models.py`
- `backend/app/modules/catalog/maps/router.py`
- `backend/app/modules/catalog/maps/schemas.py`
- `backend/app/modules/catalog/maps/service_crud.py`
- `e2e/admin.spec.ts`

### Step 5: Read docs, locale, and related audit references

- `docs/plugin-development.md`
- `frontend/src/i18n/locales/en/builder.json`
- `frontend/src/i18n/locales/es/builder.json`
- `frontend/src/i18n/locales/fr/builder.json`
- `frontend/src/i18n/locales/de/builder.json`
- `frontend/src/i18n/locales/en/admin.json`
- `frontend/src/i18n/locales/es/admin.json`
- `frontend/src/i18n/locales/fr/admin.json`
- `frontend/src/i18n/locales/de/admin.json`
- `.claude/commands/builder-audit.md`
- `.claude/commands/map-audit.md`
- `.agents/skills/geolens-builder-audit/SKILL.md`
- `.agents/skills/geolens-map-audit/SKILL.md`

### Step 6: Inventory actual plugin IDs

Derive registered plugin IDs from source, not from docs or audit commands:

```bash
rg -n "registerPlugin\\(|id: " frontend/src/components/map-plugins/register-plugins.ts frontend/src/components/map-plugins
rg -n "plugins|Plugin|enabled_plugins|map-plugins" frontend/src backend/app docs e2e .claude/commands .agents/skills --glob '!node_modules' --glob '!dist' --glob '!coverage'
```

Treat `frontend/src/components/map-plugins/register-plugins.ts` as the current source of truth for built-in plugin IDs unless the registry implementation has changed.

---

## PLUGIN AUDIT REFERENCE

### Registry and authoring contract

- Every built-in plugin MUST be registered exactly once by `register-plugins.ts`.
- Plugin IDs MUST be stable, unique, lowercase slugs suitable for saved-map JSON and settings values.
- Audit commands, docs, tests, admin copy, and examples MUST NOT maintain stale hardcoded plugin ID lists; they should derive from the registry where possible.
- `labelKey` MUST resolve under the `builder` namespace in every committed locale.
- `icon` MUST be an icon component compatible with the existing button/panel sizing conventions.
- `placement` MUST be honored for every declared mode. If `types.ts` exposes `sidebar`, the host must render sidebar plugins or the type must not promise that mode.
- Plugin components MUST receive only `PluginContext`; shared panel chrome belongs in `PluginPanel`.
- Plugins MUST guard `ctx.mapInstance` because it can be `null` during initial load.
- A plugin crash MUST be isolated by `PluginErrorBoundary` and must not break other plugins or the builder.

### Host, panel, and placement invariants

- `usePartitionedPlugins()` MUST filter by both active plugin state and admin-enabled plugin IDs.
- `enabled_plugins: null` means no restriction; `enabled_plugins: []` means no plugins; unknown IDs should not render.
- Default-visible plugins MUST not silently bypass admin restrictions when persisted or rendered.
- Floating plugins MUST not overlap the map toolbar, navigation controls, scale control, active filter chips, attribution, or each other at desktop or mobile widths.
- `PluginPanel` close controls MUST be keyboard reachable, labelled, and stable under translation.
- Plugin body scroll regions MUST be usable by keyboard and not trap focus.
- Plugin z-index and pointer event behavior MUST not block normal map interactions outside the panel bounds.
- Multiple plugins in the same anchor MUST stack predictably without layout shifts.

### Lifecycle and persistence invariants

- Active plugin state MUST be deterministic across builder mount, default-visible plugins, saved map load, and map save.
- Saved maps use `plugins: null` for client defaults, `[]` for no active plugins, and string arrays for explicit active plugin IDs.
- Saving a map MUST not persist admin-disabled plugins just because they are still in local active state.
- Loading a map with unknown legacy plugin IDs MUST fail gracefully and should not crash the builder.
- Toggling a plugin off MUST remove or deactivate any MapLibre layers, sources, controls, listeners, drawing state, timers, or subscriptions it created.
- Measurement, hover, click, drag, and selection handlers MUST not conflict with layer editing, map panning, popups, or other builder interactions.
- Plugin state MUST not cause unrelated layer style/filter/label changes to re-fetch tiles or reset map state.

### Built-in plugin invariants

Derive the current built-in plugin set from `register-plugins.ts` (the registry is the source of truth) — do not assume a hardcoded list. At the time of writing the built-ins are the measurement and legend plugins; verify against `register-plugins.ts` before auditing.

Measurement plugin:

- Distance and area modes MUST produce correct units and clear mode-specific state when switched.
- Click, double-click, escape, clear, and close behavior MUST leave the map in a clean interaction state.
- Measurement layers/sources MUST use deterministic IDs and be removed on cleanup.
- Unit labels and buttons MUST be translated and accessible.
- Measurement must not remain active after the plugin is closed unless the UI explicitly communicates that behavior.

Legend plugin:

- Legend content MUST track visible builder layers, layer order, `show_in_legend`, display names, and style changes.
- Vector, raster, heatmap, categorical, graduated, and label-related styles MUST render sensible legend entries or clear fallback text.
- Empty, loading, or unsupported layers MUST render a quiet empty state, not stale legend data.
- Legend rendering MUST not throw when layer style objects are partial, malformed, or legacy.
- Legend layout MUST remain readable over the map at desktop and mobile sizes.

### Admin and API invariants

- Admin plugin toggles MUST be generated from the registry, not a duplicated list.
- Admin save/reset behavior MUST preserve `null` versus `[]` semantics where the backend contract distinguishes them.
- Backend settings validation MUST reject malformed `enabled_plugins` values and accept `null` or string arrays.
- The public enabled-plugins endpoint MUST expose only the IDs needed by the frontend and no sensitive settings.
- Permission checks for settings changes MUST match the rest of the admin settings surface.
- Audit logs or config governance should capture plugin setting changes if the settings system supports that elsewhere.
- Map schemas and generated frontend API types MUST keep `plugins?: string[] | null` aligned.

### Documentation, i18n, and test invariants

- `docs/plugin-development.md` MUST match the current registry API, placement modes, plugin context, built-ins, and admin setting semantics.
- Locale files MUST have complete keys for every plugin label, panel action, empty state, and error state.
- Unit tests SHOULD cover registry behavior, active-state store behavior, host filtering, error isolation, default visibility, and save payload resolution.
- Built-in plugin tests SHOULD cover cleanup and at least one useful behavior per plugin.
- E2E or Playwright smoke coverage SHOULD exercise opening/closing plugins in the builder and admin plugin enablement.
- Command drift checks SHOULD compare hardcoded plugin mentions in `.claude/commands/**` and `.agents/skills/**` with `register-plugins.ts`.

---

## AUDIT AREAS

Run only the matching section when scoped. For full audits, cover all sections.

### 1. Registry and Authoring Contract

1. Read the registry, type definitions, and registration side effect path.
2. Confirm built-in IDs, labels, icons, placements, and `defaultVisible` values are valid.
3. Check for duplicate or overwritten IDs.
4. Verify all `labelKey` values exist in every builder locale.
5. Check whether all declared placement modes are actually rendered.
6. Compare docs and audit commands for stale plugin ID lists.

**Output:** finding list - contract issue x evidence x fix.

### 2. Host, Panel, and Layout

1. Read `PluginHost`, `PluginPanel`, `PluginErrorBoundary`, `MapBuilderPage`, and `MapToolbar`.
2. Verify active + enabled filtering semantics for `null`, `[]`, unknown IDs, and disabled default-visible plugins.
3. Check anchor offsets against map controls and active filter chips.
4. Check keyboard access, close button labels, scrollable body behavior, and focus order.
5. Use Playwright screenshots when visual overlap or responsive behavior is in scope.
6. Verify every rendered plugin is individually error-boundaried.

**Output:** finding list - host/layout issue x viewport or state x fix.

### 3. Lifecycle and Persistence

1. Read the plugin store (`frontend/src/stores/map-plugin-store.ts`), `MapBuilderPage`, `use-builder-save`, map schemas, and map service persistence.
2. Trace default-visible plugin activation on builder mount.
3. Trace saved map plugin load and save semantics.
4. Verify explicit `[]` is not collapsed into `null`, and `null` does not unintentionally become an explicit active set.
5. Check admin-disabled active plugins are not persisted unless intentionally allowed and documented.
6. Check cleanup behavior for plugins that attach MapLibre listeners, layers, sources, timers, or subscriptions.

**Output:** finding list - lifecycle issue x affected saved-map state x fix.

### 4. Built-in Plugins

1. Audit the measurement plugin (`MeasurementPlugin`) for modes, units, event handlers, layer/source cleanup, and interaction conflicts.
2. Audit the legend plugin (`LegendPlugin`) for layer coverage, style coverage, layer order, visibility handling, error tolerance, and empty states.
3. Verify built-ins guard `ctx.mapInstance` and partial layer data.
4. Verify all visible text and aria labels use i18n.
5. Check built-in plugin unit tests or identify missing coverage.

**Output:** finding list - plugin ID x behavior x fix.

### 5. Admin, API, and Governance

1. Read admin settings UI, frontend settings API, backend settings router/schemas, and persistent config defaults.
2. Verify admin plugin toggles come from `getPlugins()` and preserve the intended backend semantics.
3. Verify backend validation rejects malformed values and settings updates require the right permission.
4. Verify `GET /settings/enabled-plugins/` returns `list[str] | null` as expected.
5. Check generated frontend types and OpenAPI alignment if backend schemas changed.
6. Verify admin E2E coverage includes the plugin settings section.

**Output:** finding list - admin/API issue x contract impact x fix.

### 6. UX and Accessibility

1. Check plugin controls with keyboard-only interaction.
2. Check screen-reader names for toolbar triggers, panel headers, close buttons, measurement controls, and legend content.
3. Check mobile and narrow desktop layouts for clipped content, overlap, unusable scroll areas, or hidden controls.
4. Check that plugin panels do not obscure critical map controls without an obvious close/minimize path.
5. Check that measurement mode visual feedback is visible and not color-only.

**Output:** finding list - UX/a11y issue x user impact x fix.

### 7. Docs and Command Drift

1. Compare `docs/plugin-development.md` with actual registry types and built-in plugins.
2. Compare `.claude/commands/**` and `.agents/skills/**` plugin references with current registered IDs.
3. Verify examples compile conceptually against `PluginDefinition`.
4. Verify admin setting semantics are documented consistently.

**Output:** finding list - stale doc/command x source of truth x fix.

### 8. Test Coverage

1. Inventory plugin unit tests, builder save tests, admin settings tests, and E2E coverage.
2. Identify missing tests for high-risk invariants: admin-disabled default plugins, `plugins: []`, unknown saved IDs, cleanup on close, and legend style coverage.
3. Check whether tests assert user-facing behavior rather than implementation details only.
4. Recommend the smallest useful tests before broad snapshots.

**Output:** finding list - missing test x risk covered x suggested test.

---

## SYNTHESIS

Grade only scoped dimensions when `$SCOPE` is set.

| Dimension | What it measures |
| --- | --- |
| Registry Health | Plugin definitions, IDs, i18n, placement contract, command/docs drift |
| Host Correctness | Filtering, anchoring, panel behavior, error isolation |
| Lifecycle Safety | defaultVisible, save/load semantics, cleanup, map interaction conflicts |
| Built-in Quality | Built-in plugin behavior (derive set from `register-plugins.ts`), resilience, accessibility |
| Admin/API Contract | enabled plugin settings, validation, permissions, type alignment |
| UX/A11y | keyboard, labels, responsive layout, visual overlap |
| Test Confidence | focused coverage for registry, host, lifecycle, built-ins, admin |

Use this output shape:

```markdown
# Plugin Audit - [scope or full]

## Verdict
- Overall: PASS | PASS WITH ISSUES | FAIL
- Highest severity:
- Registered plugins:
- Scopes audited:

## Scorecard
| Dimension | Grade | Notes |
| --- | --- | --- |

## Findings
### [SEVERITY] [Short title]
- Evidence: `file:line`
- Impact:
- Fix:

## Coverage Gaps
- ...

## Verification
- Commands run:
- Playwright/manual flows:
- Skipped areas:
```

Severity guidance:

- `[CRITICAL]` plugin state or admin settings can expose, corrupt, or crash core builder flows.
- `[HIGH]` common plugin operations break, leak map handlers, or persist incorrect saved-map state.
- `[MEDIUM]` important UX, accessibility, docs, or test gaps that can cause user confusion or regressions.
- `[LOW]` minor drift, cleanup, naming, or maintainability issues.

---

## DELIVERY

Write the full report (the output shape above) to
`docs-internal/audits/plugin-audit-{YYYYMMDD}.md` — matches the persistence
convention used by `/builder-audit`, `/map-audit`, and the rest of the audit
suite. Print a concise inline summary after writing.

---

## FALSE POSITIVES TO AVOID

- `usePluginStore` is acceptable for global overlay plugin UI state; do not apply the builder working-layer local-state rule mechanically.
- Legacy saved maps may contain unknown plugin IDs. Flag crashes or poor migration behavior, not the mere existence of unknown historical values.
- Hex colors inside MapLibre paint/legend rendering can be correct; design token rules apply to UI chrome.
- Lack of jsdom MapLibre rendering is expected. Prefer E2E or targeted unit tests around pure logic and cleanup.
- Admin `enabled_plugins: null` and map `plugins: null` are meaningful defaults; do not collapse them to empty arrays unless the contract explicitly changed.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/builder-audit` audits the whole map builder; this command owns the plugin platform and plugin-specific integration.
- `/map-audit` audits one saved map; this command audits plugin infrastructure and catches stale map-audit plugin assumptions.
- `/admin-audit settings` covers governance broadly; this command checks plugin-specific settings semantics.
- `/design-audit` covers frontend-wide design and accessibility (it has an `a11y` scope); this command checks plugin-specific layout and interaction behavior.
- `/test-audit frontend` covers test health broadly; this command identifies plugin-specific coverage gaps.
