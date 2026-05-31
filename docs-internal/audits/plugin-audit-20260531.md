# Plugin Audit - full

_Date: 2026-05-31 · Branch: `builder-audit-fixes-v2` · Auditor: automated `/plugin-audit`_

> **REMEDIATION (2026-05-31, same day):** All 5 findings below were fixed and verified.
> - **MED-1 (sidebar not mounted):** `<PluginSidebar>` now mounted in the builder sidebar (`MapBuilderPage.tsx`, non-rail; null until a `sidebar`-placement plugin exists).
> - **MED-2 (per-map toggles ignore admin allowlist):** `SettingsEditorScene` now renders `getEnabledPluginDefinitions(enabledPluginIds)`; `MapBuilderPage` passes `enabledPluginIds`. +2 regression tests.
> - **LOW-3 (stale anchor comments):** corrected in `ActiveFilterChips.tsx` + `mcp-verify-1134-06.spec.ts`; new `register-plugins.test.ts` pins the built-in anchor/defaultVisible set against drift.
> - **LOW-4 (residual "widget"):** swept (`legend-plugin-`, `PLUGINS`, test fixtures); genuine compass-widget + migration/changelog/README left intact.
> - **LOW-5 (leaf-registry import):** `SettingsEditorScene` now imports from the barrel `@/components/map-plugins`.
> - **Coverage:** added `register-plugins.test.ts`, `MeasurementPlugin.test.ts`, `LegendPlugin.test.ts` + admin-filter regression tests.
> - **Verification:** full suite 2672/2672 · `tsc -b` 0 · `vite build` ✓ · ESLint clean · 11-agent adversarial review confirmed 0 real defects.
> - **E2E (live-verified):** `e2e/plugin-lifecycle.spec.ts` (3/3 green against the live stack) now covers both deferred gaps — the builder toggle→save→reload round-trip through the `plugins` column, and the admin `enabled_plugins` allowlist hiding admin-disabled toggles. Self-contained with precise global-setting restore.
> - The original snapshot findings below are retained as the point-in-time record.

## Verdict
- **Overall: PASS WITH ISSUES**
- **Highest severity:** MEDIUM (2 findings)
- **Registered plugins:** `measurement` (floating top-left, `defaultVisible: false`), `legend` (floating bottom-left, `defaultVisible: true`) — derived from `register-plugins.ts`
- **Scopes audited:** registry, host, lifecycle, builtins, admin, ux, docs, tests (full)

This audit lands immediately after the **Widget → Plugin platform rename** (milestone v1036 / Phases 1162–1163; `RENAME-widgets-to-plugins-BRIEF.md`). The rename is substantially complete and correct: the `map-plugins/` module, the `catalog.maps.plugins` JSONB column, the `enabled_plugins` config key, the public `/settings/enabled-plugins/` endpoint, the `MapResponse.plugins` field, and all four locales are renamed and aligned. The `null` / `[]` / omitted semantics round-trip correctly end-to-end. No functional `widget` residue remains in the backend or locale files; what is left is cosmetic comments.

## Scorecard
| Dimension | Grade | Notes |
| --- | --- | --- |
| Registry Health | A− | Stable IDs, memoized cache w/ correct invalidation, dup-overwrite warns in DEV, full i18n parity, accurate dev guide. Minor: no test asserts the built-in set; residual "widget" comments. |
| Host Correctness | B+ | `usePartitionedPlugins` filters by active **and** admin-enabled; every plugin individually error-boundaried. But the declared `sidebar` placement mode is exported/tested/documented yet **never mounted** in the builder. |
| Lifecycle Safety | A− | `null`/`[]`/omitted round-trip correct end-to-end (`exclude_unset` on the server). Measurement cleanup removes sources/layers/handlers/cursor/dblclick. Minor: global `keydown`/`click` listeners while measurement is open. |
| Built-in Quality | A− | Measurement: deterministic `_measure-*` ids, full teardown, i18n + `aria-pressed`. Legend: per-entry `try/catch` resilience, partial-style tolerance, quiet empty state. Minor: no behavior unit tests for either. |
| Admin/API Contract | A | Validator rejects malformed + accepts `null`/string[]; public endpoint typed `list[str] \| null`, no auth; admin toggles registry-derived; types aligned; migration O(1) rename, value-preserving, round-trip tested. |
| UX/A11y | B+ | Strong aria labels (Enable/Disable {name}), keyboard-reachable close, availability note. But per-map plugin toggles show dead controls when an admin restricts plugins; stale collision geometry in one e2e. |
| Test Confidence | B | 55/55 targeted unit tests green + migration round-trip green. Gaps: no admin-enablement e2e, no builder open/close + save→reload e2e, no built-in-set or built-in-behavior assertions. |

## Findings

### [MEDIUM] `sidebar` placement mode is declared/exported/tested/documented but never rendered in the builder
- **Evidence:** `frontend/src/components/map-plugins/types.ts:11` declares `{ mode: 'sidebar' }`; `PluginHost.tsx:96-110` exports `PluginSidebar`; `usePartitionedPlugins` returns a `sidebar` bucket (`PluginHost.tsx:42,53`); `docs/plugin-development.md` §4 & §6 document it; `PluginHost.test.tsx:120-124` tests it. But `frontend/src/pages/MapBuilderPage.tsx:330` destructures only `const { byAnchor } = usePartitionedPlugins()` — the `sidebar` bucket and `<PluginSidebar>` are never consumed.
- **Impact:** A third-party (or future built-in) plugin registered with `placement: { mode: 'sidebar' }` would silently never appear in the builder, with no error. Contract violation: "If `types.ts` exposes `sidebar`, the host must render sidebar plugins or the type must not promise that mode." Latent today — no built-in uses `sidebar`.
- **Fix:** Either mount `<PluginSidebar plugins={sidebar} ctx={pluginCtx} />` inside the builder left sidebar (`builder-sidebar` aside) and pull `sidebar` from the hook, or remove the `sidebar` mode from `types.ts` / `PluginHost` / docs until a real consumer exists. Pick one so the type contract matches reality.

### [MEDIUM] Per-map "Settings → Plugins" toggles list all registered plugins, ignoring admin `enabled_plugins` (dead toggles)
- **Evidence:** `frontend/src/components/builder/SettingsEditorScene.tsx:50` `const plugins = useMemo(() => getPlugins(), [])` (full registry), rendered at `:186`. `MapBuilderPage.tsx:331-333` passes `activePlugins` + `onTogglePlugin` but **not** `enabledPluginIds`. The admin allowlist is applied only downstream in `usePartitionedPlugins` (`PluginHost.tsx:35`) and `resolvePluginsPayload` (`use-builder-save.ts:240`).
- **Impact:** When an admin sets a non-null `enabled_plugins` that excludes a plugin, the builder's per-map Settings panel still renders a toggle for it. Toggling it on adds the id to `activePlugins`, but both render (`usePartitionedPlugins`) and persistence (`resolvePluginsPayload`) strip it — so the control does nothing visible and nothing is saved. Confusing no-op. **No data corruption** (persistence is correctly filtered). Only manifests when `enabled_plugins` is non-null; default deployments (`null`) are unaffected.
- **Fix:** Pass `enabledPluginIds` into `SettingsEditorScene` and render `getEnabledPluginDefinitions(enabledPluginIds)` instead of `getPlugins()`, so the per-map list matches what can actually appear.

### [LOW] Stale anchor geometry: comments + e2e label measurement as "bottom-left"
- **Evidence:** `register-plugins.ts:10` anchors `measurement` at **top-left** (git history confirms this is long-standing; `legend` is the bottom-left one at `:19`). But `frontend/src/components/builder/ActiveFilterChips.tsx:128` ("…growing into the MeasurementPlugin at ≤800px … Filter-Pill vs Measure-Widget") and `e2e/mcp-verify-1134-06.spec.ts:226-227,567,583-588` repeatedly describe/hover "MeasurementPlugin at bottom-left."
- **Impact:** Functionally fine — measurement and the `topLeftSlot` filter chips share the top-left flex-col and stack with `gap-2` (no overlap); legend sits bottom-left alone. But the e2e "no measure-plugin collision" assertions hover at the wrong corner, so they validate collision avoidance against incorrect geometry, and the comments mislead future maintainers.
- **Fix:** Correct the comments (measurement = top-left, shares anchor with filter chips; legend = bottom-left) and re-aim the e2e hover/collision coordinates accordingly.

### [LOW] Residual "widget" vocabulary in active code comments/identifiers
- **Evidence:** `LegendPlugin.tsx:169` `layerId={`legend-widget-${idx}`}` (internal icon layer id); `SettingsEditorScene.tsx:20,151` (`// Widgets`, `{/* Section 3: WIDGETS */}` — the rendered eyebrow is correctly `PLUGINS`); `SettingsEditorScene.plugins.test.tsx:6`; `normalize-saved-map.test.ts:151` (`undefined widgets` comment, input is actually `plugins: undefined`); `ActiveFilterChips.tsx:128`. No backend or locale residue (`rg -i widget backend/app frontend/src/i18n` → 0).
- **Impact:** Cosmetic only; no behavior. Slightly confusing post-rename.
- **Fix:** Sweep these strings to "plugin" for consistency. `legend-widget-${idx}` is just a DOM/icon id but worth renaming to `legend-plugin-${idx}`.

### [LOW] Direct `registry` imports bypass the registration side-effect
- **Evidence:** `SettingsEditorScene.tsx:9` imports `getPlugins` from `@/components/map-plugins/registry` (the leaf module), not the barrel `@/components/map-plugins` whose `index.ts:2` runs `import './register-plugins'`. It works only because `MapBuilderPage.tsx:99` imports the barrel first, so registration has already run before the lazy `SettingsEditorScene` mounts. (`SettingsMapTab.tsx:12` correctly imports from the barrel.)
- **Impact:** Fragile import-order dependency. If the module graph ever changes so a direct-`registry` consumer loads before any barrel import, `getPlugins()` returns `[]` with no warning (empty plugin UI). The plugins unit test mocks the registry, so it would not catch this.
- **Fix:** Import `getPlugins` from the barrel `@/components/map-plugins` in `SettingsEditorScene.tsx` (mirroring `SettingsMapTab.tsx`).

## Coverage Gaps
- **No admin-enablement E2E.** `e2e/admin.spec.ts` has zero plugin references. The `enabled_plugins` round-trip (admin Map tab toggle → `PUT /settings` → public `/settings/enabled-plugins/` → builder filtering) is not exercised end-to-end. This is exactly where the MEDIUM dead-toggle finding lives.
- **No builder open/close + save→reload E2E.** The brief's step-5 "live MCP set→save→reload of a plugin (round-trips the renamed DB column)" is not encoded as a functional test. Helpers are unit-tested and the column rename is migration-tested, but no test drives a real plugin toggle → save → reload → assert persisted `plugins`.
- **No built-in-set assertion.** `registry.test.ts` tests generic register/get; `plugin-availability.test.ts` only indirectly confirms `legend` via `getDefaultPluginIds(null) === ['legend']`. Nothing asserts `measurement` is registered with anchor top-left / `defaultVisible:false` — an anchor or default flip would pass CI.
- **No built-in behavior/cleanup unit tests.** The pure helpers `rebuildMeasurement` (MeasurementPlugin), `getSwatchStyleFromPaint` / `parsePaintColors` / `expressionColumn` (LegendPlugin) are extractable and testable without MapLibre, but currently have no coverage. (jsdom can't render MapLibre; the pure logic still can be pinned.)

## Verification
- **Commands run:**
  - `npx vitest run src/components/map-plugins src/stores/__tests__/map-plugin-store.test.ts src/components/builder/__tests__/SettingsEditorScene.plugins.test.tsx src/lib/__tests__/normalize-saved-map.test.ts` → **6 files / 55 tests passed**
  - `uv run pytest tests/test_migration_0025_plugins_rename.py` → **1 passed** (upgrade/downgrade round-trip)
  - `npm run typecheck` (`tsc -b --noEmit`) → **0 errors**
  - i18n parity: `plugins.*` (15 keys) + `settings.plugins*` (7 keys) in `builder.json` and `settings.plugins.{title,description}` in `admin.json` — **identical key sets across en/es/fr/de**
  - `rg -i widget` across backend/app, frontend/src/i18n, locales — **0 functional hits** (only cosmetic comments in frontend components/tests)
  - Backend `null` vs omitted vs `[]`: confirmed via `service_crud.py:242,283` (`_UNSET` sentinel) + `router.py:765,775` (`model_dump(exclude_unset=True)`).
- **Manual/static flows traced:** builder mount → `getDefaultPluginIds` seed (`MapBuilderPage.tsx:249-256`); saved-map load → `resolveAvailablePluginIds`; save → `resolvePluginsPayload` (default-collapse-to-`null`/`undefined`, explicit-array, admin-filter); admin toggle → `coerceEnabledPlugins` (`null`→full, `[]`→none) → `validate_enabled_plugins`; error isolation via `PluginErrorBoundary` (test-confirmed).
- **Skipped areas:** Live Playwright MCP not run (no functional open→save→reload smoke this session); the save→reload DB round-trip is inferred from unit + migration tests, not observed live. Recommend a live MCP pass before tagging v1036 per the brief's step-5.
